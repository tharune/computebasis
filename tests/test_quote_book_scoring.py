"""Independently invented public scenarios; no workbook or vendor fixtures."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from compute_pricing.control.domain import ValidationError
from compute_pricing.control.quote_book.scoring import (
    ASSUMPTIONS, CATEGORIES, grade_for, quality_score, quote_economics, validate_policy,
)


def quote():
    return {"gpu": "invented-test-device", "gpus_per_node": 2, "nodes": 2, "price": "2", "months": 12,
        "down_payment": "0.25", "payment_days": 7, "location": "Invented Test Site", "country": "CA",
        "interconnect": "invented-link", "cooling": "invented-air", "moq": 1, "lead_weeks": 0,
        "available": "2061-01-01", "expires": "2061-01-03", "currency": "USD", "price_unit": "gpu_hour",
        "synthetic": True}


def economics(values=None, *, grade="A", reference="3", assumptions=None, as_of="2061-01-01"):
    return quote_economics(quote() if values is None else values, grade=grade, reference=reference,
                           as_of=as_of, assumptions=assumptions)


class PublicScenarioScoringTests(unittest.TestCase):
    def test_weighted_ratings_manual_oracle_and_no_implicit_unknown_grade(self):
        ratings = {"certification": 4, "dc_tier": 2, "sla": 3, "delivery": 1, "credit": 0, "responsiveness": 4}
        self.assertEqual(quality_score(ratings), Decimal("57.5"))
        self.assertEqual(grade_for(quality_score(ratings))[0], "D")
        for value, score, grade in ((0, "0", "D"), (3, "75", "B"), (4, "100", "A")):
            self.assertEqual(quality_score({key: value for key in CATEGORIES}), Decimal(score))
            self.assertEqual(grade_for(Decimal(score))[0], grade)
        ratings["credit"] = None
        with self.assertRaises(ValidationError): quality_score(ratings)
        result = economics(grade=None)
        self.assertIsNone(result["grade"])
        self.assertIsNone(result["failure_probability"])
        self.assertIsNone(result["risk_adjusted_scorecard"])
        self.assertFalse(result["eligible"])
        self.assertIn("grade", result["missing"])

    def test_grade_thresholds_are_explicit_and_boundary_inclusive(self):
        for score, grade in (("100", "A"), ("90", "A"), ("89.999", "B"), ("75", "B"),
                             ("74.999", "C"), ("60", "C"), ("59.999", "D"), ("0", "D")):
            self.assertEqual(grade_for(score)[0], grade)
        self.assertEqual(grade_for(90), ("A", Decimal("0.005")))
        with self.assertRaises(ValidationError): grade_for("100.1")

    def test_complete_policy_override_propagates_weights_and_premium_without_hidden_default(self):
        policy = validate_policy()
        policy["weights"] = {key: "1" if key == "credit" else "0" for key in CATEGORIES}
        policy["grade_premiums"]["B"] = "0.123"
        ratings = {key: 0 for key in CATEGORIES}; ratings["credit"] = 3
        score = quality_score(ratings, policy)
        self.assertEqual(score, Decimal("75"))
        grade = grade_for(score, policy)
        self.assertEqual(grade, ("B", Decimal("0.123")))
        result = economics(grade=grade)
        self.assertEqual(result["scorecard_charge"], Decimal("0.246"))
        self.assertEqual(result["risk_adjusted_scorecard"], Decimal("2.2885"))

    def test_year_contract_cash_finance_and_alternative_loss_manual_oracle(self):
        result = economics()
        self.assertEqual(result["gpus"], 4)
        self.assertEqual(result["term_end"], "2062-01-01")
        self.assertEqual(result["term_days"], 365)
        self.assertEqual(result["term_hours"], Decimal("8760"))
        self.assertEqual(result["contract_value"], Decimal("70080"))
        self.assertEqual(result["down_payment_usd"], Decimal("17520"))
        self.assertEqual(result["financing_cost"], Decimal("1489.2"))
        self.assertEqual(result["financing_cost_per_gpu_hour"], Decimal("0.0425"))
        self.assertEqual(result["scorecard_charge"], Decimal("0.01"))
        # Unrecovered deposit11388 + full-term replacement increment35040.
        self.assertEqual(result["loss_exposure_usd"], Decimal("46428"))
        self.assertEqual(result["failure_probability"], Decimal("0.008"))
        self.assertEqual(result["expected_loss_usd"], Decimal("371.424"))
        self.assertEqual(result["exposure_charge"], Decimal("0.0106"))
        self.assertEqual(result["risk_adjusted_scorecard"], Decimal("2.0525"))
        self.assertEqual(result["risk_adjusted"], Decimal("2.0531"))
        self.assertTrue(result["eligible"])
        self.assertTrue(result["simulated"])
        self.assertFalse(result["firm_price_eligible"])
        self.assertFalse(result["source_evidence_eligible"])
        self.assertFalse(result["execution_enabled"])
        self.assertIn("uncalibrated", result["assumptions"]["label"])

    def test_month_end_and_leap_calendar_hours_are_not_a_fixed_month(self):
        for start, months, end, days in (
            ("2060-01-31", 1, "2060-02-29", 29), ("2060-01-31", 2, "2060-03-31", 60),
            ("2061-01-31", 1, "2061-02-28", 28), ("2060-01-01", 12, "2061-01-01", 366),
        ):
            values = quote(); values.update(available=start, months=months, expires="2063-01-01")
            result = economics(values, as_of=start)
            self.assertEqual(result["term_end"], end)
            self.assertEqual(result["term_days"], days)
            self.assertEqual(result["term_hours"], Decimal(days * 24))
            self.assertEqual(result["contract_value"], Decimal(4 * 2 * days * 24))
        leap = quote(); leap.update(available="2060-01-01", expires="2063-01-01")
        probability = economics(leap, as_of="2060-01-01")["failure_probability"]
        self.assertGreater(probability, Decimal("0.008"))
        self.assertLess(probability, Decimal("0.0081"))

    def test_unknown_deposit_and_reference_hold_while_known_zero_deposit_is_zero(self):
        values = quote(); values["down_payment"] = None
        result = economics(values)
        for field in ("down_payment_usd", "financing_cost", "loss_exposure_usd", "risk_adjusted"):
            self.assertIsNone(result[field])
        self.assertFalse(result["eligible"])
        self.assertIn("down_payment", result["missing"])
        values["down_payment"] = "0"
        result = economics(values)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["financing_cost"], 0)
        self.assertEqual(result["down_payment_usd"], 0)
        self.assertEqual(result["exposure_charge"], Decimal("0.008"))
        no_reference = economics(reference=None)
        self.assertIsNone(no_reference["reference"])
        self.assertIsNone(no_reference["discount_to_reference"])
        self.assertIsNone(no_reference["replacement_premium_usd"])
        self.assertIsNone(no_reference["risk_adjusted"])
        self.assertEqual(no_reference["risk_adjusted_scorecard"], Decimal("2.0525"))
        self.assertIn("reference", no_reference["missing"])
        self.assertFalse(no_reference["eligible"])

    def test_recovery_only_offsets_deposit_and_probability_zero_is_known(self):
        low, high = deepcopy(ASSUMPTIONS), deepcopy(ASSUMPTIONS)
        low["recovery_fraction"], high["recovery_fraction"] = "0", "1"
        unrecovered, recovered = economics(assumptions=low), economics(assumptions=high)
        self.assertEqual(unrecovered["loss_exposure_usd"], Decimal("52560"))
        self.assertEqual(recovered["loss_exposure_usd"], Decimal("35040"))
        self.assertEqual(recovered["exposure_charge"], Decimal("0.008"))
        self.assertEqual(unrecovered["financing_cost"], recovered["financing_cost"])
        self.assertEqual(unrecovered["scorecard_charge"], recovered["scorecard_charge"])
        high["annual_failure_probability"]["A"] = "0"
        result = economics(assumptions=high)
        self.assertEqual(result["failure_probability"], 0)
        self.assertEqual(result["expected_loss_usd"], 0)
        self.assertEqual(result["risk_adjusted"], Decimal("2.0425"))

    def test_price_and_deposit_knobs_change_actual_terms_and_charges(self):
        baseline = economics()
        values = quote(); values["price"] = "3"
        expensive = economics(values)
        self.assertEqual(expensive["contract_value"], Decimal("105120"))
        self.assertEqual(expensive["replacement_premium_usd"], 0)
        self.assertEqual(expensive["discount_to_reference"], 0)
        self.assertGreater(expensive["financing_cost"], baseline["financing_cost"])
        values = quote(); values["down_payment"] = "0.5"
        funded = economics(values)
        self.assertEqual(funded["down_payment_usd"], baseline["down_payment_usd"] * 2)
        self.assertEqual(funded["financing_cost"], baseline["financing_cost"] * 2)
        self.assertGreater(funded["exposure_charge"], baseline["exposure_charge"])

    def test_operational_unknown_expired_unit_and_zero_capacity_holds(self):
        for field in ("expires", "available", "currency", "price_unit", "interconnect", "cooling"):
            values = quote(); values[field] = None
            result = economics(values)
            self.assertFalse(result["eligible"])
            self.assertIn(field, result["missing"])
        values = quote(); values.update(nodes=0, active=False)
        result = economics(values)
        self.assertEqual(result["gpus"], 0)
        self.assertIsNone(result["risk_adjusted"])
        self.assertFalse(result["eligible"])
        self.assertIn("no_available_capacity", result["ineligible_reasons"])
        values = quote(); values["expires"] = "2061-01-01"
        self.assertIn("simulated_quote_expired", economics(values)["ineligible_reasons"])
        values = quote(); values["currency"] = "EUR"
        self.assertIn("unsupported_currency_no_implicit_fx", economics(values)["ineligible_reasons"])
        values = quote(); values["price_unit"] = "node_hour"
        self.assertIn("unsupported_price_unit_no_implicit_conversion", economics(values)["ineligible_reasons"])

    def test_no_unit_conversion_is_used_to_invent_economics(self):
        for field, value in (("currency", None), ("currency", "EUR"), ("price_unit", None),
                             ("price_unit", "node_hour")):
            values = quote(); values[field] = value
            result = economics(values)
            self.assertFalse(result["eligible"])
            for monetary in ("contract_value", "down_payment_usd", "financing_cost", "scorecard_charge",
                             "replacement_premium_usd", "risk_adjusted", "discount_to_reference"):
                self.assertIsNone(result[monetary])
            self.assertFalse(result["source_evidence_eligible"])
            self.assertFalse(result["firm_price_eligible"])

    def test_invalid_policy_shapes_scales_weights_and_nonfinite_are_rejected(self):
        for mutation in (
            lambda p: p.update(undocumented_adjustment="0.1"), lambda p: p.pop("weights"),
            lambda p: p["weights"].update(credit="0.3"),
            lambda p: p["weights"].update(credit="NaN"),
            lambda p: p["weights"].update(credit=0.2),
            lambda p: p["grade_bands"].update(A="60"),
            lambda p: p["grade_bands"].update(D="1"),
            lambda p: p["grade_premiums"].update(A="1.1"),
            lambda p: p["rating_scale"].update(higher_is_stronger=False),
            lambda p: p["rating_scale"].update(minimum=False),
        ):
            selected = validate_policy(); mutation(selected)
            with self.assertRaises(ValidationError): validate_policy(selected)
        with self.assertRaises(ValidationError): quality_score({key: True for key in CATEGORIES})

    def test_invalid_assumptions_financial_encoding_and_dates_fail(self):
        for field, value in (("price", "NaN"), ("price", "Infinity"), ("price", 2.0),
                             ("price", "2e0"), ("down_payment", "25"), ("gpus_per_node", 1.5),
                             ("available", "2061-02-29"), ("months", 0)):
            values = quote(); values[field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError): economics(values)
        for mutation in (
            lambda p: p.update(recovery_fraction="1.01"),
            lambda p: p.update(deposit_apr=None),
            lambda p: p.update(deposit_apr=Decimal("NaN")),
            lambda p: p["annual_failure_probability"].update(A="1.01"),
            lambda p: p.update(unregistered_default_loss="0"),
        ):
            selected = deepcopy(ASSUMPTIONS); mutation(selected)
            with self.assertRaises(ValidationError): economics(assumptions=selected)

    def test_inputs_defaults_and_decimal_context_are_detached(self):
        values = quote(); original = deepcopy(values)
        selected = deepcopy(ASSUMPTIONS)
        result = economics(values, assumptions=selected)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(economics(values, assumptions=selected), result)
            self.assertEqual(quality_score({key: 4 for key in CATEGORIES}), Decimal("100"))
        self.assertEqual(values, original)
        result["assumptions"]["annual_failure_probability"]["A"] = Decimal("1")
        self.assertEqual(selected, ASSUMPTIONS)
        fresh = validate_policy(); fresh["weights"]["credit"] = "0"
        self.assertEqual(validate_policy()["weights"]["credit"], "0.2")

    def test_known_zero_reference_remains_distinct_from_unknown_reference(self):
        result = economics(reference="0")
        self.assertEqual(result["reference"], 0)
        self.assertNotIn("reference", result["missing"])
        self.assertIsNone(result["discount_to_reference"])
        self.assertFalse(result["eligible"])
        self.assertIn("positive_reference_required_for_relative_comparison", result["ineligible_reasons"])


if __name__ == "__main__":
    unittest.main()
