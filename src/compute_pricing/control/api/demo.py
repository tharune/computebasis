"""Translate an explicit learning scenario into the existing offline kernels.

Nothing is populated until the caller supplies it. The example is invented, and
the hypothetical reference has no source permission or market admission. This
builder neither saves inventory nor submits a price or money movement.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
import re

from compute_pricing.control._numbers import (
    calculation_precision, digest, hours, number, text_number,
)
from compute_pricing.control.domain import ValidationError, utc_instant
from compute_pricing.control.treasury import evaluate_cash_payload


VERSION = "demo-scenario/1.0.0"
_DECIMALS = {
    "gpu_count", "billed_utilization", "supplier_rate", "buyer_rate", "reference_rate",
    "collection_share", "fee_on_collected", "fee_on_gross", "fixed_operating_cost",
    "opening_cash", "minimum_cash", "required_margin", "tick_size",
}
_DATES = {
    "supplier_payment_on", "buyer_invoice_on", "buyer_receipt_on", "operating_cost_on",
    "fees_on", "writeoff_on",
}
_FIELDS = _DECIMALS | {"delivery_start", "delivery_end", "payment_dates"}
_FRACTIONS = {
    "billed_utilization", "collection_share", "fee_on_collected", "fee_on_gross",
    "required_margin",
}
_POSITIVE = {"gpu_count", "billed_utilization", "buyer_rate", "reference_rate", "tick_size"}


def demo_contract() -> dict:
    """Empty intake and an opt-in invented sample; neither is source evidence."""
    labels = {
        "gpu_count": "GPU count", "delivery_start": "Delivery start (UTC)",
        "delivery_end": "Delivery end (UTC)", "billed_utilization": "Billed utilization",
        "supplier_rate": "Supplier price / GPU-hour", "buyer_rate": "Buyer price / GPU-hour",
        "reference_rate": "Hypothetical reference / GPU-hour", "collection_share": "Collection share",
        "fee_on_collected": "Fee on collections", "fee_on_gross": "Fee on gross billings",
        "fixed_operating_cost": "Fixed operating cost", "opening_cash": "Opening unrestricted cash",
        "minimum_cash": "Minimum cash floor", "required_margin": "Required margin on gross billings",
        "tick_size": "Price tick", "supplier_payment_on": "Supplier payment date",
        "buyer_invoice_on": "Buyer invoice date", "buyer_receipt_on": "Buyer receipt date",
        "operating_cost_on": "Operating cost payment date", "fees_on": "Fee payment date",
        "writeoff_on": "Uncollected receivable writeoff date",
    }
    primary = ["gpu_count", "delivery_start", "delivery_end", "supplier_rate", "buyer_rate",
               "billed_utilization", "collection_share", "opening_cash"]
    assumptions = ["reference_rate", "fee_on_collected", "fee_on_gross", "fixed_operating_cost",
                   "minimum_cash", "required_margin", "tick_size"]
    fields = [{"name": name, "label": labels[name],
               "type": "utc" if name.startswith("delivery_") else "decimal",
               "group": "primary" if name in primary else "assumptions",
               "required": True, "nullable": False, "default": None}
              for name in primary + assumptions]
    fields.extend({"name": f"payment_dates.{name}", "label": labels[name], "type": "date",
                   "group": "payment_dates", "required": True, "nullable": False, "default": None}
                  for name in sorted(_DATES))
    template = {name: None for name in sorted(_FIELDS - {"payment_dates"})}
    template["payment_dates"] = {name: None for name in sorted(_DATES)}
    sample = {
        "gpu_count": "3", "delivery_start": "2054-08-16T06:00:00Z",
        "delivery_end": "2054-08-17T18:00:00Z", "billed_utilization": "0.75",
        "supplier_rate": "4.8", "buyer_rate": "9.7", "reference_rate": "5.6",
        "collection_share": "0.94", "fee_on_collected": "0.012", "fee_on_gross": "0.004",
        "fixed_operating_cost": "37.5", "opening_cash": "500", "minimum_cash": "30",
        "required_margin": "0.12", "tick_size": "0.025",
        "payment_dates": {
            "supplier_payment_on": "2054-08-16", "buyer_invoice_on": "2054-08-17",
            "buyer_receipt_on": "2054-08-19", "operating_cost_on": "2054-08-16",
            "fees_on": "2054-08-19", "writeoff_on": "2054-08-19",
        },
    }
    return {
        "schema_version": VERSION, "fields": fields, "template_unknown": template,
        "sample": {"classification": "synthetic", "label": "Invented cash-timing scenario",
                   "inputs": sample},
        "currency": "USD", "unit": "gpu_hour", "margin_basis": "gross_billings",
        "classification": "synthetic", "source_evidence_eligible": False, "execution_enabled": False,
        "assumptions": [
            "single_exclusive_physical_allocation_with_one_supplier_and_one_buyer",
            "hypothetical_reference_is_display_only_and_never_a_market_cap",
            "recognize_full_service_billings_on_delivery_end_calendar_date",
            "explicit_collection_shortfall_is_written_off_without_reducing_gross_revenue",
            "date_only_cash_outflows_precede_receipts_on_the_same_day",
            "cash_search_ceiling_is_economic_cap_not_an_admitted_market_price",
        ],
        "limits": {"maximum_calendar_horizon_days": 3660,
                   "delivery_duration": "positive_exact_decimal_hours", "billed_utilization": "0 < value <= 1"},
    }


def _date(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValidationError(f"{name}: explicit ISO calendar date required")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{name}: valid calendar date required") from exc


def build_demo_pricing_request(payload: dict) -> dict:
    """Build a fully settled, hypothetical cash ledger from explicit exact inputs."""
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise ValidationError("demo scenario: all contract fields required; unknown fields rejected")
    dates = payload["payment_dates"]
    if not isinstance(dates, dict) or set(dates) != _DATES:
        raise ValidationError("payment_dates: all six explicit dates required; unknown fields rejected")
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        values = {name: number(payload[name], name, positive=name in _POSITIVE,
                               fraction=name in _FRACTIONS) for name in _DECIMALS}
        if values["gpu_count"] != values["gpu_count"].to_integral_value():
            raise ValidationError("gpu_count: whole physical GPU units required")
        if values["tick_size"] < Decimal("0.000000000001"):
            raise ValidationError("tick_size: finer than supported monetary grid")
        start, end = utc_instant(payload["delivery_start"]), utc_instant(payload["delivery_end"])
        delta = end - start
        micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
        if micros <= 0 or micros % 9:
            raise ValidationError("delivery interval: positive exact decimal hours required")
        span = hours(payload["delivery_start"], payload["delivery_end"])
        parsed_dates = {name: _date(value, f"payment_dates.{name}") for name, value in dates.items()}
        if parsed_dates["buyer_invoice_on"] > end.date():
            raise ValidationError("buyer invoice must exist by service recognition on delivery end")
        if parsed_dates["buyer_receipt_on"] < parsed_dates["buyer_invoice_on"]:
            raise ValidationError("buyer receipt cannot precede its invoice in this scenario model")
        if parsed_dates["writeoff_on"] < max(end.date(), parsed_dates["buyer_receipt_on"]):
            raise ValidationError("writeoff must follow service recognition and modeled collection")
        horizon_start = min(start.date(), *parsed_dates.values())
        horizon_end = max(end.date(), *parsed_dates.values())
        if (horizon_end - horizon_start).days > 3660:
            raise ValidationError("demo scenario: calendar horizon exceeds supported limit")
        supply = span * values["gpu_count"]
        billed = supply * values["billed_utilization"]
        gross = billed * values["buyer_rate"]
        received = gross * values["collection_share"]
        shortfall = gross - received
        fees = gross * (values["collection_share"] * values["fee_on_collected"]
                        + values["fee_on_gross"])
        identity = "synthetic-demo:" + digest(payload)[:16]
        supplier_invoice, buyer_invoice = identity + ":supply", identity + ":buyer"
        events, priorities, coefficients = [], {}, {}

        def event(name, on, kind, amount, priority, *, invoice=None, coefficient=None, basis=None):
            if not amount and coefficient is None:
                return
            event_id = identity + ":" + name
            row = {"event_id": event_id, "obligation_id": event_id + ":obligation", "on": on,
                   "kind": kind, "amount": text_number(amount), "currency": "USD"}
            if invoice:
                row["invoice_id"] = invoice
            if basis:
                row["basis_ref"] = basis
            events.append(row)
            priorities[event_id] = priority
            if coefficient is not None:
                coefficients[event_id] = text_number(coefficient)

        event("supplier-invoice", dates["supplier_payment_on"], "supplier_invoice", Decimal(0), 0,
              invoice=supplier_invoice, coefficient=supply)
        event("supplier-payment", dates["supplier_payment_on"], "supplier_payment", Decimal(0), 1,
              invoice=supplier_invoice, coefficient=supply)
        event("supplier-expense", end.date().isoformat(), "expense", Decimal(0), 2, coefficient=supply)
        event("operating-expense", dates["operating_cost_on"], "expense", values["fixed_operating_cost"], 2)
        event("operating-payment", dates["operating_cost_on"], "other_outflow", values["fixed_operating_cost"], 3)
        event("fee-expense", dates["fees_on"], "expense", fees, 2)
        event("fee-payment", dates["fees_on"], "other_outflow", fees, 3)
        event("buyer-invoice", dates["buyer_invoice_on"], "buyer_invoice", gross, 4, invoice=buyer_invoice)
        event("service-revenue", end.date().isoformat(), "revenue", gross, 5, invoice=buyer_invoice)
        event("buyer-receipt", dates["buyer_receipt_on"], "buyer_receipt", received, 6, invoice=buyer_invoice)
        event("uncollected-writeoff", dates["writeoff_on"], "receivable_writeoff", shortfall, 7,
              invoice=buyer_invoice, basis=identity + ":caller-collection-shortfall")
        events.sort(key=lambda row: (row["on"], priorities[row["event_id"]], row["event_id"]))
        as_of = horizon_start.isoformat() + "T00:00:00Z"
        source_id = "synthetic-demo:reference"
        request = {
            "pricing_provenance": {"mode": "declared_scenario", "policy_revision": None},
            "market": {"request_id": identity, "as_of": as_of, "observations": [{
                "id": identity + ":reference", "source_id": source_id, "source_version": VERSION,
                "kind": "listing_ask", "price_side": "ask", "status": "claimed",
                "offer_id": identity + ":offer", "lot_id": identity + ":lot",
                "provider_group_id": identity + ":invented-provider",
                "price": {"amount": text_number(values["reference_rate"]), "currency": "USD", "unit": "gpu_hour"},
                "hardware": {"model": "synthetic-demo-gpu", "accelerator_count": text_number(values["gpu_count"])},
                "region": {"country_code": "ZZ"}, "quantity": text_number(values["gpu_count"]),
                "quantity_unit": "gpu", "starts_at": payload["delivery_start"], "ends_at": payload["delivery_end"],
                "observed_at": as_of, "ingested_at": as_of, "expires_at": None,
                "rights": {"status": "denied", "observe": "FAIL", "retain": "FAIL", "benchmark": "FAIL",
                           "execution": "FAIL", "verified_by": None},
                "extensions": {"classification": "synthetic", "model_input_role": "hypothetical_reference",
                               "admitted_api": False, "source_evidence_eligible": False},
            }], "policy": {
                "policy_id": "synthetic-demo:policy", "version": "1.0.0", "model_version": "inverse-linear/1.0.0",
                "registry_version": "1.0.0", "effective_at": as_of,
                "parameters": {"benchmark": {"estimator": "weighted_median", "max_source_share": "1",
                    "max_provider_share": "1", "min_observations": 1, "min_sources": 1,
                    "min_provider_groups": 1, "source_rules": {source_id: {
                        "enabled": False, "quality": "1", "max_age_hours": "1", "half_life_hours": "1",
                    }}}},
            }},
            "target": {"scope": "physical_offer", "currency": "USD", "hardware_model": "synthetic-demo-gpu",
                "country_code": "ZZ", "gpu_count": text_number(values["gpu_count"]), "duration_hours": text_number(span),
                "starts_at": payload["delivery_start"], "ends_at": payload["delivery_end"], "configuration": {}},
            "commercial": {"currency": "USD", "exclusive_node_gpu_count": "1", "buyer_billed_gpu_hours": text_number(billed),
                "buyer_rate": text_number(values["buyer_rate"]), "supplier_ask": text_number(values["supplier_rate"]),
                "collection_share": text_number(values["collection_share"]), "fee_on_collected": text_number(values["fee_on_collected"]),
                "fee_on_gross": text_number(values["fee_on_gross"]), "required_margin": text_number(values["required_margin"]),
                "margin_basis": "gross_billings", "tick_size": text_number(values["tick_size"]), "market_discount": "0",
                "cost_owners": {"operations": "synthetic-demo:operations"}, "costs": [{
                    "id": identity + ":operating-cost", "channel": "operations", "owner_model": "synthetic-demo:operations",
                    "amount": text_number(values["fixed_operating_cost"]), "basis": "fixed_contract", "kind": "expected_cost",
                }]},
            "cash_template": {"minimum_cash": text_number(values["minimum_cash"]),
                "purchase_coefficients": coefficients, "deal_event_ids": [row["event_id"] for row in events],
                "schedule": {"legal_entity_id": identity + ":entity", "cash_account_id": identity + ":cash",
                    "currency": "USD", "opening_cash": text_number(values["opening_cash"]),
                    "start_date": horizon_start.isoformat(), "end_date": horizon_end.isoformat(), "events": events}},
            "demo_scenario": {"schema_version": VERSION, "classification": "synthetic", "inputs": deepcopy(payload),
                "market_reference_role": "display_only_not_admitted_benchmark", "source_evidence_eligible": False,
                "as_of_basis": "earliest_supplied_scenario_calendar_date", "execution_enabled": False},
        }
        return request


def demo_supplier_cash_schedule(request: dict) -> dict:
    """The declared supplier-rate path, distinct from the searched ceiling path.

    This receives the packet produced above, not a user-created ledger. It also
    remains available if unfavorable economics prevent a positive cap search.
    """
    with localcontext() as context:
        context.prec = calculation_precision(request)
        template = request["cash_template"]
        schedule = deepcopy(template["schedule"])
        rate = number(request["commercial"]["supplier_ask"], "supplier rate")
        floor = number(template["minimum_cash"], "minimum cash")
        coefficients = template["purchase_coefficients"]
        events = []
        for event in schedule["events"]:
            amount = Decimal(event["amount"]) + Decimal(coefficients.get(event["event_id"], "0")) * rate
            if amount > 0:
                events.append({**event, "amount": text_number(amount)})
        schedule["events"] = events
        cash = evaluate_cash_payload(schedule)
        if any(cash.unresolved_balances.values()):
            raise ValidationError("demo scenario: supplied-rate final settlement has unresolved balances")
        result = cash.to_dict()
        result.update({"classification": "synthetic", "supplier_rate": text_number(rate),
                       "basis": "caller_supplier_rate_not_scenario_ceiling",
                       "minimum_cash_floor": text_number(floor),
                       "cash_floor_feasible": cash.minimum_free_cash >= floor,
                       "required_extra_cash_for_floor": text_number(max(Decimal(0), floor - cash.minimum_free_cash)),
                       "source_evidence_eligible": False, "execution_enabled": False})
        return result
