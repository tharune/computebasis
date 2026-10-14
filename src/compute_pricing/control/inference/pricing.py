"""Explicit mix-specific price floors and qualified-capacity crossover analysis."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext

from compute_pricing.control._numbers import number, text_number
from compute_pricing.control.domain import ValidationError
from .supplier import apply_supplier_ceiling, initial_supplier_ceiling

RATE_FIELDS = ("input_per_million", "output_per_million", "cached_input_per_million", "request_fee")
POLICY_FIELDS = {"required_margin", "margin_basis", "policy_capital_amount", "task_price_tick", "rate_ticks"}
ZERO, ONE = Decimal(0), Decimal(1)


def _ceil_ratio(numerator, denominator):
    with localcontext() as context:
        context.rounding = ROUND_CEILING
        return numerator / denominator


def _sell_tick(value, tick):
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def _break_even(local_fixed, local_variable, routed_parts, capacity):
    if routed_parts is None:
        return {"status": "held", "blockers": ["qualified_routed_rate_and_explicit_operating_cost_items_required"]}
    routed_fixed, routed_variable = routed_parts
    fixed_difference, variable_saving = local_fixed - routed_fixed, routed_variable - local_variable
    result = {"status": "indicative", "blockers": [], "local_fixed_cost": text_number(local_fixed),
              "local_variable_cost_per_request": text_number(local_variable), "routed_fixed_cost": text_number(routed_fixed),
              "routed_variable_cost_per_request": text_number(routed_variable), "qualified_request_capacity": text_number(capacity),
              "theoretical_continuous_request_count": None, "whole_request_threshold": None,
              "threshold_utilization": None, "within_qualified_capacity": None,
              "basis": "same_declared_workload_and_horizon_no_demand_forecast"}
    if capacity <= 0:
        result.update(status="held", blockers=["no_positive_qualified_request_capacity"])
        return result
    if variable_saving == 0:
        result["relationship"] = "equal_at_all_volumes" if fixed_difference == 0 else "local_cheaper_at_all_volumes" if fixed_difference < 0 else "routed_cheaper_at_all_volumes"
        return result
    crossing = fixed_difference / variable_saving
    if crossing < 0:
        result["relationship"] = "local_cheaper_at_all_nonnegative_volumes" if fixed_difference < 0 else "routed_cheaper_at_all_nonnegative_volumes"
        return result
    result["theoretical_continuous_request_count"] = text_number(crossing)
    if variable_saving > 0:
        # Test the integer against the actual cost inequality, rather than allow
        # a finite-precision division to round an optimistic boundary downward.
        threshold = crossing.to_integral_value(rounding=ROUND_CEILING)
        if fixed_difference - variable_saving * threshold > 0:
            threshold += 1
        relationship = "local_no_more_expensive_at_or_above_threshold"
    else:
        threshold = crossing.to_integral_value(rounding=ROUND_FLOOR)
        if fixed_difference - variable_saving * threshold > 0:
            threshold -= 1
        relationship = "local_no_more_expensive_at_or_below_threshold"
    result.update(relationship=relationship, whole_request_threshold=text_number(threshold),
                  threshold_utilization=text_number(threshold / capacity), within_qualified_capacity=ZERO <= threshold <= capacity)
    if not result["within_qualified_capacity"]:
        result["status"] = "outside_qualified_capacity"
        result["blockers"] = ["crossover_not_attainable_with_qualified_whole_request_capacity"]
        result["preference_within_qualified_capacity"] = "local_no_more_expensive_at_all_feasible_whole_volumes" if variable_saving < 0 else "routed_cheaper_at_all_feasible_whole_volumes"
    return result


def inference_pricing_diagnostics(*, policy, requests, capacity, fixed_cost, variable_cost,
                                  billed_revenue, collection, collected_fee, gross_fee, sale_prices,
                                  routed_parts=None, supplier_ceiling_policy=None,
                                  allocated_gpu_hours=None, gpu_purchase_cost=None):
    break_even = _break_even(fixed_cost, variable_cost, routed_parts, capacity)
    supplier_report, supplier_tick = initial_supplier_ceiling(supplier_ceiling_policy)
    result = {"status": "held", "blockers": [], "model_version": "qualified-inference-pricing/1.1.0",
              "task_floors": None, "proportional_rate_vector": None, "break_even": break_even,
              "supplier_buy_ceiling": supplier_report,
              "warnings": ["price_vector_is_proportional_at_one_declared_mix_not_unique_or_optimized",
                           "no_buyer_demand_or_price_elasticity_validation", "capital_charge_not_a_cash_reserve_or_duplicate_expense"],
              "execution_enabled": False}
    if policy is None:
        result["blockers"] = ["missing_explicit_pricing_policy"]
        return result
    if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
        raise ValidationError("inference pricing_policy: exact fields required")
    missing = [field for field in POLICY_FIELDS if policy[field] is None]
    ticks = policy.get("rate_ticks")
    if isinstance(ticks, dict):
        if set(ticks) != set(RATE_FIELDS):
            raise ValidationError("inference rate_ticks: exact monetary dimensions required")
        missing += ["rate_ticks." + key for key in RATE_FIELDS if ticks[key] is None]
    elif ticks is not None:
        raise ValidationError("inference rate_ticks: object required")
    if missing:
        result["blockers"] = ["missing:" + field for field in sorted(missing)]
        return result
    if policy["margin_basis"] not in {"gross_billings", "collected_revenue"}:
        raise ValidationError("inference margin_basis: explicit gross or collected basis required")
    margin = number(policy["required_margin"], "required inference margin", fraction=True)
    capital = number(policy["policy_capital_amount"], "inference policy capital")
    task_tick = number(policy["task_price_tick"], "task price tick", positive=True)
    price_ticks = {key: number(ticks[key], key + " tick", positive=True) for key in RATE_FIELDS}
    if any(tick < Decimal("0.000000000001") for tick in (task_tick, *price_ticks.values())):
        raise ValidationError("inference ticks: finer than supported monetary grid")
    if requests <= 0:
        result["blockers"] = ["positive_served_request_volume_required_for_price_floors"]
        return result
    fee_factor = collection * (ONE - collected_fee) - gross_fee
    margin_factor = fee_factor - margin * (ONE if policy["margin_basis"] == "gross_billings" else collection)
    result.update(margin_basis=policy["margin_basis"], required_margin=text_number(margin),
                  policy_capital_amount=text_number(capital), net_collection_fee_factor=text_number(fee_factor),
                  required_margin_factor=text_number(margin_factor))
    if fee_factor <= 0 or margin_factor <= 0:
        result["blockers"] = ["no_positive_collection_fee_margin_denominator"]
        return result
    expected_cost = fixed_cost + variable_cost * requests
    economic_cost = expected_cost + capital
    current_profit = billed_revenue * fee_factor - economic_cost
    margin_denominator = billed_revenue if policy["margin_basis"] == "gross_billings" else billed_revenue * collection
    result.update(current_economic_profit=text_number(current_profit),
                  current_margin_denominator=text_number(margin_denominator),
                  current_economic_margin=text_number(current_profit / margin_denominator) if margin_denominator else None)
    expected_floor = _ceil_ratio(expected_cost, requests * fee_factor)
    economic_floor = _ceil_ratio(economic_cost, requests * fee_factor)
    margin_floor = _ceil_ratio(economic_cost, requests * margin_factor)
    result["task_floors"] = {"unit": "per_declared_task", "expected_cost": text_number(expected_cost),
                           "economic_cost": text_number(economic_cost), "zero_expected_contribution": text_number(expected_floor),
                           "zero_economic_profit": text_number(economic_floor), "required_margin": text_number(margin_floor),
                           "required_margin_sell_tick": text_number(_sell_tick(margin_floor, task_tick))}
    if billed_revenue <= 0:
        result["blockers"] = ["zero_sale_vector_cannot_be_proportionally_scaled"]
        return result
    apply_supplier_ceiling(supplier_report, supplier_tick, hours=allocated_gpu_hours, purchase_cost=gpu_purchase_cost,
        other_cost=expected_cost - gpu_purchase_cost if gpu_purchase_cost is not None else ZERO,
        capital=capital, gross=billed_revenue, margin_factor=margin_factor)
    scale = _ceil_ratio(economic_cost, billed_revenue * margin_factor)
    with localcontext() as context:
        context.rounding = ROUND_CEILING
        scaled = {key: _sell_tick(sale_prices[key] * scale, price_ticks[key]) for key in RATE_FIELDS}
    result["proportional_rate_vector"] = {"status": "indicative", "scale": text_number(scale),
                                         "rates": {key: text_number(value) for key, value in scaled.items()},
                                         "rate_ticks": {key: text_number(tick) for key, tick in price_ticks.items()},
                                         "basis": "upward_ticks_at_declared_workload_not_a_universal_price_floor"}
    result["status"] = "indicative"
    return result
