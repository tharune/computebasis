"""Indicative comparable index; financial and token units have separate models.

Quality weights and cap policy are explicit uncalibrated inputs. The bounded
coordinate projection holds an index if the caps cannot be satisfied numerically.
It does not claim an optimal statistical estimator or a forecast confidence bound.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
import re

from .._numbers import calculation_precision, number, text_number
from ..domain import ValidationError, parse_market_observation, utc_instant
from ..domain.spec import ID_PATTERN

ZERO, ONE = Decimal(0), Decimal(1)
TOLERANCE = Decimal("0.000000000000000000000001")
PHYSICAL_KINDS = {"listing_ask", "firm_supplier_rfq", "confirmed_rental_trade"}


def _median(samples):
    """Use the declared numerical tolerance for a near-half weight tie."""
    values = sorted(samples)
    total = sum(weight for _, weight in values)
    cumulative = ZERO
    for position, (price, weight) in enumerate(values):
        cumulative += weight
        difference = cumulative - total / 2
        if difference > TOLERANCE:
            return price
        if abs(difference) <= TOLERANCE:
            return (price + values[min(position + 1, len(values) - 1)][0]) / 2
    raise ArithmeticError("empty weighted sample")


def _integer(raw, field, minimum=1):
    if type(raw) is not int or not minimum <= raw <= 10000:
        raise ValidationError(f"{field}: bounded integer required")
    return raw


def _project(rows, source_cap, group_cap):
    """Bounded cyclic cap projection with transparent fail-closed convergence.

    Each coordinate rescales its members and renormalizes the total. Repeated
    source/provider corrections satisfy both families or return no index. Sparse
    boundary cases can be numerically unresolved; that is not proof of infeasibility.
    """
    raw_total = sum(row["raw_weight"] for row in rows)
    weights = [row["raw_weight"] / raw_total for row in rows]
    constraints = []
    for field, cap in (("source_id", source_cap), ("group_id", group_cap)):
        groups = defaultdict(list)
        for position, row in enumerate(rows):
            groups[row[field]].append(position)
        if len(groups) * cap < ONE:
            return None, "infeasible_weight_cap"
        constraints += [(tuple(groups[group]), cap) for group in sorted(groups)]
    for _ in range(2000):
        for members, cap in constraints:
            current = sum(weights[i] for i in members)
            if current <= cap + TOLERANCE:
                continue
            if current >= ONE:
                return None, "infeasible_weight_cap"
            factor = cap * (ONE - current) / (current * (ONE - cap))
            for i in members:
                weights[i] *= factor
            total = sum(weights)
            weights = [weight / total for weight in weights]
        if all(sum(weights[i] for i in members) <= cap + TOLERANCE
               for members, cap in constraints):
            return weights, None
    return None, "cap_projection_numerically_unresolved"


def _microseconds(delta):
    return Decimal((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds)


def evaluate_benchmark(observations: list[dict], target: dict, policy: dict, as_of: str) -> dict:
    with localcontext() as context:
        context.prec = calculation_precision({"observations": observations, "target": target, "policy": policy})
        return _evaluate(observations, target, policy, as_of)


def _evaluate(observations, target, policy, as_of):
    if not isinstance(observations, list) or len(observations) > 10000:
        raise ValidationError("observations: bounded array required")
    if not isinstance(target, dict) or not isinstance(policy, dict):
        raise ValidationError("target and policy: objects required")
    for name in ("hardware_model", "currency"):
        if not isinstance(target.get(name), str) or not target[name]:
            raise ValidationError(f"target.{name}: required")
    if target.get("scope") not in {"physical_offer", "aggregate_reference"}:
        raise ValidationError("target.scope: physical_offer or aggregate_reference required")
    if not isinstance(target.get("configuration", {}), dict):
        raise ValidationError("target.configuration: object required")
    duration = number(target.get("duration_hours"), "target.duration_hours", positive=True)
    quantity = number(target.get("gpu_count"), "target.gpu_count", positive=True)
    if quantity != quantity.to_integral_value():
        raise ValidationError("target.gpu_count: whole accelerator units required")
    clock = utc_instant(as_of)
    starts, ends = target.get("starts_at"), target.get("ends_at")
    if (starts is None) != (ends is None):
        raise ValidationError("target: both delivery timestamps are required together")
    if target["scope"] == "physical_offer" and starts is None:
        raise ValidationError("target: physical comparison needs explicit delivery interval")
    if starts is not None:
        start_time, end_time = utc_instant(starts), utc_instant(ends)
        span = _microseconds(end_time - start_time)
        if span <= 0:
            raise ValidationError("target: delivery interval must have positive duration")
        if duration * Decimal(3600000000) != span:
            raise ValidationError("target: declared duration conflicts with delivery timestamps")
    aggregate_terms = target.get("aggregate_terms")
    aggregate_terms_known = (
        isinstance(aggregate_terms, dict)
        and set(aggregate_terms) == {"billing_type", "reservation_months"}
        and isinstance(aggregate_terms.get("billing_type"), str)
        and bool(aggregate_terms["billing_type"].strip())
        and (aggregate_terms.get("reservation_months") is None
             or type(aggregate_terms.get("reservation_months")) is int
             and 1 <= aggregate_terms["reservation_months"] <= 1200)
    )
    if policy.get("estimator") not in {"weighted_median", "weighted_mean"}:
        raise ValidationError("policy.estimator: unsupported method")
    source_cap = number(policy.get("max_source_share"), "max_source_share", positive=True, fraction=True)
    group_cap = number(policy.get("max_provider_share"), "max_provider_share", positive=True, fraction=True)
    minimum = {key: _integer(policy.get(key), key)
               for key in ("min_observations", "min_sources", "min_provider_groups")}
    source_rules = policy.get("source_rules")
    if not isinstance(source_rules, dict):
        raise ValidationError("policy.source_rules: required")
    rules = {}
    for source, value in source_rules.items():
        if not isinstance(source, str) or not re.fullmatch(ID_PATTERN, source):
            raise ValidationError("source rule: canonical source ID required")
        if not isinstance(value, dict) or type(value.get("enabled")) is not bool:
            raise ValidationError("source rule: explicit enablement required")
        rules[source] = {"enabled": value["enabled"],
                         "quality": number(value.get("quality"), "source quality", positive=True, fraction=True),
                         "max_age_hours": number(value.get("max_age_hours"), "max age", positive=True),
                         "half_life_hours": number(value.get("half_life_hours"), "half life", positive=True)}
    exclusions, admitted, identities = [], [], set()
    for position, raw in enumerate(observations):
        raw_id = raw.get("id") if isinstance(raw, dict) else None
        valid_id = isinstance(raw_id, str) and re.fullmatch(ID_PATTERN, raw_id)
        if valid_id and raw_id in identities:
            raise ValidationError("observations: duplicate observation IDs")
        if valid_id:
            identities.add(raw_id)
        try:
            observation = parse_market_observation(raw)
        except ValidationError:
            exclusions.append({"observation_id": raw_id if valid_id else f"invalid-observation-{position}", "reasons": ["domain_validation"]})
            continue
        reasons = list(observation.admission_blockers(as_of, purpose="indicative"))
        aggregate = observation.kind == "aggregate_advertised_index"
        if aggregate and target["scope"] != "aggregate_reference":
            reasons.append("aggregate_is_not_physical_supply")
        if not aggregate and (observation.kind not in PHYSICAL_KINDS or target["scope"] != "physical_offer"):
            reasons.append("incompatible_observation_role")
        if aggregate and target.get("country_code") is not None:
            reasons.append("aggregate_region_not_verified")
        if aggregate:
            if not aggregate_terms_known:
                reasons.append("aggregate_target_terms_unknown")
            elif (observation.extensions.get("billing_type") != aggregate_terms["billing_type"]
                    or "reservation_months" not in observation.extensions
                    or observation.extensions["reservation_months"] != aggregate_terms["reservation_months"]):
                reasons.append("aggregate_billing_or_reservation_mismatch")
            if target.get("configuration"):
                reasons.append("aggregate_configuration_not_verified")
        if observation.price is None or observation.price.amount is None:
            reasons.append("missing_price")
        elif observation.price.unit not in {"gpu_hour", "node_hour"}:
            reasons.append("incompatible_price_unit")
        elif observation.price.currency != target["currency"]:
            reasons.append("currency_mismatch_no_implicit_fx")
        if observation.hardware is None or observation.hardware.model != target["hardware_model"]:
            reasons.append("hardware_mismatch")
        if not aggregate:
            country = observation.region.country_code if observation.region else None
            if target.get("country_code") is None or country != target["country_code"]:
                reasons.append("unknown_or_mismatched_region")
            available = ZERO
            if observation.quantity is None or observation.quantity_unit is None:
                reasons.append("insufficient_or_unknown_quantity")
            else:
                available = number(observation.quantity, "quantity")
                if available != available.to_integral_value():
                    reasons.append("fractional_capacity_quantity_unsupported")
                if observation.quantity_unit == "node":
                    count = observation.hardware.accelerator_count if observation.hardware else None
                    if count is None or Decimal(count) <= 0:
                        reasons.append("unknown_node_quantity_conversion")
                    else:
                        available *= Decimal(count)
                if available < quantity:
                    reasons.append("insufficient_or_unknown_quantity")
            if observation.starts_at is None or observation.ends_at is None:
                reasons.append("unknown_delivery_interval")
            elif starts is not None:
                if (utc_instant(observation.starts_at) > utc_instant(target["starts_at"])
                        or utc_instant(observation.ends_at) < utc_instant(target["ends_at"])):
                    reasons.append("delivery_interval_not_covered")
            if not observation.lot_id or not observation.provider_group_id:
                reasons.append("unknown_underlying_lot_or_provider_group")
            for key, expected in target.get("configuration", {}).items():
                actual = observation.configuration.to_dict().get(key) if observation.configuration else None
                if actual is None or actual != expected:
                    reasons.append("configuration_mismatch")
        rule = rules.get(observation.source_id)
        age = _microseconds(clock - utc_instant(observation.observed_at)) / Decimal(3600000000)
        if not rule or not rule["enabled"]:
            reasons.append("source_not_admitted_by_policy")
        elif age < 0 or age > rule["max_age_hours"]:
            reasons.append("source_timestamp_future_or_stale")
        if reasons:
            exclusions.append({"observation_id": observation.id, "reasons": sorted(set(reasons))})
            continue
        price = number(observation.price.amount, "price")
        if price <= 0:
            exclusions.append({"observation_id": observation.id, "reasons": ["nonpositive_benchmark_price"]})
            continue
        steps = []
        if observation.price.unit == "node_hour":
            count = number(observation.hardware.accelerator_count, "node accelerator count", positive=True)
            if count != count.to_integral_value():
                exclusions.append({"observation_id": observation.id, "reasons": ["fractional_node_count_unsupported"]})
                continue
            price /= count
            steps.append("full_node_bundle_total_divided_by_explicit_accelerator_count")
        decay = age / rule["half_life_hours"]
        if decay > 100000:
            exclusions.append({"observation_id": observation.id, "reasons": ["weight_underflow"]})
            continue
        weight = rule["quality"] * (-Decimal(2).ln() * decay).exp()
        if weight <= 0:
            exclusions.append({"observation_id": observation.id, "reasons": ["weight_underflow"]})
            continue
        admitted.append({"observation_id": observation.id, "source_id": observation.source_id,
                         "group_id": "aggregate/" + observation.source_id if aggregate else observation.provider_group_id,
                         "lot_id": observation.lot_id or observation.id, "observed_at": observation.observed_at,
                         "ingested_at": observation.ingested_at,
                         "dedupe_key": (observation.source_id, observation.hardware.model,
                                        observation.extensions.get("billing_type"),
                                        observation.extensions.get("reservation_months"),
                                        utc_instant(observation.observed_at).isoformat()) if aggregate else observation.lot_id,
                         "price": price, "raw_weight": weight, "steps": steps,
                         "warnings": list(observation.admission_warnings(as_of)),
                         "source_status": observation.status})
    # Canonical underlying lots are global IDs, not reseller-local aliases. A
    # conflicting beneficial provider mapping quarantines every conflicting row.
    physical_groups = defaultdict(set)
    for row in admitted:
        if target["scope"] == "physical_offer":
            physical_groups[row["lot_id"]].add(row["group_id"])
    conflicted_lots = {lot for lot, groups in physical_groups.items() if len(groups) > 1}
    latest = {}
    for row in admitted:
        if row["lot_id"] in conflicted_lots:
            exclusions.append({"observation_id": row["observation_id"], "reasons": ["underlying_lot_provider_identity_conflict"]})
            continue
        key = row["dedupe_key"]
        current = latest.get(key)
        if current is None or (utc_instant(row["observed_at"]), utc_instant(row["ingested_at"]), row["observation_id"]) > (utc_instant(current["observed_at"]), utc_instant(current["ingested_at"]), current["observation_id"]):
            latest[key] = row
    rows = sorted(latest.values(), key=lambda item: item["observation_id"])
    winners = {row["observation_id"] for row in rows}
    exclusions += [{"observation_id": row["observation_id"], "reasons": ["underlying_lot_superseded"]}
                   for row in admitted if row["observation_id"] not in winners and row["lot_id"] not in conflicted_lots]
    counts = {"min_observations": len(rows), "min_sources": len({r["source_id"] for r in rows}),
              "min_provider_groups": len({r["group_id"] for r in rows})}
    holds = ["insufficient_" + key.removeprefix("min_") for key in minimum if counts[key] < minimum[key]]
    result = {"status": "held" if holds else "indicative", "executable": False,
              "hold_reasons": holds, "warnings": ["source_quality_policy_is_not_calibrated"],
              "currency": target["currency"], "unit": "gpu_hour", "as_of": as_of,
              "cohort": dict(target), "price": None, "contributors": [], "exclusions": exclusions}
    if target["scope"] == "aggregate_reference":
        result["warnings"].append("advertised_aggregate_is_not_executable_inventory_or_region_premium")
        result["warnings"].append("aggregate_provider_groups_are_publisher_proxy_groups")
        result["warnings"].append("aggregate_does_not_verify_requested_quantity_or_calendar_duration")
    result["warnings"] = sorted(set(result["warnings"]) | {warning for row in rows for warning in row["warnings"]})
    if holds:
        return result
    weights, error = _project(rows, source_cap, group_cap)
    if error:
        result.update(status="held", hold_reasons=[error])
        return result
    samples = [(row["price"], weight) for row, weight in zip(rows, weights)]
    if policy["estimator"] == "weighted_median":
        mark = _median(samples)
    elif len({price for price, _ in samples}) == 1:
        mark = samples[0][0]
    else:
        mark = sum(p * w for p, w in samples) / sum(weights)
    source_shares, group_shares = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for row, weight in zip(rows, weights):
        source_shares[row["source_id"]] += weight
        group_shares[row["group_id"]] += weight
        result["contributors"].append({**{k: v for k, v in row.items() if k not in {"price", "raw_weight", "dedupe_key"}},
                                       "normalized_price": text_number(row["price"]),
                                       "raw_weight": text_number(row["raw_weight"]), "weight": text_number(weight)})
    result.update(price=text_number(mark), estimator=policy["estimator"], diagnostics={
        "source_shares": {key: text_number(value) for key, value in source_shares.items()},
        "provider_shares": {key: text_number(value) for key, value in group_shares.items()},
        "weight_sum": text_number(sum(weights)), "weight_tolerance": text_number(TOLERANCE),
        "effective_support": text_number(sum(weights) ** 2 / sum(weight * weight for weight in weights)),
        "weighted_dispersion": text_number(sum(weight * (price - mark) ** 2 for price, weight in samples) / sum(weights)),
        "median_half_weight_tolerance": text_number(TOLERANCE),
        "uncertainty_status": "dispersion_not_a_calibrated_confidence_interval",
    })
    return result
