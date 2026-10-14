"""Dated, exact single-entity/account/currency cash and advance roll-forwards.

This is a pure offline accounting slice. Dates and cleared amounts are supplied
evidence; nothing here fetches, transfers, approves or executes money movements.
Same-day events retain the caller's explicit order. A daily schedule cannot
prove intraday settlement availability without actual timestamps.
"""

from dataclasses import dataclass, asdict
from datetime import timedelta
from decimal import Decimal, localcontext
from typing import Mapping, Sequence
from ._validation import calculation_precision, currency_value, decimal_value, identifier, iso_date


NATIVE_KINDS = frozenset({"buyer_advance", "advance_apply", "advance_refund",
    "receivable_writeoff", "deposit_forfeit", "buyer_credit_note"})
KINDS = frozenset({"buyer_invoice", "supplier_invoice", "revenue", "expense",
    "buyer_receipt", "buyer_deposit", "deposit_apply", "deposit_refund",
    "supplier_prepayment", "prepaid_apply", "supplier_payment", "other_inflow",
    "other_outflow", "facility_draw", "facility_repay", "facility_release",
    "facility_interest"}) | NATIVE_KINDS
_ZERO = Decimal("0")


@dataclass(frozen=True)
class CashEvent:
    event_id: str
    obligation_id: str
    on: str
    kind: str
    amount: str
    currency: str
    invoice_id: str | None = None
    advance_account: str | None = None
    basis_ref: str | None = None
    revenue_reversal_amount: str | None = None

    def __post_init__(self):
        identifier(self.event_id, "event_id")
        identifier(self.obligation_id, "obligation_id")
        iso_date(self.on)
        currency_value(self.currency)
        if self.kind not in KINDS:
            raise ValueError("unknown cash event kind")
        if decimal_value(self.amount, "amount") <= 0:
            raise ValueError("event amount must be positive")
        if self.kind in {"buyer_invoice", "supplier_invoice", "buyer_receipt", "supplier_payment", "deposit_apply", "prepaid_apply", "revenue", "advance_apply", "receivable_writeoff", "buyer_credit_note"}:
            identifier(self.invoice_id, "invoice_id")
        if self.kind in {"buyer_deposit", "deposit_apply", "deposit_refund", "supplier_prepayment", "prepaid_apply", "buyer_advance", "advance_apply", "advance_refund", "deposit_forfeit"}:
            identifier(self.advance_account, "advance_account")
        if self.kind in NATIVE_KINDS:
            identifier(self.basis_ref, "basis_ref")
        elif self.basis_ref is not None:
            raise ValueError("basis_ref is registered only for native accounting events")
        if self.kind == "buyer_credit_note":
            if decimal_value(self.revenue_reversal_amount, "revenue_reversal_amount") > decimal_value(self.amount, "amount"):
                raise ValueError("credit note revenue reversal exceeds credit amount")
        elif self.revenue_reversal_amount is not None:
            raise ValueError("revenue_reversal_amount is registered only for buyer credit notes")


@dataclass(frozen=True)
class Facility:
    facility_id: str
    currency: str
    committed_limit: str
    opening_outstanding: str
    opening_drawn_total: str
    opening_accrued_interest: str
    annual_rate: str
    available_from: str
    maturity_date: str
    day_count: str
    revolving: bool

    def __post_init__(self):
        identifier(self.facility_id, "facility_id")
        currency_value(self.currency)
        limit = decimal_value(self.committed_limit, "committed_limit")
        outstanding = decimal_value(self.opening_outstanding, "opening_outstanding")
        drawn_total = decimal_value(self.opening_drawn_total, "opening_drawn_total")
        decimal_value(self.opening_accrued_interest, "opening_accrued_interest")
        decimal_value(self.annual_rate, "annual_rate")
        if outstanding > limit or drawn_total < outstanding or (not self.revolving and drawn_total > limit):
            raise ValueError("invalid facility outstanding or annual rate")
        if iso_date(self.maturity_date) <= iso_date(self.available_from):
            raise ValueError("facility maturity must follow availability")
        if self.day_count not in {"ACT/365F", "ACT/360"}:
            raise ValueError("unsupported facility day-count convention")
        if not isinstance(self.revolving, bool):
            raise ValueError("revolving must be explicit boolean")


@dataclass(frozen=True)
class Reserve:
    reserve_id: str
    coverage_id: str
    amount: str
    start_date: str
    end_date: str

    def __post_init__(self):
        identifier(self.reserve_id, "reserve_id")
        identifier(self.coverage_id, "coverage_id")
        decimal_value(self.amount, "reserve amount")
        if iso_date(self.end_date) <= iso_date(self.start_date):
            raise ValueError("reserve interval must be nonempty and half-open")


@dataclass(frozen=True)
class DailyCash:
    on: str
    cash: Decimal
    restricted_deposits: Decimal
    prepaid_assets: Decimal
    buyer_receivables: Decimal
    supplier_payables: Decimal
    earned_revenue: Decimal
    recognized_expense: Decimal
    facility_outstanding: Decimal
    accrued_interest: Decimal
    drawable_undrawn: Decimal
    policy_reserves: Decimal
    free_cash: Decimal
    minimum_ordered_free_cash: Decimal
    liquidity_headroom: Decimal
    unearned_advance_liabilities: Decimal = _ZERO
    noncash_receivable_losses: Decimal = _ZERO
    forfeiture_income: Decimal = _ZERO
    credit_note_amount: Decimal = _ZERO
    revenue_reversals: Decimal = _ZERO


@dataclass(frozen=True)
class CashSchedule:
    legal_entity_id: str
    cash_account_id: str
    currency: str
    days: tuple[DailyCash, ...]
    minimum_free_cash: Decimal
    minimum_free_cash_date: str
    required_extra_cash: Decimal
    minimum_headroom: Decimal
    required_extra_committed_funding: Decimal
    maturity_breach: bool
    unresolved_balances: Mapping[str, Mapping[str, Decimal]]
    accounting_extension: Mapping[str, object] | None = None

    def to_dict(self) -> dict:
        def encode(value):
            if isinstance(value, Decimal):
                return format(value, "f")
            if isinstance(value, dict):
                return {key: encode(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [encode(item) for item in value]
            return value
        result = asdict(self)
        if self.accounting_extension is None:
            # Existing native-v1 examples and callers retain their exact envelope.
            result.pop("accounting_extension")
            for day in result["days"]:
                for key in ("unearned_advance_liabilities", "noncash_receivable_losses",
                            "forfeiture_income", "credit_note_amount", "revenue_reversals"):
                    day.pop(key)
        return encode(result)


def _balances(values: Mapping[str, str] | None, name: str) -> dict[str, Decimal]:
    result = {}
    for key, amount in (values or {}).items():
        identifier(key, name)
        result[key] = decimal_value(amount, name)
    return result


def _advance_terms(values: Mapping[str, Mapping[str, object]] | None) -> dict[str, dict]:
    """Caller assertions identify a usable advance; this is not legal verification."""
    if values is not None and not isinstance(values, Mapping):
        raise ValueError("advance_terms must be an explicit account-to-terms mapping")
    result = {}
    required = {"buyer_entity_id", "basis_ref", "usable_for_operations", "refund_terms_ref"}
    for account, terms in (values or {}).items():
        identifier(account, "advance account")
        if not isinstance(terms, Mapping) or set(terms) != required:
            raise ValueError("advance terms require explicit buyer, basis, usable flag and refund terms")
        if terms["usable_for_operations"] is not True:
            raise ValueError("usable advance requires usable_for_operations=true caller assertion")
        for key in required - {"usable_for_operations"}:
            identifier(terms[key], key)
        result[account] = dict(terms)
    return result


def evaluate_cash_schedule(events: Sequence[CashEvent], *, legal_entity_id: str,
        cash_account_id: str, currency: str, opening_cash: str, start_date: str,
        end_date: str, reserves: Sequence[Reserve] = (), facility: Facility | None = None,
        opening_deposits: Mapping[str, str] | None = None,
        opening_prepaids: Mapping[str, str] | None = None,
        opening_receivables: Mapping[str, str] | None = None,
        opening_earned_for_release: Mapping[str, str] | None = None,
        opening_payables: Mapping[str, str] | None = None,
        opening_advances: Mapping[str, str] | None = None,
        advance_terms: Mapping[str, Mapping[str, object]] | None = None) -> CashSchedule:
    """Evaluate every day through the explicit final settlement horizon.

    Opening cash is UNRESTRICTED bank cash. Opening restricted deposits are
    separate assets and matching liabilities. Undrawn funding is separately
    reported, never added to bank cash until an explicit eligible draw event.
    All deals sharing this bank/facility must be evaluated together.
    """
    identifier(legal_entity_id, "legal_entity_id")
    identifier(cash_account_id, "cash_account_id")
    currency_value(currency)
    start, end = iso_date(start_date), iso_date(end_date)
    if end < start or (end - start).days > 36600:
        raise ValueError("invalid or excessively long cash horizon")
    if facility and facility.currency != currency:
        raise ValueError("facility currency mismatch; explicit FX settlement required")
    if facility and iso_date(facility.maturity_date) > end:
        raise ValueError("cash horizon must cover facility maturity")
    if facility and start < iso_date(facility.available_from) and decimal_value(facility.opening_drawn_total, "opening_drawn_total") > 0:
        raise ValueError("historical facility draws cannot precede facility availability")
    for balances in (opening_deposits, opening_prepaids, opening_receivables, opening_earned_for_release, opening_payables, opening_advances):
        if balances is not None and not isinstance(balances, Mapping):
            raise ValueError("opening balances must be explicit identifier-to-Decimal-string mappings")
    terms = _advance_terms(advance_terms)
    native = opening_advances is not None or advance_terms is not None or any(
        isinstance(event, CashEvent) and event.kind in NATIVE_KINDS for event in events)
    for account in opening_advances or {}:
        if account not in terms:
            raise ValueError("opening advance requires matching declared usable/refund terms")
    event_ids, obligation_ids, by_day = set(), set(), {}
    for event in events:
        if not isinstance(event, CashEvent) or event.currency != currency:
            raise ValueError("event must use the ledger currency")
        if event.event_id in event_ids or event.obligation_id in obligation_ids:
            raise ValueError("duplicate event or obligation; cannot count a cash leg twice")
        event_ids.add(event.event_id)
        obligation_ids.add(event.obligation_id)
        if event.kind in {"buyer_advance", "advance_apply", "advance_refund"}:
            if event.advance_account not in terms or event.basis_ref != terms[event.advance_account]["basis_ref"]:
                raise ValueError("usable advance event requires matching declared terms basis_ref")
        on = iso_date(event.on)
        if not start <= on <= end:
            raise ValueError("cash horizon omits an event")
        by_day.setdefault(on, []).append(event)
    reserve_ids = set()
    for index, reserve in enumerate(reserves):
        if not isinstance(reserve, Reserve) or reserve.reserve_id in reserve_ids:
            raise ValueError("invalid or duplicate reserve")
        reserve_ids.add(reserve.reserve_id)
        for prior in reserves[:index]:
            if reserve.coverage_id == prior.coverage_id and max(reserve.start_date, prior.start_date) < min(reserve.end_date, prior.end_date):
                raise ValueError("overlapping reserves cover the same obligation")
    with localcontext() as context:
        values = [opening_cash, *[event.amount for event in events], *[reserve.amount for reserve in reserves]]
        for balances in (opening_deposits, opening_prepaids, opening_receivables, opening_earned_for_release, opening_payables, opening_advances):
            values.extend((balances or {}).values())
        values.extend(event.revenue_reversal_amount for event in events if event.revenue_reversal_amount is not None)
        if facility:
            values.extend((facility.committed_limit, facility.opening_outstanding, facility.opening_drawn_total, facility.opening_accrued_interest, facility.annual_rate))
        for value in values:
            decimal_value(value, "financial input")
        context.prec = calculation_precision(values, len(events) + (end - start).days + 1)
        cash = decimal_value(opening_cash, "opening_cash")
        deposits = _balances(opening_deposits, "deposit account")
        advances = _balances(opening_advances, "unearned advance account")
        prepaids = _balances(opening_prepaids, "prepaid account")
        receivables = _balances(opening_receivables, "receivable")
        payables = _balances(opening_payables, "payable")
        issued_buyer_invoices = dict(receivables)
        earned_for_release = {key: _ZERO for key in receivables}
        settled_unrecognized = {key: _ZERO for key in receivables}
        for key, value in _balances(opening_earned_for_release, "earned receivable").items():
            if key not in receivables or value > receivables[key]:
                raise ValueError("opening earned release exceeds outstanding receivable")
            earned_for_release[key] = value
            issued_buyer_invoices[key] -= value
        outstanding = decimal_value(facility.opening_outstanding, "outstanding") if facility else _ZERO
        accrued = decimal_value(facility.opening_accrued_interest, "interest") if facility else _ZERO
        commitment = decimal_value(facility.committed_limit, "commitment") if facility else _ZERO
        consumed = decimal_value(facility.opening_drawn_total, "opening_drawn_total") if facility else _ZERO
        revenue, expense, rows = _ZERO, _ZERO, []
        noncash_losses, forfeitures, credit_notes, reversals = _ZERO, _ZERO, _ZERO, _ZERO
        min_free, min_headroom, min_date = None, None, start.isoformat()
        maturity_breach = False

        def available(on):
            if not facility or not iso_date(facility.available_from) <= on < iso_date(facility.maturity_date):
                return _ZERO
            return commitment - (outstanding if facility.revolving else consumed)

        def credit_invoice(balances, invoice, amount):
            if invoice not in balances or balances[invoice] < amount:
                raise ValueError("application/payment exceeds issued unsettled invoice")
            balances[invoice] -= amount

        def consume_earned(invoice, amount):
            if invoice not in earned_for_release or earned_for_release[invoice] < amount:
                raise ValueError("accounting reduction exceeds recognized unpaid invoice earnings")
            earned_for_release[invoice] -= amount

        def check_restricted_overlap(active):
            if any(r.coverage_id == f"deposit:{key}" and amount > 0 for r in active for key, amount in deposits.items()):
                raise ValueError("restricted deposit already covers this reserve")

        on = start
        while on <= end:
            active = [r for r in reserves if r.start_date <= on.isoformat() < r.end_date]
            reserved = sum((decimal_value(r.amount, "reserve") for r in active), _ZERO)
            check_restricted_overlap(active)
            ordered_min = cash - reserved
            daily_headroom_min = ordered_min + available(on)
            for event in by_day.get(on, ()):
                value = decimal_value(event.amount, "amount")
                kind = event.kind
                if kind == "buyer_invoice":
                    if event.invoice_id in receivables:
                        raise ValueError("buyer invoice identifier already issued")
                    receivables[event.invoice_id] = value
                    issued_buyer_invoices[event.invoice_id] = value
                    earned_for_release[event.invoice_id] = _ZERO
                    settled_unrecognized[event.invoice_id] = _ZERO
                elif kind == "supplier_invoice":
                    if event.invoice_id in payables:
                        raise ValueError("supplier invoice identifier already issued")
                    payables[event.invoice_id] = value
                elif kind == "revenue":
                    if event.invoice_id not in issued_buyer_invoices or value > issued_buyer_invoices[event.invoice_id]:
                        raise ValueError("revenue exceeds the supplied issued invoice amount")
                    issued_buyer_invoices[event.invoice_id] -= value
                    paid_part = min(value, settled_unrecognized[event.invoice_id])
                    settled_unrecognized[event.invoice_id] -= paid_part
                    earned_for_release[event.invoice_id] += value - paid_part
                    revenue += value
                elif kind == "expense":
                    expense += value
                elif kind == "buyer_receipt":
                    credit_invoice(receivables, event.invoice_id, value)
                    earned_part = min(value, earned_for_release[event.invoice_id])
                    earned_for_release[event.invoice_id] -= earned_part
                    settled_unrecognized[event.invoice_id] += value - earned_part
                    cash += value
                elif kind == "buyer_deposit":
                    deposits[event.advance_account] = deposits.get(event.advance_account, _ZERO) + value
                elif kind == "deposit_apply":
                    if deposits.get(event.advance_account, _ZERO) < value:
                        raise ValueError("deposit application exceeds restricted liability")
                    if earned_for_release.get(event.invoice_id, _ZERO) < value:
                        raise ValueError("deposit release exceeds evidenced earned unpaid invoice amount")
                    credit_invoice(receivables, event.invoice_id, value)
                    deposits[event.advance_account] -= value
                    earned_for_release[event.invoice_id] -= value
                    cash += value  # Internal release; no second external receipt.
                elif kind == "deposit_refund":
                    if deposits.get(event.advance_account, _ZERO) < value:
                        raise ValueError("refund exceeds restricted deposit liability")
                    deposits[event.advance_account] -= value  # Paid from the segregated account.
                elif kind == "buyer_advance":
                    advances[event.advance_account] = advances.get(event.advance_account, _ZERO) + value
                    cash += value
                elif kind == "advance_apply":
                    if advances.get(event.advance_account, _ZERO) < value:
                        raise ValueError("advance application exceeds unearned liability")
                    consume_earned(event.invoice_id, value)
                    credit_invoice(receivables, event.invoice_id, value)
                    advances[event.advance_account] -= value
                elif kind == "advance_refund":
                    if advances.get(event.advance_account, _ZERO) < value:
                        raise ValueError("advance refund exceeds unearned liability")
                    advances[event.advance_account] -= value
                    cash -= value
                elif kind == "receivable_writeoff":
                    consume_earned(event.invoice_id, value)
                    credit_invoice(receivables, event.invoice_id, value)
                    expense += value
                    noncash_losses += value
                elif kind == "deposit_forfeit":
                    if deposits.get(event.advance_account, _ZERO) < value:
                        raise ValueError("forfeiture exceeds restricted deposit liability")
                    deposits[event.advance_account] -= value
                    cash += value  # Release already held restricted cash; no second receipt.
                    forfeitures += value
                elif kind == "buyer_credit_note":
                    reversal = decimal_value(event.revenue_reversal_amount, "revenue_reversal_amount")
                    unearned_part = value - reversal
                    consume_earned(event.invoice_id, reversal)
                    if (event.invoice_id not in issued_buyer_invoices or
                            unearned_part > issued_buyer_invoices[event.invoice_id] - settled_unrecognized[event.invoice_id]):
                        raise ValueError("credit note exceeds unrecognized unpaid invoice amount")
                    credit_invoice(receivables, event.invoice_id, value)
                    issued_buyer_invoices[event.invoice_id] -= unearned_part
                    revenue -= reversal
                    reversals += reversal
                    credit_notes += value
                elif kind == "supplier_prepayment":
                    prepaids[event.advance_account] = prepaids.get(event.advance_account, _ZERO) + value
                    cash -= value
                elif kind == "prepaid_apply":
                    if prepaids.get(event.advance_account, _ZERO) < value:
                        raise ValueError("supplier application exceeds prepaid asset")
                    credit_invoice(payables, event.invoice_id, value)
                    prepaids[event.advance_account] -= value
                elif kind == "supplier_payment":
                    credit_invoice(payables, event.invoice_id, value)
                    cash -= value
                elif kind == "other_inflow":
                    cash += value
                elif kind == "other_outflow":
                    cash -= value
                else:
                    if facility is None:
                        raise ValueError("financing event requires an explicit committed facility")
                    if kind == "facility_draw":
                        if value > available(on):
                            raise ValueError("draw exceeds eligible undrawn committed funding")
                        outstanding += value
                        consumed += value
                        cash += value
                    elif kind == "facility_repay":
                        if value > outstanding:
                            raise ValueError("repayment exceeds facility outstanding")
                        outstanding -= value
                        cash -= value
                    elif kind == "facility_release":
                        used = outstanding if facility.revolving else consumed
                        if value > commitment - used:
                            raise ValueError("commitment release exceeds undrawn amount")
                        commitment -= value
                    elif kind == "facility_interest":
                        if value > accrued:
                            raise ValueError("interest payment exceeds accrued interest")
                        accrued -= value
                        cash -= value
                check_restricted_overlap(active)
                ordered_min = min(ordered_min, cash - reserved)
                daily_headroom_min = min(daily_headroom_min, cash - reserved + available(on))
            free = cash - reserved
            headroom = free + available(on)
            if min_free is None or ordered_min < min_free:
                min_free, min_date = ordered_min, on.isoformat()
            min_headroom = daily_headroom_min if min_headroom is None else min(min_headroom, daily_headroom_min)
            if facility and on >= iso_date(facility.maturity_date) and (outstanding > 0 or accrued > 0):
                maturity_breach = True
            rows.append(DailyCash(on.isoformat(), cash, sum(deposits.values(), _ZERO), sum(prepaids.values(), _ZERO),
                sum(receivables.values(), _ZERO), sum(payables.values(), _ZERO), revenue, expense,
                outstanding, accrued, available(on), reserved, free, ordered_min, headroom,
                sum(advances.values(), _ZERO), noncash_losses, forfeitures, credit_notes, reversals))
            if facility and on < end:
                divisor = Decimal(365 if facility.day_count == "ACT/365F" else 360)
                accrued += outstanding * decimal_value(facility.annual_rate, "annual_rate") / divisor
            if on == end:
                break
            on += timedelta(days=1)
        unresolved = {name: {key: value for key, value in balances.items() if value != 0}
            for name, balances in (("deposits", deposits), ("prepaids", prepaids), ("receivables", receivables), ("payables", payables))}
        extension = None
        if native:
            unresolved["advances"] = {key: value for key, value in advances.items() if value != 0}
            extension = {"model": "dated-cash/2.0.0", "evidence_status": "caller_declared_accounting_basis",
                "legal_terms_verified": False, "actual_settlement_verified": False,
                "native_event_kinds": sorted({event.kind for event in events} & NATIVE_KINDS),
                "advance_terms": terms,
                "warnings": ["basis_references_and_usable_refund_terms_are_caller_assertions",
                    "buyer_receipts_settle_earned_before_unrecognized_billing_by_declared_convention",
                    "earned_revenue_is_net_recognition_within_horizon_including_opening_balance_reversals",
                    "forfeiture_income_is_separate_from_service_revenue",
                    "unresolved_unearned_advances_remain_liabilities_not_profit"]}
        return CashSchedule(legal_entity_id, cash_account_id, currency, tuple(rows), min_free, min_date,
            max(_ZERO, -min_free), min_headroom, max(_ZERO, -min_headroom), maturity_breach, unresolved, extension)
