"""Explicit receipt timelines and senior cash waterfall; no financing actions."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, localcontext
from typing import Sequence
from compute_pricing.control.treasury._validation import calculation_precision, currency_value, decimal_value, identifier, iso_date
from .receivables import BorrowingFacility, Pledge, Receivable, validate_pledges


@dataclass(frozen=True)
class Collection:
    collection_id: str
    obligation_leg_id: str
    economic_id: str
    on: str
    legal_entity_id: str
    cash_account_id: str
    currency: str
    amount: str
    status: str
    evidence_id: str

    def __post_init__(self):
        for field in ("collection_id", "obligation_leg_id", "economic_id", "legal_entity_id", "cash_account_id", "evidence_id"):
            identifier(getattr(self, field), field)
        iso_date(self.on)
        currency_value(self.currency)
        if decimal_value(self.amount, "collection") <= 0 or self.status not in {"scheduled", "cleared"}:
            raise ValueError("collection requires positive amount and explicit scheduled/cleared status")


@dataclass(frozen=True)
class WaterfallPolicy:
    policy_version: str
    reserve_required: str
    priority: tuple[str, ...]

    def __post_init__(self):
        identifier(self.policy_version, "waterfall policy version")
        decimal_value(self.reserve_required, "reserve required")
        if self.priority not in {("reserve", "interest", "principal", "residual"), ("interest", "principal", "reserve", "residual")}:
            raise ValueError("explicit supported senior/reserve waterfall priority required")


@dataclass(frozen=True)
class WaterfallDay:
    on: str
    collected: Decimal
    interest_paid: Decimal
    principal_paid: Decimal
    reserve_held: Decimal
    residual_distributed: Decimal
    outstanding_principal: Decimal
    accrued_interest: Decimal
    reserve_shortfall: Decimal
    maturity_shortfall: Decimal


@dataclass(frozen=True)
class WaterfallReport:
    days: tuple[WaterfallDay, ...]
    uncollected_receivables: dict[str, Decimal]
    ending_principal: Decimal
    ending_interest: Decimal
    final_reserve_shortfall: Decimal
    maximum_maturity_shortfall: Decimal
    scheduled_cash_assumed: bool
    execution_eligible: bool = False


def evaluate_waterfall(receivables: Sequence[Receivable], pledges: Sequence[Pledge],
        facility: BorrowingFacility, policy: WaterfallPolicy, collections: Sequence[Collection], *,
        opening_cash: str, start_date: str, end_date: str, as_of: str, mode: str,
        pledge_registry_evidence_id: str) -> WaterfallReport:
    """Forecast includes scheduled cash only when explicitly requested.

    Cleared-only mode ignores scheduled records. A future record cannot claim
    cleared bank cash. A complete inclusive horizon must cover invoice due dates,
    every supplied collection and facility maturity. Missing collections remain
    uncollected balances, never synthetic receipts.
    """
    start, end, now = iso_date(start_date), iso_date(end_date), iso_date(as_of)
    identifier(pledge_registry_evidence_id, "pledge registry evidence")
    if end < start or (end - start).days > 36600 or end < iso_date(facility.maturity_date) or mode not in {"forecast", "cleared_only"}:
        raise ValueError("invalid waterfall horizon or mode")
    if start < iso_date(facility.available_from) and decimal_value(facility.outstanding_principal, "principal") > 0:
        raise ValueError("opening debt cannot precede facility availability")
    registry = validate_pledges(pledges)
    if any(not isinstance(item, Receivable) for item in receivables) or len({item.economic_id for item in receivables}) != len(receivables):
        raise ValueError("unique receivables required")
    outstanding = {}
    for item in receivables:
        if (item.legal_entity_id, item.currency) != (facility.legal_entity_id, facility.currency) or end < iso_date(item.due_date):
            raise ValueError("waterfall omits receivable maturity or legal scope")
        if item.economic_id not in registry or registry[item.economic_id].facility_id != facility.facility_id:
            raise ValueError("collection collateral must be uniquely pledged to this facility")
        if not item.assignability_verified or not item.legal_evidence_id or not item.eligibility_evidence_id or not item.ownership_evidence_id or not item.acceptance_confirmed or not item.acceptance_evidence_id or item.acceptance_date is None:
            raise ValueError("waterfall collateral legal/acceptance evidence incomplete")
        if iso_date(item.acceptance_date) > now or now >= iso_date(item.evidence_expiry_date):
            raise ValueError("waterfall collateral evidence is future-dated or expired")
        outstanding[item.economic_id] = decimal_value(item.outstanding_amount, "outstanding")
    ids, legs, by_day = set(), set(), {}
    scheduled = False
    for collection in collections:
        if not isinstance(collection, Collection) or collection.collection_id in ids or collection.obligation_leg_id in legs:
            raise ValueError("duplicate collection or obligation leg")
        ids.add(collection.collection_id)
        legs.add(collection.obligation_leg_id)
        on = iso_date(collection.on)
        if not start <= on <= end or collection.economic_id not in outstanding:
            raise ValueError("collection outside horizon or unknown invoice")
        if (collection.legal_entity_id, collection.cash_account_id, collection.currency) != (facility.legal_entity_id, facility.collection_account_id, facility.currency):
            raise ValueError("collection currency/entity/account cannot be implicitly converted or pooled")
        if collection.status == "cleared" and on > now:
            raise ValueError("future collection cannot claim cleared bank cash")
        if collection.status == "scheduled":
            if mode == "cleared_only":
                continue
            scheduled = True
        by_day.setdefault(on, []).append(collection)
    values = [opening_cash, facility.outstanding_principal, facility.accrued_interest, facility.annual_rate, policy.reserve_required, *[item.outstanding_amount for item in receivables], *[item.amount for item in collections]]
    for value in values:
        decimal_value(value, "waterfall input")
    with localcontext() as context:
        context.prec = calculation_precision(values, (end - start).days + len(collections))
        cash, reserve, principal, interest = decimal_value(opening_cash, "cash"), Decimal("0"), decimal_value(facility.outstanding_principal, "principal"), decimal_value(facility.accrued_interest, "interest")
        target, rate = decimal_value(policy.reserve_required, "reserve"), decimal_value(facility.annual_rate, "rate")
        rows, maximum_call, on = [], Decimal("0"), start
        while on <= end:
            received = Decimal("0")
            for collection in by_day.get(on, ()):
                amount = decimal_value(collection.amount, "receipt")
                if amount > outstanding[collection.economic_id]:
                    raise ValueError("collection exceeds unpaid economic receivable")
                outstanding[collection.economic_id] -= amount
                cash += amount
                received += amount
            interest_paid = principal_paid = residual = Decimal("0")
            for stage in policy.priority:
                if stage == "reserve":
                    funded = min(cash, max(Decimal("0"), target - reserve))
                    reserve += funded
                    cash -= funded
                elif stage == "interest":
                    interest_paid = min(cash, interest)
                    interest -= interest_paid
                    cash -= interest_paid
                elif stage == "principal":
                    principal_paid = min(cash, principal)
                    principal -= principal_paid
                    cash -= principal_paid
                else:
                    residual, cash = cash, Decimal("0")
            reserve_shortfall = max(Decimal("0"), target - reserve)
            call = principal + interest if on >= iso_date(facility.maturity_date) else Decimal("0")
            maximum_call = max(maximum_call, call)
            rows.append(WaterfallDay(on.isoformat(), received, interest_paid, principal_paid, reserve, residual, principal, interest, reserve_shortfall, call))
            if on < end:
                interest += principal * rate / Decimal(365 if facility.day_count == "ACT/365F" else 360)
            on += timedelta(days=1)
        return WaterfallReport(tuple(rows), {key: amount for key, amount in outstanding.items() if amount > 0}, principal, interest, max(Decimal("0"), target - reserve), maximum_call, scheduled)
