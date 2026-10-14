"""Explicit comparable books; commitment references are not forward markets.

All evidence and permissions in this offline request are caller declarations.
Even a mathematically comparable two-sided book supplies neither an admitted
source, owned inventory nor execution authority.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, localcontext
import re

from compute_pricing.control._numbers import calculation_precision, digest, number, text_number
from compute_pricing.control.domain import ValidationError, exact_decimal, utc_instant
from compute_pricing.control.domain.spec import ID_PATTERN


VERSION = "comparable-quotes/1.0.0"
ROLES = {"spot", "physical_forward", "financial_future", "advertised_commitment"}
_COMMON = {"product_role", "hardware_model", "configuration", "region", "delivery_start", "delivery_end",
           "commitment_months", "payment_terms", "cost_scope", "unit", "currency", "quantity_unit", "contract_spec"}
_TARGET = _COMMON | {"provider_scope", "quantity"}
_QUOTE = _COMMON | {"id", "source_id", "provider_id", "side", "price", "available_quantity", "minimum_quantity",
                     "observed_at", "expires_at", "status", "quote_type", "evidence_ref", "rights", "source_quality"}
_CONFIG_NUMBERS = {"cpu_cores", "ram_gib", "storage_gib", "network_gbps",
                   "accelerator_memory_gib", "accelerators_per_node"}
_CONFIG_LABELS = {"interconnect", "privacy_class", "tenancy"}
_CONFIG = _CONFIG_NUMBERS | _CONFIG_LABELS
_COST = {"power", "network", "support", "taxes", "platform_fees"}
_REGION = {"scope", "country_code", "subdivision", "locality"}
_RIGHTS = {"status", "observe", "retain", "benchmark", "execution", "verified_by", "expires_at"}
_SPEC = {"id", "settlement", "multiplier", "multiplier_unit", "expires_at"}


def quote_contract() -> dict:
    target = {name: None for name in sorted(_TARGET)}
    target.update(configuration={name: None for name in sorted(_CONFIG)},
        cost_scope={name: None for name in sorted(_COST)},
        provider_scope={"kind": None, "provider_id": None})
    quote = {name: None for name in sorted(_QUOTE)}
    quote.update(configuration={name: None for name in sorted(_CONFIG)},
        cost_scope={name: None for name in sorted(_COST)},
        rights={name: None for name in sorted(_RIGHTS)})
    return {
        "schema_version": VERSION, "request_fields": ["as_of", "max_age_seconds", "target", "quotes"],
        "target_fields": sorted(_TARGET), "quote_fields": sorted(_QUOTE),
        "product_roles": sorted(ROLES), "configuration_fields": sorted(_CONFIG),
        "region_fields": sorted(_REGION), "cost_scope_fields": sorted(_COST),
        "rights_fields": sorted(_RIGHTS), "contract_spec_fields": sorted(_SPEC),
        "configuration_numeric_fields": sorted(_CONFIG_NUMBERS),
        "cost_scope_values": ["included", "excluded", "not_applicable", "unknown"],
        "provider_scope": {"fields": ["kind", "provider_id"],
                           "kind": ["single_provider", "all_declared_providers"]},
        "units": ["gpu_hour", "node_hour", "contract"], "quantity_units": ["gpu", "node", "contract"],
        "quote_types": ["firm", "indicative", "advertised"], "statuses": ["claimed", "verified", "stale", "rejected"],
        "decimal_encoding": "finite_plain_decimal_strings", "missing_is_known": False,
        "template_unknown": {"as_of": None, "max_age_seconds": None, "target": target, "quotes": []},
        "quote_template_unknown": quote, "source_evidence_eligible": False,
        "midpoint_basis": "(highest_comparable_bid+lowest_comparable_ask)/2",
        "price_weighting": "none_best_price_not_source_quality_weighted",
        "advertised_reference_basis": "unweighted_median_comparable_advertised_asks_never_a_midpoint",
        "inventory_verified": False, "firm_price_eligible": False, "execution_enabled": False,
        "source_evidence_basis": "caller_declared_not_server_admitted",
        "rules": [
            "all_required_terms_explicit_unknown_terms_hold",
            "no_implicit_currency_unit_configuration_or_payment_conversion",
            "physical_delivery_intervals_must_match_exactly",
            "physical_gpu_quantities_and_quote_size_bounds_must_be_whole_node_allocations",
            "spot_interval_contains_as_of_physical_forward_starts_after_as_of",
            "advertised_commitment_has_explicit_month_tenor_and_no_delivery_window",
            "financial_future_requires_cash_settlement_multiplier_spec_and_unexpired_contract",
            "reference_tenor_never_infers_future_start_delivery_or_tradable_inventory",
            "firm_two_sided_quotes_require_declared_verified_evidence_and_execution_permission",
            "crossed_and_one_sided_books_have_no_midpoint",
            "permissions_and_evidence_still_require_server_binding_before_firm_use",
        ],
    }


def _shape(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(f"{label}: exact explicit contract fields required")


def _text(value, label, reasons, *, identity=False):
    if value is None or value == "":
        reasons.append(label + "_unknown")
        return None
    if not isinstance(value, str) or len(value) > 512 or value != value.strip():
        raise ValidationError(f"{label}: bounded plain text required")
    if identity and (len(value) > 128 or not re.fullmatch(ID_PATTERN, value)):
        raise ValidationError(f"{label}: canonical identifier required")
    return value


def _choice(value, options, label, reasons):
    if value is None:
        reasons.append(label + "_unknown")
        return None
    if not isinstance(value, str) or value not in options:
        raise ValidationError(f"{label}: unsupported value")
    return value


def _terms(raw, now):
    reasons = []
    role = _choice(raw["product_role"], ROLES, "product_role", reasons)
    hardware = _text(raw["hardware_model"], "hardware_model", reasons)
    currency = _text(raw["currency"], "currency", reasons)
    if currency is not None and not re.fullmatch("[A-Z]{3}", currency):
        raise ValidationError("currency: explicit three-letter currency required")
    unit = _choice(raw["unit"], {"gpu_hour", "node_hour", "contract"}, "unit", reasons)
    quantity_unit = _choice(raw["quantity_unit"], {"gpu", "node", "contract"}, "quantity_unit", reasons)
    payment = _text(raw["payment_terms"], "payment_terms", reasons)
    config = raw["configuration"]
    if not isinstance(config, dict):
        if config is not None:
            raise ValidationError("configuration: explicit object required")
        config = {}
        reasons.append("configuration_unknown")
    elif set(config) - _CONFIG:
        reasons.append("unregistered_configuration_keys")
    normalized_config = {}
    if role != "financial_future":
        if _CONFIG - set(config):
            reasons.append("configuration_incomplete")
        for key in sorted(_CONFIG & set(config)):
            if config[key] is None:
                reasons.append("configuration_" + key + "_unknown")
                normalized_config[key] = None
            elif key in _CONFIG_NUMBERS:
                value = number(config[key], key, positive=True)
                if key == "accelerators_per_node" and value != value.to_integral_value():
                    raise ValidationError("accelerators_per_node: whole physical allocation required")
                normalized_config[key] = text_number(value)
            else:
                normalized_config[key] = _text(config[key], "configuration_" + key, reasons)
    elif config:
        reasons.append("financial_contract_configuration_not_applicable")
    region = raw["region"]
    normalized_region = None
    if role == "financial_future":
        if region is not None:
            reasons.append("financial_index_region_not_physical_delivery")
    elif region is None:
        reasons.append("region_unknown")
    else:
        _shape(region, _REGION, "region")
        scope = _choice(region["scope"], {"country", "subdivision", "locality"}, "region_scope", reasons)
        country = _text(region["country_code"], "country_code", reasons)
        if country is not None and not re.fullmatch("[A-Z]{2}", country):
            raise ValidationError("country_code: explicit two-letter code required")
        normalized_region = {"scope": scope, "country_code": country, "subdivision": None, "locality": None}
        if scope in {"subdivision", "locality"}:
            normalized_region["subdivision"] = _text(region["subdivision"], "subdivision", reasons)
        elif region["subdivision"] is not None:
            raise ValidationError("country region scope cannot contain unused subdivision")
        if scope == "locality":
            normalized_region["locality"] = _text(region["locality"], "locality", reasons)
        elif region["locality"] is not None:
            raise ValidationError("region scope cannot contain unused locality")
    costs = raw["cost_scope"]
    if costs is None:
        normalized_cost = None
        reasons.append("cost_scope_unknown")
    else:
        _shape(costs, _COST, "cost_scope")
        normalized_cost = {key: _choice(costs[key], {"included", "excluded", "not_applicable", "unknown"},
                                        "cost_scope_" + key, reasons) for key in sorted(_COST)}
        if "unknown" in normalized_cost.values():
            reasons.append("cost_scope_unknown")
    start, end = raw["delivery_start"], raw["delivery_end"]
    months = raw["commitment_months"]
    if role == "advertised_commitment":
        if start is not None or end is not None:
            reasons.append("advertised_tenor_is_not_future_start_delivery")
        if months is None:
            reasons.append("commitment_months_unknown")
        else:
            months = number(months, "commitment_months")
            if months != months.to_integral_value() or months > 1200:
                raise ValidationError("commitment_months: bounded whole month tenor required")
            months = text_number(months)
        start = end = None
    else:
        if months is not None:
            reasons.append("delivery_window_cannot_be_replaced_by_advertised_tenor")
        if start is None or end is None:
            reasons.append("delivery_window_unknown")
        else:
            begin, finish = utc_instant(start), utc_instant(end)
            if finish <= begin:
                raise ValidationError("delivery: positive explicit interval required")
            if role == "spot" and not begin <= now < finish:
                reasons.append("spot_delivery_not_current")
            elif role == "physical_forward" and begin <= now:
                reasons.append("physical_forward_not_future_start")
            elif role == "financial_future" and finish <= now:
                reasons.append("financial_settlement_window_expired")
    spec = raw["contract_spec"]
    normalized_spec = None
    if role == "financial_future":
        if quantity_unit != "contract":
            reasons.append("financial_quantity_requires_contract_units")
        if spec is None:
            reasons.append("financial_contract_spec_unknown")
        else:
            _shape(spec, _SPEC, "contract_spec")
            spec_id = _text(spec["id"], "contract_spec_id", reasons, identity=True)
            settlement = _choice(spec["settlement"], {"cash"}, "financial_settlement", reasons)
            multiplier_unit = _choice(spec["multiplier_unit"], {"gpu_hours", "contract"}, "multiplier_unit", reasons)
            multiplier = None if spec["multiplier"] is None else text_number(number(spec["multiplier"], "multiplier", positive=True))
            if multiplier is None:
                reasons.append("multiplier_unknown")
            if spec["expires_at"] is None:
                reasons.append("financial_expiry_unknown")
            elif utc_instant(spec["expires_at"]) <= now:
                reasons.append("financial_contract_expired")
            normalized_spec = {"id": spec_id, "settlement": settlement, "multiplier": multiplier,
                               "multiplier_unit": multiplier_unit, "expires_at": spec["expires_at"]}
    elif spec is not None:
        reasons.append("financial_spec_cannot_describe_physical_supply")
    if role != "financial_future" and (unit == "contract" or quantity_unit == "contract"):
        reasons.append("physical_capacity_requires_gpu_or_node_units")
    return {"product_role": role, "hardware_model": hardware, "configuration": normalized_config,
            "region": normalized_region, "delivery_start": start, "delivery_end": end,
            "commitment_months": months, "payment_terms": payment, "cost_scope": normalized_cost,
            "unit": unit, "currency": currency, "quantity_unit": quantity_unit,
            "contract_spec": normalized_spec}, sorted(set(reasons))


def _rights(raw, now, *, execution):
    if raw is None:
        return ["source_permissions_unknown"]
    _shape(raw, _RIGHTS, "rights")
    if raw["status"] not in {"allowed", "pending", "denied"}:
        raise ValidationError("rights.status: unsupported value")
    if any(raw[key] not in {"PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"}
           for key in ("observe", "retain", "benchmark", "execution")):
        raise ValidationError("rights: explicit permission gates required")
    reasons = []
    if raw["status"] != "allowed":
        reasons.append("source_rights_not_allowed")
    for key in ("observe", "retain", "benchmark") + (("execution",) if execution else ()):
        if raw[key] != "PASS":
            reasons.append("source_permission_" + key + "_not_pass")
    _text(raw["verified_by"], "permission_verifier", reasons, identity=True)
    if raw["expires_at"] is not None and utc_instant(raw["expires_at"]) <= now:
        reasons.append("source_permission_expired")
    return reasons


def evaluate_quote_payload(payload: dict) -> dict:
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        return _evaluate(payload)


def _evaluate(payload):
    _shape(payload, {"as_of", "max_age_seconds", "target", "quotes"}, "quote request")
    now = utc_instant(payload["as_of"])
    max_age = number(payload["max_age_seconds"], "max_age_seconds", positive=True)
    if max_age > 31536000:
        raise ValidationError("max_age_seconds: exceeds supported declared freshness window")
    target = payload["target"]
    _shape(target, _TARGET, "target")
    terms, target_reasons = _terms(target, now)
    quantity = None if target["quantity"] is None else number(target["quantity"], "target quantity", positive=True)
    if quantity is None:
        target_reasons.append("requested_quantity_unknown")
    elif quantity != quantity.to_integral_value():
        raise ValidationError("quantity: whole allocation or contract units required")
    elif terms["product_role"] in {"spot", "physical_forward"} and terms["quantity_unit"] == "gpu":
        node_count = terms["configuration"].get("accelerators_per_node")
        if node_count is not None and quantity % Decimal(node_count):
            target_reasons.append("requested_quantity_not_whole_nodes")
    scope = target["provider_scope"]
    _shape(scope, {"kind", "provider_id"}, "provider_scope")
    if scope["kind"] == "single_provider":
        _text(scope["provider_id"], "target_provider", target_reasons, identity=True)
    elif scope["kind"] == "all_declared_providers":
        if scope["provider_id"] is not None:
            raise ValidationError("broad provider scope requires explicit null provider_id")
    else:
        raise ValidationError("provider_scope: unsupported kind")
    raw_quotes = payload["quotes"]
    if not isinstance(raw_quotes, list) or len(raw_quotes) > 10000:
        raise ValidationError("quotes: bounded explicit array required")
    seen, admitted, exclusions = set(), [], []
    for raw in raw_quotes:
        _shape(raw, _QUOTE, "quote")
        reasons = []
        identity = _text(raw["id"], "quote_id", reasons, identity=True)
        source = _text(raw["source_id"], "source_id", reasons, identity=True)
        provider = _text(raw["provider_id"], "provider_id", reasons, identity=True)
        if identity is None or source is None:
            raise ValidationError("quote: identifiable source and quote required")
        if identity in seen:
            raise ValidationError("quotes: duplicate quote identifier")
        seen.add(identity)
        quote_terms, unknown = _terms(raw, now)
        reasons.extend(unknown)
        if target_reasons:
            reasons.append("target_comparability_unknown_or_invalid")
        mismatches = [key for key, value in terms.items() if quote_terms[key] != value]
        reasons.extend("incomparable_" + key for key in mismatches)
        if scope["kind"] == "single_provider" and provider != scope["provider_id"]:
            reasons.append("incomparable_provider")
        side = _choice(raw["side"], {"bid", "ask"}, "side", reasons)
        quote_type = _choice(raw["quote_type"], {"firm", "indicative", "advertised"}, "quote_type", reasons)
        if raw["status"] not in {"claimed", "verified", "stale", "rejected"}:
            raise ValidationError("quote.status: unsupported value")
        if raw["status"] != "verified":
            reasons.append("quote_evidence_not_verified")
        _text(raw["evidence_ref"], "quote_evidence", reasons, identity=True)
        advertised = terms["product_role"] == "advertised_commitment"
        if advertised:
            if quote_type != "advertised" or side != "ask":
                reasons.append("advertised_reference_requires_advertised_ask")
        elif quote_type != "firm":
            reasons.append("two_sided_book_requires_firm_quotes")
        reasons.extend(_rights(raw["rights"], now, execution=not advertised))
        observed = utc_instant(raw["observed_at"])
        delta = now - observed
        age = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1000000
        if age < 0 or age > max_age:
            reasons.append("quote_future_or_stale")
        if raw["expires_at"] is None:
            reasons.append("quote_expiry_unknown")
        elif utc_instant(raw["expires_at"]) <= now or utc_instant(raw["expires_at"]) <= observed:
            reasons.append("quote_expired_or_invalid_expiry")
        minimum = None if raw["minimum_quantity"] is None else number(raw["minimum_quantity"], "minimum_quantity", positive=True)
        available = None if raw["available_quantity"] is None else number(raw["available_quantity"], "available_quantity", positive=True)
        if minimum is None or available is None:
            reasons.append("quote_size_unknown")
        elif minimum != minimum.to_integral_value() or available != available.to_integral_value():
            raise ValidationError("quote size: whole allocation or contract units required")
        else:
            if quantity is not None and not minimum <= quantity <= available:
                reasons.append("requested_quantity_outside_quote_size")
            if quote_terms["product_role"] in {"spot", "physical_forward"} and quote_terms["quantity_unit"] == "gpu":
                node_count = quote_terms["configuration"].get("accelerators_per_node")
                if node_count is not None:
                    if available % Decimal(node_count):
                        reasons.append("available_quantity_not_whole_nodes")
                    if minimum % Decimal(node_count):
                        reasons.append("minimum_quantity_not_whole_nodes")
        quality = None if raw["source_quality"] is None else number(raw["source_quality"], "source_quality", positive=True, fraction=True)
        if quality is None:
            reasons.append("source_quality_unknown")
        try:
            price = exact_decimal(raw["price"], nonnegative=terms["product_role"] != "financial_future")
        except (ValueError, TypeError) as exc:
            raise ValidationError("price: finite plain decimal string required") from exc
        if abs(price) > Decimal("1000000000000000000000000"):
            raise ValidationError("price: exceeds supported range")
        if reasons:
            exclusions.append({"quote_id": identity, "reasons": sorted(set(reasons))})
        else:
            admitted.append({"quote_id": identity, "source_id": source, "provider_id": provider,
                             "side": side, "price": text_number(price), "available_quantity": text_number(available),
                             "minimum_quantity": text_number(minimum), "age_seconds": text_number(age),
                             "declared_source_quality": text_number(quality), "quote_type": quote_type,
                             "observed_at": raw["observed_at"], "expires_at": raw["expires_at"],
                             "evidence_ref": raw["evidence_ref"]})
    result = {"schema_version": VERSION, "model_version": VERSION, "as_of": payload["as_of"], "status": "held",
              "product_role": terms["product_role"], "currency": terms["currency"], "unit": terms["unit"],
              "target": deepcopy(target), "best_bid": None, "best_ask": None, "midpoint": None, "spread": None,
              "advertised_reference": None, "hold_reasons": sorted(set(target_reasons)),
              "admitted_quotes": admitted, "exclusions": exclusions,
              "price_weighting": "none_best_price_not_source_quality_weighted",
              "midpoint_basis": "arithmetic_midpoint_of_individually_size_sufficient_comparable_quotes",
              "source_evidence_basis": "caller_declared_not_server_admitted",
              "source_evidence_eligible": False, "inventory_verified": False,
              "tradable": False, "firm_price_eligible": False, "execution_enabled": False,
              "warnings": ["quote_verification_and_permissions_are_caller_assertions",
                           "midpoint_is_not_a_profitability_bid_or_owned_inventory",
                           "quantity_is_not_aggregated_across_quotes_or_venues"]}
    if scope["kind"] == "all_declared_providers":
        result["warnings"].append("broad_provider_scope_does_not_equalize_credit_or_delivery_risk")
    if terms["product_role"] == "advertised_commitment":
        asks = sorted(Decimal(row["price"]) for row in admitted)
        if asks:
            middle = len(asks) // 2
            median = asks[middle] if len(asks) % 2 else (asks[middle - 1] + asks[middle]) / 2
            result["advertised_reference"] = {"ask_median": text_number(median), "quote_count": len(asks),
                "source_counts": dict(sorted(Counter(row["source_id"] for row in admitted).items())),
                "basis": "median_comparable_advertised_asks_not_midpoint", "unweighted": True}
        result["hold_reasons"].append("advertised_reference_is_not_a_two_sided_market")
    else:
        bids = [row for row in admitted if row["side"] == "bid"]
        asks = [row for row in admitted if row["side"] == "ask"]
        if bids:
            result["best_bid"] = min(bids, key=lambda row: (-Decimal(row["price"]), row["quote_id"]))
        if asks:
            result["best_ask"] = min(asks, key=lambda row: (Decimal(row["price"]), row["quote_id"]))
        if not bids or not asks:
            result["hold_reasons"].append("two_sided_comparable_book_required")
        else:
            bid, ask = Decimal(result["best_bid"]["price"]), Decimal(result["best_ask"]["price"])
            if bid > ask:
                result["hold_reasons"].append("crossed_comparable_book")
            elif not result["hold_reasons"]:
                result.update(status="comparable_two_sided", midpoint=text_number((bid + ask) / 2),
                              spread=text_number(ask - bid))
    result["hold_reasons"] = sorted(set(result["hold_reasons"]))
    result["input_hash"] = digest(payload)
    result["decision_hash"] = digest(result)
    return result
