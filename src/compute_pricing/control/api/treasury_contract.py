"""Discover registered settlement fields without inventing financial inputs."""
from dataclasses import fields, MISSING

from compute_pricing.control.treasury import invoice_due_date
from compute_pricing.control.treasury.cash import CashEvent, Facility, KINDS, NATIVE_KINDS, Reserve

CALENDAR_FIELDS = {"trigger_date", "net_days", "settlement_lag_days", "weekend_adjustment", "holidays"}


def evaluate_calendar(packet):
    if not isinstance(packet, dict) or set(packet) != CALENDAR_FIELDS:
        raise ValueError("explicit calendar contract required")
    if not isinstance(packet["holidays"], list) or len(packet["holidays"]) > 4096:
        raise ValueError("bounded declared holiday array required")
    if any(type(packet[key]) is not int or not 0 <= packet[key] <= 36600 for key in ("net_days", "settlement_lag_days")):
        raise ValueError("bounded whole calendar terms required")
    calculated = invoice_due_date(packet["trigger_date"], net_days=packet["net_days"],
        settlement_lag_days=packet["settlement_lag_days"], weekend_adjustment=packet["weekend_adjustment"],
        holidays=tuple(packet["holidays"]))
    return {"model_version": "cash-calendar/1.0.0", "due_date": calculated,
        "evidence_status": "caller_declared_calendar_convention", "bank_calendar_verified": False,
        "warnings": ["calendar_arithmetic_does_not_verify_cleared_cash",
            "preceding_can_cross_a_month_year_or_trigger", "bank_cutoffs_and_timezone_not_inferred"],
        "execution_enabled": False}


def cash_template():
    blank = dict.fromkeys(("legal_entity_id", "cash_account_id", "currency", "opening_cash", "start_date", "end_date", "facility"))
    return {**blank, "events": [], "reserves": [], "opening_advances": {}, "advance_terms": {}}


def cash_contract():
    def describe(cls):
        fs = fields(cls)
        return {"fields": [item.name for item in fs], "required_fields": [item.name for item in fs
            if item.default is MISSING and item.default_factory is MISSING]}
    invoice = {"buyer_invoice", "supplier_invoice", "buyer_receipt", "supplier_payment", "deposit_apply",
        "prepaid_apply", "revenue", "advance_apply", "receivable_writeoff", "buyer_credit_note"}
    accounts = {"buyer_deposit", "deposit_apply", "deposit_refund", "supplier_prepayment",
        "prepaid_apply", "buyer_advance", "advance_apply", "advance_refund", "deposit_forfeit"}
    effects = {"buyer_receipt": "unrestricted_inflow", "other_inflow": "unrestricted_inflow",
        "facility_draw": "unrestricted_inflow", "buyer_advance": "unrestricted_inflow",
        "supplier_payment": "unrestricted_outflow", "supplier_prepayment": "unrestricted_outflow",
        "other_outflow": "unrestricted_outflow", "facility_repay": "unrestricted_outflow",
        "facility_interest": "unrestricted_outflow", "advance_refund": "unrestricted_outflow",
        "deposit_apply": "restricted_asset_release", "deposit_forfeit": "restricted_asset_release"}
    rows = []
    event = describe(CashEvent)
    for name in sorted(KINDS):
        required = [*event["required_fields"]]
        required.extend(["invoice_id"] if name in invoice else [])
        required.extend(["advance_account"] if name in accounts else [])
        required.extend(["basis_ref"] if name in NATIVE_KINDS else [])
        required.extend(["revenue_reversal_amount"] if name == "buyer_credit_note" else [])
        rows.append({"kind": name, "required_fields": required,
            "cash_effect": effects.get(name, "no_unrestricted_cash_effect"), "native_accounting": name in NATIVE_KINDS,
            "requires_advance_terms": name in {"buyer_advance", "advance_apply", "advance_refund"}})
    return {"contract_version": "cash-input/2.0.0", "event": event, "facility": describe(Facility),
        "reserve": describe(Reserve), "event_kinds": rows, "template": cash_template(),
        "advance_terms_fields": ["buyer_entity_id", "basis_ref", "usable_for_operations", "refund_terms_ref"],
        "advance_terms_usable_for_operations_required_value": True,
        "calendar_conventions": ["none", "following", "preceding"],
        "calendar": {"endpoint": "/v1/cash/calendar", "required_fields": sorted(CALENDAR_FIELDS),
            "maximum_holidays": 4096, "maximum_term_or_lag_days": 36600},
        "money_encoding": "exact_plain_decimal_string", "missing_is_zero": False,
        "warnings": ["blank_template_is_not_evaluable", "opening_advances_do_not_add_opening_cash",
            "declared_basis_is_not_verified_contract_authority", "paid_invoice_credit_refunds_need_a_separate_model",
            "advances_and_forfeiture_are_not_service_revenue"], "execution_enabled": False}
