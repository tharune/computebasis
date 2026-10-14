"""Independent adversarial checks of units, sell floors and dated funding."""
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.pricing import evaluate_pricing
from test_pricing_v1 import pricing_packet


class PricingReviewV1Tests(unittest.TestCase):
    def test_explicit_cost_currency_cannot_be_silently_treated_as_inherited(self):
        packet = pricing_packet()
        packet["commercial"]["costs"][0]["currency"] = "EUR"
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)
        packet["commercial"]["costs"][0]["currency"] = "USD"
        self.assertEqual(evaluate_pricing(packet)["bid"]["submitted_limit"], "0.93")

    def test_sell_tick_meets_declared_gross_billings_margin(self):
        packet = pricing_packet()
        result = evaluate_pricing(packet)
        with localcontext() as context:
            context.prec = 100
            ask = Decimal(result["ask"]["sell_floor_tick"])
            def margin_at(rate):
                billed = rate * Decimal(8)
                collected = billed * Decimal("0.9")
                profit = collected - collected * Decimal("0.02") - billed * Decimal("0.01") - Decimal("12.4")
                return profit / billed
            self.assertGreaterEqual(margin_at(ask), Decimal("0.1"))
            self.assertLess(margin_at(ask - Decimal("0.01")), Decimal("0.1"))

    def test_collected_margin_uses_collected_denominator_and_fees_once(self):
        packet = pricing_packet()
        packet["commercial"]["margin_basis"] = "collected_revenue"
        result = evaluate_pricing(packet)
        ask = Decimal(result["ask"]["sell_floor_tick"])
        billed = ask * 8
        collected = billed * Decimal("0.9")
        profit = collected - collected * Decimal("0.02") - billed * Decimal("0.01") - Decimal("12.4")
        self.assertGreaterEqual(profit / collected, Decimal("0.1"))
        self.assertEqual(result["economics"]["margin_denominator"], "21.6")

    def test_supplier_ask_cash_is_distinct_from_feasible_our_bid(self):
        result = evaluate_pricing(pricing_packet())
        cash = result["cash_constraint"]
        self.assertEqual(cash["maximum_purchase_tick"], "0.93")
        self.assertGreaterEqual(Decimal(cash["minimum_free_cash"]), 0)
        self.assertFalse(cash["supplied_ask_cash_feasible"])
        self.assertEqual(cash["supplied_ask_minimum_free_cash"], "-0.672")
        self.assertEqual(cash["supplied_ask_required_extra_cash"], "0.672")
        self.assertFalse(result["firm_price_eligible"])
        self.assertFalse(result["executable"])

    def test_same_day_receipt_after_payment_does_not_hide_earlier_trough(self):
        packet = pricing_packet()
        for event in packet["cash_template"]["schedule"]["events"]:
            event["on"] = "2026-01-01"
        result = evaluate_pricing(packet)
        self.assertEqual(result["bid"]["submitted_limit"], "0.93")
        self.assertEqual(result["cash_constraint"]["minimum_free_cash"], "0.028")

    def test_nonfinite_unmodeled_metadata_never_returns_a_price_snapshot(self):
        for extra in (float("nan"), float("inf")):
            packet = pricing_packet()
            packet["commercial"]["extensions"] = {"future_factor": extra}
            with self.subTest(extra=extra), self.assertRaises((ValueError, TypeError)):
                evaluate_pricing(packet)

    def test_unmodeled_terms_are_visible_and_do_not_silently_change_formula(self):
        packet = pricing_packet()
        packet["commercial"]["future_privacy_factor"] = "0.2"
        result = evaluate_pricing(packet)
        self.assertIn("future_privacy_factor", result["unused_commercial_fields"])
        self.assertEqual(result["bid"]["submitted_limit"], "0.93")
        self.assertFalse(result["firm_price_eligible"])

    def test_partial_node_procurement_is_not_assumed(self):
        packet = pricing_packet()
        packet["commercial"]["exclusive_node_gpu_count"] = "4"
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)

    def test_non_monotone_inflow_and_incomplete_financial_reconciliation_reject(self):
        packet = pricing_packet()
        packet["cash_template"]["purchase_coefficients"]["buyer-pay"] = "1"
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)
        packet = pricing_packet()
        packet["cash_template"]["schedule"]["events"][2]["amount"] = "2.671"
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)

    def test_sub_tick_feasibility_is_held_and_no_positive_tick_is_invented(self):
        packet = pricing_packet()
        packet["commercial"]["stress_price_cap"] = "0.009"
        result = evaluate_pricing(packet)
        self.assertEqual(result["status"], "held")
        self.assertIn("no_positive_feasible_purchase_price", result["hold_reasons"])


if __name__ == "__main__":
    unittest.main()
