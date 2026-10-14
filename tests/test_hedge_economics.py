"""Independent synthetic hedge ratios, probability tails and collateral paths."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from compute_pricing.control.domain import ValidationError
from compute_pricing.control.hedging import evaluate_hedge_payload, hedge_contract


def study():
    return {"schema_version": "hedge-study/1.0", "request_id": "sample:scalar-hedge", "as_of": "2052-09-08T00:00:00Z",
        "currency": "USD", "loss_unit": "USD", "payoff_unit": "USD_per_long_contract", "confidence": "0.8",
        "contract": {"payoff_kind": "linear_futures", "settlement_currency": "USD", "minimum_position": -3,
            "maximum_position": 3, "fee_per_contract": "0.75", "initial_collateral_per_contract": "3",
            "collateral_post_on": "2052-09-08", "collateral_release_on": "2052-09-12"},
        "cash": {"opening_cash": "70", "minimum_free_cash": "0", "start_date": "2052-09-08",
            "end_date": "2052-09-12", "baseline_events": []},
        "scenarios": [{"scenario_id": identity, "probability": probability, "unhedged_loss": loss,
            "long_contract_payoff": payoff, "variation_margin": [
                {"on": "2052-09-09", "cash_per_long_contract": first},
                {"on": "2052-09-11", "cash_per_long_contract": first}]}
            for identity, probability, loss, payoff, first in
            (("sample:soft", "0.2", "9", "-6", "-3"), ("sample:flat", "0.6", "18", "0", "0"),
             ("sample:firm", "0.2", "27", "6", "3"))]}


def at(report, size):
    return next(row for row in report["candidates"] if row["position"] == size)


class ScalarHedgeEconomicsTests(unittest.TestCase):
    def test_fractional_ratio_and_fee_tie_choose_smaller_scenario_position(self):
        report = evaluate_hedge_payload(study())
        self.assertEqual(report["fit"]["long_contract_payoff_variance"], "14.4")
        self.assertEqual(report["fit"]["loss_payoff_covariance"], "21.6")
        self.assertEqual(report["fit"]["minimum_variance_signed_contracts"], "1.5")
        self.assertEqual([item["position"] for item in report["candidates"]], [0, 1, 2])
        self.assertEqual(at(report, 1)["economic_loss"]["variance"], "3.6")
        self.assertEqual(at(report, 2)["economic_loss"]["variance"], "3.6")
        self.assertEqual(at(report, 1)["economic_loss"]["expected_loss"], "18.75")
        self.assertEqual(at(report, 2)["economic_loss"]["expected_loss"], "19.5")
        self.assertEqual(report["preferred_compared_scenario_position"], 1)
        self.assertFalse(report["execution_enabled"])
        self.assertFalse(report["firm_price_eligible"])
        self.assertFalse(report["calibration_verified"])
        self.assertFalse(report["sample_probabilities_verified"])

    def test_many_linear_maps_match_independent_centered_covariance_oracle(self):
        checked = 0
        for intercept in ("17", "41"):
            for slope in ("-3", "-1.5", "-0.25", "0", "0.25", "1.5", "3"):
                for shift in ("0", "7"):
                    raw = study()
                    raw["cash"]["opening_cash"] = "10000"
                    for case, h in zip(raw["scenarios"], (Decimal(shift) - 6, Decimal(shift), Decimal(shift) + 6)):
                        case["long_contract_payoff"] = str(h)
                        case["unhedged_loss"] = str(Decimal(intercept) + Decimal(slope) * h)
                        case["variation_margin"] = [{"on": "2052-09-11", "cash_per_long_contract": str(h)}]
                    weights = [Decimal(row["probability"]) for row in raw["scenarios"]]
                    hs = [Decimal(row["long_contract_payoff"]) for row in raw["scenarios"]]
                    ls = [Decimal(row["unhedged_loss"]) for row in raw["scenarios"]]
                    h_mean = sum(p * h for p, h in zip(weights, hs))
                    l_mean = sum(p * loss for p, loss in zip(weights, ls))
                    var = sum(p * (h - h_mean) ** 2 for p, h in zip(weights, hs))
                    cov = sum(p * (h - h_mean) * (loss - l_mean) for p, h, loss in zip(weights, hs, ls))
                    result = evaluate_hedge_payload(raw)
                    self.assertEqual(Decimal(result["fit"]["minimum_variance_signed_contracts"]), cov / var)
                    self.assertEqual(Decimal(result["fit"]["minimum_variance_signed_contracts"]), Decimal(slope))
                    checked += 1
        self.assertEqual(checked, 28)

    def test_short_hedge_pays_when_long_contract_loses_and_fee_uses_absolute_size(self):
        raw = study()
        for row in raw["scenarios"]:
            row["unhedged_loss"] = str(18 - 2 * Decimal(row["long_contract_payoff"]))
        result = evaluate_hedge_payload(raw)
        self.assertEqual(result["fit"]["minimum_variance_signed_contracts"], "-2")
        self.assertEqual(result["preferred_compared_scenario_position"], -2)
        short = at(result, -2)
        self.assertEqual(short["fees"], "1.5")
        self.assertEqual(short["economic_loss"]["variance"], "0")
        self.assertEqual(short["margin_liquidity"]["scenarios"][0]["variation_margin_total"], "12")

    def test_zero_variance_holds_but_identifiable_zero_correlation_does_not(self):
        raw = study()
        for row in raw["scenarios"]:
            row["long_contract_payoff"] = "4"
            row["variation_margin"] = [{"on": "2052-09-11", "cash_per_long_contract": "4"}]
        held = evaluate_hedge_payload(raw)
        self.assertEqual(held["status"], "held")
        self.assertIsNone(held["fit"]["minimum_variance_signed_contracts"])
        self.assertIsNone(held["preferred_compared_scenario_position"])
        self.assertIn("hedge_payoff_variance_zero", held["blockers"])
        raw = study()
        for row, loss in zip(raw["scenarios"], ("12", "24", "12")):
            row["unhedged_loss"] = loss
        identified = evaluate_hedge_payload(raw)
        self.assertEqual(identified["status"], "scenario_only")
        self.assertEqual(identified["fit"]["minimum_variance_signed_contracts"], "0")

    def test_declared_bounds_clip_continuous_fit_and_zero_remains_only_reference(self):
        raw = study()
        raw["contract"].update(minimum_position=2, maximum_position=2)
        result = evaluate_hedge_payload(raw)
        self.assertEqual(result["fit"]["minimum_variance_signed_contracts"], "1.5")
        self.assertEqual(result["fit"]["bound_projected_signed_contracts"], "2")
        self.assertFalse(at(result, 0)["within_declared_position_bounds"])
        self.assertEqual(result["preferred_compared_scenario_position"], 2)

    def test_both_bounded_contracts_and_funding_must_pass(self):
        raw = study()
        raw["contract"].update(minimum_position=2, maximum_position=2, initial_collateral_per_contract="100")
        result = evaluate_hedge_payload(raw)
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["preferred_compared_scenario_position"])
        self.assertIn("no_compared_position_passes_declared_bounds_and_funding", result["blockers"])

    def test_tail_uses_partial_mass_at_boundary_and_preserves_signed_gains(self):
        raw = study()
        raw["confidence"] = "0.6"
        for row, probability, loss in zip(raw["scenarios"], ("0.45", "0.4", "0.15"), ("-4", "8", "24")):
            row.update(probability=probability, unhedged_loss=loss)
        result = evaluate_hedge_payload(raw)
        zero = at(result, 0)["economic_loss"]
        self.assertEqual(zero["expected_loss"], "5")
        self.assertEqual(zero["value_at_risk"], "8")
        self.assertEqual(zero["expected_shortfall"], "14")
        raw["confidence"] = "0.85"
        tail = at(evaluate_hedge_payload(raw), 0)["economic_loss"]
        self.assertEqual((tail["value_at_risk"], tail["expected_shortfall"]), ("8", "24"))

    def test_initial_collateral_is_returned_asset_and_payoff_is_not_added_again(self):
        raw = study()
        result = evaluate_hedge_payload(raw)
        first = at(result, 1)["margin_liquidity"]["scenarios"][0]
        self.assertEqual(first["variation_margin_total"], "-6")
        self.assertEqual(first["ending_unrestricted_cash"], "63.25")
        self.assertEqual(first["minimum_free_cash"], "60.25")
        self.assertEqual(first["ending_posted_collateral"], "0")
        self.assertFalse(first["terminal_payoff_added_separately"])
        raw["contract"]["initial_collateral_per_contract"] = "11"
        changed = evaluate_hedge_payload(raw)
        self.assertEqual(at(changed, 1)["economic_loss"], at(result, 1)["economic_loss"])
        self.assertEqual(at(changed, 1)["margin_liquidity"]["scenarios"][0]["ending_unrestricted_cash"], "63.25")

    def test_future_margin_recovery_does_not_cover_earlier_funding_trough(self):
        raw = study()
        raw["cash"]["opening_cash"] = "7"
        raw["contract"].update(fee_per_contract="0", initial_collateral_per_contract="1")
        for row, payoff in zip(raw["scenarios"], (0, 3, 6)):
            row.update(unhedged_loss=str(2 * payoff), long_contract_payoff=str(payoff), variation_margin=[
                {"on": "2052-09-09", "cash_per_long_contract": "-12"},
                {"on": "2052-09-11", "cash_per_long_contract": str(12 + payoff)}])
        result = evaluate_hedge_payload(raw)
        perfect = at(result, 2)
        self.assertEqual(perfect["economic_loss"]["expected_shortfall"], "0")
        self.assertFalse(perfect["margin_liquidity"]["all_scenarios_pass_declared_funding"])
        self.assertEqual(perfect["margin_liquidity"]["funding_shortfall_tail"]["expected_shortfall"], "19")
        self.assertTrue(all(Decimal(row["ending_unrestricted_cash"]) >= 7 for row in perfect["margin_liquidity"]["scenarios"]))
        self.assertEqual(result["preferred_compared_scenario_position"], 0)

    def test_same_date_cash_credits_cannot_erase_gross_outflow_requirement(self):
        raw = study()
        raw["cash"]["opening_cash"] = "0"
        raw["cash"]["baseline_events"] = [{"event_id": "cash:sample", "on": "2052-09-08", "cash_change": "70"}]
        report = evaluate_hedge_payload(raw)
        path = at(report, 1)["margin_liquidity"]["scenarios"][0]
        self.assertEqual(path["required_extra_cash"], "3.75")
        self.assertEqual(path["minimum_free_cash_witness"]["on"], "2052-09-08")
        self.assertEqual(path["ending_unrestricted_cash"], "63.25")

    def test_vm_must_telescope_and_baseline_cannot_reuse_trace_namespace(self):
        raw = study()
        raw["scenarios"][0]["long_contract_payoff"] = "-5"
        with self.assertRaises(ValidationError):
            evaluate_hedge_payload(raw)
        raw = study()
        raw["cash"]["baseline_events"] = [{"event_id": "hedge:fees", "on": "2052-09-08", "cash_change": "0"}]
        with self.assertRaises(ValidationError):
            evaluate_hedge_payload(raw)

    def test_exact_results_survive_low_ambient_precision_and_mutable_output(self):
        raw = study()
        original = deepcopy(raw)
        with localcontext() as context:
            context.prec = 2
            result = evaluate_hedge_payload(raw)
        self.assertEqual(result, evaluate_hedge_payload(raw))
        result["candidates"][0]["margin_liquidity"]["scenarios"][0]["dates"].clear()
        self.assertEqual(raw, original)
        self.assertTrue(evaluate_hedge_payload(raw)["candidates"][0]["margin_liquidity"]["scenarios"][0]["dates"])

    def test_normalization_units_kind_and_unknown_fields_never_become_defaults(self):
        invalid = []
        for value in (None, True, 0.2, "0", "-0.1", "NaN", "1e-2", "0.3"):
            raw = study(); raw["scenarios"][0]["probability"] = value; invalid.append(raw)
        raw = study(); raw["scenarios"].pop(); invalid.append(raw)
        raw = study(); raw["scenarios"][1]["scenario_id"] = raw["scenarios"][0]["scenario_id"]; invalid.append(raw)
        raw = study(); raw["payoff_unit"] = "GPU_hours"; invalid.append(raw)
        raw = study(); raw["currency"] = "GBP"; invalid.append(raw)
        raw = study(); raw["contract"]["payoff_kind"] = "option"; invalid.append(raw)
        raw = study(); raw["contract"].pop("initial_collateral_per_contract"); invalid.append(raw)
        raw = study(); raw["covariance_matrix"] = []; invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                evaluate_hedge_payload(raw)

    def test_invalid_bound_money_dates_and_point_shapes_are_rejected(self):
        invalid = []
        for value in (None, True, "2", 2.0, 10**12 + 1):
            raw = study(); raw["contract"]["maximum_position"] = value; invalid.append(raw)
        for value in (None, False, 2, "Infinity", "01", "-1", "1" * 101):
            raw = study(); raw["contract"]["fee_per_contract"] = value; invalid.append(raw)
        raw = study(); raw["cash"]["end_date"] = "2052-09-11"; invalid.append(raw)
        raw = study(); raw["contract"]["collateral_post_on"] = "2052-09-13"; invalid.append(raw)
        raw = study(); raw["scenarios"][0]["variation_margin"][0]["on"] = "2052-09-07"; invalid.append(raw)
        raw = study(); raw["scenarios"][0]["variation_margin"][1]["on"] = "2052-09-09"; invalid.append(raw)
        raw = study(); raw["scenarios"][0]["variation_margin"][0]["reference_price"] = "3"; invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                evaluate_hedge_payload(raw)

    def test_discovery_template_has_no_invented_probability_margin_or_fee(self):
        raw = hedge_contract()
        self.assertIsNone(raw["confidence"])
        self.assertIsNone(raw["contract"]["fee_per_contract"])
        self.assertIsNone(raw["contract"]["initial_collateral_per_contract"])
        self.assertEqual(raw["scenarios"], [])
        with self.assertRaises(ValidationError):
            evaluate_hedge_payload(raw)

    def test_scenario_path_and_combined_cash_budgets_fail_before_calculation(self):
        raw = study()
        raw["scenarios"] = [deepcopy(raw["scenarios"][0]) for _ in range(257)]
        with self.assertRaises(ValidationError):
            evaluate_hedge_payload(raw)
        raw = study()
        raw["scenarios"][0]["variation_margin"] *= 257
        with self.assertRaises(ValidationError):
            evaluate_hedge_payload(raw)
        raw = study()
        raw["cash"]["baseline_events"] = [{"event_id": "cash:" + str(i), "on": "2052-09-08", "cash_change": "0"} for i in range(40)]
        raw["scenarios"] = [dict(deepcopy(raw["scenarios"][0]), scenario_id="scenario:" + str(i)) for i in range(220)]
        with self.assertRaises(ValidationError):
            evaluate_hedge_payload(raw)


if __name__ == "__main__":
    unittest.main()
