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


KINDS = frozenset({"buyer_invoice", "supplier_invoice", "revenue", "expense",
    "buyer_receipt", "buyer_deposit", "deposit_apply", "deposit_refund",
    "supplier_prepayment", "prepaid_apply", "supplier_payment", "other_inflow",
    "other_outflow", "facility_draw", "facility_repay", "facility_release",
    "facility_interest"})
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

    def __post_init__(self):
        identifier(self.event_id, "event_id")
        identifier(self.obligation_id, "obligation_id")
        iso_date(self.on)
        currency_value(self.currency)
        if self.kind not in KINDS:
            raise ValueError("unknown cash event kind")
        if decimal_value(self.amount, "amount") <= 0:
            raise ValueError("event amount must be positive")
        if self.kind in {"buyer_invoice", "supplier_invoice", "buyer_receipt", "supplier_payment", "deposit_apply", "prepaid_apply", "revenue"}:
            identifier(self.invoice_id, "invoice_id")
        if self.kind in {"buyer_deposit", "deposit_apply", "deposit_refund", "supplier_prepayment", "prepaid_apply"}:
            identifier(self.advance_account, "advance_account")


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

    def to_dict(self) -> dict:
        def encode(value):
            if isinstance(value, Decimal):
                return format(value, "f")
            if isinstance(value, dict):
                return {key: encode(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [encode(item) for item in value]
            return value
        return encode(asdict(self))


def _balances(values: Mapping[str, str] | None, name: str) -> dict[str, Decimal]:
    result = {}
    for key, amount in (values or {}).items():
        identifier(key, name)
        result[key] = decimal_value(amount, name)
    return result


def evaluate_cash_schedule(events: Sequence[CashEvent], *, legal_entity_id: str,
        cash_account_id: str, currency: str, opening_cash: str, start_date: str,
        end_date: str, reserves: Sequence[Reserve] = (), facility: Facility | None = None,
        opening_deposits: Mapping[str, str] | None = None,
        opening_prepaids: Mapping[str, str] | None = None,
        opening_receivables: Mapping[str, str] | None = None,
        opening_earned_for_release: Mapping[str, str] | None = None,
        opening_payables: Mapping[str, str] | None = None) -> CashSchedule:
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
    for balances in (opening_deposits, opening_prepaids, opening_receivables, opening_earned_for_release, opening_payables):
        if balances is not None and not isinstance(balances, Mapping):
            raise ValueError("opening balances must be explicit identifier-to-Decimal-string mappings")
    event_ids, obligation_ids, by_day = set(), set(), {}
    for event in events:
        if not isinstance(event, CashEvent) or event.currency != currency:
            raise ValueError("event must use the ledger currency")
        if event.event_id in event_ids or event.obligation_id in obligation_ids:
            raise ValueError("duplicate event or obligation; cannot count a cash leg twice")
        event_ids.add(event.event_id)
        obligation_ids.add(event.obligation_id)
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
        for balances in (opening_deposits, opening_prepaids, opening_receivables, opening_earned_for_release, opening_payables):
            values.extend((balances or {}).values())
        if facility:
            values.extend((facility.committed_limit, facility.opening_outstanding, facility.opening_drawn_total, facility.opening_accrued_interest, facility.annual_rate))
        for value in values:
            decimal_value(value, "financial input")
        context.prec = calculation_precision(values, len(events) + (end - start).days + 1)
        cash = decimal_value(opening_cash, "opening_cash")
        deposits = _balances(opening_deposits, "deposit account")
        prepaids = _balances(opening_prepaids, "prepaid account")
        receivables = _balances(opening_receivables, "receivable")
        payables = _balances(opening_payables, "payable")
        issued_buyer_invoices = dict(receivables)
        earned_for_release = {key: _ZERO for key in receivables}
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
                elif kind == "supplier_invoice":
                    if event.invoice_id in payables:
                        raise ValueError("supplier invoice identifier already issued")
                    payables[event.invoice_id] = value
                elif kind == "revenue":
                    if event.invoice_id not in issued_buyer_invoices or value > issued_buyer_invoices[event.invoice_id]:
                        raise ValueError("revenue exceeds the supplied issued invoice amount")
                    issued_buyer_invoices[event.invoice_id] -= value
                    earned_for_release[event.invoice_id] += value
                    revenue += value
                elif kind == "expense":
                    expense += value
                elif kind == "buyer_receipt":
                    credit_invoice(receivables, event.invoice_id, value)
                    cash += value
                elif kind == "buyer_deposit":
                    deposits[event.advance_account] = deposits.get(event.advance_account, _ZERO) + value
                elif kind == "deposit_apply":
                    if deposits.get(event.advance_account, _ZERO) < value:
                        raise ValueError("deposit application exceeds restricted liability")
                    if earned_for_release.get(event.invoice_id, _ZERO) < value:
                        raise ValueError("deposit release exceeds evidenced earned invoice amount")
                    credit_invoice(receivables, event.invoice_id, value)
                    deposits[event.advance_account] -= value
                    earned_for_release[event.invoice_id] -= value
                    cash += value  # Internal release; no second external receipt.
                elif kind == "deposit_refund":
                    if deposits.get(event.advance_account, _ZERO) < value:
                        raise ValueError("refund exceeds restricted deposit liability")
                    deposits[event.advance_account] -= value  # Paid from the segregated account.
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
                outstanding, accrued, available(on), reserved, free, ordered_min, headroom))
            if facility and on < end:
                divisor = Decimal(365 if facility.day_count == "ACT/365F" else 360)
                accrued += outstanding * decimal_value(facility.annual_rate, "annual_rate") / divisor
            on += timedelta(days=1)
        unresolved = {name: {key: value for key, value in balances.items() if value != 0}
            for name, balances in (("deposits", deposits), ("prepaids", prepaids), ("receivables", receivables), ("payables", payables))}
        return CashSchedule(legal_entity_id, cash_account_id, currency, tuple(rows), min_free, min_date,
            max(_ZERO, -min_free), min_headroom, max(_ZERO, -min_headroom), maturity_breach, unresolved)
