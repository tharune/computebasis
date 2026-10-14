"""Deterministic explicit exposure limits and nonoverlapping loss attribution."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Sequence
from compute_pricing.control.treasury._validation import calculation_precision, currency_value, decimal_value, identifier


SCOPES = frozenset({"entity", "group", "site", "currency"})
LOSS_CATEGORIES = frozenset({"supplier_credit", "buyer_credit", "refund", "performance", "replacement", "market", "operating"})


@dataclass(frozen=True)
class Exposure:
    exposure_id: str
    entity_id: str
    group_id: str
    site_id: str
    currency: str
    amount: str

    def __post_init__(self):
        for name in ("exposure_id", "entity_id", "group_id", "site_id"):
            identifier(getattr(self, name), name)
        currency_value(self.currency)
        decimal_value(self.amount, "exposure amount")


@dataclass(frozen=True)
class ExposureLimit:
    limit_id: str
    scope: str
    member_id: str
    currency: str
    maximum_amount: str

    def __post_init__(self):
        identifier(self.limit_id, "limit_id")
        identifier(self.member_id, "member_id")
        if self.scope not in SCOPES:
            raise ValueError("unsupported exposure scope")
        currency_value(self.currency)
        decimal_value(self.maximum_amount, "exposure limit")
        if self.scope == "currency" and self.member_id != self.currency:
            raise ValueError("currency scope member must equal settlement currency")


@dataclass(frozen=True)
class LimitAssessment:
    limit_id: str
    amount: Decimal
    maximum_amount: Decimal
    breached: bool
    remaining: Decimal


@dataclass(frozen=True)
class ExposureReport:
    totals: dict[tuple[str, str, str], Decimal]
    limits: tuple[LimitAssessment, ...]
    uncovered: tuple[tuple[str, str, str], ...]
    admitted: bool


def assess_exposures(exposures: Sequence[Exposure], limits: Sequence[ExposureLimit]) -> ExposureReport:
    """Every present entity/group/site/currency requires an explicit policy limit.

    Amounts are supplied exposure measures in each settlement currency. They
    are never added across currencies or inferred from uncalibrated scores.
    Include the baseline portfolio and candidate once in the same call.
    """
    if any(not isinstance(item, Exposure) for item in exposures) or any(not isinstance(item, ExposureLimit) for item in limits):
        raise ValueError("exposure assessment requires validated records")
    ids, totals = set(), {}
    with localcontext() as context:
        context.prec = calculation_precision([item.amount for item in exposures] + [item.maximum_amount for item in limits], len(exposures) + len(limits))
        for exposure in exposures:
            if not isinstance(exposure, Exposure) or exposure.exposure_id in ids:
                raise ValueError("duplicate or invalid exposure")
            ids.add(exposure.exposure_id)
            value = decimal_value(exposure.amount, "exposure amount")
            members = {"entity": exposure.entity_id, "group": exposure.group_id, "site": exposure.site_id, "currency": exposure.currency}
            for scope, member in members.items():
                key = (scope, member, exposure.currency)
                totals[key] = totals.get(key, Decimal("0")) + value
        limit_ids, keys, assessments = set(), set(), []
        for limit in limits:
            if not isinstance(limit, ExposureLimit) or limit.limit_id in limit_ids:
                raise ValueError("duplicate or invalid exposure limit")
            limit_ids.add(limit.limit_id)
            key = (limit.scope, limit.member_id, limit.currency)
            if key in keys:
                raise ValueError("duplicate policy coverage; resolve limit precedence explicitly")
            keys.add(key)
            amount, maximum = totals.get(key, Decimal("0")), decimal_value(limit.maximum_amount, "limit")
            assessments.append(LimitAssessment(limit.limit_id, amount, maximum, amount > maximum, maximum - amount))
        uncovered = tuple(sorted(set(totals) - keys))
        return ExposureReport(totals, tuple(assessments), uncovered, not uncovered and not any(item.breached for item in assessments))


@dataclass(frozen=True)
class LossComponent:
    loss_id: str
    ownership_id: str
    category: str
    currency: str
    amount: str
    cash_event_ids: tuple[str, ...]

    def __post_init__(self):
        identifier(self.loss_id, "loss_id")
        identifier(self.ownership_id, "ownership_id")
        if self.category not in LOSS_CATEGORIES:
            raise ValueError("unknown loss category")
        currency_value(self.currency)
        decimal_value(self.amount, "loss amount")
        if not isinstance(self.cash_event_ids, tuple) or len(set(self.cash_event_ids)) != len(self.cash_event_ids):
            raise ValueError("loss cash-event identifiers must be unique tuple")
        for event_id in self.cash_event_ids:
            identifier(event_id, "loss cash event")


def attribute_losses(losses: Sequence[LossComponent]) -> dict[tuple[str, str], Decimal]:
    """Report supplied losses once; this does not subtract them from cash again.

    ownership_id identifies an economic loss component even when its cash
    event is delayed or absent. Reusing either ownership or a cash-event ID
    across categories is rejected rather than silently charging it twice.
    """
    if any(not isinstance(item, LossComponent) for item in losses):
        raise ValueError("loss attribution requires validated records")
    ids, owners, events, totals = set(), set(), set(), {}
    with localcontext() as context:
        context.prec = calculation_precision([item.amount for item in losses], len(losses))
        for loss in losses:
            if not isinstance(loss, LossComponent) or loss.loss_id in ids or loss.ownership_id in owners:
                raise ValueError("duplicate loss or economic ownership")
            if events & set(loss.cash_event_ids):
                raise ValueError("cash event has overlapping loss ownership")
            ids.add(loss.loss_id)
            owners.add(loss.ownership_id)
            events.update(loss.cash_event_ids)
            key = (loss.currency, loss.category)
            totals[key] = totals.get(key, Decimal("0")) + decimal_value(loss.amount, "loss")
        return totals
