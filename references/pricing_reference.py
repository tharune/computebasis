"""Synthetic weighted-price and bid/ask arithmetic oracle. No execution APIs.

Pre-admitted normalized observations and supplied simplified caps are assumed.
This does not implement production admission, calibration, daily liquidity,
portfolio risk, credit modeling, or a regression-derived region premium.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
from pathlib import Path
from typing import Any


def number(raw: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ValueError(f"{label} requires a decimal string or integer")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{label} is not a decimal") from exc
    if not value.is_finite() or value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def linear_gross_margin_ask(
    cost: Decimal, gross_billed_hours: Decimal, collection_share: Decimal,
    collected_fee_fraction: Decimal, gross_fee_fraction: Decimal, gross_margin: Decimal,
) -> Decimal:
    """Collection loss is represented by q, and therefore excluded from cost.

All inputs are Decimal. C is ask-independent, volume known, and fees linear.
"""
    inputs = (cost, gross_billed_hours, collection_share, collected_fee_fraction, gross_fee_fraction, gross_margin)
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in inputs):
        raise ValueError("Finite Decimal inputs required")
    if cost < 0 or gross_billed_hours <= 0:
        raise ValueError("Nonnegative cost and positive gross billed hours required")
    if any(value < 0 or value > 1 for value in inputs[2:]):
        raise ValueError("Shares must be fractions between zero and one")
    with localcontext() as context:
        context.prec = 40
        factor = collection_share * (1 - collected_fee_fraction) - gross_fee_fraction - gross_margin
        if factor <= 0:
            raise ValueError("No feasible linear ask with this collection, fee and margin basis")
        return cost / (gross_billed_hours * factor)


def round_tick(value: Decimal, tick: Decimal, *, sell: bool) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_CEILING if sell else ROUND_FLOOR) * tick


def calculate(data: dict[str, Any]) -> dict[str, Any]:
    with localcontext() as context:
        context.prec = 40
        return _calculate(data)


def _calculate(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("kind") != "illustrative_pricing_fixture" or data.get("source_is_mock") is not True:
        raise ValueError("Labeled synthetic fixtures only")
    if data.get("currency") != "USD" or data.get("unit") != "USD/GPU-hour":
        raise ValueError("This reference requires normalized USD/GPU-hour")
    if data.get("price_independent_costs") is not True or number(data.get("collection_share"), "collection_share") != 1:
        raise ValueError("Fixture calculator requires price-independent costs and full collection")
    if data.get("market_cap_policy") != "localized_mark_for_fixture" or data.get("liquidity_cap_scope") != "signing_only":
        raise ValueError("Simplified market/liquidity assumptions must be explicit")
    observations = data.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("At least one pre-admitted comparable observation required")
    prices_weights = []
    ids = set()
    for observation in observations:
        if observation.get("kind") not in {"listing_ask", "firm_supplier_rfq", "confirmed_rental_trade"} or observation.get("unit") != "USD/GPU-hour":
            raise ValueError("Incompatible observation; no event, options, futures or token price averaging")
        identity = observation.get("id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("Unique nonempty observation IDs required")
        ids.add(identity)
        prices_weights.append((number(observation.get("price"), identity + ".price", positive=True), number(observation.get("weight"), identity + ".weight")))
    weight_total = sum((weight for _, weight in prices_weights), Decimal(0))
    if weight_total == 0:
        raise ValueError("Zero benchmark support")
    benchmark = sum((price * weight for price, weight in prices_weights), Decimal(0)) / weight_total
    final_weights = [weight / weight_total for _, weight in prices_weights]
    effective_support = 1 / sum((weight * weight for weight in final_weights), Decimal(0))
    localized_mark = benchmark * number(data.get("target_region_multiplier"), "region multiplier", positive=True)
    buyer_rate = number(data.get("gross_buyer_rate_per_gpu_hour"), "buyer rate", positive=True)
    fee = number(data.get("distribution_fee_fraction_of_gross_revenue"), "fee")
    margin = number(data.get("required_economic_margin_fraction_of_gross_revenue"), "margin")
    if fee + margin >= 1:
        raise ValueError("Fee and margin leave no feasible ask denominator")
    costs = data.get("nonpurchase_expected_costs_per_gpu_hour")
    if not isinstance(costs, dict) or not costs:
        raise ValueError("Explicit nonpurchase expected costs required")
    nonpurchase_expected = sum((number(value, key) for key, value in costs.items()), Decimal(0))
    capital_charge = number(data.get("policy_capital_charge_per_gpu_hour"), "capital charge")
    nonpurchase_economic = nonpurchase_expected + capital_charge
    economic_cap = buyer_rate * (1 - fee - margin) - nonpurchase_economic
    stress_cap = number(data.get("assumed_stress_bid_cap_per_gpu_hour"), "stress cap", positive=True)
    funds = number(data.get("usable_signing_funds_before_buffer"), "signing funds")
    buffer = number(data.get("required_signing_buffer"), "buffer")
    advance = number(data.get("supplier_advance_fraction_of_full_horizon"), "supplier advance", positive=True)
    if advance > 1:
        raise ValueError("Advance fraction cannot exceed one")
    hours = number(data.get("contractual_billed_gpu_hours"), "billed hours", positive=True)
    liquidity_cap = (funds - buffer) / (advance * hours)
    caps = {"economic": economic_cap, "market": localized_mark, "stress": stress_cap, "signing_liquidity_only": liquidity_cap}
    reservation_bid = min(caps.values())
    if reservation_bid <= 0:
        raise ValueError("No positive feasible bid; return hold/restructure in production")
    supplier_ask = number(data.get("observed_supplier_ask_per_gpu_hour"), "supplier ask", positive=True)
    tick = number(data.get("tick_size_per_gpu_hour"), "tick", positive=True)
    submitted_bid_limit = round_tick(reservation_bid, tick, sell=False)
    if submitted_bid_limit <= 0:
        raise ValueError("No positive feasible buy tick at or below the reservation bid")
    expected_cost = supplier_ask + nonpurchase_expected
    economic_cost = expected_cost + capital_charge
    zero_expected_ask = linear_gross_margin_ask(expected_cost, Decimal(1), Decimal(1), Decimal(0), fee, Decimal(0))
    zero_economic_ask = linear_gross_margin_ask(economic_cost, Decimal(1), Decimal(1), Decimal(0), fee, Decimal(0))
    minimum_margin_ask = linear_gross_margin_ask(economic_cost, Decimal(1), Decimal(1), Decimal(0), fee, margin)
    expected_contribution = buyer_rate * (1 - fee) - expected_cost
    economic_profit = expected_contribution - capital_charge
    return {
        "kind": "synthetic_reference_result", "executable": False,
        "benchmark": benchmark, "final_normalized_weights": final_weights,
        "effective_weight_support_not_confidence": effective_support,
        "localized_mark": localized_mark, "bid_caps": caps,
        "binding_constraints": [name for name, value in caps.items() if value == reservation_bid],
        "reservation_bid": reservation_bid, "submitted_bid_limit_tick": submitted_bid_limit,
        "supplier_ask_within_simplified_caps": supplier_ask <= reservation_bid,
        "zero_expected_contribution_ask": zero_expected_ask,
        "zero_economic_profit_ask": zero_economic_ask,
        "minimum_economic_margin_ask": minimum_margin_ask,
        "sell_floor_tick": round_tick(minimum_margin_ask, tick, sell=True),
        "expected_contribution_per_gpu_hour": expected_contribution,
        "economic_profit_per_gpu_hour": economic_profit,
        "expected_contribution_total": expected_contribution * hours,
        "economic_profit_total": economic_profit * hours,
        "economic_margin_on_gross_billings": economic_profit / buyer_rate,
        "assumptions": data.get("assumptions", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    result = calculate(json.loads(args.fixture.read_text()))
    print(json.dumps(result, indent=2, default=lambda value: str(value) if isinstance(value, Decimal) else value))


if __name__ == "__main__":
    main()
