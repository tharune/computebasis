"""Explicit joint cash paths. No fabricated default probabilities or priors."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Sequence
from compute_pricing.control.treasury import CashEvent, CashSchedule, evaluate_cash_schedule
from compute_pricing.control.treasury._validation import calculation_precision, decimal_value, identifier
from .exposure import LossComponent, attribute_losses


@dataclass(frozen=True)
class CashScenario:
    scenario_id: str
    events: tuple[CashEvent, ...]
    losses: tuple[LossComponent, ...] = ()
    probability: str | None = None

    def __post_init__(self):
        identifier(self.scenario_id, "scenario_id")
        if not isinstance(self.events, tuple) or any(not isinstance(event, CashEvent) for event in self.events):
            raise ValueError("scenario events must be an immutable tuple of CashEvent records")
        if not isinstance(self.losses, tuple):
            raise ValueError("scenario losses must be an immutable tuple")
        if self.probability is not None and decimal_value(self.probability, "scenario probability") > 1:
            raise ValueError("scenario probability exceeds one")
        # Loss attribution is reporting only: all actual cash effects belong in events.
        attribute_losses(self.losses)
        event_ids = {event.event_id for event in self.events}
        if any(not set(loss.cash_event_ids) <= event_ids for loss in self.losses):
            raise ValueError("scenario loss refers to a missing cash event")
        by_id = {event.event_id: event for event in self.events}
        cash_kinds = {"buyer_receipt", "buyer_deposit", "deposit_refund", "supplier_prepayment", "supplier_payment", "other_inflow", "other_outflow", "facility_interest",
                      "buyer_advance", "advance_refund", "deposit_forfeit"}
        if any(by_id[key].currency != loss.currency or by_id[key].kind not in cash_kinds for loss in self.losses for key in loss.cash_event_ids):
            raise ValueError("loss cash-event ownership must reference a cash effect in its currency")


@dataclass(frozen=True)
class ScenarioReport:
    schedules: dict[str, CashSchedule]
    worst_scenario_id: str
    worst_required_extra_cash: Decimal
    expected_required_extra_cash: Decimal | None
    metric_basis: str = "full_dated_funding_shortfall_not_economic_loss_tail"
    distribution_calibration_verified: bool = False


def evaluate_scenarios(scenarios: Sequence[CashScenario], **shared_ledger_inputs) -> ScenarioReport:
    """Evaluate complete joint paths using ONE common opening balance/facility.

    Each scenario is an alternative full-portfolio cash path, not a separately
    funded deal. This function never sums independent deal liquidity outputs.
    Probabilities are optional supplied/calibrated evidence; missing values
    produce no probability-weighted assertion.
    """
    if not scenarios or any(not isinstance(scenario, CashScenario) for scenario in scenarios) or len({scenario.scenario_id for scenario in scenarios}) != len(scenarios):
        raise ValueError("nonempty uniquely identified scenarios required")
    supplied = [scenario.probability is not None for scenario in scenarios]
    if any(supplied) and not all(supplied):
        raise ValueError("probabilities must be supplied for every path or none")
    with localcontext() as context:
        # Validate supplied probability totals without rounding a nearly-one sum.
        context.prec = max(38, max((len(scenario.probability) for scenario in scenarios if scenario.probability is not None), default=0) + len(str(len(scenarios))) + 100)
        if all(supplied) and sum((decimal_value(scenario.probability, "probability") for scenario in scenarios), Decimal("0")) != 1:
            raise ValueError("scenario probabilities must sum exactly to one")
        schedules = {scenario.scenario_id: evaluate_cash_schedule(scenario.events, **shared_ledger_inputs) for scenario in scenarios}
        worst = max(schedules, key=lambda key: schedules[key].required_extra_cash)
        context.prec = calculation_precision([scenario.probability for scenario in scenarios if scenario.probability is not None] + [format(schedule.required_extra_cash, "f") for schedule in schedules.values()], len(scenarios))
        expected = sum((decimal_value(scenario.probability, "probability") * schedules[scenario.scenario_id].required_extra_cash for scenario in scenarios), Decimal("0")) if all(supplied) else None
    return ScenarioReport(schedules, worst, schedules[worst].required_extra_cash, expected)
