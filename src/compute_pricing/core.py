"""A bounded pricing reference model with explicit, caller-supplied assumptions.

This module neither downloads data nor executes transactions. Source admission,
commercial rights, forecast calibration, and full cash scheduling live outside
this calculation. Every admitted price belongs to one exact hardware, region,
currency, and tenor cohort. No implicit currency or performance conversion occurs.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, localcontext
import json
import re
from typing import Any, Mapping


ZERO = Decimal("0")
ONE = Decimal("1")
DECIMAL_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?$")
UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
MAX_DECIMAL = Decimal("1000000000000000000000000")
MAX_OBSERVATIONS = 10000


class InputError(ValueError):
    """A missing, invalid, or contradictory input; no executable quote results."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise InputError(field, "must be an object with string keys")
    return value


def _required(obj: Mapping[str, Any], key: str, field: str) -> Any:
    if key not in obj:
        raise InputError(f"{field}.{key}", "is required")
    return obj[key]


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise InputError(field, "must be a nonempty string of at most 200 characters")
    return value


def _decimal(value: Any, field: str, *, minimum: Decimal = ZERO,
             maximum: Decimal = MAX_DECIMAL, positive: bool = False,
             integer: bool = False) -> Decimal:
    if not isinstance(value, str) or len(value) > 80 or not DECIMAL_PATTERN.fullmatch(value):
        raise InputError(field, "must be a finite decimal string without exponent notation")
    number = Decimal(value)
    if not number.is_finite() or number < minimum or number > maximum:
        raise InputError(field, "is outside the supported range")
    if positive and number <= ZERO:
        raise InputError(field, "must be greater than zero")
    if integer and number != number.to_integral_value():
        raise InputError(field, "must be an integer expressed as a decimal string")
    return number


def _fraction(value: Any, field: str, *, positive: bool = False,
              below_one: bool = False) -> Decimal:
    result = _decimal(value, field, maximum=ONE, positive=positive)
    if below_one and result >= ONE:
        raise InputError(field, "must be less than one")
    return result


def _integer(value: Any, field: str, *, minimum: int = 1,
             maximum: int = MAX_OBSERVATIONS) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise InputError(field, f"must be an integer between {minimum} and {maximum}")
    return value


def _date(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not UTC_PATTERN.fullmatch(value):
        raise InputError(field, "must be a UTC timestamp ending in Z, with seconds")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise InputError(field, "must be a real calendar timestamp") from exc


def _hours(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    seconds = Decimal(delta.days * 86400 + delta.seconds)
    seconds += Decimal(delta.microseconds) / Decimal("1000000")
    return seconds / Decimal("3600")


def _number(value: Decimal) -> str:
    if not value.is_finite():
        raise ArithmeticError("nonfinite calculation result")
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _extras(obj: Mapping[str, Any], known: set[str], field: str) -> dict[str, Any]:
    declared = _object(obj.get("extensions", {}), f"{field}.extensions")
    return {
        "declared": dict(declared),
        "unmapped": {key: value for key, value in obj.items() if key not in known | {"extensions"}},
    }


def _median(values: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Weighted median, averaging the two adjacent values at an exact half split."""
    ordered = sorted(values)
    half = sum(weight for _, weight in ordered) / Decimal("2")
    running = ZERO
    for position, (value, weight) in enumerate(ordered):
        running += weight
        if running > half:
            return value
        if running == half:
            if position + 1 < len(ordered):
                return (value + ordered[position + 1][0]) / Decimal("2")
            return value
    raise ArithmeticError("weighted median requires positive total weight")


def _capped_shares(weights: Mapping[str, Decimal], cap: Decimal) -> dict[str, Decimal]:
    """Water-fill provider shares: each share is min(cap, multiplier * weight).

    Each pass fixes at least one capped group or finishes, so at most n passes
    occur. A cap is feasible only when n * cap >= 1. No black-box optimizer is
    needed. Positive group weights are required.
    """
    if Decimal(len(weights)) * cap < ONE:
        raise InputError("policy.max_provider_share", "cannot cover all weight with the admitted provider groups")
    remaining = dict(weights)
    shares: dict[str, Decimal] = {}
    budget = ONE
    while remaining:
        total = sum(remaining.values())
        proposed = {group: budget * weight / total for group, weight in remaining.items()}
        capped = [group for group, share in proposed.items() if share > cap]
        if not capped:
            shares.update(proposed)
            break
        for group in capped:
            shares[group] = cap
            budget -= cap
            del remaining[group]
    return shares


TARGET_KEYS = {"hardware_class", "region", "currency", "tenor_hours"}
RULE_KEYS = {"enabled", "quality", "max_age_hours", "freshness_half_life_hours"}
POLICY_KEYS = {"estimator", "max_provider_share", "min_observations", "min_provider_groups",
               "min_sources", "winsor_band_fraction", "source_rules"}
OBSERVATION_KEYS = {"observation_id", "source_id", "provider_group", "lot_id", "observed_at",
                    "status", "hardware_class", "region", "currency", "tenor_min_hours",
                    "tenor_max_hours", "unit", "price", "gpus_per_node"}
DEAL_KEYS = {"start_at", "end_at", "gpu_count", "buyer_rate_per_gpu_hour", "utilization",
             "availability", "buyer_collection_fraction", "required_margin_fraction",
             "supplier_advance_fraction", "available_advance_funding", "buyer_prepayment",
             "liquidity_reserve", "capital_charge", "market_discount_fraction", "costs",
             "supplier_rate_cap", "buyer_prepayment_available_for_procurement"}


def _read_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    policy = _object(_required(payload, "policy", "input"), "policy")
    estimator = _required(policy, "estimator", "policy")
    if estimator not in ("weighted_median", "winsorized_mean"):
        raise InputError("policy.estimator", "must be weighted_median or winsorized_mean")
    result = {
        "estimator": estimator,
        "max_provider_share": _fraction(_required(policy, "max_provider_share", "policy"),
                                        "policy.max_provider_share", positive=True),
        "winsor_band_fraction": _fraction(_required(policy, "winsor_band_fraction", "policy"),
                                          "policy.winsor_band_fraction"),
        "extensions": _extras(policy, POLICY_KEYS, "policy"),
    }
    for key in ("min_observations", "min_provider_groups", "min_sources"):
        result[key] = _integer(_required(policy, key, "policy"), f"policy.{key}")
    rules = _object(_required(policy, "source_rules", "policy"), "policy.source_rules")
    result["source_rules"] = {}
    for source, raw_rule in rules.items():
        _text(source, "policy.source_rules key")
        field = f"policy.source_rules.{source}"
        rule = _object(raw_rule, field)
        enabled = _required(rule, "enabled", field)
        if not isinstance(enabled, bool):
            raise InputError(f"{field}.enabled", "must be a boolean")
        result["source_rules"][source] = {
            "enabled": enabled,
            "quality": _fraction(_required(rule, "quality", field), f"{field}.quality", positive=True),
            "max_age_hours": _decimal(_required(rule, "max_age_hours", field), f"{field}.max_age_hours", positive=True),
            "freshness_half_life_hours": _decimal(_required(rule, "freshness_half_life_hours", field),
                                                  f"{field}.freshness_half_life_hours", positive=True),
            "extensions": _extras(rule, RULE_KEYS, field),
        }
    return result


def _index(payload: Mapping[str, Any], target: dict[str, Any], as_of: datetime,
           policy: dict[str, Any]) -> dict[str, Any]:
    raw_observations = _required(payload, "observations", "input")
    if not isinstance(raw_observations, list) or len(raw_observations) > MAX_OBSERVATIONS:
        raise InputError("observations", f"must be an array of at most {MAX_OBSERVATIONS} observations")
    rows: list[dict[str, Any]] = []
    admitted: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for position, raw in enumerate(raw_observations):
        field = f"observations[{position}]"
        row: dict[str, Any] = {"input_position": position, "admitted": False}
        rows.append(row)
        try:
            obs = _object(raw, field)
            row["extensions"] = _extras(obs, OBSERVATION_KEYS, field)
            obs_id = _text(_required(obs, "observation_id", field), f"{field}.observation_id")
            if obs_id in seen_ids:
                raise InputError("observations", "observation_id values must be unique")
            seen_ids.add(obs_id)
            row["observation_id"] = obs_id
            source = _text(_required(obs, "source_id", field), f"{field}.source_id")
            provider = _text(_required(obs, "provider_group", field), f"{field}.provider_group")
            lot = _text(_required(obs, "lot_id", field), f"{field}.lot_id")
            row.update({"source_id": source, "provider_group": provider, "lot_id": lot})
            observed = _date(_required(obs, "observed_at", field), f"{field}.observed_at")
            row["observed_at"] = obs["observed_at"]
            age = _hours(observed, as_of)
            row["age_hours"] = _number(age)
            status = _required(obs, "status", field)
            if status not in ("available", "indicative", "unavailable"):
                raise InputError(f"{field}.status", "must be available, indicative, or unavailable")
            for key in ("hardware_class", "region", "currency"):
                _text(_required(obs, key, field), f"{field}.{key}")
                row[key] = obs[key]
            tenor_min = _decimal(_required(obs, "tenor_min_hours", field), f"{field}.tenor_min_hours")
            tenor_max = _decimal(_required(obs, "tenor_max_hours", field), f"{field}.tenor_max_hours", positive=True)
            if tenor_max < tenor_min:
                raise InputError(f"{field}.tenor_max_hours", "must not be less than tenor_min_hours")
            row.update({"tenor_min_hours": obs["tenor_min_hours"], "tenor_max_hours": obs["tenor_max_hours"]})
            price = _decimal(_required(obs, "price", field), f"{field}.price", positive=True)
            unit = _required(obs, "unit", field)
            if unit == "node_hour":
                count = _decimal(_required(obs, "gpus_per_node", field), f"{field}.gpus_per_node", positive=True, integer=True)
                normalized = price / count
                row["gpus_per_node"] = _number(count)
            elif unit == "gpu_hour":
                normalized = price
            else:
                raise InputError(f"{field}.unit", "must be gpu_hour or node_hour")
            row.update({"original_unit": unit, "original_price": obs["price"],
                        "normalized_price_per_gpu_hour": _number(normalized)})
            reasons = []
            rule = policy["source_rules"].get(source)
            if rule is None or not rule["enabled"]:
                reasons.append("source_not_admitted")
            if status != "available":
                reasons.append("not_available")
            if any(obs[key] != target[key] for key in ("hardware_class", "region", "currency")):
                reasons.append("incompatible_cohort")
            if not tenor_min <= target["tenor_hours"] <= tenor_max:
                reasons.append("incompatible_tenor")
            if age < ZERO:
                reasons.append("future_timestamp")
            elif rule is not None and age > rule["max_age_hours"]:
                reasons.append("stale")
            if reasons:
                row["exclusion_reasons"] = reasons
                continue
            half_lives = age / rule["freshness_half_life_hours"]
            # Guard extreme caller-supplied half-lives before exponent evaluation.
            # This is a numerical limit, not a source reliability assumption.
            if half_lives > Decimal("100000"):
                row["exclusion_reasons"] = ["weight_underflow"]
                continue
            weight = rule["quality"] * (-Decimal("2").ln() * half_lives).exp()
            if weight <= ZERO:
                row["exclusion_reasons"] = ["weight_underflow"]
                continue
            admitted.append({"row": row, "id": obs_id, "source": source, "provider": provider,
                             "lot": lot, "observed": observed, "price": normalized, "weight": weight})
        except InputError as exc:
            if exc.field == "observations" and exc.message == "observation_id values must be unique":
                raise
            row["exclusion_reasons"] = ["invalid_input"]
            row["input_error"] = {"field": exc.field, "message": exc.message}

    # Cross-source relistings of the same physical lot never create extra weight.
    # Latest admitted observation wins; ties resolve by ID, independent of order.
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for obs in admitted:
        key = (obs["provider"], obs["lot"])
        winner = latest.get(key)
        if winner is None or (obs["observed"], obs["id"]) > (winner["observed"], winner["id"]):
            latest[key] = obs
    eligible = sorted(latest.values(), key=lambda obs: obs["id"])
    for obs in admitted:
        if latest[(obs["provider"], obs["lot"])]["id"] != obs["id"]:
            obs["row"]["exclusion_reasons"] = ["duplicate_lot_superseded"]
    groups = {obs["provider"] for obs in eligible}
    sources = {obs["source"] for obs in eligible}
    holds = []
    for count, minimum, reason in (
        (len(eligible), policy["min_observations"], "insufficient_observations"),
        (len(groups), policy["min_provider_groups"], "insufficient_provider_groups"),
        (len(sources), policy["min_sources"], "insufficient_sources"),
    ):
        if count < minimum:
            holds.append(reason)
    if Decimal(len(groups)) * policy["max_provider_share"] < ONE:
        holds.append("infeasible_provider_weight_cap")
    result = {"status": "held" if holds else "indicative", "hold_reasons": holds,
              "observations": rows, "eligible_observation_count": len(eligible),
              "provider_group_count": len(groups), "source_count": len(sources),
              "unit": "gpu_hour", "currency": target["currency"],
              "estimator": policy["estimator"], "price_per_gpu_hour": None}
    if holds:
        return result
    group_weights: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for obs in eligible:
        group_weights[obs["provider"]] += obs["weight"]
    shares = _capped_shares(group_weights, policy["max_provider_share"])
    samples = []
    source_shares: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for obs in eligible:
        weight = shares[obs["provider"]] * obs["weight"] / group_weights[obs["provider"]]
        obs["row"].update({"admitted": True, "uncapped_quality_freshness_weight": _number(obs["weight"]),
                           "index_weight": _number(weight)})
        samples.append((obs["price"], weight))
        source_shares[obs["source"]] += weight
    median = _median(samples)
    weighted_mean = sum(price * weight for price, weight in samples)
    band = policy["winsor_band_fraction"]
    lower = median * (ONE - band)
    upper = median * (ONE + band)
    winsorized_mean = sum(min(upper, max(lower, price)) * weight for price, weight in samples)
    selected = median if policy["estimator"] == "weighted_median" else winsorized_mean
    result.update({
        "price_per_gpu_hour": _number(selected),
        "diagnostics": {
            "weighted_median": _number(median), "weighted_mean": _number(weighted_mean),
            "winsorized_mean": _number(winsorized_mean),
            "winsor_lower": _number(lower), "winsor_upper": _number(upper),
            "weighted_median_absolute_deviation": _number(_median([(abs(price - median), weight) for price, weight in samples])),
            "min_price": _number(min(price for price, _ in samples)),
            "max_price": _number(max(price for price, _ in samples)),
            "effective_observation_count": _number(ONE / sum(weight * weight for _, weight in samples)),
            "provider_weight_shares": {group: _number(share) for group, share in sorted(shares.items())},
            "source_weight_shares": {source: _number(share) for source, share in sorted(source_shares.items())},
            "uncertainty_kind": "cross_observation_dispersion_not_forecast_error",
        },
    })
    return result


def _cost_map(value: Any, field: str) -> dict[str, Decimal]:
    costs = _object(value, field)
    if len(costs) > 1000:
        raise InputError(field, "must have at most 1000 named cost components")
    return {_text(name, field): _decimal(amount, f"{field}.{name}") for name, amount in costs.items()}


def _deal(raw: Any, target: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    deal = _object(raw, "deal")
    start = _date(_required(deal, "start_at", "deal"), "deal.start_at")
    end = _date(_required(deal, "end_at", "deal"), "deal.end_at")
    duration = _hours(start, end)
    if duration <= ZERO:
        raise InputError("deal.end_at", "must be after start_at")
    if duration != target["tenor_hours"]:
        raise InputError("target.tenor_hours", "must equal the actual deal start/end duration")
    gpu_count = _decimal(_required(deal, "gpu_count", "deal"), "deal.gpu_count", positive=True, integer=True)
    capacity = duration * gpu_count
    rates: dict[str, Decimal] = {}
    for key in ("buyer_rate_per_gpu_hour", "available_advance_funding", "buyer_prepayment", "liquidity_reserve", "capital_charge"):
        rates[key] = _decimal(_required(deal, key, "deal"), f"deal.{key}")
    for key in ("utilization", "availability", "buyer_collection_fraction", "supplier_advance_fraction", "market_discount_fraction"):
        rates[key] = _fraction(_required(deal, key, "deal"), f"deal.{key}")
    rates["required_margin_fraction"] = _fraction(_required(deal, "required_margin_fraction", "deal"),
                                                   "deal.required_margin_fraction", below_one=True)
    prepayment_permitted = _required(deal, "buyer_prepayment_available_for_procurement", "deal")
    if not isinstance(prepayment_permitted, bool):
        raise InputError("deal.buyer_prepayment_available_for_procurement", "must be a boolean")
    costs = _object(_required(deal, "costs", "deal"), "deal.costs")
    known_cost_maps = {"per_committed_gpu_hour", "fixed_contract", "upfront_fixed"}
    if set(costs) != known_cost_maps:
        raise InputError("deal.costs", "must explicitly contain per_committed_gpu_hour, fixed_contract, and upfront_fixed maps")
    named = {key: _cost_map(costs[key], f"deal.costs.{key}") for key in sorted(known_cost_maps)}
    nonpurchase = sum(named["per_committed_gpu_hour"].values()) * capacity
    nonpurchase += sum(named["fixed_contract"].values()) + sum(named["upfront_fixed"].values()) + rates["capital_charge"]
    collected_hours = capacity * rates["utilization"] * rates["availability"] * rates["buyer_collection_fraction"]
    revenue = collected_hours * rates["buyer_rate_per_gpu_hour"]
    if rates["buyer_prepayment"] > revenue:
        raise InputError("deal.buyer_prepayment", "must not exceed expected collected contract revenue in this model")
    usable_prepayment = rates["buyer_prepayment"] if prepayment_permitted else ZERO
    funding = rates["available_advance_funding"] + usable_prepayment
    funding -= sum(named["upfront_fixed"].values()) + rates["liquidity_reserve"]
    result = {
        "status": "held", "hold_reasons": [], "currency": target["currency"], "unit": "gpu_hour",
        "contract_hours": _number(duration), "committed_gpu_hours": _number(capacity),
        "expected_collected_gpu_hours": _number(collected_hours), "expected_revenue": _number(revenue),
        "nonpurchase_cost": _number(nonpurchase), "available_supplier_advance_cash": _number(funding),
        "recommended_bid_per_gpu_hour": None, "minimum_ask_per_gpu_hour": None,
        "cost_breakdown": {key: {name: _number(value) for name, value in components.items()} for key, components in named.items()},
        "capital_charge": _number(rates["capital_charge"]),
        "buyer_prepayment_admitted_to_funding": _number(usable_prepayment),
        "assumptions": {**{key: _number(value) for key, value in rates.items()},
                        "gpu_count": _number(gpu_count), "start_at": deal["start_at"], "end_at": deal["end_at"],
                        "buyer_prepayment_available_for_procurement": prepayment_permitted},
        "funding_scope": "supplier_advance_and_upfront_costs_only_not_a_full_cash_schedule",
        "extensions": _extras(deal, DEAL_KEYS, "deal"),
    }
    caps = {"economics": ((ONE - rates["required_margin_fraction"]) * revenue - nonpurchase) / capacity}
    if index["price_per_gpu_hour"] is not None:
        caps["market"] = Decimal(index["price_per_gpu_hour"]) * (ONE - rates["market_discount_fraction"])
    if "supplier_rate_cap" in deal:
        caps["supplier_policy"] = _decimal(deal["supplier_rate_cap"], "deal.supplier_rate_cap")
        result["assumptions"]["supplier_rate_cap"] = _number(caps["supplier_policy"])
    advance_fraction = rates["supplier_advance_fraction"]
    if advance_fraction > ZERO:
        caps["advance_funding"] = funding / (capacity * advance_fraction)
    result["bid_caps_per_gpu_hour"] = {key: _number(value) for key, value in caps.items()}
    if index["status"] == "held":
        result["hold_reasons"].append("index_held")
    if collected_hours <= ZERO or revenue <= ZERO:
        result["hold_reasons"].append("no_expected_collected_revenue")
    if funding < ZERO:
        result["hold_reasons"].append("upfront_funding_shortfall")
    bid = min(caps.values())
    if bid <= ZERO:
        result["hold_reasons"].append("no_positive_bid")
    if result["hold_reasons"]:
        return result
    procurement = bid * capacity
    all_in = procurement + nonpurchase
    ask = all_in / (collected_hours * (ONE - rates["required_margin_fraction"]))
    profit = revenue - all_in
    result.update({
        "status": "indicative", "recommended_bid_per_gpu_hour": _number(bid),
        "minimum_ask_per_gpu_hour": _number(ask), "supplier_purchase_cost": _number(procurement),
        "all_in_cost": _number(all_in), "expected_profit": _number(profit),
        "expected_margin_fraction": _number(profit / revenue),
        "supplier_advance_required": _number(procurement * advance_fraction),
        "advance_cash_remaining": _number(funding - procurement * advance_fraction),
        "binding_bid_caps": [key for key, value in caps.items() if value == bid],
    })
    return result


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a versioned JSON-compatible snapshot, using only supplied inputs.

    Malformed top-level, policy, or deal inputs raise InputError. Invalid individual
    observations remain in exclusion diagnostics. Insufficient evidence returns a
    held result. All successful calculations are indicative, never execution-ready.
    Unknown fields are retained under extensions and never silently affect pricing.
    """
    _object(payload, "input")
    try:
        # Extensions may contain finite JSON numbers, but cannot make an otherwise
        # successful result impossible to serialize. Validate without echoing data.
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InputError("input", "must be JSON-compatible and contain only finite numbers") from exc
    with localcontext() as context:
        context.prec = 50
        return _evaluate(deepcopy(payload))


def _evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _object(payload, "input")
    if _required(obj, "api_version", "input") != "1.0":
        raise InputError("api_version", "must be 1.0")
    as_of = _date(_required(obj, "as_of", "input"), "as_of")
    raw_target = _object(_required(obj, "target", "input"), "target")
    target: dict[str, Any] = {}
    for key in ("hardware_class", "region", "currency"):
        target[key] = _text(_required(raw_target, key, "target"), f"target.{key}")
    target["tenor_hours"] = _decimal(_required(raw_target, "tenor_hours", "target"), "target.tenor_hours", positive=True)
    policy = _read_policy(obj)
    index = _index(obj, target, as_of, policy)
    deal = _deal(obj["deal"], target, index) if "deal" in obj else None
    return {
        "api_version": "1.0", "model_version": "0.1.0", "as_of": obj["as_of"],
        "status": "held" if index["status"] == "held" or (deal and deal["status"] == "held") else "indicative",
        "execution_ready": False,
        "target": {**{key: value for key, value in target.items() if key != "tenor_hours"},
                   "tenor_hours": _number(target["tenor_hours"]),
                   "extensions": _extras(raw_target, TARGET_KEYS, "target")},
        "index": index, "deal": deal,
        "policy_snapshot": deepcopy(obj["policy"]),
        "extensions": _extras(obj, {"api_version", "as_of", "target", "policy", "observations", "deal"}, "input"),
    }
