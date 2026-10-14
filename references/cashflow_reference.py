"""Decimal arithmetic oracle for the planning fixture. No execution capabilities.

Monthly accrual and cash are intentionally simplified; this is not the production
daily liquidity engine. Negative balances show funding needs before financing.
"""
from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any


def decimal_input(data: dict[str, Any], key: str) -> Decimal:
    raw = data[key]
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ValueError(f"{key} must be a decimal string or integer")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{key} must contain a valid decimal") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{key} must be finite and nonnegative")
    return value


def integer_input(data: dict[str, Any], key: str, minimum: int = 0) -> int:
    value = data[key]
    if type(value) is not int or value < minimum:
        raise ValueError(f"{key} must be an integer >= {minimum}")
    return value


def calculate(data: dict[str, Any]) -> dict[str, Any]:
    with localcontext() as context:
        context.prec = 40
        return _calculate(data)


def _calculate(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("kind") != "illustrative_planning_fixture" or data.get("source_is_mock") is not True:
        raise ValueError("This reference accepts labeled mock planning fixtures only")
    if not re.fullmatch(r"[A-Z]{3}", data.get("currency", "")):
        raise ValueError("Explicit ISO-style currency code required")
    if data.get("supplier_advance_treatment") != "credited_evenly":
        raise ValueError("Only evenly credited supplier advances are modeled")
    if data.get("forward_advance_restricted_until_delivery") is not True:
        raise ValueError("This reference requires forward advance restriction")

    nodes = integer_input(data, "supply_nodes", 1)
    gpus = integer_input(data, "gpus_per_node", 1)
    months = integer_input(data, "months", 1)
    wholesale_nodes = integer_input(data, "wholesale_nodes")
    forward_nodes = integer_input(data, "forward_nodes")
    forward_start = integer_input(data, "forward_start_month", 1)
    forward_months = integer_input(data, "forward_months", 1)
    if forward_start + forward_months - 1 > months:
        raise ValueError("Forward delivery extends beyond supply rights")
    if wholesale_nodes + forward_nodes > nodes:
        raise ValueError("Dedicated reservations exceed supply capacity")

    keys = (
        "hours_per_month", "supply_rate_per_gpu_hour", "supplier_advance_fraction",
        "wholesale_rate_per_gpu_hour", "wholesale_advance_fraction",
        "forward_rate_per_gpu_hour", "forward_advance_fraction",
        "inference_paid_utilization", "inference_revenue_equivalent_per_occupied_gpu_hour",
        "distribution_cost_fraction_of_earned_revenue", "monthly_operations_cost",
        "treasury_buffer",
    )
    values = {key: decimal_input(data, key) for key in keys}
    for key in (
        "supplier_advance_fraction", "wholesale_advance_fraction",
        "forward_advance_fraction", "inference_paid_utilization",
        "distribution_cost_fraction_of_earned_revenue",
    ):
        if values[key] > 1:
            raise ValueError(f"{key} must be a fraction between zero and one")
    if values["distribution_cost_fraction_of_earned_revenue"] == 1:
        raise ValueError("Distribution cost fraction must be less than one")
    if values["hours_per_month"] == 0:
        raise ValueError("Hours must be positive")
    if type(data.get("wholesale_advance_permitted_use")) is not bool:
        raise ValueError("Wholesale advance permitted-use decision required")

    node_hours = Decimal(gpus) * values["hours_per_month"]
    supply_cost = Decimal(nodes) * node_hours * values["supply_rate_per_gpu_hour"]
    wholesale_revenue = Decimal(wholesale_nodes) * node_hours * values["wholesale_rate_per_gpu_hour"]
    forward_revenue = Decimal(forward_nodes) * node_hours * values["forward_rate_per_gpu_hour"]
    basis = data.get("supplier_advance_basis")
    if basis not in ("full_term", "first_month"):
        raise ValueError("Supplier advance base must be explicit: full_term or first_month")
    supplier_advance = supply_cost * (months if basis == "full_term" else 1) * values["supplier_advance_fraction"]
    wholesale_advance = wholesale_revenue * months * values["wholesale_advance_fraction"]
    forward_advance = forward_revenue * forward_months * values["forward_advance_fraction"]

    supplier_credit = supplier_advance / months
    wholesale_credit = wholesale_advance / months
    forward_credit = forward_advance / forward_months
    supplier_asset = supplier_advance
    wholesale_liability = wholesale_advance
    forward_liability = forward_advance
    wholesale_is_usable = data["wholesale_advance_permitted_use"]
    total_cash = wholesale_advance + forward_advance - supplier_advance
    restricted_cash = forward_liability + (0 if wholesale_is_usable else wholesale_liability)
    unrestricted = total_cash - restricted_cash
    min_unrestricted = unrestricted
    total_contribution = Decimal(0)
    rows = [{
        "month": 0, "earned_revenue": Decimal(0), "contribution": Decimal(0),
        "net_cash_flow": total_cash, "closing_cash_before_financing": total_cash,
        "restricted_cash": restricted_cash, "unrestricted_cash_before_financing": unrestricted,
        "supplier_prepaid_asset": supplier_asset, "buyer_advance_liability": wholesale_liability + forward_liability,
    }]
    for month in range(1, months + 1):
        forward_active = forward_start <= month < forward_start + forward_months
        active_forward_nodes = forward_nodes if forward_active else 0
        inference_nodes = nodes - wholesale_nodes - active_forward_nodes
        inference_revenue = Decimal(inference_nodes) * node_hours * values["inference_paid_utilization"] * values["inference_revenue_equivalent_per_occupied_gpu_hour"]
        earned_forward = forward_revenue if forward_active else Decimal(0)
        earned_revenue = wholesale_revenue + inference_revenue + earned_forward
        distribution = earned_revenue * values["distribution_cost_fraction_of_earned_revenue"]
        operations = values["monthly_operations_cost"]
        contribution = earned_revenue - supply_cost - distribution - operations
        forward_application = forward_credit if forward_active else Decimal(0)
        cash_receipts = wholesale_revenue - wholesale_credit + inference_revenue + earned_forward - forward_application
        cash_payments = supply_cost - supplier_credit + distribution + operations
        net_cash = cash_receipts - cash_payments
        total_cash += net_cash
        supplier_asset -= supplier_credit
        wholesale_liability -= wholesale_credit
        forward_liability -= forward_application
        restricted_cash = forward_liability + (0 if wholesale_is_usable else wholesale_liability)
        unrestricted = total_cash - restricted_cash
        min_unrestricted = min(min_unrestricted, unrestricted)
        total_contribution += contribution
        rows.append({
            "month": month, "wholesale_nodes": wholesale_nodes,
            "inference_nodes": inference_nodes, "forward_nodes": active_forward_nodes,
            "supply_cost": supply_cost, "wholesale_revenue": wholesale_revenue,
            "inference_revenue": inference_revenue, "forward_revenue": earned_forward,
            "earned_revenue": earned_revenue, "distribution_cost": distribution,
            "operations_cost": operations, "contribution": contribution,
            "cash_receipts": cash_receipts, "cash_payments": cash_payments,
            "net_cash_flow": net_cash, "closing_cash_before_financing": total_cash,
            "restricted_cash": restricted_cash, "unrestricted_cash_before_financing": unrestricted,
            "supplier_prepaid_asset": supplier_asset,
            "buyer_advance_liability": wholesale_liability + forward_liability,
        })

    # Decimal division can leave sub-cent precision tails for arbitrary inputs.
    tolerance = Decimal("0.00000000000000000001")
    if any(abs(value) > tolerance for value in (supplier_asset, wholesale_liability, forward_liability)):
        raise ArithmeticError("Advance balances do not amortize to zero")
    if abs(total_cash - total_contribution) > tolerance:
        raise ArithmeticError("Lifetime cash does not reconcile with earned contribution")
    initial_inference_nodes = nodes - wholesale_nodes - (forward_nodes if forward_start == 1 else 0)
    denominator = Decimal(initial_inference_nodes) * node_hours * values["inference_revenue_equivalent_per_occupied_gpu_hour"] * (1 - values["distribution_cost_fraction_of_earned_revenue"])
    initial_forward_revenue = forward_revenue if forward_start == 1 else Decimal(0)
    numerator = supply_cost + values["monthly_operations_cost"] - (wholesale_revenue + initial_forward_revenue) * (1 - values["distribution_cost_fraction_of_earned_revenue"])
    break_even = numerator / denominator if denominator else None
    return {
        "kind": "illustrative_monthly_reference_result", "currency": data["currency"],
        "supplier_advance": supplier_advance, "wholesale_advance": wholesale_advance,
        "forward_advance": forward_advance, "minimum_unrestricted_cash_before_financing": min_unrestricted,
        "required_opening_funding_including_buffer": max(Decimal(0), values["treasury_buffer"] - min_unrestricted),
        "total_operating_contribution_before_excluded_costs": total_contribution,
        "lifetime_cash_before_financing": total_cash,
        "early_inference_break_even_paid_utilization": break_even,
        "rows": rows,
        "limitations": data.get("excluded_costs", []) + [data.get("timing_assumption", "Monthly only")],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    result = calculate(json.loads(args.fixture.read_text()))
    print(json.dumps(result, indent=2, default=lambda value: str(value) if isinstance(value, Decimal) else value))


if __name__ == "__main__":
    main()
