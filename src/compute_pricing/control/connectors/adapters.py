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
    try:
        return json.loads(raw.body.decode("utf-8"), parse_float=Decimal,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeDecodeError, ValueError):
        raise ConnectorError("invalid_json_response") from None


@dataclasses.dataclass(frozen=True)
class ConnectorBatch:
    source_id: str
    raw_metadata: Mapping[str, Any]
    observations: tuple[Mapping[str, Any], ...]
    catalog_records: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({"source_id": self.source_id, "raw_metadata": dict(self.raw_metadata),
                "observations": list(self.observations), "catalog_records": list(self.catalog_records),
                "warnings": list(self.warnings), "execution_enabled": False})


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
                 amount: Decimal, unit: str, model: str, observed: dt.datetime,
                 accelerator_count: int | None = None, side: str = "mark",
                 provider_group_id: str | None = None, region: str | None = None,
                 extensions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    captured = parse_utc(raw.captured_at)
    if observed > captured:
        raise ConnectorError("future_source_observation")
    expires = observed + dt.timedelta(seconds=policy.max_age_s)
    id_digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return {
        "schema_version": "1.0.0", "source_version": "adapter-contract/1.0",
        "id": f"{policy.source_id}-{id_digest}", "source_id": policy.source_id,
        "offer_id": None, "lot_id": None, "provider_group_id": provider_group_id,
        "kind": kind, "price": {"amount": decimal_string(amount), "currency": "USD", "unit": unit},
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
        "extensions": {"attribution": policy.attribution, "executable": False,
                       "source_claim_not_independent_verification": True, **(extensions or {})},
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


def parse_openrouter(raw: RawResponse, policy: SourcePolicy) -> ConnectorBatch:
    if raw.source_id != "openrouter" or policy.source_id != "openrouter":
        raise ConnectorError("source_policy_mismatch")
    policy.require("benchmark", parse_utc(raw.captured_at))
    payload = json_payload(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ConnectorError("model_catalog_shape_changed")
    observations, seen = [], set()
    for model in payload["data"]:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not isinstance(model.get("pricing"), dict):
            raise ConnectorError("invalid_model_catalog_entry")
        model_id = model["id"]
        if not model_id or model_id in seen:
            raise ConnectorError("duplicate_or_missing_model_id")
        seen.add(model_id)
        for field, unit in (("prompt", "input_million_tokens"), ("completion", "output_million_tokens")):
            if field not in model["pricing"]:
                continue  # No invented zero or old fixture fallback.
            amount = per_million(decimal_value(model["pricing"][field]))
            observations.append(_observation(raw, policy, key=model_id + "|" + field + "|" + raw.captured_at,
                kind="model_token_price", amount=amount, unit=unit, model=model_id,
                observed=parse_utc(raw.captured_at), side="ask", extensions={"source_row": model,
                    "pricing_dimension": field, "catalog_price_not_provider_pinned_quote": True,
                    "privacy_and_route_compatibility_not_assumed": True}))
    return ConnectorBatch(policy.source_id, raw.metadata(), tuple(observations),
        catalog_records=tuple(payload["data"]), warnings=("token_prices_never_enter_gpu_hour_index",))


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
        if self.source_id == "vast":
            payload = {"limit": limit, "type": "on-demand", **dict(filters or {})}
            return ReadRequest(spec, "https://" + spec.host + "/api/v0/bundles", payload)
        paths = {"getdeploying": "/dataset/gpu-prices/weekly.csv", "openrouter": "/api/v1/models",
                 "runpod": "/v2/catalog/gpus", "kalshi": "/trade-api/v2/markets"}
        query = urllib.parse.urlencode(dict(filters or {}), doseq=False)
        return ReadRequest(spec, "https://" + spec.host + paths[self.source_id] + ("?" + query if query else ""))

    def parse(self, raw: RawResponse, policy: SourcePolicy) -> ConnectorBatch:
        if raw.source_id != self.source_id or policy.source_id != self.source_id:
            raise ConnectorError("source_policy_mismatch")
        parser = {"getdeploying": parse_getdeploying, "vast": parse_vast, "openrouter": parse_openrouter}.get(self.source_id)
        if parser:
            return parser(raw, policy)
        # Unit/specification/legal review must finish before normalizing other feeds.
        return ConnectorBatch(self.source_id, raw.metadata(), (), warnings=("normalization_not_admitted",))


ADAPTERS = {adapter.source_id: adapter for adapter in (
    SourceAdapter("getdeploying", "aggregate_advertised_index", "https://getdeploying.com/dataset/gpu-prices", "implemented"),
    SourceAdapter("vast", "listing_ask", "https://docs.vast.ai/api-reference/search/search-offers", "implemented"),
    SourceAdapter("openrouter", "model_token_price", "https://openrouter.ai/docs/api/api-reference/models/get-models", "implemented"),
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
                       "can_attempt_read": not blocked, "blockers": blocked, "execution_enabled": False})
    return result


def collect_source(source_id: str, policies: Mapping[str, SourcePolicy], *,
                   transport: ReadOnlyTransport | None = None,
                   filters: Mapping[str, Any] | None = None) -> ConnectorBatch:
    if source_id not in ADAPTERS or source_id not in policies:
        raise ConnectorError("unknown_or_unadmitted_source")
    adapter, policy = ADAPTERS[source_id], policies[source_id]
    raw = (transport or ReadOnlyTransport()).fetch(adapter.request(filters=filters), policy)
    return adapter.parse(raw, policy)
