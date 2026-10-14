"""Evidence-gated receivable eligibility, unique pledges and borrowing base."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Sequence
from compute_pricing.control.treasury._validation import calculation_precision, currency_value, decimal_value, identifier, iso_date


@dataclass(frozen=True)
class ReceivableExclusion:
    exclusion_id: str
    ownership_id: str
    reason: str
    amount: str

    def __post_init__(self):
        identifier(self.exclusion_id, "exclusion_id")
        identifier(self.ownership_id, "exclusion ownership")
        if self.reason not in {"dispute", "dilution", "chargeback", "offset", "tax", "other_verified_exclusion"}:
            raise ValueError("unsupported receivable exclusion")
        decimal_value(self.amount, "excluded amount")


@dataclass(frozen=True)
class Receivable:
    economic_id: str
    legal_entity_id: str
    currency: str
    debtor_entity_id: str
    debtor_group_id: str
    outstanding_amount: str
    issue_date: str
    due_date: str
    evidence_expiry_date: str
    acceptance_confirmed: bool
    acceptance_date: str | None
    assignability_verified: bool
    acceptance_evidence_id: str | None
    eligibility_evidence_id: str | None
    legal_evidence_id: str | None
    ownership_evidence_id: str | None
    exclusions: tuple[ReceivableExclusion, ...]

    def __post_init__(self):
        for field in ("economic_id", "legal_entity_id", "debtor_entity_id", "debtor_group_id"):
            identifier(getattr(self, field), field)
        currency_value(self.currency)
        decimal_value(self.outstanding_amount, "outstanding receivable")
        if iso_date(self.due_date) < iso_date(self.issue_date) or iso_date(self.evidence_expiry_date) <= iso_date(self.issue_date):
            raise ValueError("invalid receivable due/expiry dates")
        if self.acceptance_date is not None and iso_date(self.acceptance_date) < iso_date(self.issue_date):
            raise ValueError("acceptance cannot precede invoice issue")
        if not isinstance(self.acceptance_confirmed, bool) or not isinstance(self.assignability_verified, bool):
            raise ValueError("receivable eligibility assertions require explicit booleans")
        for field in ("acceptance_evidence_id", "eligibility_evidence_id", "legal_evidence_id", "ownership_evidence_id"):
            if getattr(self, field) is not None:
                identifier(getattr(self, field), field)
        if not isinstance(self.exclusions, tuple) or any(not isinstance(item, ReceivableExclusion) for item in self.exclusions):
            raise ValueError("exclusions must be immutable validated records")
        if len({item.exclusion_id for item in self.exclusions}) != len(self.exclusions) or len({item.ownership_id for item in self.exclusions}) != len(self.exclusions):
            raise ValueError("overlapping/duplicate receivable exclusion ownership")
        with localcontext() as context:
            context.prec = calculation_precision([self.outstanding_amount, *[item.amount for item in self.exclusions]], len(self.exclusions))
            if sum((decimal_value(item.amount, "exclusion") for item in self.exclusions), Decimal("0")) > decimal_value(self.outstanding_amount, "outstanding"):
                raise ValueError("disjoint exclusions exceed outstanding receivable")


@dataclass(frozen=True)
class Pledge:
    economic_id: str
    facility_id: str
    evidence_id: str

    def __post_init__(self):
        identifier(self.economic_id, "pledged economic_id")
        identifier(self.facility_id, "pledged facility_id")
        identifier(self.evidence_id, "pledge evidence")


@dataclass(frozen=True)
class BorrowingFacility:
    facility_id: str
    legal_entity_id: str
    collection_account_id: str
    currency: str
    committed_limit: str
    outstanding_principal: str
    accrued_interest: str
    annual_rate: str
    day_count: str
    available_from: str
    maturity_date: str

    def __post_init__(self):
        identifier(self.facility_id, "facility_id")
        identifier(self.legal_entity_id, "legal_entity_id")
        identifier(self.collection_account_id, "collection_account_id")
        currency_value(self.currency)
        for field in ("committed_limit", "outstanding_principal", "accrued_interest", "annual_rate"):
            decimal_value(getattr(self, field), field)
        if decimal_value(self.outstanding_principal, "principal") > decimal_value(self.committed_limit, "limit"):
            raise ValueError("opening principal exceeds committed facility")
        if self.day_count not in {"ACT/365F", "ACT/360"} or iso_date(self.maturity_date) <= iso_date(self.available_from):
            raise ValueError("invalid facility convention or dates")


@dataclass(frozen=True)
class BorrowingPolicy:
    policy_version: str
    advance_rate: str
    haircut: str
    maximum_debtor_fraction: str
    maximum_group_fraction: str
    concentration_denominator: str
    reserve_amount: str
    maximum_overdue_days: int
    maximum_age_days: int

    def __post_init__(self):
        identifier(self.policy_version, "policy_version")
        for field in ("advance_rate", "haircut", "maximum_debtor_fraction", "maximum_group_fraction"):
            if decimal_value(getattr(self, field), field) > 1:
                raise ValueError("advance/haircut/concentration fractions must lie in [0,1]")
        if self.concentration_denominator != "pre_concentration_eligible":
            raise ValueError("unsupported concentration denominator; do not infer legal policy")
        decimal_value(self.reserve_amount, "borrowing reserve")
        for field in ("maximum_overdue_days", "maximum_age_days"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("age/overdue thresholds must be explicit nonnegative days")


@dataclass(frozen=True)
class BorrowingBase:
    eligible_amounts: dict[str, Decimal]
    exclusions: dict[str, tuple[str, ...]]
    eligible_before_concentration: Decimal
    eligible_after_concentration: Decimal
    concentration_excess: Decimal
    borrowing_base: Decimal
    current_credit_limit: Decimal
    drawable_undrawn: Decimal
    principal_deficiency: Decimal
    maturity_call: Decimal
    execution_eligible: bool = False


def validate_pledges(pledges: Sequence[Pledge]) -> dict[str, Pledge]:
    result = {}
    for pledge in pledges:
        if not isinstance(pledge, Pledge) or pledge.economic_id in result:
            raise ValueError("economic receivable cannot be pledged twice across facilities")
        result[pledge.economic_id] = pledge
    return result


def evaluate_borrowing_base(receivables: Sequence[Receivable], pledges: Sequence[Pledge],
        facility: BorrowingFacility, policy: BorrowingPolicy, *, as_of: str,
        pledge_registry_evidence_id: str | None) -> BorrowingBase:
    """No source score invents eligibility. Missing required evidence excludes.

    Concentration caps deliberately use the explicitly selected PRE-concentration
    eligible denominator. Other lender definitions need a separately implemented,
    versioned policy; the result does not assert their legal compatibility.
    """
    now = iso_date(as_of)
    registry = validate_pledges(pledges)
    if pledge_registry_evidence_id is not None:
        identifier(pledge_registry_evidence_id, "pledge registry evidence")
    if any(not isinstance(item, Receivable) for item in receivables) or len({item.economic_id for item in receivables}) != len(receivables):
        raise ValueError("unique validated economic receivables required")
    values = [facility.committed_limit, facility.outstanding_principal, facility.accrued_interest,
        policy.advance_rate, policy.haircut, policy.maximum_debtor_fraction, policy.maximum_group_fraction, policy.reserve_amount]
    values.extend(value for item in receivables for value in (item.outstanding_amount, *[exclusion.amount for exclusion in item.exclusions]))
    with localcontext() as context:
        context.prec = calculation_precision(values, len(receivables))
        eligible, exclusions, entities, entity_groups = {}, {}, {}, {}
        for item in receivables:
            if (item.legal_entity_id, item.currency) != (facility.legal_entity_id, facility.currency):
                raise ValueError("receivable requires separately scoped entity/currency funding")
            if item.debtor_entity_id in entity_groups and entity_groups[item.debtor_entity_id] != item.debtor_group_id:
                raise ValueError("debtor parent identity is inconsistent")
            entity_groups[item.debtor_entity_id] = item.debtor_group_id
            reasons = []
            if not item.acceptance_confirmed or item.acceptance_date is None or not item.acceptance_evidence_id:
                reasons.append("acceptance_not_independently_evidenced")
            elif iso_date(item.acceptance_date) > now:
                reasons.append("acceptance_is_future")
            if not item.assignability_verified or not item.legal_evidence_id or not item.eligibility_evidence_id or not item.ownership_evidence_id:
                reasons.append("legal_eligibility_or_ownership_evidence_missing")
            if not pledge_registry_evidence_id:
                reasons.append("pledge_registry_evidence_missing")
            if item.economic_id in registry and registry[item.economic_id].facility_id != facility.facility_id:
                reasons.append("pledged_to_other_facility")
            if now < iso_date(item.issue_date):
                reasons.append("invoice_not_issued")
            if now >= iso_date(item.evidence_expiry_date):
                reasons.append("evidence_expired")
            if (now - iso_date(item.due_date)).days > policy.maximum_overdue_days:
                reasons.append("overdue_outside_policy")
            if (now - iso_date(item.issue_date)).days > policy.maximum_age_days:
                reasons.append("age_outside_policy")
            if reasons:
                exclusions[item.economic_id] = tuple(reasons)
                continue
            amount = decimal_value(item.outstanding_amount, "outstanding") - sum((decimal_value(exclusion.amount, "exclusion") for exclusion in item.exclusions), Decimal("0"))
            eligible[item.economic_id] = amount
            entities[item.debtor_entity_id] = entities.get(item.debtor_entity_id, Decimal("0")) + amount
        before = sum(eligible.values(), Decimal("0"))
        debtor_cap = before * decimal_value(policy.maximum_debtor_fraction, "debtor cap")
        group_cap = before * decimal_value(policy.maximum_group_fraction, "group cap")
        groups = {}
        for entity, amount in entities.items():
            group = entity_groups[entity]
            groups[group] = groups.get(group, Decimal("0")) + min(amount, debtor_cap)
        after = sum((min(amount, group_cap) for amount in groups.values()), Decimal("0"))
        base = max(Decimal("0"), after * (1 - decimal_value(policy.haircut, "haircut")) * decimal_value(policy.advance_rate, "advance") - decimal_value(policy.reserve_amount, "reserve"))
        available = iso_date(facility.available_from) <= now < iso_date(facility.maturity_date)
        limit = min(base, decimal_value(facility.committed_limit, "commitment")) if available else Decimal("0")
        principal = decimal_value(facility.outstanding_principal, "principal")
        maturity_call = principal + decimal_value(facility.accrued_interest, "interest") if now >= iso_date(facility.maturity_date) else Decimal("0")
        return BorrowingBase(eligible, exclusions, before, after, before - after, base, limit,
            max(Decimal("0"), limit - principal), max(Decimal("0"), principal - limit), maturity_call)
