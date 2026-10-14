"""Inverse linear bid/ask model with explicit denominators and owned costs.

This model implements declared scenarios, not calibrated collection forecasts.
Liquidity is recomputed through the supplied final dated settlement horizon.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from typing import Any

from .._numbers import calculation_precision, digest, hours, number, text_number
from ..benchmark import evaluate_benchmark
from ..domain import ValidationError, admission_blockers, parse_pricing_request, utc_instant
from .liquidity import cash_price_limit

ZERO, ONE = Decimal(0), Decimal(1)


def _tick(value: Decimal, tick: Decimal, *, sell=False) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_CEILING if sell else ROUND_FLOOR) * tick


def _costs(commercial, supply_hours):
    entries = commercial.get("costs")
    owners = commercial.get("cost_owners")
    if not isinstance(entries, list) or len(entries) > 1000 or not isinstance(owners, dict):
        raise ValidationError("commercial: explicit owned cost list required")
    seen, channels = set(), set()
    expected_fixed = capital_fixed = purchase_coefficient = ZERO
    breakdown = []
    for row in entries:
        if not isinstance(row, dict):
            raise ValidationError("cost: object required")
        if row.get("currency", commercial["currency"]) != commercial["currency"]:
            raise ValidationError("cost: currency mismatch requires explicit conversion")
        identity, channel, owner = row.get("id"), row.get("channel"), row.get("owner_model")
        if (not isinstance(identity, str) or not identity or identity in seen
                or not isinstance(channel, str) or not channel or channel in channels
                or owners.get(channel) != owner or not isinstance(owner, str) or not owner):
            raise ValidationError("cost: unique IDs/channels and approved model ownership required")
        if channel == "buyer_nonpayment":
            raise ValidationError("buyer nonpayment belongs in collection_share, not a duplicate cost")
        seen.add(identity)
        channels.add(channel)
        amount = number(row.get("amount"), "cost amount")
        basis, kind = row.get("basis"), row.get("kind")
        if kind not in {"expected_cost", "policy_capital"}:
            raise ValidationError("cost kind: expected_cost or policy_capital required")
        if basis == "fixed_contract":
            contribution = amount
        elif basis == "supply_gpu_hour":
            contribution = amount * supply_hours
        elif basis == "fraction_of_supply_purchase" and kind == "expected_cost":
            contribution = ZERO
            purchase_coefficient += number(row["amount"], "purchase cost fraction", fraction=True)
        else:
            raise ValidationError("cost basis: unsupported or ambiguous")
        if kind == "policy_capital":
            capital_fixed += contribution
        else:
            expected_fixed += contribution
        breakdown.append({**row, "fixed_amount": text_number(contribution)})
    return expected_fixed, capital_fixed, purchase_coefficient, breakdown


def evaluate_pricing(payload: dict[str, Any]) -> dict:
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        return _evaluate(payload)


def _evaluate(payload):
    if not isinstance(payload, dict):
        raise ValidationError("pricing input: object required")
    market = parse_pricing_request(payload.get("market"))
    target = payload.get("target")
    if not isinstance(target, dict):
        raise ValidationError("target: required")
    benchmark_policy = market.policy.parameters.get("benchmark")
    if not isinstance(benchmark_policy, dict):
        # Domain snapshots expose immutable Mapping proxies, not necessarily dicts.
        benchmark_policy = market.policy.to_dict()["parameters"].get("benchmark")
    policy_eligible = [o for o in market.observations if not admission_blockers(o, as_of=market.as_of, purpose="indicative", policy=market.policy)]
    benchmark = evaluate_benchmark([o.to_dict() for o in policy_eligible], target,
                                  benchmark_policy, market.as_of)
    result = {"schema_version": "1.0.0", "status": "held", "executable": False,
              "firm_price_eligible": False, "hold_reasons": [],
              "warnings": ["declared_scenario_not_calibrated_collection_or_performance_forecast",
                           "firm_pricing_and_execution_review_not_implemented"],
              "request_id": market.request_id, "as_of": market.as_of,
              "benchmark": benchmark, "economics": None, "bid": None,
              "versions": {"model": "inverse-linear/1.0.0", "implementation": "net-service-settlement/1.0.2", "policy": market.policy.version,
                           "registry": market.policy.registry_version, "schema": market.schema_version}}
    if utc_instant(market.as_of) < utc_instant(market.policy.effective_at):
        result["hold_reasons"].append("policy_not_yet_effective")
    if market.policy.expires_at is not None and utc_instant(market.as_of) >= utc_instant(market.policy.expires_at):
        result["hold_reasons"].append("policy_expired")
    if market.policy.critical_feature_ids:
        result["hold_reasons"].append("critical_feature_model_activation_requires_validated_model")
    result["unused_feature_ids"] = [feature.feature_id for feature in market.features]
    if market.features:
        result["warnings"].append("features_preserved_but_not_priced_without_validated_owning_model")
    result["policy_excluded_observation_ids"] = [o.id for o in market.observations if o not in policy_eligible]
    if benchmark["status"] == "held":
        result["hold_reasons"].append("benchmark_held")
    commercial = payload.get("commercial")
    if commercial is None:
        result.update(status="indicative" if not result["hold_reasons"] else "held")
        result["warnings"].append("no_commercial_terms_no_bid_or_ask")
        result["input_hash"] = digest(payload)
        result["decision_hash"] = digest(result)
        return result
    if not isinstance(commercial, dict) or commercial.get("currency") != target["currency"]:
        raise ValidationError("commercial: explicit matching currency required")
    known_terms = {"currency", "exclusive_node_gpu_count", "buyer_billed_gpu_hours", "buyer_rate", "supplier_ask", "collection_share", "fee_on_collected", "fee_on_gross", "required_margin", "margin_basis", "tick_size", "market_discount", "stress_price_cap", "costs", "cost_owners", "extensions"}
    result["unused_commercial_fields"] = sorted(set(commercial) - known_terms)
    if result["unused_commercial_fields"] or commercial.get("extensions"):
        result["warnings"].append("unregistered_commercial_fields_preserved_but_not_priced")
    if target["scope"] != "physical_offer":
        result["hold_reasons"].append("aggregate_reference_cannot_price_physical_commitment")
    actual_hours = hours(target.get("starts_at"), target.get("ends_at"))
    if actual_hours != number(target.get("duration_hours"), "duration_hours", positive=True):
        raise ValidationError("target duration does not match actual calendar")
    supply_hours = actual_hours * number(target.get("gpu_count"), "gpu_count", positive=True)
    allocation = number(commercial.get("exclusive_node_gpu_count"), "exclusive node GPU count", positive=True)
    count = number(target.get("gpu_count"), "GPU count", positive=True)
    if allocation != allocation.to_integral_value() or count != count.to_integral_value() or count % allocation != 0:
        raise ValidationError("exclusive physical allocation requires complete nodes and integer GPUs")
    billed_hours = number(commercial.get("buyer_billed_gpu_hours"), "buyer billed hours", positive=True)
    if billed_hours > supply_hours:
        raise ValidationError("buyer physical billings exceed exclusive supply hours")
    buyer_rate = number(commercial.get("buyer_rate"), "buyer rate", positive=True)
    supplier_ask = number(commercial.get("supplier_ask"), "supplier ask")
    q = number(commercial.get("collection_share"), "collection share", fraction=True)
    collected_fee = number(commercial.get("fee_on_collected"), "collected fee", fraction=True)
    gross_fee = number(commercial.get("fee_on_gross"), "gross fee", fraction=True)
    margin = number(commercial.get("required_margin"), "required margin", fraction=True)
    margin_basis = commercial.get("margin_basis")
    if margin_basis not in {"gross_billings", "collected_revenue"}:
        raise ValidationError("margin_basis: explicit gross or collected revenue required")
    margin_multiplier = ONE if margin_basis == "gross_billings" else q
    fee_factor = q * (ONE - collected_fee) - gross_fee
    margin_factor = fee_factor - margin * margin_multiplier
    tick = number(commercial.get("tick_size"), "tick size", positive=True)
    if tick < Decimal("0.000000000001"):
        raise ValidationError("tick size: finer than supported monetary grid")
    discount = number(commercial.get("market_discount"), "market discount", fraction=True)
    expected_fixed, capital, purchase_extra, costs = _costs(commercial, supply_hours)
    total_fixed = expected_fixed + capital
    supply_coefficient = supply_hours * (ONE + purchase_extra)
    if margin_factor <= 0:
        result["hold_reasons"].append("no_feasible_collection_fee_margin_denominator")
    caps = {}
    if margin_factor > 0:
        caps["economic_margin"] = (buyer_rate * billed_hours * margin_factor - total_fixed) / supply_coefficient
    if benchmark["price"] is not None:
        caps["market"] = Decimal(benchmark["price"]) * (ONE - discount)
    if commercial.get("stress_price_cap") is not None:
        caps["stress"] = number(commercial["stress_price_cap"], "stress price cap")
    if "liquidity_points" in payload:
        raise ValidationError("unverified liquidity points: supply complete cash_template instead")
    if payload.get("cash_template") is None:
        result["hold_reasons"].append("missing_full_horizon_cash_evidence")
    elif caps and min(caps.values()) > 0:
        liquidity = cash_price_limit(payload["cash_template"], currency=target["currency"],
                                     as_of=market.as_of, delivery_end=target["ends_at"],
                                     maximum=min(caps.values()), tick=tick,
                                     expected_purchase_coefficient=supply_coefficient,
                                     expected_fixed_outflows=expected_fixed + buyer_rate * billed_hours * (q * collected_fee + gross_fee),
                                     expected_collections=buyer_rate * billed_hours * q,
                                     expected_billings=buyer_rate * billed_hours,
                                     supplied_ask=supplier_ask)
        result["cash_constraint"] = liquidity
        if liquidity["status"] != "feasible":
            result["hold_reasons"].append("daily_cash_constraints_infeasible")
        elif liquidity["liquidity_binding_on_searched_grid"]:
            caps["daily_liquidity"] = Decimal(liquidity["maximum_purchase_tick"])
    if "economic_margin" not in caps or "market" not in caps:
        result["hold_reasons"].append("missing_required_purchase_cap")
    result["caps"] = {key: text_number(value) for key, value in caps.items()}
    if caps:
        reservation = min(caps.values())
        if reservation <= 0:
            result["hold_reasons"].append("no_positive_feasible_purchase_price")
        else:
            bid = _tick(reservation, tick)
            if bid <= 0:
                result["hold_reasons"].append("no_positive_feasible_purchase_tick")
            if not result["hold_reasons"]:
                result["bid"] = {"reservation": text_number(reservation), "submitted_limit": text_number(bid),
                                 "reservation_basis": "minimum_required_and_explicit_optional_caps_before_final_tick_rounding",
                                 "binding_constraints": [key for key, value in caps.items() if value == reservation],
                                 "supplier_ask_within_caps": supplier_ask <= reservation}
    gross_revenue = buyer_rate * billed_hours
    collected_revenue = gross_revenue * q
    expected_cost = supplier_ask * supply_coefficient + expected_fixed
    economic_cost = expected_cost + capital
    expected_contribution = gross_revenue * fee_factor - expected_cost
    economic_profit = expected_contribution - capital
    floors = {}
    if fee_factor > 0:
        floors["zero_expected_contribution"] = expected_cost / (billed_hours * fee_factor)
        floors["zero_economic_profit"] = economic_cost / (billed_hours * fee_factor)
    if margin_factor > 0:
        floors["required_margin"] = economic_cost / (billed_hours * margin_factor)
        floors["sell_floor_tick"] = _tick(floors["required_margin"], tick, sell=True)
    result["ask"] = {key: text_number(value) for key, value in floors.items()}
    result["economics"] = {
        "currency": target["currency"], "unit": "gpu_hour", "supply_gpu_hours": text_number(supply_hours),
        "gross_billed_gpu_hours": text_number(billed_hours), "gross_billings": text_number(gross_revenue),
        "expected_collections": text_number(collected_revenue), "expected_cost": text_number(expected_cost),
        "economic_cost": text_number(economic_cost), "capital_charge": text_number(capital),
        "expected_contribution": text_number(expected_contribution), "economic_profit": text_number(economic_profit),
        "margin_basis": margin_basis, "margin_denominator": text_number(gross_revenue if margin_basis == "gross_billings" else collected_revenue),
        "cost_breakdown": costs, "supplier_price_basis": "supplied_supplier_ask_not_reservation_bid",
        "collection_share": text_number(q), "collected_fee_fraction": text_number(collected_fee),
        "gross_fee_fraction": text_number(gross_fee), "net_collection_fee_factor": text_number(fee_factor),
        "required_margin_factor": text_number(margin_factor), "purchase_cost_coefficient": text_number(supply_coefficient),
        "fees": text_number(gross_revenue * (q * collected_fee + gross_fee)),
    }
    denominator = gross_revenue if margin_basis == "gross_billings" else collected_revenue
    result["economics"]["economic_margin"] = text_number(economic_profit / denominator) if denominator > 0 else None
    result["hold_reasons"] = sorted(set(result["hold_reasons"]))
    result["status"] = "held" if result["hold_reasons"] else "indicative"
    result["input_hash"] = digest(payload)
    result["decision_hash"] = digest(result)
    return result
