"""Source contracts and dynamic catalog parsers; no fixture price fallback exists."""
from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import hashlib
import io
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
import xml.parsers.expat
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .transport import (ConnectorError, RawResponse, ReadOnlyTransport, ReadRequest,
                        SOURCE_SPECS, SourcePolicy, UTC, parse_utc, utc_string)


def decimal_value(value: Any, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ConnectorError("invalid_price")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ConnectorError("invalid_price") from None
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        raise ConnectorError("invalid_price")
    if len(result.as_tuple().digits) > 128 or abs(result.as_tuple().exponent) > 128:
        raise ConnectorError("numeric_precision_limit")
    return result


def integer_value(value: Any, *, positive: bool = False) -> int:
    number = decimal_value(value, positive=positive)
    if number != number.to_integral_value():
        raise ConnectorError("invalid_integer")
    return int(number)


def decimal_string(value: Decimal) -> str:
    if not value.is_finite() or len(value.as_tuple().digits) > 128 or abs(value.as_tuple().exponent) > 128:
        raise ConnectorError("numeric_precision_limit")
    result = format(value, "f")
    if len(result) > 128:
        raise ConnectorError("numeric_precision_limit")
    return result


def per_million(value: Decimal) -> Decimal:
    # Moving the exponent is exact even beyond the default Decimal context's
    # 28-digit precision; multiplying in that context can round source prices.
    sign, digits, exponent = value.as_tuple()
    return Decimal((sign, digits, exponent + 6))


def json_payload(raw: RawResponse) -> Any:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ConnectorError("duplicate_json_response_key")
            result[key] = value
        return result
    try:
        return json.loads(raw.body.decode("utf-8"), object_pairs_hook=pairs, parse_float=Decimal,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ConnectorError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ConnectorError("invalid_json_response") from None


@dataclasses.dataclass(frozen=True)
class ConnectorBatch:
    source_id: str
    raw_metadata: Mapping[str, Any]
    observations: tuple[Mapping[str, Any], ...]
    catalog_records: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    coverage: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({"source_id": self.source_id, "raw_metadata": dict(self.raw_metadata),
                "observations": list(self.observations), "catalog_records": list(self.catalog_records),
                "warnings": list(self.warnings), "coverage": dict(self.coverage), "execution_enabled": False})


def _jsonable(value: Any) -> Any:
    # Preserve JSON number precision as decimal strings through application storage.
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _permission(policy: SourcePolicy) -> dict[str, Any]:
    return {"status": policy.rights_status, **{name: policy.permissions.get(name, "UNKNOWN")
            for name in ("observe", "retain", "benchmark", "execution")},
            "verified_by": policy.verified_by, "scope": list(policy.permissions),
            "expires_at": policy.expires_at}


def _observation(raw: RawResponse, policy: SourcePolicy, *, key: str, kind: str,
                 amount: Decimal, unit: str, model: str | None, observed: dt.datetime,
                 accelerator_count: int | None = None, side: str = "mark",
                 provider_group_id: str | None = None, region: str | None = None,
                 extensions: Mapping[str, Any] | None = None, currency: str = "USD") -> dict[str, Any]:
    captured = parse_utc(raw.captured_at)
    if observed > captured:
        raise ConnectorError("future_source_observation")
    expires = observed + dt.timedelta(seconds=policy.max_age_s)
    id_digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return {
        "schema_version": "1.0.0", "source_version": "adapter-contract/1.0",
        "id": f"{policy.source_id}-{id_digest}", "source_id": policy.source_id,
        "offer_id": None, "lot_id": None, "provider_group_id": provider_group_id,
        "kind": kind, "price": {"amount": decimal_string(amount), "currency": currency, "unit": unit},
        "price_side": side, "hardware": {"model": model, "accelerator_count": None if accelerator_count is None else str(accelerator_count)},
        "region": region, "quantity": None, "starts_at": None, "ends_at": None,
        "observed_at": utc_string(observed), "ingested_at": raw.captured_at,
        "expires_at": utc_string(expires), "status": "stale" if expires <= captured else "claimed",
        "rights": _permission(policy),
        "evidence": [{"id": f"{policy.source_id}-{raw.sha256[:24]}", "source_id": policy.source_id,
                      "artifact_sha256": raw.sha256, "locator": raw.endpoint_path,
                      "event_at": utc_string(observed), "accessed_at": raw.captured_at,
                      "verifier": policy.verified_by, "scope": ["advertised_market_data"],
                      "expires_at": policy.expires_at, "permission": _permission(policy)}],
        "extensions": _jsonable({"attribution": policy.attribution, "executable": False,
                       "source_claim_not_independent_verification": True, **(extensions or {})}),
    }


GD_COLUMNS = frozenset({"gpu_slug", "date", "billing_type", "reservation_months", "min_price",
                        "max_price", "median_price", "provider_median_price", "provider_count", "offering_count"})


def parse_getdeploying(raw: RawResponse, policy: SourcePolicy) -> ConnectorBatch:
    policy.require("benchmark", parse_utc(raw.captured_at))
    if raw.source_id != policy.source_id or policy.source_id != "getdeploying":
        raise ConnectorError("source_policy_mismatch")
    try:
        content = raw.body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ConnectorError("invalid_csv_encoding") from None
    reader = csv.DictReader(io.StringIO(content), strict=True)
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or not GD_COLUMNS <= set(reader.fieldnames):
        raise ConnectorError("dataset_header_changed")
    observations, seen = [], set()
    try:
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ConnectorError("malformed_dataset_row")
            model = row["gpu_slug"]
            if not model or not re.fullmatch(r"[A-Za-z0-9_.-]+", model):
                raise ConnectorError("invalid_dataset_model")
            try:
                date = dt.date.fromisoformat(row["date"])
            except ValueError:
                raise ConnectorError("invalid_dataset_date") from None
            if date.weekday() != 0:
                raise ConnectorError("dataset_week_not_monday")
            billing = row["billing_type"]
            if not billing:
                raise ConnectorError("missing_billing_type")
            reservation = None if row["reservation_months"] == "" else integer_value(row["reservation_months"], positive=True)
            prices = {name: decimal_value(row[name]) for name in
                      ("min_price", "max_price", "median_price", "provider_median_price")}
            if any(not prices["min_price"] <= prices[field] <= prices["max_price"]
                   for field in ("median_price", "provider_median_price")):
                raise ConnectorError("inconsistent_dataset_price_range")
            provider_count, offering_count = integer_value(row["provider_count"]), integer_value(row["offering_count"])
            if provider_count > offering_count:
                raise ConnectorError("inconsistent_dataset_counts")
            key = "|".join((model, row["date"], billing, row["reservation_months"]))
            if key in seen:
                raise ConnectorError("duplicate_dataset_row")
            seen.add(key)
            observed = dt.datetime.combine(date, dt.time(), tzinfo=UTC)
            observations.append(_observation(raw, policy, key=key, kind="aggregate_advertised_index",
                amount=prices["provider_median_price"], unit="gpu_hour", model=model, observed=observed,
                extensions={"source_row": dict(row), "billing_type": billing, "reservation_months": reservation,
                            "price_statistic": "provider_median_price", "provider_count": provider_count,
                            "offering_count": offering_count, "availability": "not_verified_rentable",
                            "period": "weekly_median_of_daily_values", "week_start": row["date"],
                            "latest_week_may_be_partial": True, "regional_scope": "market_aggregate",
                            "currency_conversion": "publisher_usd_conversion"}))
    except csv.Error:
        raise ConnectorError("malformed_dataset_csv") from None
    if not observations:
        raise ConnectorError("empty_dataset")
    return ConnectorBatch(policy.source_id, raw.metadata(), tuple(observations), warnings=(
        "weekly_advertised_aggregate_not_live_executable_quote", "unknown_and_waitlisted_listings_may_be_included",
        "model_and_term_compatibility_requires_separate_review"))


def azure_request(filters: Mapping[str, Any] | None) -> ReadRequest:
    options = dict(filters or {})
    if set(options) - {"region", "sku", "sku_prefix", "max_pages"}:
        raise ConnectorError("azure_collection_option_not_allowed")
    region, sku, prefix = options.get("region"), options.get("sku"), options.get("sku_prefix", "Standard_N")
    if not isinstance(region, str) or not re.fullmatch(r"[a-z0-9]{1,64}", region):
        raise ConnectorError("azure_explicit_region_required")
    if not isinstance(prefix, str) or not re.fullmatch(r"Standard_[A-Za-z][A-Za-z0-9_.-]{0,100}", prefix):
        raise ConnectorError("azure_sku_prefix_invalid")
    if sku is not None and (not isinstance(sku, str) or not re.fullmatch(r"Standard_[A-Za-z0-9_.-]{1,100}", sku) or not sku.startswith(prefix)):
        raise ConnectorError("azure_gpu_family_sku_required")
    max_pages = options.get("max_pages", 3)
    if type(max_pages) is not int or not 1 <= max_pages <= 5:
        raise ConnectorError("azure_pagination_budget_invalid")
    gpu_filter = "armSkuName eq '" + sku + "'" if sku else "startswith(armSkuName, '" + prefix + "')"
    expression = "serviceName eq 'Virtual Machines' and priceType eq 'Consumption' and armRegionName eq '" + region + "' and " + gpu_filter
    query = urllib.parse.urlencode({"api-version": "2023-01-01-preview", "currencyCode": "'USD'",
                                   "meterRegion": "'primary'", "$filter": expression})
    return ReadRequest(SOURCE_SPECS["azure"], "https://prices.azure.com/api/retail/prices?" + query)


def parse_azure(raw: RawResponse, policy: SourcePolicy, *, sku_prefix: str = "Standard_N") -> ConnectorBatch:
    if raw.source_id != "azure" or policy.source_id != "azure":
        raise ConnectorError("source_policy_mismatch")
    policy.require("benchmark", parse_utc(raw.captured_at))
    if not isinstance(sku_prefix, str) or not re.fullmatch(r"Standard_[A-Za-z][A-Za-z0-9_.-]{0,100}", sku_prefix):
        raise ConnectorError("azure_sku_prefix_invalid")
    payload = json_payload(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("Items"), list) or "NextPageLink" not in payload:
        raise ConnectorError("azure_catalog_shape_changed")
    rows, exclusions = [], []
    for position, meter in enumerate(payload["Items"]):
        if not isinstance(meter, dict):
            raise ConnectorError("invalid_azure_meter")
        sku = meter.get("armSkuName")
        if not isinstance(sku, str) or not sku.startswith(sku_prefix):
            exclusions.append({"row": position, "reason": "outside_requested_sku_prefix"})
            continue
        if (meter.get("serviceName") != "Virtual Machines" or meter.get("type") != "Consumption"
                or meter.get("unitOfMeasure") != "1 Hour" or meter.get("isPrimaryMeterRegion") is not True
                or meter.get("currencyCode") != "USD" or decimal_value(meter.get("tierMinimumUnits")) != 0):
            exclusions.append({"row": position, "reason": "non_base_hourly_consumption_meter"})
            continue
        if not all(isinstance(meter.get(key), str) and meter[key] for key in ("meterId", "skuId", "armRegionName", "productName", "meterName")):
            raise ConnectorError("azure_meter_identity_missing")
        amount = decimal_value(meter.get("retailPrice"))
        effective = meter.get("effectiveStartDate")
        if effective is not None and parse_utc(effective) > parse_utc(raw.captured_at):
            exclusions.append({"row": position, "reason": "future_effective_price"})
            continue
        label = " ".join(str(meter.get(key, "")) for key in ("productName", "skuName", "meterName"))
        billing = "SPOT" if "spot" in label.lower() else "LOW_PRIORITY" if "low priority" in label.lower() else "ON_DEMAND"
        item = _observation(raw, policy, key=meter["meterId"] + "|" + meter["skuId"] + "|" + raw.captured_at,
            kind="listing_ask", amount=amount, unit="node_hour", model=None,
            observed=parse_utc(raw.captured_at), side="ask", provider_group_id="microsoft-azure",
            extensions={"source_row": meter, "cloud_sku": sku, "provider_region": meter["armRegionName"],
                "requested_sku_prefix": sku_prefix, "hardware_class_not_inferred_from_sku": True,
                "provider_location_label": meter.get("location"), "billing_type": billing,
                "effective_start_date": effective, "price_scope": "retail_vm_meter_hour", "os_license_variant": meter["productName"],
                "gpu_model_and_count": "not_in_price_api_response", "availability": "not_verified_rentable",
                "normalization_blockers": ["gpu_model_unknown", "gpu_count_unknown", "country_not_independently_mapped", "inventory_and_delivery_rights_unknown"],
                "discounts_taxes_storage_transfer_and_contract_rates_not_assumed_included": True})
        item["offer_id"] = "azure-meter-" + hashlib.sha256((meter["meterId"] + "|" + meter["skuId"]).encode()).hexdigest()[:24]
        rows.append(item)
    next_page = payload["NextPageLink"]
    if next_page is not None and not isinstance(next_page, str):
        raise ConnectorError("azure_next_page_invalid")
    return ConnectorBatch("azure", raw.metadata(), tuple(rows), warnings=("retail_cloud_vm_price_not_verified_inventory_or_gpu_hour",),
        coverage={"complete": not bool(next_page), "rows_received": len(payload["Items"]), "rows_accepted": len(rows),
                  "exclusions": exclusions, "next_page_present": bool(next_page), "request_count": 1})


def parse_ecb(raw: RawResponse, policy: SourcePolicy) -> ConnectorBatch:
    if raw.source_id != "ecb" or policy.source_id != "ecb":
        raise ConnectorError("source_policy_mismatch")
    policy.require("benchmark", parse_utc(raw.captured_at))
    if len(raw.body) > 256 * 1024:
        raise ConnectorError("ecb_xml_resource_or_entity_forbidden")
    def refuse_declaration(*_args):
        raise ConnectorError("ecb_xml_resource_or_entity_forbidden")
    validator = xml.parsers.expat.ParserCreate()
    validator.StartDoctypeDeclHandler = refuse_declaration
    validator.EntityDeclHandler = refuse_declaration
    validator.UnparsedEntityDeclHandler = refuse_declaration
    validator.ExternalEntityRefHandler = refuse_declaration
    try:
        # Encoding-aware callbacks run before any DTD/entity expansion. A byte
        # substring scan misses UTF-16 declarations accepted by XML parsers.
        validator.Parse(raw.body, True)
        root = ET.fromstring(raw.body)
    except (xml.parsers.expat.ExpatError, ET.ParseError):
        raise ConnectorError("invalid_ecb_xml") from None
    namespace = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"
    if root.tag != "{http://www.gesmes.org/xml/2002-08-01}Envelope":
        raise ConnectorError("ecb_daily_envelope_shape_changed")
    containers = root.findall(namespace + "Cube")
    periods = containers[0].findall(namespace + "Cube") if len(containers) == 1 else []
    if len(periods) != 1 or "time" not in periods[0].attrib:
        raise ConnectorError("ecb_daily_period_shape_changed")
    period = periods[0]
    try:
        day = dt.date.fromisoformat(period.attrib["time"])
    except (KeyError, ValueError):
        raise ConnectorError("invalid_ecb_observation_date") from None
    captured = parse_utc(raw.captured_at)
    if day > captured.date():
        raise ConnectorError("future_source_observation")
    currencies, rows = set(), []
    for cube in period.findall(namespace + "Cube"):
        if len(cube):
            raise ConnectorError("ecb_currency_shape_changed")
        currency = cube.attrib.get("currency")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency) or currency == "EUR" or currency in currencies:
            raise ConnectorError("ecb_currency_duplicate_or_invalid")
        currencies.add(currency)
        rate = decimal_value(cube.attrib.get("rate"), positive=True)
        expired = dt.datetime.combine(day, dt.time(), tzinfo=UTC) + dt.timedelta(seconds=policy.max_age_s) <= captured
        rows.append({"schema_version": "reference-fx/1.0", "source_id": "ecb", "base_currency": "EUR", "quote_currency": currency,
            "quote_per_base": decimal_string(rate), "unit": currency + "_per_EUR", "observed_date": day.isoformat(),
            "observed_time": None, "captured_at": raw.captured_at, "status": "stale" if expired else "claimed",
            "role": "informational_reference_fx", "transaction_quote": False, "execution_enabled": False,
            "attribution": policy.attribution, "raw_sha256": raw.sha256, "rights": _permission(policy),
            "source_free_notice": "ECB reference data is available free of charge from the ECB website",
            "derived_or_modified": False})
    if len(period) != len(rows):
        raise ConnectorError("ecb_currency_shape_changed")
    if not rows:
        raise ConnectorError("empty_ecb_rates")
    return ConnectorBatch("ecb", raw.metadata(), (), catalog_records=tuple(rows),
        warnings=("reference_fx_not_transaction_or_settlement_quote", "no_implicit_currency_conversion", "source_observation_time_not_published"),
        coverage={"complete": True, "population": "published_latest_daily_ecb_reference_currencies", "rows_received": len(rows), "request_count": 1})


def parse_vast(raw: RawResponse, policy: SourcePolicy) -> ConnectorBatch:
    if raw.source_id != "vast" or policy.source_id != "vast":
        raise ConnectorError("source_policy_mismatch")
    policy.require("benchmark", parse_utc(raw.captured_at))
    payload = json_payload(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("offers"), list):
        raise ConnectorError("vast_offer_shape_changed")
    observations = []
    seen = set()
    for offer in payload["offers"]:
        if not isinstance(offer, dict) or not isinstance(offer.get("gpu_name"), str) or offer.get("id") is None:
            raise ConnectorError("invalid_vast_offer")
        offer_id = str(offer["id"])
        if offer_id in seen:
            raise ConnectorError("duplicate_vast_offer")
        seen.add(offer_id)
        count = integer_value(offer.get("num_gpus"), positive=True)
        amount = decimal_value(offer.get("dph_total"))
        # dph_total is a whole bundle rate; disk/transfer ancillary rates remain explicit.
        observation = _observation(raw, policy, key=offer_id + "|" + raw.captured_at, kind="listing_ask",
            amount=amount, unit="node_hour", model=offer["gpu_name"], observed=parse_utc(raw.captured_at),
            accelerator_count=count, side="ask", extensions={"source_row": offer,
                "price_scope": "advertised_bundle_dph_total", "availability": "source_claim_only",
                "transfer_and_storage_usage_costs_not_assumed_included": True,
                "raw_location_not_normalized": offer.get("geolocation"),
                "rentable_claim": offer.get("rentable"), "rented_claim": offer.get("rented"),
                "reliability_claim": offer.get("reliability")})
        observation["offer_id"] = "vast-offer-" + hashlib.sha256(offer_id.encode()).hexdigest()[:24]
        observations.append(observation)
    return ConnectorBatch(policy.source_id, raw.metadata(), tuple(observations), warnings=(
        "bundle_rate_not_gpu_only_rate", "listing_claims_not_verified_executable_capacity"))


OPENROUTER_PRICE_FIELDS = frozenset({"prompt", "completion", "request", "image", "web_search", "internal_reasoning",
    "input_cache_read", "input_cache_write", "input_audio", "output_audio", "input_audio_cache"})
OPENROUTER_CONDITION_FIELDS = frozenset({"min_prompt_tokens", "utc_start", "utc_end", "utc_days"})


def _openrouter_validate_rate(field: str, value: Any) -> None:
    amount = decimal_value(value)
    decimal_string(amount)
    if field in {"prompt", "completion"}:
        # Validate the actual observation representation before catalog
        # admission. A bounded per-token amount may exceed its output budget
        # after exact per-million scaling; that model must remain unpriced.
        decimal_string(per_million(amount))


def _openrouter_price_quality(pricing: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate rate claims without assigning meaning to negative sentinels.

    A model with an unsupported rate is discovery metadata only. Other pricing
    fields remain workload-specific; this helper never evaluates an override.
    """
    invalid = []
    if len(pricing) > 128:
        return [{"dimension": "pricing", "code": "price_dimension_budget"}]
    for field, value in pricing.items():
        if field == "overrides":
            continue
        try:
            _openrouter_validate_rate(field, value)
        except ConnectorError as error:
            invalid.append({"dimension": field, "code": error.code})
    if "overrides" in pricing:
        overrides = pricing["overrides"]
        if not isinstance(overrides, list) or len(overrides) > 128:
            invalid.append({"dimension": "overrides", "code": "invalid_override_list_or_budget"})
        else:
            for index, override in enumerate(overrides):
                if not isinstance(override, dict) or len(override) > 128:
                    invalid.append({"dimension": f"overrides[{index}]", "code": "invalid_override_record_or_budget"})
                    continue
                rate_fields = (OPENROUTER_PRICE_FIELDS | set(pricing)) - {"overrides"} - OPENROUTER_CONDITION_FIELDS
                for field in set(override) & rate_fields:
                    try:
                        _openrouter_validate_rate(field, override[field])
                    except ConnectorError as error:
                        invalid.append({"dimension": f"overrides[{index}].{field}", "code": error.code})
    return sorted(invalid, key=lambda item: item["dimension"])


def parse_openrouter(raw: RawResponse, policy: SourcePolicy) -> ConnectorBatch:
    if raw.source_id != "openrouter" or policy.source_id != "openrouter":
        raise ConnectorError("source_policy_mismatch")
    policy.require("benchmark", parse_utc(raw.captured_at))
    payload = json_payload(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ConnectorError("model_catalog_shape_changed")
    observations, catalog, seen, excluded = [], [], set(), []
    for model in payload["data"]:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not isinstance(model.get("pricing"), dict):
            raise ConnectorError("invalid_model_catalog_entry")
        model_id = model["id"]
        if not model_id or len(model_id) > 256 or model_id in seen:
            raise ConnectorError("duplicate_or_missing_model_id")
        seen.add(model_id)
        retained = {key: model[key] for key in ("id", "canonical_slug", "name", "created", "context_length",
            "architecture", "top_provider", "per_request_limits", "supported_parameters", "expiration_date") if key in model}
        invalid_dimensions = _openrouter_price_quality(model["pricing"])
        # Invalid monetary claims are never persisted as rates or substituted
        # with zero. The source hash and safe dimension codes explain the hold.
        retained["pricing"] = None if invalid_dimensions else model["pricing"]
        unknown = sorted(set(model) - set(retained) - {"description", "benchmarks", "links"})
        conditional = bool(model["pricing"].get("overrides"))
        available = [field for field in ("prompt", "completion") if field in model["pricing"]]
        price_status = "unpriced_invalid_advertised_dimensions" if invalid_dimensions else "unpriced_missing_token_rates" if not available else "partial_token_rates" if len(available) < 2 else "advertised_token_rates"
        if invalid_dimensions:
            excluded.append({"model_id": model_id, "invalid_dimensions": invalid_dimensions})
        catalog.append(_jsonable({"source_id": "openrouter", "kind": "model_price_catalog", "model_id": model_id,
            "observed_at": raw.captured_at, "expires_at": utc_string(parse_utc(raw.captured_at) + dt.timedelta(seconds=policy.max_age_s)),
            "status": "claimed", "metadata": retained, "unknown_field_names": unknown,
            "price_status": price_status, "price_eligible": bool(available) and not invalid_dimensions,
            "invalid_dimensions": invalid_dimensions,
            "base_rate_basis": "advertised_current_default_conditions", "conditional_pricing_present": conditional,
            "qualification_verified": False, "gpu_hour_benchmark_eligible": False, "execution_enabled": False,
            "rights": _permission(policy), "attribution": policy.attribution,
            "evidence": {"artifact_sha256": raw.sha256, "accessed_at": raw.captured_at, "locator": raw.endpoint_path}}))
        if invalid_dimensions:
            continue
        for field, unit in (("prompt", "input_million_tokens"), ("completion", "output_million_tokens")):
            if field not in model["pricing"]:
                continue  # No invented zero or old fixture fallback.
            amount = per_million(decimal_value(model["pricing"][field]))
            observations.append(_observation(raw, policy, key=model_id + "|" + field + "|" + raw.captured_at,
                kind="model_token_price", amount=amount, unit=unit, model=model_id,
                observed=parse_utc(raw.captured_at), side="ask", extensions={"model_metadata": retained,
                    "pricing_dimension": field, "catalog_price_not_provider_pinned_quote": True,
                    "pricing_conditions_present": conditional, "base_rate_basis": "advertised_current_default_conditions",
                    "pricing_overrides_unapplied": model["pricing"].get("overrides", []),
                    "other_billing_dimensions_require_separate_workload_costs": True,
                    "unknown_field_names": unknown, "privacy_and_route_compatibility_not_assumed": True}))
    warnings = ("token_prices_never_enter_gpu_hour_index",
            "current_default_catalog_rates_not_future_pinned_route_quotes",
            "conditional_cache_request_media_and_other_rates_require_workload_and_time_qualification")
    if excluded:
        warnings += ("invalid_advertised_rates_quarantined_as_unpriced_catalog_metadata",)
    return ConnectorBatch(policy.source_id, raw.metadata(), tuple(observations),
        catalog_records=tuple(catalog), warnings=warnings, coverage={
            "price_coverage_complete": not excluded and all(row["price_status"] == "advertised_token_rates" for row in catalog),
            "models_with_token_rates": sum(row["price_eligible"] for row in catalog),
            "models_without_token_rates": sum(not row["price_eligible"] for row in catalog),
            "models_with_partial_token_rates": sum(row["price_status"] == "partial_token_rates" for row in catalog),
            "invalid_price_model_count": len(excluded),
            "invalid_price_dimension_count": sum(len(row["invalid_dimensions"]) for row in excluded),
            "price_exclusions": excluded})


@dataclasses.dataclass(frozen=True)
class SourceAdapter:
    source_id: str
    role: str
    docs_url: str
    normalization: str
    unavailable_reason: str | None = None

    def request(self, *, filters: Mapping[str, Any] | None = None, limit: int = 100) -> ReadRequest:
        if self.source_id not in SOURCE_SPECS:
            raise ConnectorError("source_transport_not_implemented")
        spec = SOURCE_SPECS[self.source_id]
        if self.source_id == "gpuhunt_catalog":
            from .gpuhunt import gpuhunt_request
            return gpuhunt_request(filters)
        if self.source_id == "energinet_day_ahead":
            from .energy import energinet_request
            return energinet_request(filters)
        if self.source_id == "azure":
            return azure_request(filters)
        if self.source_id == "aws_public_pricing":
            from .aws import aws_request
            return aws_request(filters)
        if self.source_id == "openrouter":
            from .openrouter import openrouter_request
            return openrouter_request(filters)
        if self.source_id == "huggingface_catalog":
            from .huggingface_catalog import catalog_request
            return catalog_request(filters)
        if self.source_id == "oracle":
            options = dict(filters or {})
            if set(options) != {"partNumber", "currencyCode"} or not isinstance(options["partNumber"], str) or not re.fullmatch(r"B[0-9]{3,12}", options["partNumber"]) or not isinstance(options["currencyCode"], str) or not re.fullmatch(r"[A-Z]{3}", options["currencyCode"]):
                raise ConnectorError("oracle_explicit_part_currency_required")
            return ReadRequest(spec, "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/?" + urllib.parse.urlencode(options))
        if self.source_id == "ecb":
            if filters:
                raise ConnectorError("ecb_daily_request_has_no_filters")
            return ReadRequest(spec, "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml")
        if self.source_id == "scaleway":
            query = urllib.parse.urlencode(dict(filters or {"page": 1, "page_size": 100}))
            return ReadRequest(spec, "https://api.scaleway.com/product-catalog/v2alpha1/public-catalog/products?" + query)
        if self.source_id == "huggingface":
            from .huggingface import huggingface_query
            query = urllib.parse.urlencode(huggingface_query(filters))
            return ReadRequest(spec, "https://huggingface.co/api/models?" + query)
        if self.source_id == "vast":
            payload = {"limit": limit, "type": "on-demand", **dict(filters or {})}
            return ReadRequest(spec, "https://" + spec.host + "/api/v0/bundles", payload)
        paths = {"getdeploying": "/dataset/gpu-prices/weekly.csv", "openrouter": "/api/v1/models",
                 "runpod": "/v2/catalog/gpus", "kalshi": "/trade-api/v2/markets"}
        query = urllib.parse.urlencode(dict(filters or {}), doseq=False)
        return ReadRequest(spec, "https://" + spec.host + paths[self.source_id] + ("?" + query if query else ""))

    def parse(self, raw: RawResponse, policy: SourcePolicy, *, filters: Mapping[str, Any] | None = None) -> ConnectorBatch:
        if raw.source_id != self.source_id or policy.source_id != self.source_id:
            raise ConnectorError("source_policy_mismatch")
        if self.source_id == "gpuhunt_catalog":
            from .gpuhunt import parse_gpuhunt
            if not isinstance(filters, Mapping) or "version" not in filters:
                raise ConnectorError("gpuhunt_pinned_parse_version_required")
            return parse_gpuhunt(raw, policy, filters=filters, version=filters["version"])
        if self.source_id == "energinet_day_ahead":
            from .energy import parse_energinet
            return parse_energinet(raw, policy, filters=filters)
        if self.source_id == "huggingface":
            from .huggingface import parse_huggingface
            return parse_huggingface(raw, policy)
        parser = {"getdeploying": parse_getdeploying, "vast": parse_vast, "openrouter": parse_openrouter,
                  "azure": parse_azure, "ecb": parse_ecb}.get(self.source_id)
        if parser:
            return parser(raw, policy)
        # Unit/specification/legal review must finish before normalizing other feeds.
        return ConnectorBatch(self.source_id, raw.metadata(), (), warnings=("normalization_not_admitted",))


ADAPTERS = {adapter.source_id: adapter for adapter in (
    SourceAdapter("gpuhunt_catalog", "publisher_gpu_vm_reference", "https://github.com/dstackai/gpuhunt", "implemented"),
    SourceAdapter("gcp_cloud_billing", "direct_vendor_sku_tariff", "https://docs.cloud.google.com/billing/v1/how-tos/catalog-api", "not_implemented", "api_key_and_bounded_read_contract_required"),
    SourceAdapter("skypilot_catalog", "publisher_gpu_vm_reference", "https://github.com/skypilot-org/skypilot-catalog", "rights_review_pending", "catalog_data_license_unresolved"),
    SourceAdapter("energinet_day_ahead", "energy_market_reference", "https://www.energidataservice.dk/guides/api-guides", "implemented"),
    SourceAdapter("huggingface_catalog", "model_recipe_metadata", "https://huggingface.co/docs/inference-endpoints/en/api_reference", "implemented"),
    SourceAdapter("aws_public_pricing", "native_cloud_meter_tariff", "https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html", "implemented"),
    SourceAdapter("aws_ec2", "cloud_vm_list_price", "https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api-fetching-price-list-files-manually.html", "not_implemented", "bounded_file_or_authenticated_query_required"),
    SourceAdapter("oracle", "native_product_price_catalog", "https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/signingup_topic-Estimating_Costs.htm", "rights_review_pending", "commercial_retention_use_permission_required"),
    SourceAdapter("ovhcloud", "public_cloud_catalog", "https://www.ovhcloud.com/en/public-cloud/prices/", "not_implemented", "documented_catalog_reuse_rights_required"),
    SourceAdapter("azure", "cloud_vm_list_price", "https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices", "implemented"),
    SourceAdapter("ecb", "reference_fx", "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html", "implemented"),
    SourceAdapter("scaleway", "public_cloud_catalog", "https://www.scaleway.com/en/developers/api/product-catalog/public-catalog", "rights_review_pending"),
    SourceAdapter("huggingface", "model_metadata", "https://huggingface.co/docs/hub/en/api", "implemented"),
    SourceAdapter("getdeploying", "aggregate_advertised_index", "https://getdeploying.com/dataset/gpu-prices", "implemented"),
    SourceAdapter("vast", "listing_ask", "https://docs.vast.ai/api-reference/search/search-offers", "implemented"),
    SourceAdapter("openrouter", "model_token_price", "https://openrouter.ai/docs/guides/overview/models", "implemented"),
    SourceAdapter("runpod", "catalog", "https://docs.runpod.io/api-reference-v2/catalog/list-gpu-types", "price_units_pending"),
    SourceAdapter("kalshi", "event_contract_price", "https://docs.kalshi.com/api-reference/market/get-markets", "rights_review_pending"),
    SourceAdapter("silicon_data", "licensed_compute_index", "https://www.silicondata.com/products/index-datasets", "not_implemented", "licensed_spec_required"),
    SourceAdapter("cme", "financial_future_mark", "https://www.cmegroup.com/market-data/market-data-api.html", "not_implemented", "licensing_and_product_liveness_required"),
    SourceAdapter("cboe", "licensed_index", "https://www.cboe.com/data/global-indices-feed/", "not_implemented", "licensed_spec_and_relevant_instrument_required"),
    SourceAdapter("liquid_ai", "model_catalog", "https://docs.liquid.ai/lfm/models/complete-library", "not_implemented", "direct_pricing_api_and_access_not_verified"),
)}


def source_status(policies: Mapping[str, SourcePolicy], now: dt.datetime | None = None) -> list[dict[str, Any]]:
    result = []
    for name, adapter in sorted(ADAPTERS.items()):
        policy = policies.get(name)
        blocked = policy.blockers("observe", now) if policy else ["source_policy_missing"]
        spec = SOURCE_SPECS.get(name)
        auth_ready = not (spec and spec.secret_env) or bool(os.environ.get(spec.secret_env))
        if not auth_ready:
            blocked.append("authentication_missing")
        if adapter.unavailable_reason:
            blocked.append(adapter.unavailable_reason)
        implementation = "candidate_only" if not spec else "implemented" if adapter.normalization == "implemented" else "schema_unverified"
        result.append({"source_id": name, "role": adapter.role, "docs_url": adapter.docs_url,
                       "implementation_state": implementation,
                       "normalization": adapter.normalization, "liveness": policy.liveness if policy else "not_verified",
                       "enabled": policy.enabled if policy else False,
                       "rights_status": policy.rights_status if policy else "pending",
                       "permissions": dict(policy.permissions) if policy else {},
                       "auth_required": bool(spec and spec.secret_env), "auth_present": auth_ready,
                       "auth_state": "not_required" if not (spec and spec.secret_env) else "present" if auth_ready else "missing",
                       "max_age_s": policy.max_age_s if policy else None,
                       "collection_parameters": {"required": ["region"], "optional": ["sku", "sku_prefix", "max_pages"], "max_pages": 5, "default_sku_prefix": "Standard_N"} if name == "azure" else {"required": ["service", "region"], "optional": ["sku"], "approved_services": ["AWSLambda", "AmazonBedrock", "AmazonECS", "AmazonLightsail", "AmazonS3", "AmazonSageMaker"], "native_units_not_gpu_hours": True} if name == "aws_public_pricing" else {"required": [], "optional": ["q", "input_modalities", "output_modalities", "offset", "limit", "max_pages"], "max_limit": 100, "max_pages": 3, "price_scope": "current_default_conditions_only"} if name == "openrouter" else {"required": ["partNumber", "currencyCode"], "optional": []} if name == "oracle" else {"required": ["limit"], "at_least_one_scope": ["task", "accelerator", "engine", "license", "search"], "optional": ["task", "accelerator", "engine", "license", "search"], "max_limit": 100, "price_eligible": False} if name == "huggingface_catalog" else {"required": ["author", "pipeline_tag", "limit", "full"], "optional": [], "max_limit": 100} if name == "huggingface" else {"required": [], "optional": []},
                       "can_attempt_read": not blocked, "blockers": blocked, "execution_enabled": False})
        if name == "energinet_day_ahead":
            result[-1]["collection_parameters"] = {"required": ["price_area", "limit"],
                "one_of_scope": [["start", "end"], ["rolling_days"]], "max_days": 7, "max_limit": 1000,
                "native_unit": "MWh", "signed_prices": True, "price_areas": ["DK1", "DK2", "DE", "NO2", "SE3", "SE4"],
                "recommended_refresh_s": 86400, "price_eligible": False}
        if name == "gpuhunt_catalog":
            result[-1]["collection_parameters"] = {"required": ["provider", "limit"],
                "one_of_scope": [["location"], ["location_prefix"]], "optional": ["gpu_name", "spot", "version"],
                "providers": ["aws", "azure", "gcp"], "max_limit": 1000, "max_scanned_rows": 100000,
                "max_archive_bytes": 2097152, "max_uncompressed_csv_bytes": 16777216,
                "price_unit": "USD_per_instance_hour", "gpu_division": "diagnostic_per_publisher_count_only",
                "direct_vendor_quotes": False, "vendor_price_age_known": False, "price_eligible": False}
        if name == "gcp_cloud_billing":
            result[-1].update(auth_required=True, auth_present=False, auth_state="not_configured")
            result[-1]["blockers"].append("authentication_missing")
            result[-1]["can_attempt_read"] = False
    return result


def collect_source(source_id: str, policies: Mapping[str, SourcePolicy], *,
                   transport: ReadOnlyTransport | None = None,
                   filters: Mapping[str, Any] | None = None) -> ConnectorBatch:
    if source_id not in ADAPTERS or source_id not in policies:
        raise ConnectorError("unknown_or_unadmitted_source")
    adapter, policy = ADAPTERS[source_id], policies[source_id]
    client = transport or ReadOnlyTransport()
    # The catalog collector returns retainable comparison data. Resolve all
    # purposes before constructing a request or processing user query filters.
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, client.clock())
    if source_id == "gpuhunt_catalog":
        from .gpuhunt import collect_gpuhunt
        return collect_gpuhunt(policy, client, filters)
    if source_id == "energinet_day_ahead":
        from .energy import collect_energinet
        return collect_energinet(policy, client, filters)
    if source_id == "huggingface_catalog":
        from .huggingface_catalog import collect_catalog
        return collect_catalog(policy, client, filters)
    if source_id == "aws_public_pricing":
        from .aws import collect_aws
        return collect_aws(policy, client, filters)
    if source_id == "openrouter":
        from .openrouter import collect_openrouter
        return collect_openrouter(policy, client, filters)
    if source_id == "azure":
        return collect_azure(policy, client, filters)
    raw = client.fetch(adapter.request(filters=filters), policy)
    batch = adapter.parse(raw, policy)
    if source_id == "huggingface":
        from .huggingface import huggingface_query
        query = huggingface_query(filters)
        if len(batch.catalog_records) > int(query["limit"]):
            raise ConnectorError("model_metadata_response_exceeds_requested_limit")
        for record in batch.catalog_records:
            if not record["model_id"].startswith(query["author"] + "/") or record.get("author") not in {None, query["author"]} or record.get("pipeline_tag") not in {None, query["pipeline_tag"]}:
                raise ConnectorError("model_metadata_response_scope_mismatch")
        unknown_tags = sum(record.get("pipeline_tag") is None for record in batch.catalog_records)
        batch = dataclasses.replace(batch, coverage={**batch.coverage, "request_scope": query,
            "maximum_records": int(query["limit"]), "missing_pipeline_tags": unknown_tags},
            warnings=batch.warnings + (("missing_pipeline_tag_remains_unqualified_metadata",) if unknown_tags else ()))
    return batch


def collect_azure(policy: SourcePolicy, transport: ReadOnlyTransport,
                  filters: Mapping[str, Any] | None) -> ConnectorBatch:
    request = azure_request(filters)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.url).query))
    options = dict(filters or {})
    max_pages = options.get("max_pages", 3)
    observations, pages, exclusions, seen, total_rows, total_bytes = [], [], [], set(), 0, 0
    current_skip, complete = 0, False
    for page in range(max_pages):
        if page:
            transport.wait_for_source("azure", max_wait_s=transport.max_wait_s)
        raw = transport.fetch(request, policy)
        batch = parse_azure(raw, policy, sku_prefix=options.get("sku_prefix", "Standard_N"))
        total_bytes += len(raw.body)
        if total_bytes > 8 * 1024 * 1024:
            raise ConnectorError("azure_collection_size_budget")
        pages.append(raw.metadata())
        total_rows += batch.coverage["rows_received"]
        exclusions.extend({**record, "page": page + 1} for record in batch.coverage["exclusions"])
        for item in batch.observations:
            meter = item["extensions"]["source_row"]
            identity = (meter["meterId"], meter["skuId"], meter["armRegionName"])
            if identity in seen:
                raise ConnectorError("duplicate_azure_meter_across_pages")
            if meter["armRegionName"] != options["region"] or options.get("sku") is not None and meter["armSkuName"] != options["sku"]:
                raise ConnectorError("azure_response_scope_mismatch")
            seen.add(identity)
            observations.append(item)
        next_page = json_payload(raw)["NextPageLink"]
        if not next_page:
            complete = True
            break
        candidate = ReadRequest(SOURCE_SPECS["azure"], next_page)
        candidate.validate()
        next_query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(next_page).query))
        if next_query.get("$filter") != query["$filter"]:
            raise ConnectorError("azure_pagination_scope_changed")
        for key in ("currencyCode", "api-version", "meterRegion"):
            if key in next_query and next_query[key] != query[key]:
                raise ConnectorError("azure_pagination_contract_changed")
        try:
            next_skip = int(next_query["$skip"])
        except (KeyError, ValueError):
            raise ConnectorError("azure_pagination_cursor_invalid") from None
        if next_skip <= current_skip:
            raise ConnectorError("azure_pagination_cursor_not_advancing")
        current_skip, request = next_skip, candidate
    metadata = {**pages[0], "pages": pages, "total_bytes": total_bytes,
                "sha256": hashlib.sha256("|".join(page["sha256"] for page in pages).encode()).hexdigest(),
                "sha256_scope": "ordered_page_content_hashes"}
    coverage = {"complete": complete, "pagination_truncated": not complete,
                "completion_basis": "provider_next_page_contract", "request_count": len(pages),
                "rows_received": total_rows, "rows_accepted": len(observations), "exclusions": exclusions,
                "scope": {"provider": "Azure", "region": options["region"], "sku": options.get("sku"),
                          "family": options.get("sku_prefix", "Standard_N"), "price_type": "Consumption", "meter_region": "primary", "currency": "USD"},
                "all_market_inventory": False, "gpu_model_mapping_complete": False}
    warnings = ["retail_cloud_vm_price_not_verified_inventory_or_gpu_hour", "gpu_model_and_count_require_separate_specification_join"]
    if not complete:
        warnings.append("pagination_budget_reached_partial_scoped_catalog")
    return ConnectorBatch("azure", metadata, tuple(observations), warnings=tuple(warnings), coverage=coverage)
