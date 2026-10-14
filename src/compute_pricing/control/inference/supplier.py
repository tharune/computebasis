"""Conditional expected-economic limit for one explicitly owned GPU rate.

No cash calendar, market admission, lender approval or executable bid is inferred.
"""
from decimal import Decimal, ROUND_FLOOR, localcontext

from .._numbers import number, text_number
from ..domain import ValidationError

FIELDS = {"buy_tick_per_gpu_hour", "nonpurchase_costs_complete", "nonpurchase_costs_rate_independent"}
WAITING = "complete_calculable_pricing_policy_required"


def initial_supplier_ceiling(policy):
    report = {"status": "held", "blockers": [], "basis": "conditional_expected_economic_base_gpu_rate",
        "supplier_cost_owner": "gpu_allocation", "unit": "currency_per_allocated_gpu_hour",
        "allocated_gpu_hours": None, "nonpurchase_expected_cost": None, "policy_capital_amount": None,
        "signed_supplier_budget": None, "required_margin_ceiling_per_gpu_hour": None,
        "required_margin_buy_tick_ceiling": None, "buy_tick_per_gpu_hour": None,
        "nonnegative_supplier_rate_feasible": None, "current_base_gpu_quote_meets_required_margin": None,
        "cash_funding_assessed": False, "market_qualified_bid": False,
        "firm_price_eligible": False, "execution_enabled": False,
        "warnings": ["caller_cost_completeness_and_rate_independence_not_verified",
            "other_supplier_linked_charges_retained_at_declared_values_reprice_if_rate_sensitive",
            "no_dated_funding_market_credit_or_contract_admission"]}
    if policy is None:
        report["blockers"] = ["missing_explicit_supplier_ceiling_policy"]
        return report, None
    if not isinstance(policy, dict) or set(policy) != FIELDS:
        raise ValidationError("supplier ceiling: explicit tick, coverage and independence fields required")
    tick = None
    for field in sorted(FIELDS):
        value = policy[field]
        if value is None:
            report["blockers"].append("missing:" + field)
        elif field == "buy_tick_per_gpu_hour":
            tick = number(value, "supplier price grid", positive=True)
            if tick < Decimal("0.000000000001"):
                raise ValidationError("supplier price grid: below supported resolution")
            report[field] = text_number(tick)
        elif type(value) is not bool:
            raise ValidationError("supplier ceiling: coverage and independence require explicit booleans")
        elif not value:
            report["blockers"].append("complete_nonpurchase_cost_coverage_required" if field == "nonpurchase_costs_complete"
                                      else "rate_independent_nonpurchase_costs_required")
    if not report["blockers"]:
        report["blockers"] = [WAITING]
    return report, tick


def apply_supplier_ceiling(report, tick, *, hours, purchase_cost, other_cost, capital, gross, margin_factor):
    if report["blockers"] != [WAITING]:
        return
    if hours is None or purchase_cost is None or hours <= 0:
        report["blockers"] = ["positive_explicit_allocated_gpu_hours_and_base_cost_required"]
        return
    if other_cost < 0:
        raise ValidationError("supplier ceiling: expected operating cost ownership cannot be negative")
    budget = gross * margin_factor - other_cost - capital
    report.update(allocated_gpu_hours=text_number(hours), nonpurchase_expected_cost=text_number(other_cost),
        policy_capital_amount=text_number(capital), signed_supplier_budget=text_number(budget),
        nonnegative_supplier_rate_feasible=budget >= 0,
        current_base_gpu_quote_meets_required_margin=purchase_cost <= budget)
    if budget < 0:
        report["blockers"] = ["no_nonnegative_supplier_rate_meets_required_margin"]
        return
    with localcontext() as context:
        context.rounding = ROUND_FLOOR
        rate = budget / hours
        grid_rate = (rate / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    # Check the monetary inequality itself as well as the division direction.
    if grid_rate * hours > budget:
        grid_rate -= tick
    report.update(status="indicative", blockers=[], required_margin_ceiling_per_gpu_hour=text_number(rate),
        required_margin_buy_tick_ceiling=text_number(grid_rate))
