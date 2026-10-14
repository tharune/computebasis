"""Independent invented threshold quotes; no source, prices or venue payloads."""
from copy import deepcopy
from decimal import localcontext
import itertools
import unittest

from compute_pricing.control.market_diagnostics import DiagnosticError, evaluate_threshold_ladder
from compute_pricing.control.market_diagnostics.ladder import MAX_QUOTES, MAX_VIOLATIONS, SCHEMA


def packet(specification):
    terms = {"terms_id": "terms:sample", "underlying_id": "metric:sample", "settlement_id": "resolution:sample",
        "issuer_id": "issuer:sample", "threshold_unit": "reference-unit", "comparison": "strict_gt",
        "bound_basis": "conditional_common_pricing_measure", "alignment_evidence_id": "evidence:alignment"}
    rows = [{"quote_id": "quote:" + str(index), **{name: terms[name] for name in
        ("terms_id", "underlying_id", "settlement_id", "issuer_id", "threshold_unit", "comparison")},
        "normalization_evidence_id": "evidence:normalization", "threshold": threshold, "bid_bound": bid, "ask_bound": ask,
        "observed_at": "2032-06-01T09:00:00Z", "expires_at": "2032-06-01T11:00:00Z"}
        for index, (threshold, bid, ask) in enumerate(specification)]
    return {"schema_version": SCHEMA, "as_of": "2032-06-01T10:00:00Z", "survival_level": "0.6",
            "common_terms": terms, "quotes": rows}


class ThresholdDiagnosticsTests(unittest.TestCase):
    def test_feasible_observed_bracket_is_open_below_closed_above_without_point(self):
        output = evaluate_threshold_ladder(packet([("12", "0.8", "0.9"), ("24", "0.2", "0.4")]))
        self.assertTrue(output["conditional_envelope_feasible"])
        self.assertEqual(output["status"], "conditional_feasible")
        band = output["level_identification"]
        self.assertEqual((band["lower"], band["upper"], band["width"]), ("12", "24", "12"))
        self.assertTrue(band["lower_open"])
        self.assertTrue(band["upper_closed"])
        self.assertIsNone(band["point_estimate"])
        self.assertFalse(band["real_world_quantile_claim"])
        self.assertFalse(output["compute_price_eligible"])
        self.assertFalse(output["no_arbitrage_certificate"])
        self.assertFalse(output["execution_eligible"])
        self.assertIsNone(output["expected_underlying_value"])

    def test_nonadjacent_crossing_is_found_even_with_an_unquoted_middle(self):
        output = evaluate_threshold_ladder(packet([("-3", None, "0.3"), ("0", None, None), ("7", "0.7", None)]))
        self.assertFalse(output["conditional_envelope_feasible"])
        self.assertEqual(output["status"], "held")
        self.assertIsNone(output["level_identification"])
        self.assertEqual(output["dominance"]["violation_count"], 1)
        violation = output["dominance"]["violations"][0]
        self.assertEqual(violation["normalized_gross_gap"], "0.4")
        self.assertEqual(violation["lower_threshold_quote_id"], "quote:0")
        self.assertEqual(violation["higher_threshold_quote_id"], "quote:2")
        self.assertFalse(output["dominance"]["executable_arbitrage_claim"])

    def test_same_threshold_crossed_interval_cannot_produce_a_negative_width_band(self):
        output = evaluate_threshold_ladder(packet([("8", "0.9", "0.1")]))
        self.assertFalse(output["conditional_envelope_feasible"])
        self.assertIsNone(output["level_identification"])
        self.assertEqual(output["dominance"]["violations"][0]["code"], "same_threshold_crossing")

    def test_missing_quotes_are_universal_constraints_not_imputed_zero_prices(self):
        output = evaluate_threshold_ladder(packet([("2", "0", None), ("4", None, "1")]))
        rows = output["envelopes"]
        self.assertEqual(rows[0]["bid_bound"], "0")
        self.assertIsNone(rows[0]["ask_bound"])
        self.assertEqual(rows[0]["lower_quote_witness"], "quote:0")
        self.assertTrue(rows[0]["universal_upper_only"])
        self.assertIsNone(rows[1]["bid_bound"])
        self.assertEqual(rows[1]["upper_quote_witness"], "quote:1")
        band = output["level_identification"]
        self.assertIsNone(band["lower"])
        self.assertIsNone(band["upper"])
        self.assertTrue(band["lower_tail_unbounded"])
        self.assertTrue(band["upper_tail_unbounded"])
        self.assertIsNone(band["width"])

    def test_no_bounds_or_empty_ladder_is_held_instead_of_uninformative_readiness(self):
        for raw in (packet([]), packet([("2", None, None)])):
            output = evaluate_threshold_ladder(raw)
            self.assertEqual(output["status"], "held")
            self.assertIsNone(output["conditional_envelope_feasible"])
            self.assertIsNone(output["level_identification"])

    def test_one_sided_observed_bound_does_not_complete_the_other_tail(self):
        output = evaluate_threshold_ladder(packet([("4", "0.8", None), ("9", "0.7", None)]))
        band = output["level_identification"]
        self.assertEqual(band["lower"], "9")
        self.assertIsNone(band["upper"])
        self.assertTrue(band["upper_tail_unbounded"])
        self.assertFalse(band["bounded"])
        output = evaluate_threshold_ladder(packet([("4", None, "0.3"), ("9", None, "0.2")]))
        self.assertEqual(output["level_identification"]["upper"], "4")
        self.assertIsNone(output["level_identification"]["lower"])

    def test_level_equality_has_the_generalized_inverse_direction(self):
        output = evaluate_threshold_ladder(packet([("4", "0.6", "0.6"), ("9", "0.2", "0.4")]))
        band = output["level_identification"]
        self.assertIsNone(band["lower"])
        self.assertEqual(band["upper"], "4")
        self.assertTrue(band["lower_tail_unbounded"])

    def test_envelopes_propagate_higher_bids_lower_asks_and_keep_witnesses(self):
        output = evaluate_threshold_ladder(packet([("1", None, "0.8"), ("2", None, None), ("3", "0.7", None)]))
        self.assertEqual([row["lower"] for row in output["envelopes"]], ["0.7"] * 3)
        self.assertEqual([row["upper"] for row in output["envelopes"]], ["0.8"] * 3)
        self.assertEqual({row["lower_quote_witness"] for row in output["envelopes"]}, {"quote:2"})
        self.assertEqual({row["upper_quote_witness"] for row in output["envelopes"]}, {"quote:0"})

    def test_every_identity_dimension_and_comparison_mismatch_holds_all_arithmetic(self):
        original = packet([("1", "0.9", "1"), ("2", "0", "0.2")])
        for name in ("terms_id", "underlying_id", "settlement_id", "issuer_id", "threshold_unit", "comparison"):
            raw = deepcopy(original)
            raw["quotes"][1][name] = "different" if name != "comparison" else "inclusive_ge"
            output = evaluate_threshold_ladder(raw)
            self.assertIsNone(output["conditional_envelope_feasible"])
            self.assertEqual(output["envelopes"], [])
            self.assertTrue(any(row.get("field") == name for row in output["blockers"]))

    def test_missing_alignment_normalization_and_measure_do_not_grant_interpretation(self):
        original = packet([("1", "0.9", "1"), ("2", "0", "0.2")])
        changes = [("common_terms", "alignment_evidence_id", None), ("common_terms", "bound_basis", None),
                   ("common_terms", "bound_basis", "real_world_probability"), ("common_terms", "comparison", "inclusive_ge")]
        for group, field, value in changes:
            raw = deepcopy(original)
            raw[group][field] = value
            self.assertIsNone(evaluate_threshold_ladder(raw)["level_identification"])
        raw = deepcopy(original)
        raw["quotes"][0]["normalization_evidence_id"] = None
        self.assertIsNone(evaluate_threshold_ladder(raw)["level_identification"])

    def test_future_stale_and_exact_expiry_quotes_hold_without_renewal(self):
        original = packet([("1", "0.9", "1"), ("2", "0", "0.2")])
        for field, value in (("observed_at", "2032-06-01T10:30:00Z"), ("expires_at", "2032-06-01T10:00:00Z")):
            raw = deepcopy(original)
            raw["quotes"][0][field] = value
            self.assertIsNone(evaluate_threshold_ladder(raw)["conditional_envelope_feasible"])

    def test_malformed_numbers_null_thresholds_floats_booleans_and_nonfinite_are_rejected(self):
        for field in ("threshold", "bid_bound", "ask_bound"):
            for value in (True, False, 0.1, "NaN", "Infinity", "1e-2", "+1", "01", " " * 200):
                raw = packet([("1", "0.2", "0.3")])
                raw["quotes"][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(DiagnosticError):
                    evaluate_threshold_ladder(raw)
        raw = packet([("1", "0.2", "0.3")])
        raw["quotes"][0]["threshold"] = None
        with self.assertRaises(DiagnosticError):
            evaluate_threshold_ladder(raw)

    def test_out_of_range_probabilities_and_endpoint_levels_are_rejected(self):
        for value in ("-0.1", "1.1"):
            raw = packet([("1", value, None)])
            with self.assertRaises(DiagnosticError):
                evaluate_threshold_ladder(raw)
        for value in ("0", "1", None, False):
            raw = packet([("1", "0.2", "0.3")])
            raw["survival_level"] = value
            with self.assertRaises(DiagnosticError):
                evaluate_threshold_ladder(raw)

    def test_duplicate_numeric_thresholds_ids_unknown_fields_and_bad_times_fail(self):
        original = packet([("1", "0.9", "1"), ("2", "0", "0.2")])
        for field, value in (("threshold", "1.00"), ("quote_id", "quote:0"), ("expires_at", "2032-06-01T08:00:00Z"),
                             ("observed_at", "2032-06-01Z"), ("observed_at", "2032-06-01T09:00:00+00:00")):
            raw = deepcopy(original)
            raw["quotes"][1][field] = value
            with self.assertRaises(DiagnosticError):
                evaluate_threshold_ladder(raw)
        original["quotes"][0]["unknown"] = "not silently ignored"
        with self.assertRaises(DiagnosticError):
            evaluate_threshold_ladder(original)

    def test_arithmetic_stays_exact_under_low_ambient_precision(self):
        raw = packet([("0.00000000000000000000000000001", "0.8000000000000000000000000001", "0.9"),
                      ("0.00000000000000000000000000003", "0.2", "0.4")])
        with localcontext() as context:
            context.prec = 2
            output = evaluate_threshold_ladder(raw)
        self.assertEqual(output["envelopes"][0]["lower"], "0.8000000000000000000000000001")
        self.assertEqual(output["level_identification"]["width"], "0.00000000000000000000000000002")

    def test_order_invariance_no_input_alias_and_bounded_violation_output(self):
        raw = packet([("1", "0.9", "1"), ("2", "0.4", "0.5"), ("3", "0.1", "0.2")])
        original = deepcopy(raw)
        expected = evaluate_threshold_ladder(raw)
        for permutation in itertools.permutations(raw["quotes"]):
            changed = deepcopy(raw)
            changed["quotes"] = list(permutation)
            self.assertEqual(evaluate_threshold_ladder(changed), expected)
        expected["envelopes"][0]["bid_bound"] = "mutated"
        self.assertEqual(raw, original)
        raw = packet([(str(index), "0.8", "0.2") for index in range(12)])
        output = evaluate_threshold_ladder(raw)
        self.assertEqual(len(output["dominance"]["violations"]), MAX_VIOLATIONS)
        self.assertTrue(output["dominance"]["violations_truncated"])
        self.assertGreater(output["dominance"]["violation_count"], MAX_VIOLATIONS)

    def test_oversized_ladder_and_invalid_metadata_types_fail_with_safe_codes(self):
        raw = packet([(str(index), None, "0.2") for index in range(MAX_QUOTES + 1)])
        with self.assertRaises(DiagnosticError) as error:
            evaluate_threshold_ladder(raw)
        self.assertEqual(str(error.exception), "bounded_diagnostic_quotes_required")
        raw = packet([("1", "0.2", "0.3")])
        raw["common_terms"]["issuer_id"] = True
        with self.assertRaises(DiagnosticError):
            evaluate_threshold_ladder(raw)


if __name__ == "__main__":
    unittest.main()
