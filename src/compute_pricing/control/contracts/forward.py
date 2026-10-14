"""Evidence-driven forward readiness over separate signing and service dates."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from compute_pricing.control.capacity import CapacityLot, Maintenance, Reservation, validate_capacity
from compute_pricing.control.treasury import CashSchedule
from compute_pricing.control.treasury._validation import calculation_precision, currency_value, decimal_value, identifier, iso_date


@dataclass(frozen=True)
class ForwardTerms:
    contract_id: str
    legal_entity_id: str
    cash_account_id: str
    currency: str
    signature_date: str
    service_start_date: str
    service_end_date: str
    deposit_required: str
    capacity_lot_id: str
    capacity_unit_ids: tuple[str, ...]

    def __post_init__(self):
        for field in ("contract_id", "legal_entity_id", "cash_account_id", "capacity_lot_id"):
            identifier(getattr(self, field), field)
        currency_value(self.currency)
        decimal_value(self.deposit_required, "deposit_required")
        if not iso_date(self.signature_date) <= iso_date(self.service_start_date) < iso_date(self.service_end_date):
            raise ValueError("signing, future delivery and service end must be separately ordered")
        if not isinstance(self.capacity_unit_ids, tuple) or not self.capacity_unit_ids:
            raise ValueError("explicit immutable physical capacity units required")
        for unit in self.capacity_unit_ids:
            identifier(unit, "capacity unit")
        if len(set(self.capacity_unit_ids)) != len(self.capacity_unit_ids):
            raise ValueError("duplicate physical capacity unit")


@dataclass(frozen=True)
class BankReceipt:
    receipt_id: str
    bank_evidence_id: str
    settled_date: str
    legal_entity_id: str
    cash_account_id: str
    currency: str
    amount: str
    net_unreversed_amount: str
    cleared: bool

    def __post_init__(self):
        for field in ("receipt_id", "bank_evidence_id", "legal_entity_id", "cash_account_id"):
            identifier(getattr(self, field), field)
        iso_date(self.settled_date)
        currency_value(self.currency)
        if decimal_value(self.net_unreversed_amount, "net receipt") > decimal_value(self.amount, "receipt amount"):
            raise ValueError("net receipt cannot exceed cleared original amount")
        if not isinstance(self.cleared, bool):
            raise ValueError("cleared status must be explicit boolean")


@dataclass(frozen=True)
class ForwardEvidence:
    signature_evidence_id: str | None = None
    enforceability_evidence_id: str | None = None
    receipts: tuple[BankReceipt, ...] = ()
    funding_evidence_id: str | None = None
    cash_schedule: CashSchedule | None = None
    capacity_evidence_id: str | None = None
    capacity_lots: tuple[CapacityLot, ...] = ()
    reservations: tuple[Reservation, ...] = ()
    maintenance: tuple[Maintenance, ...] = ()
    delivery_readiness_evidence_id: str | None = None
    delivery_acceptance_evidence_id: str | None = None
    delivery_acceptance_date: str | None = None
    completion_reconciliation_evidence_id: str | None = None
    default_evidence_id: str | None = None

    def __post_init__(self):
        for field in ("signature_evidence_id", "enforceability_evidence_id", "funding_evidence_id", "capacity_evidence_id", "delivery_readiness_evidence_id", "delivery_acceptance_evidence_id", "completion_reconciliation_evidence_id", "default_evidence_id"):
            if getattr(self, field) is not None:
                identifier(getattr(self, field), field)
        for field, cls in (("receipts", BankReceipt), ("capacity_lots", CapacityLot), ("reservations", Reservation), ("maintenance", Maintenance)):
            values = getattr(self, field)
            if not isinstance(values, tuple) or any(not isinstance(value, cls) for value in values):
                raise ValueError(f"{field} must be an immutable tuple of validated records")
        if self.cash_schedule is not None and not isinstance(self.cash_schedule, CashSchedule):
            raise ValueError("cash_schedule must be a validated dated schedule")
        if (self.delivery_acceptance_evidence_id is None) != (self.delivery_acceptance_date is None):
            raise ValueError("delivery acceptance requires both evidence and actual date")
        if self.delivery_acceptance_date is not None:
            iso_date(self.delivery_acceptance_date)


@dataclass(frozen=True)
class ForwardReadiness:
    state: str
    lead_days: int
    service_days: int
    cleared_net_deposit: Decimal
    blockers: tuple[str, ...]
    execution_eligible: bool = False


def assess_forward_readiness(terms: ForwardTerms, evidence: ForwardEvidence, *, as_of: str) -> ForwardReadiness:
    """Assess supplied evidence claims, without inferring legal/bank verification.

    An evidence ID is a required pointer, not proof of authenticity. Production
    evidence ingestion, signatures and independent checks remain separate gates.
    This paper slice never grants execution eligibility.
    """
    now = iso_date(as_of)
    signature, start, end = iso_date(terms.signature_date), iso_date(terms.service_start_date), iso_date(terms.service_end_date)
    def result(state, blocker=(), deposit=Decimal("0")):
        return ForwardReadiness(state, (start - signature).days, (end - start).days, deposit, tuple(blocker))
    if evidence.default_evidence_id:
        return result("defaulted", ("explicit_default_evidence",))
    if not evidence.signature_evidence_id:
        return result("draft", ("signature_evidence_missing",))
    if now < signature:
        raise ValueError("signature evidence cannot establish a future signed date")
    seen, cleared_amounts = set(), []
    for receipt in evidence.receipts:
        if receipt.receipt_id in seen:
            raise ValueError("duplicate bank receipt cannot fund deposit twice")
        seen.add(receipt.receipt_id)
        if (receipt.legal_entity_id, receipt.cash_account_id, receipt.currency) != (terms.legal_entity_id, terms.cash_account_id, terms.currency):
            raise ValueError("bank receipt belongs to a different entity/account/currency")
        if iso_date(receipt.settled_date) > now:
            raise ValueError("future bank receipt is not cleared cash as of today")
        if receipt.cleared:
            cleared_amounts.append(receipt.net_unreversed_amount)
    with localcontext() as context:
        context.prec = calculation_precision(cleared_amounts, len(cleared_amounts))
        deposit = sum((decimal_value(value, "net receipt") for value in cleared_amounts), Decimal("0"))
    # A final legally required refund may exhaust the deposit after performance.
    # Separate final reconciliation, rather than an expired deposit milestone,
    # governs completion after every other evidence/capacity/cash gate below.
    final_reconciliation = now >= end and evidence.completion_reconciliation_evidence_id is not None
    if deposit < decimal_value(terms.deposit_required, "required deposit") and not final_reconciliation:
        return result("signature", ("cleared_deposit_shortfall",), deposit)
    cash = evidence.cash_schedule
    if not evidence.funding_evidence_id or cash is None:
        return result("deposit_verified", ("full_tail_funding_evidence_missing",), deposit)
    if (cash.legal_entity_id, cash.cash_account_id, cash.currency) != (terms.legal_entity_id, terms.cash_account_id, terms.currency):
        raise ValueError("funding cash belongs to a different legal scope")
    if iso_date(cash.days[0].on) > now or iso_date(cash.days[-1].on) < end:
        return result("deposit_verified", ("funding_schedule_omits_signing_or_service_tail",), deposit)
    if cash.required_extra_cash > 0 or cash.maturity_breach or any(cash.unresolved_balances.values()):
        return result("deposit_verified", ("funding_gap_or_unreconciled_tail",), deposit)
    if not evidence.capacity_evidence_id:
        return result("funding_ready", ("authoritative_capacity_evidence_missing",), deposit)
    validate_capacity(evidence.capacity_lots, evidence.reservations, evidence.maintenance)
    service_start, service_end = terms.service_start_date + "T00:00:00Z", terms.service_end_date + "T00:00:00Z"
    for unit in terms.capacity_unit_ids:
        cursor = service_start
        intervals = sorted((reservation.start_at, reservation.end_at) for reservation in evidence.reservations
            if reservation.allocation_id == terms.contract_id and reservation.lot_id == terms.capacity_lot_id and unit in reservation.unit_ids)
        for left, right in intervals:
            if left > cursor:
                break
            if right > cursor:
                cursor = right
        if cursor < service_end:
            return result("funding_ready", ("service_capacity_gap",), deposit)
    if not evidence.enforceability_evidence_id or not evidence.delivery_readiness_evidence_id:
        return result("capacity_ready", ("enforceability_or_delivery_readiness_evidence_missing",), deposit)
    if evidence.delivery_acceptance_date is None:
        return result("delivery_ready", ("actual_delivery_acceptance_missing",), deposit)
    acceptance = iso_date(evidence.delivery_acceptance_date)
    if not start <= acceptance <= now or acceptance >= end:
        raise ValueError("delivery acceptance must be an actual date within service period")
    if now >= end and evidence.completion_reconciliation_evidence_id:
        return result("completed", (), deposit)
    return result("active", ("final_reconciliation_missing",) if now >= end else (), deposit)
