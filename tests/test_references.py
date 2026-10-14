"""Independent synthetic examples for the generic arithmetic references."""
import copy
import unittest
from decimal import Decimal as D
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from references.cashflow_reference import calculate as cashflow
from references.pricing_reference import calculate as pricing


def pricing_input():
    return {
        "kind": "illustrative_pricing_fixture", "source_is_mock": True,
        "currency": "USD", "unit": "USD/GPU-hour", "collection_share": "1",
        "price_independent_costs": True,
        "observations": [
            {"id": "demo-alpha", "kind": "listing_ask", "unit": "USD/GPU-hour", "price": "1.10", "weight": "1"},
            {"id": "demo-beta", "kind": "firm_supplier_rfq", "unit": "USD/GPU-hour", "price": "1.40", "weight": "2"},
            {"id": "demo-gamma", "kind": "confirmed_rental_trade", "unit": "USD/GPU-hour", "price": "1.70", "weight": "1"},
        ],
        "target_region_multiplier": "1.05", "market_cap_policy": "localized_mark_for_fixture",
        "gross_buyer_rate_per_gpu_hour": "2.40", "distribution_fee_fraction_of_gross_revenue": "0.04",
        "required_economic_margin_fraction_of_gross_revenue": "0.12",
        "nonpurchase_expected_costs_per_gpu_hour": {"operations": "0.09", "expected_loss": "0.04"},
        "policy_capital_charge_per_gpu_hour": "0.02", "assumed_stress_bid_cap_per_gpu_hour": "1.32",
        "liquidity_cap_scope": "signing_only", "usable_signing_funds_before_buffer": "420",
        "required_signing_buffer": "24", "supplier_advance_fraction_of_full_horizon": "0.25",
        "contractual_billed_gpu_hours": "1200", "observed_supplier_ask_per_gpu_hour": "1.25",
        "tick_size_per_gpu_hour": "0.02", "assumptions": ["Independent synthetic arithmetic example."],
    }


def cashflow_input():
    return {
        "kind": "illustrative_planning_fixture", "source_is_mock": True, "currency": "USD",
        "supplier_advance_treatment": "credited_evenly", "forward_advance_restricted_until_delivery": True,
        "supply_nodes": 3, "gpus_per_node": 2, "months": 4,
        "wholesale_nodes": 1, "forward_nodes": 1, "forward_start_month": 3, "forward_months": 2,
        "hours_per_month": "672", "supply_rate_per_gpu_hour": "0.85",
        "supplier_advance_fraction": "0.10", "supplier_advance_basis": "full_term",
        "wholesale_rate_per_gpu_hour": "1.20", "wholesale_advance_fraction": "0.20",
        "wholesale_advance_permitted_use": True, "forward_rate_per_gpu_hour": "1.45",
        "forward_advance_fraction": "0.35", "inference_paid_utilization": "0.55",
        "inference_revenue_equivalent_per_occupied_gpu_hour": "2.10",
        "distribution_cost_fraction_of_earned_revenue": "0.04",
        "monthly_operations_cost": "17", "treasury_buffer": "120",
        "excluded_costs": ["Independent synthetic example; no production policy calibrated."],
        "timing_assumption": "Monthly simplification with explicit input hours.",
    }


class PublicReferenceTests(unittest.TestCase):
    def test_weighted_index_caps_and_tick(self):
        result = pricing(pricing_input())
        self.assertEqual(result["benchmark"], D("1.40"))
        self.assertEqual(result["localized_mark"], D("1.47"))
        self.assertEqual(result["reservation_bid"], D("1.32"))
        self.assertEqual(set(result["binding_constraints"]), {"stress", "signing_liquidity_only"})
        self.assertEqual(result["sell_floor_tick"], D("1.68"))
        self.assertFalse(result["executable"])

    def test_pricing_changes_when_observations_costs_or_policy_change(self):
        baseline = pricing(pricing_input())
        data = pricing_input()
        data["observations"][0]["price"] = "0.70"
        self.assertLess(pricing(data)["benchmark"], baseline["benchmark"])
        data = pricing_input()
        data["nonpurchase_expected_costs_per_gpu_hour"]["additional_cost"] = "0.75"
        self.assertLess(pricing(data)["reservation_bid"], baseline["reservation_bid"])
        self.assertGreater(pricing(data)["sell_floor_tick"], baseline["sell_floor_tick"])

    def test_nonfinite_prices_and_unit_mixing_rejected(self):
        for value in ("NaN", "Infinity", "-1", 1.0):
            data = pricing_input()
            data["observations"][0]["price"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                pricing(data)
        data = pricing_input()
        data["observations"][0]["unit"] = "USD/token"
        with self.assertRaises(ValueError):
            pricing(data)

    def test_cashflows_reconcile_and_prepaid_cash_stays_restricted(self):
        result = cashflow(cashflow_input())
        self.assertEqual(result["rows"][1]["contribution"], D("1084.5424"))
        self.assertEqual(result["rows"][3]["contribution"], D("1465.1632"))
        self.assertEqual(result["total_operating_contribution_before_excluded_costs"], D("5099.4112"))
        self.assertEqual(result["required_opening_funding_including_buffer"], D("200.64"))
        self.assertEqual(result["rows"][0]["restricted_cash"], D("1364.16"))
        self.assertEqual(result["rows"][-1]["buyer_advance_liability"], 0)
        self.assertEqual(sum(row["net_cash_flow"] for row in result["rows"]), result["lifetime_cash_before_financing"])

    def test_calendar_hours_are_inputs_and_capacity_bounds_hold(self):
        baseline = cashflow(cashflow_input())
        data = cashflow_input()
        data["hours_per_month"] = "720"
        self.assertNotEqual(cashflow(data)["rows"][1]["supply_cost"], baseline["rows"][1]["supply_cost"])
        for key, value in (("forward_nodes", 3), ("forward_start_month", 4)):
            data = copy.deepcopy(cashflow_input())
            data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                cashflow(data)


if __name__ == "__main__":
    unittest.main()
