import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.pricing import evaluate_pricing_scenarios
from test_pricing_v1 import pricing_packet


class PricingScenarioTests(unittest.TestCase):
    def test_funding_alternative_is_separate_complete_cash_path(self):
        baseline = pricing_packet()
        more_cash = copy.deepcopy(baseline)
        more_cash["cash_template"]["schedule"]["opening_cash"] = "100"
        result = evaluate_pricing_scenarios({"baseline": baseline, "scenarios": [{"scenario_id": "funded", "request": more_cash}]})
        self.assertEqual(result["baseline"]["bid"]["submitted_limit"], "0.93")
        self.assertEqual(result["scenarios"][0]["result"]["bid"]["submitted_limit"], "1.61")
        self.assertEqual(baseline["cash_template"]["schedule"]["opening_cash"], "12")
        self.assertNotIn("expected_loss", result)

    def test_collection_shock_requires_reconciled_cash_not_only_economic_assumption(self):
        baseline = pricing_packet()
        shocked = copy.deepcopy(baseline)
        shocked["commercial"]["collection_share"] = "0.5"
        with self.assertRaises(ValidationError):
            evaluate_pricing_scenarios({"baseline": baseline, "scenarios": [{"scenario_id": "collection", "request": shocked}]})

    def test_duplicate_and_empty_alternatives_fail(self):
        baseline = pricing_packet()
        row = {"scenario_id": "duplicate", "request": baseline}
        for alternatives in ([], [row, row]):
            with self.assertRaises(ValidationError):
                evaluate_pricing_scenarios({"baseline": baseline, "scenarios": alternatives})


if __name__ == "__main__":
    unittest.main()
