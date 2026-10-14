"""Independent economic counterexample: identical marginals, different tails."""
import unittest

from compute_pricing.control.risk import (
    CashScenario, Exposure, LossComponent, evaluate_portfolio_tail_risk,
)
from compute_pricing.control.treasury import CashEvent


class JointDistributionSemanticsTests(unittest.TestCase):
    def evaluate(self, values):
        paths = []
        for index, pair in enumerate(values):
            events, losses = [], []
            for component, amount in enumerate(pair):
                if amount == 0:
                    continue
                identity = f"path-{index}-component-{component}"
                events.append(CashEvent(identity, f"leg-{identity}", "2025-02-03",
                                        "other_outflow", str(amount), "USD"))
                losses.append(LossComponent(f"loss-{identity}", f"component-{component}",
                                            "operating", "USD", str(amount), (identity,)))
            paths.append(CashScenario(f"path-{index}", tuple(events), tuple(losses), "0.5"))
        return evaluate_portfolio_tail_risk(
            paths, [Exposure("position", "counterparty", "group", "site", "USD", "30")],
            confidence="0.75", distribution_evidence_id="invented-dependence-counterexample",
            legal_entity_id="operator", cash_account_id="planning-account", currency="USD",
            opening_cash="40", start_date="2025-02-03", end_date="2025-02-03",
        )

    def test_identical_marginals_do_not_determine_joint_percentile(self):
        alternating = self.evaluate(((0, 12), (12, 0)))
        together = self.evaluate(((0, 0), (12, 12)))
        self.assertEqual(alternating.expected_loss, together.expected_loss)
        self.assertEqual(alternating.expected_loss, 12)
        self.assertEqual((alternating.value_at_risk, alternating.expected_shortfall), (12, 12))
        self.assertEqual((together.value_at_risk, together.expected_shortfall), (24, 24))
        self.assertEqual(alternating.cash_stress.worst_required_extra_cash, 0)
        self.assertEqual(together.cash_stress.worst_required_extra_cash, 0)
        self.assertFalse(alternating.calibration_verified)
        self.assertFalse(together.execution_eligible)


if __name__ == "__main__":
    unittest.main()
