"""Bind an explicit paper resale scenario to one immutable simulated quote.

The selected supplier terms never come from a client copy. Buyer demand,
collections, cash and settlement choices remain explicit caller assumptions.
"""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, localcontext
import json
import sqlite3

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from compute_pricing.control._numbers import calculation_precision, digest, number, text_number
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.policies.repository import PolicyStoreError
from compute_pricing.control.reporting import SnapshotStoreError
from compute_pricing.control.quote_book.scoring import _month_end
from .demo import build_demo_pricing_request, demo_contract

VERSION = "book-deal/1.0.0"
ECONOMIC_FIELDS = frozenset({"buyer_rate", "billed_utilization", "collection_share", "fee_on_collected",
    "fee_on_gross", "fixed_operating_cost", "opening_cash", "minimum_cash", "required_margin", "tick_size"})
DATE_FIELDS = frozenset({"deposit_on", "supplier_invoice_on", "buyer_invoice_on", "buyer_receipt_on",
    "operating_cost_on", "fees_on", "writeoff_on"})
FIELDS = ECONOMIC_FIELDS | {"book_revision", "quote_id", "nodes", "payment_dates", "supplier_invoice_basis"}


def book_deal_contract():
    return {"contract_version": VERSION, "template": {**dict.fromkeys(sorted(FIELDS - {"payment_dates"})),
        "payment_dates": dict.fromkeys(sorted(DATE_FIELDS))},
        "book_revision": "Exact ETag returned by GET /v1/book; changes require a fresh decision",
        "supplier_invoice_basis_required": "single_full_contract_invoice",
        "bound_supplier_fields": ["price", "currency", "price_unit", "gpus_per_node", "nodes", "moq",
            "available", "months", "down_payment", "payment_days", "gpu", "location", "country",
            "lead_weeks", "interconnect", "cooling", "expires"],
        "quantity_unit": "whole_nodes", "money_encoding": "exact_plain_decimal_string",
        "calendar": "UTC delivery midnight; supplier balance due invoice date plus unadjusted calendar net days",
        "classification": "synthetic", "source_evidence_eligible": False, "execution_enabled": False,
        "warnings": ["single_full_contract_invoice_is_explicit_scenario_not_verified_supplier_billing",
            "deposit_is_percentage_of_full_contract_value_and_applied_once",
            "no_supplier_financing_interest_or_failure_premium_is_automatically_added",
            "buyer_terms_and_owned_operating_costs_are_caller_declared",
            "hypothetical_book_reference_is_not_an_admitted_market_cap"]}


def _calendar(value, label):
    if not isinstance(value, str) or len(value) != 10:
        raise ValidationError(label + ": explicit ISO calendar date required")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(label + ": invalid calendar date") from exc
    if result.isoformat() != value:
        raise ValidationError(label + ": canonical calendar date required")
    return result


def build_book_deal(payload, frame, revision):
    """Return a fresh native pricing request without saving or reserving capacity."""
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise ValidationError("book deal: complete explicit contract required")
    if payload["book_revision"] != revision:
        raise ValidationError("book_revision_changed")
    if (payload["supplier_invoice_basis"] != "single_full_contract_invoice"
            or not isinstance(payload["quote_id"], str) or len(payload["quote_id"]) > 128):
        raise ValidationError("explicit single invoice basis and quote ID required")
    quote = next((row for row in frame["quotes"] if row["id"] == payload["quote_id"]), None)
    if quote is None:
        raise ValidationError("simulated_quote_not_found")
    if quote.get("eligible") is not True or quote.get("synthetic") is not True:
        raise ValidationError("selected_simulated_quote_is_held")
    nodes = payload["nodes"]
    if type(nodes) is not int or not quote["moq"] <= nodes <= quote["nodes"]:
        raise ValidationError("whole node quantity must satisfy MOQ and quoted capacity")
    if quote["currency"] != "USD" or quote["price_unit"] != "gpu_hour":
        raise ValidationError("unsupported quote currency or price unit")
    dates = payload["payment_dates"]
    if not isinstance(dates, dict) or set(dates) != DATE_FIELDS:
        raise ValidationError("payment_dates: complete explicit calendar required")
    parsed = {key: _calendar(value, key) for key, value in dates.items()}
    as_of = _calendar(frame["meta"]["as_of"], "book assessment date")
    start = _calendar(quote["available"], "available")
    end = _month_end(start, quote["months"])
    if not as_of <= parsed["deposit_on"] <= start:
        raise ValidationError("deposit date must be between assessment and delivery start")
    if not start <= parsed["supplier_invoice_on"] <= end:
        raise ValidationError("supplier invoice must occur during declared delivery")
    if min(parsed.values()) < as_of:
        raise ValidationError("scenario settlement cannot precede assessment")
    try:
        balance_due = parsed["supplier_invoice_on"] + timedelta(days=quote["payment_days"])
    except (OverflowError, ValueError) as exc:
        raise ValidationError("supplier balance calendar outside supported years") from exc
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        fraction = number(quote["down_payment"], "down payment", fraction=True)
        gpu_count = nodes * quote["gpus_per_node"]
        compact = {key: payload[key] for key in ECONOMIC_FIELDS}
        model = next(row for row in frame["models"] if row["gpu"] == quote["gpu"])
        compact.update(gpu_count=str(gpu_count), delivery_start=start.isoformat() + "T00:00:00Z",
            delivery_end=end.isoformat() + "T00:00:00Z", supplier_rate=quote["price"],
            reference_rate=model["reference"], payment_dates={key: dates[key] for key in DATE_FIELDS
                if key not in {"deposit_on", "supplier_invoice_on"}})
        compact["payment_dates"]["supplier_payment_on"] = balance_due.isoformat()
        request = build_demo_pricing_request(compact)
        supply = Decimal(request["target"]["duration_hours"]) * gpu_count
        template = request["cash_template"]
        schedule = template["schedule"]
        events = schedule["events"]
        supplier = {row["kind"]: row for row in events if row["kind"] in {"supplier_invoice", "supplier_payment"}}
        invoice, payment = supplier["supplier_invoice"], supplier["supplier_payment"]
        invoice["on"] = dates["supplier_invoice_on"]
        payment["on"] = balance_due.isoformat()
        coefficients = template["purchase_coefficients"]
        if fraction:
            account = invoice["invoice_id"] + ":prepaid"
            deposit = {"event_id": invoice["event_id"] + ":deposit", "obligation_id": account + ":payment",
                "on": dates["deposit_on"], "kind": "supplier_prepayment", "amount": "0", "currency": "USD",
                "advance_account": account}
            apply = {"event_id": invoice["event_id"] + ":apply", "obligation_id": account + ":application",
                "on": dates["supplier_invoice_on"], "kind": "prepaid_apply", "amount": "0", "currency": "USD",
                "advance_account": account, "invoice_id": invoice["invoice_id"]}
            events.extend([deposit, apply])
            coefficients[deposit["event_id"]] = coefficients[apply["event_id"]] = text_number(supply * fraction)
        if fraction == 1:
            events.remove(payment)
            del coefficients[payment["event_id"]]
        else:
            coefficients[payment["event_id"]] = text_number(supply * (1 - fraction))
        priority = {"supplier_prepayment": 0, "supplier_invoice": 1, "prepaid_apply": 2,
            "supplier_payment": 3, "expense": 4, "other_outflow": 5, "buyer_invoice": 6,
            "revenue": 7, "buyer_receipt": 8, "receivable_writeoff": 9}
        events.sort(key=lambda row: (row["on"], priority[row["kind"]], row["event_id"]))
        template["deal_event_ids"] = [row["event_id"] for row in events]
        schedule["start_date"] = min(as_of.isoformat(), *(row["on"] for row in events))
        schedule["end_date"] = max(end.isoformat(), *(row["on"] for row in events))
        if (_calendar(schedule["end_date"], "horizon") - as_of).days > 3660:
            raise ValidationError("book deal calendar exceeds bounded ten-year horizon")
        request["market"]["as_of"] = as_of.isoformat() + "T00:00:00Z"
        request["market"]["policy"]["effective_at"] = request["market"]["as_of"]
        for observation in request["market"]["observations"]:
            observation["observed_at"] = observation["ingested_at"] = request["market"]["as_of"]
        request["target"].update(hardware_model=quote["gpu"], country_code=quote["country"],
            configuration={"interconnect": quote["interconnect"], "cooling": quote["cooling"]})
        request["commercial"]["exclusive_node_gpu_count"] = str(quote["gpus_per_node"])
        request["book_deal"] = {"contract_version": VERSION, "book_revision": revision,
            "quote_id": quote["id"], "provider_id": quote["provider_id"], "nodes": nodes,
            "bound_supplier_terms": {key: deepcopy(quote[key]) for key in book_deal_contract()["bound_supplier_fields"]},
            "simulation_policy": deepcopy(frame.get("policy")), "quality_grade": quote.get("grade"),
            "quality_inputs_are_calibrated": False,
            "caller_inputs": deepcopy(payload), "supplier_balance_due_on": balance_due.isoformat(),
            "classification": "synthetic", "source_evidence_eligible": False, "execution_enabled": False,
            "input_digest": digest(payload)}
        # The pricing engine accepts only its documented top-level fields.
        request["demo_scenario"]["book_binding"] = request.pop("book_deal")
        return request


def book_deal_sample_inputs(frame, revision):
    """Opt-in independent scenario; absence of a buyer never becomes live demand."""
    quote = next(row for row in frame["quotes"] if row["eligible"])
    sample = demo_contract()["sample"]["inputs"]
    start = _calendar(quote["available"], "available")
    end = _month_end(start, quote["months"])
    settle = end + timedelta(days=2)
    return {**{key: sample[key] for key in ECONOMIC_FIELDS}, "book_revision": revision,
        "quote_id": quote["id"], "nodes": quote["moq"], "supplier_invoice_basis": "single_full_contract_invoice",
        "payment_dates": {"deposit_on": frame["meta"]["as_of"], "supplier_invoice_on": start.isoformat(),
            "buyer_invoice_on": end.isoformat(), "buyer_receipt_on": settle.isoformat(),
            "operating_cost_on": start.isoformat(), "fees_on": settle.isoformat(), "writeoff_on": settle.isoformat()}}


def attach_book_deals(app, *, get_book, authenticated, json_body, evaluator, save):
    @app.get("/v1/book/deal/contract", dependencies=[Depends(authenticated)])
    async def contract():
        return book_deal_contract()

    @app.post("/v1/book/deal/evaluate", dependencies=[Depends(authenticated)])
    async def evaluate(request: Request):
        from .demo import demo_supplier_cash_schedule
        payload = await json_body(request)
        revision, encoded = await run_in_threadpool(get_book().encoded)
        if payload.get("book_revision") != revision:
            raise HTTPException(409, detail="book_revision_changed_reload_selected_quote")
        try:
            pricing_request = await run_in_threadpool(build_book_deal, payload, json.loads(encoded), revision)
            output = await run_in_threadpool(evaluator, pricing_request)
            output["scenario_supplier_cash_schedule"] = await run_in_threadpool(demo_supplier_cash_schedule, pricing_request)
            output["book_binding"] = pricing_request["demo_scenario"]["book_binding"]
            output["decision_hash"] = digest({key: value for key, value in output.items() if key != "decision_hash"})
        except (SnapshotStoreError, PolicyStoreError, sqlite3.Error):
            raise HTTPException(503, detail="pricing_evidence_store_unavailable") from None
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise HTTPException(422, detail="invalid_book_deal_input") from None
        return await run_in_threadpool(save, "pricing", pricing_request, output)
