"""Exact tick search against a complete, monotone, dated cash ledger.

Only supplier outflows and their accounting counterparts may depend on the
purchase rate. Facilities and price-dependent inflows require a different model.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_FLOOR

from .._numbers import number, text_number
from ..domain import ValidationError
from ..treasury import evaluate_cash_payload


VARIABLE_KINDS = {"supplier_invoice", "supplier_payment", "supplier_prepayment", "prepaid_apply", "expense", "other_outflow"}


def cash_price_limit(template, *, currency, as_of, delivery_end, maximum, tick,
                     expected_purchase_coefficient, expected_fixed_outflows, expected_collections, supplied_ask):
    if not isinstance(template, dict) or set(template) != {"schedule", "purchase_coefficients", "minimum_cash", "deal_event_ids"}:
        raise ValidationError("cash_template: explicit schedule, coefficients and minimum cash required")
    schedule = template["schedule"]
    coefficients = template["purchase_coefficients"]
    if not isinstance(schedule, dict) or not isinstance(coefficients, dict) or not coefficients:
        raise ValidationError("cash_template: nonempty price-dependent supplier schedule required")
    if schedule.get("currency") != currency or schedule.get("facility") is not None:
        raise ValidationError("cash_template: matching currency and cash-only funding required")
    floor = number(template["minimum_cash"], "minimum cash")
    try:
        if date.fromisoformat(schedule["start_date"]) > date.fromisoformat(as_of[:10]) or date.fromisoformat(schedule["end_date"]) < max(date.fromisoformat(delivery_end[:10]), date.fromisoformat(as_of[:10])):
            raise ValidationError("cash_template: horizon must include as-of, delivery and final settlement")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("cash_template: valid complete calendar required") from exc
    events = schedule.get("events")
    if not isinstance(events, list) or len(events) > 10000:
        raise ValidationError("cash_template: bounded ordered events required")
    ids = [event.get("event_id") for event in events if isinstance(event, dict)]
    if len(ids) != len(events) or len(set(ids)) != len(ids) or set(coefficients) - set(ids):
        raise ValidationError("cash_template: unique registered event coefficients required")
    parsed = {key: number(value, "purchase coefficient", positive=True) for key, value in coefficients.items()}
    deal_ids = template["deal_event_ids"]
    if (not isinstance(deal_ids, list) or any(not isinstance(identity, str) for identity in deal_ids)
            or len(set(deal_ids)) != len(deal_ids) or set(deal_ids) - set(ids)
            or set(coefficients) - set(deal_ids)):
        raise ValidationError("cash_template: explicit unique deal event scope required")
    if not any(event.get("kind") in {"supplier_payment", "supplier_prepayment"} and event["event_id"] in parsed for event in events):
        raise ValidationError("cash_template: purchase coefficient must reach actual supplier cash")
    for event in events:
        number(event.get("amount"), "cash fixed event amount")
        if event["event_id"] in parsed and event.get("kind") not in VARIABLE_KINDS:
            raise ValidationError("cash_template: price-dependent inflow or financing is not monotone")
        if event.get("kind", "").startswith("facility_"):
            raise ValidationError("cash_template: facility legs unsupported in cash-only inversion")
    deal = [event for event in events if event["event_id"] in deal_ids]
    outflow_kinds = {"supplier_payment", "supplier_prepayment", "other_outflow"}
    coefficient_total = sum((parsed.get(event["event_id"], Decimal(0)) for event in deal if event.get("kind") in outflow_kinds), Decimal(0))
    fixed_total = sum((Decimal(event["amount"]) for event in deal if event.get("kind") in outflow_kinds), Decimal(0))
    collections = sum((Decimal(event["amount"]) for event in deal if event.get("kind") in {"buyer_receipt", "deposit_apply"}), Decimal(0))
    if (coefficient_total != expected_purchase_coefficient or fixed_total != expected_fixed_outflows
            or collections != expected_collections):
        raise ValidationError("cash_template: deal collections and purchase/cost legs must reconcile to economics")

    evaluations = 0

    def run(rate):
        nonlocal evaluations
        packet = deepcopy(schedule)
        packet["events"] = []
        for event in events:
            amount = Decimal(event["amount"]) + parsed.get(event["event_id"], Decimal(0)) * rate
            if amount > 0:
                packet["events"].append({**event, "amount": text_number(amount)})
        try:
            result = evaluate_cash_payload(packet)
        except (ValueError, TypeError) as exc:
            raise ValidationError("cash_template: inconsistent dated accounting at candidate price") from exc
        if any(result.unresolved_balances.values()):
            raise ValidationError("cash_template: final settlement leaves unresolved balances")
        evaluations += 1
        return result

    zero = run(Decimal(0))
    if zero.minimum_free_cash < floor:
        return {"status": "infeasible_at_zero", "maximum_purchase_tick": None,
                "binding_date": zero.minimum_free_cash_date, "evaluations": evaluations,
                "minimum_cash": text_number(floor), "model": "full-ledger-monotone-tick/1.0.1"}
    upper = max(0, int((maximum / tick).to_integral_value(rounding=ROUND_FLOOR)))
    upper_result = run(Decimal(upper) * tick)
    low, high = 0, upper
    binding = upper_result.minimum_free_cash < floor
    if binding:
        while low < high:
            middle = (low + high + 1) // 2
            result = run(Decimal(middle) * tick)
            if result.minimum_free_cash >= floor:
                low = middle
            else:
                high = middle - 1
    else:
        low = upper
    selected = run(Decimal(low) * tick)
    ask_schedule = run(supplied_ask)
    return {"status": "feasible", "maximum_purchase_tick": text_number(Decimal(low) * tick) if binding else None,
            "liquidity_binding_on_searched_grid": binding,
            "limit_censored_by_search_ceiling": not binding,
            "tested_purchase_tick": text_number(Decimal(low) * tick),
            "search_ceiling": text_number(maximum),
            "limit_basis": "maximum_feasible_purchase_tick" if binding else "cash_feasible_at_other_caps_tick_no_independent_liquidity_limit_identified",
            "binding_date": selected.minimum_free_cash_date,
            "minimum_free_cash": text_number(selected.minimum_free_cash),
            "minimum_cash": text_number(floor), "evaluations": evaluations,
            "start_date": schedule["start_date"], "end_date": schedule["end_date"],
            "legal_entity_id": schedule["legal_entity_id"], "cash_account_id": schedule["cash_account_id"],
            "model": "full-ledger-monotone-tick/1.0.1",
            "evidence_status": "caller_supplied_complete_settlement_scenario",
            "supplied_ask_cash_feasible": ask_schedule.minimum_free_cash >= floor,
            "supplied_ask_required_extra_cash": text_number(max(Decimal(0), floor - ask_schedule.minimum_free_cash)),
            "supplied_ask_minimum_free_cash": text_number(ask_schedule.minimum_free_cash),
            "selected_schedule": selected.to_dict()}
