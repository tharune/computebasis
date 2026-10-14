"""Discrete weighted tail loss from explicit complete portfolio scenarios."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Sequence
from compute_pricing.control.treasury._validation import calculation_precision, decimal_value, identifier
from .exposure import Exposure, attribute_losses
from .scenarios import CashScenario, ScenarioReport, evaluate_scenarios


@dataclass(frozen=True)
class TailRiskReport:
    confidence: Decimal
    expected_loss: Decimal
    value_at_risk: Decimal
    expected_shortfall: Decimal
    worst_loss: Decimal
    cash_stress: ScenarioReport
    portfolio_exposure_ids: tuple[str, ...]
    distribution_evidence_id: str
    calibration_verified: bool = False
    execution_eligible: bool = False


def evaluate_portfolio_tail_risk(scenarios: Sequence[CashScenario], exposures: Sequence[Exposure], *,
        confidence: str, distribution_evidence_id: str, **shared_ledger_inputs) -> TailRiskReport:
    """All scenarios share one portfolio and one cash/facility baseline.

    VaR is the smallest discrete loss whose CDF reaches confidence. ES is the
    mean loss in the highest 1-confidence probability mass, including only the
    required fraction of boundary mass. Exhaustive/calibrated distribution
    coverage is a caller evidence claim; normalized weights alone cannot prove it.
    """
    identifier(distribution_evidence_id, "distribution evidence")
    alpha = decimal_value(confidence, "confidence")
    if not 0 < alpha < 1:
        raise ValueError("tail confidence must lie strictly between zero and one")
    if not scenarios or any(not isinstance(scenario, CashScenario) or scenario.probability is None for scenario in scenarios):
        raise ValueError("complete explicit normalized scenario probabilities required")
    if not exposures or any(not isinstance(item, Exposure) for item in exposures) or len({item.exposure_id for item in exposures}) != len(exposures):
        raise ValueError("one unique baseline portfolio exposure set required")
    currency = shared_ledger_inputs.get("currency")
    if any(item.currency != currency for item in exposures) or any(loss.currency != currency for scenario in scenarios for loss in scenario.losses):
        raise ValueError("tail loss cannot combine currencies without explicit FX settlement")
    cash_stress = evaluate_scenarios(scenarios, **shared_ledger_inputs)
    values = [confidence, *[scenario.probability for scenario in scenarios], *[loss.amount for scenario in scenarios for loss in scenario.losses]]
    with localcontext() as context:
        context.prec = calculation_precision(values, len(scenarios))
        distribution = sorted((sum(attribute_losses(scenario.losses).values(), Decimal("0")), decimal_value(scenario.probability, "probability")) for scenario in scenarios)
        expected = sum((loss * probability for loss, probability in distribution), Decimal("0"))
        cumulative, var = Decimal("0"), Decimal("0")
        for loss, probability in distribution:
            cumulative += probability
            if cumulative >= alpha:
                var = loss
                break
        budget, tail_loss = 1 - alpha, Decimal("0")
        remaining = budget
        for loss, probability in reversed(distribution):
            included = min(probability, remaining)
            tail_loss += loss * included
            remaining -= included
            if remaining == 0:
                break
        return TailRiskReport(alpha, expected, var, tail_loss / budget, max((loss for loss, probability in distribution if probability > 0), default=Decimal("0")), cash_stress,
            tuple(sorted(item.exposure_id for item in exposures)), distribution_evidence_id)
