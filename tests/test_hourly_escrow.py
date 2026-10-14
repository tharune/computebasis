"""Independently invented hourly principal, service and yield accounting cases."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from compute_pricing.control.demo_pricing.escrow import evaluate_escrow, escrow_contract


def example(hours=2):
    start = datetime(2035, 3, 14, tzinfo=timezone.utc)
    return {
        "schema_version": "hourly-escrow/1.0", "delivery_start": start.isoformat().replace("+00:00", "Z"),
        "delivery_end": (start + timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
        "gpu_count": 1, "service_basis": "delivered", "hourly_service_fractions": ["1"] * hours,
        "buyer_rate": "10", "provider_rate": "7", "prefunded_principal": str(10 * hours),
        "asset_kind": "bank_deposit", "asset_unit": "USD", "asset_price_usd": "1",
        "liquidity": "liquid", "depeg_status": "not_applicable", "annual_yield_apr": "0.876",
        "yield_shares": {"provider": "0", "broker": "1", "buyer": "0"},
        "yield_access": "hourly_withdrawable", "release_authorized": True, "refund_at_end": True,
        "entitlement_basis": "Invented hourly yield entitlement assertion for this scenario",
        "opening_broker_cash": "0", "minimum_broker_cash": "0", "broker_operating_cost_per_hour": "0",
        "provider_risk_grade": "D", "buffer_hours": 1, "collateral_fraction": "0.2",
    }


class HourlyEscrowTests(unittest.TestCase):
    def test_hourly_yield_uses_only_opening_unreleased_principal_without_compounding(self):
        result = evaluate_escrow(example())
        self.assertEqual(result["yield"]["total_accrued_asset_units"], "0.003")
        rows = result["chart"]["rows"]
        self.assertEqual([row["opening_restricted_principal_asset_units"] for row in rows], ["20", "10"])
        self.assertEqual([row["yield_accrued_asset_units"] for row in rows], ["0.002", "0.001"])
        self.assertEqual(result["settlement"]["provider_service_paid_usd"], "14")
        self.assertEqual(result["settlement"]["provider_service_owed_usd"], "0")
        self.assertEqual(result["broker"]["ending_available_cash_usd"], "6.003")
        self.assertEqual(result["settlement"]["restricted_principal_remaining_asset_units"], "0")
        self.assertEqual(result["prefunding"]["available_broker_funding_from_unearned_principal_usd"], "0")

    def test_outage_vests_only_earned_service_and_refunds_unearned_principal(self):
        payload = example()
        payload["service_basis"] = "available_sla"
        payload["hourly_service_fractions"] = ["1", "0"]
        result = evaluate_escrow(payload)
        self.assertEqual(result["service"]["recognized_gpu_hours"], "1")
        self.assertEqual(result["settlement"]["buyer_service_earned_usd"], "10")
        self.assertEqual(result["settlement"]["provider_service_earned_usd"], "7")
        self.assertEqual(result["settlement"]["refundable_principal_before_terminal_refund_asset_units"], "10")
        self.assertEqual(result["settlement"]["terminal_buyer_refund_asset_units"], "10")
        self.assertEqual(result["settlement"]["unearned_liability_remaining_asset_units"], "0")
        self.assertEqual(result["broker"]["ending_available_cash_usd"], "3.003")
        self.assertEqual(result["risk_proposal"]["buffer_usd"], "7")
        self.assertEqual(result["risk_proposal"]["collateral_usd"], "2.8")
        self.assertFalse(result["risk_proposal"]["buffer_added_to_available_cash"])

    def test_accrued_yield_is_income_entitlement_not_automatically_available_cash(self):
        payload = example()
        payload["yield_access"] = "accrued_only"
        result = evaluate_escrow(payload)
        self.assertEqual(result["yield"]["broker_economic_entitlement_usd"], "0.003")
        self.assertEqual(result["yield"]["broker_cash_received_usd"], "0")
        self.assertEqual(result["yield"]["unpaid_entitlement_asset_units_by_party"]["broker"], "0.003")
        self.assertEqual(result["broker"]["ending_available_cash_usd"], "6")
        self.assertEqual(result["broker"]["economic_margin_with_yield_usd"], "6.003")

    def test_yield_party_shares_reconcile_without_changing_provider_service_earnings(self):
        payload = example()
        payload["yield_shares"] = {"provider": "0.25", "broker": "0.5", "buyer": "0.25"}
        result = evaluate_escrow(payload)
        accrued = result["yield"]["accrued_asset_units_by_party"]
        self.assertEqual(accrued, {"provider": "0.00075", "broker": "0.0015", "buyer": "0.00075"})
        self.assertEqual(sum(map(Decimal, accrued.values())), Decimal("0.003"))
        self.assertEqual(result["yield"]["paid_asset_units_by_party"], accrued)
        self.assertEqual(result["settlement"]["provider_service_earned_usd"], "14")
        self.assertEqual(result["broker"]["ending_available_cash_usd"], "6.0015")

    def test_native_stable_units_use_the_declared_mark_instead_of_assuming_parity(self):
        payload = example()
        payload.update(asset_kind="stable_asset", asset_unit="DEMO-STABLE", asset_price_usd="0.5",
                       depeg_status="normal", prefunded_principal="40")
        result = evaluate_escrow(payload)
        self.assertEqual(result["prefunding"]["declared_value_usd"], "20")
        self.assertEqual(result["settlement"]["principal_released_asset_units"], "40")
        self.assertEqual(result["yield"]["total_accrued_asset_units"], "0.006")
        self.assertEqual(result["yield"]["broker_cash_received_usd"], "0.003")
        self.assertEqual(result["broker"]["ending_available_cash_usd"], "6.003")
        self.assertFalse(result["asset"]["stable_parity_verified"])

    def test_depeg_holds_principal_and_yield_and_keeps_unpaid_provider_obligations(self):
        payload = example()
        payload.update(asset_kind="stable_asset", asset_unit="DEMO-STABLE", asset_price_usd="0.8", depeg_status="depegged")
        result = evaluate_escrow(payload)
        self.assertEqual(result["prefunding"]["shortfall_usd"], "4")
        self.assertEqual(result["settlement"]["provider_service_owed_usd"], "14")
        self.assertEqual(result["settlement"]["principal_released_asset_units"], "0")
        self.assertEqual(result["settlement"]["restricted_principal_remaining_asset_units"], "20")
        self.assertEqual(result["yield"]["broker_cash_received_usd"], "0")
        self.assertEqual(result["yield"]["total_accrued_asset_units"], "0.004")
        self.assertEqual(result["broker"]["required_extra_cash_for_all_obligations_and_floor_usd"], "14")
        self.assertFalse(result["broker"]["scenario_cash_floor_feasible"])

    def test_illiquid_earned_and_unearned_principal_remain_restricted(self):
        payload = example()
        payload.update(liquidity="illiquid", hourly_service_fractions=["1", "0"])
        result = evaluate_escrow(payload)
        self.assertEqual(result["settlement"]["earned_unreleased_principal_asset_units"], "10")
        self.assertEqual(result["settlement"]["unearned_liability_remaining_asset_units"], "10")
        self.assertEqual(result["settlement"]["terminal_buyer_refund_asset_units"], "0")
        self.assertEqual(result["settlement"]["provider_service_owed_usd"], "7")
        self.assertFalse(result["broker"]["scenario_cash_floor_feasible"])

    def test_unknown_mark_and_entitlements_stay_unknown_instead_of_becoming_dollars(self):
        payload = example()
        payload.update(asset_kind="stable_asset", asset_unit="DEMO-STABLE", asset_price_usd=None,
                       depeg_status="unknown", liquidity="unknown", release_authorized=None, entitlement_basis=None)
        result = evaluate_escrow(payload)
        self.assertIsNone(result["prefunding"]["full_prefunding_declared"])
        self.assertIsNone(result["settlement"]["unearned_liability_remaining_usd"])
        self.assertIsNone(result["settlement"]["unearned_liability_remaining_asset_units"])
        self.assertIsNone(result["broker"]["scenario_cash_floor_feasible"])
        self.assertIsNone(result["yield"]["broker_economic_entitlement_usd"])
        self.assertEqual(result["settlement"]["restricted_principal_remaining_asset_units"], "20")
        self.assertEqual(result["broker"]["ending_available_cash_usd"], "0")
        self.assertFalse(result["legal_entitlements_verified"])

    def test_insufficient_prefunding_is_a_real_scenario_shortfall_not_available_credit(self):
        payload = example()
        payload.update(prefunded_principal="10", annual_yield_apr="0")
        result = evaluate_escrow(payload)
        self.assertFalse(result["prefunding"]["full_prefunding_declared"])
        self.assertEqual(result["prefunding"]["shortfall_usd"], "10")
        self.assertEqual(result["settlement"]["buyer_service_receivable_usd"], "10")
        self.assertEqual(result["settlement"]["provider_service_paid_usd"], "10")
        self.assertEqual(result["settlement"]["provider_service_owed_usd"], "4")
        self.assertEqual(result["broker"]["required_extra_cash_for_all_obligations_and_floor_usd"], "4")
        self.assertFalse(result["broker"]["scenario_cash_floor_feasible"])

    def test_provider_cost_above_buyer_rate_cannot_create_cash_or_hide_owed_amounts(self):
        payload = example()
        payload.update(provider_rate="15", annual_yield_apr="0")
        result = evaluate_escrow(payload)
        self.assertEqual(result["settlement"]["broker_service_economic_margin_usd"], "-10")
        self.assertEqual(result["settlement"]["provider_service_paid_usd"], "20")
        self.assertEqual(result["settlement"]["provider_service_owed_usd"], "10")
        self.assertEqual(result["broker"]["minimum_cash_if_all_obligations_paid_usd"], "-10")
        self.assertEqual(result["broker"]["required_extra_cash_for_all_obligations_and_floor_usd"], "10")
        self.assertEqual(result["broker"]["ending_available_cash_usd"], "0")

    def test_all_hours_contribute_to_totals_while_chart_rows_are_bounded(self):
        payload = example(25)
        result = evaluate_escrow(payload)
        self.assertEqual(result["yield"]["total_accrued_asset_units"], "0.325")
        self.assertEqual(result["broker"]["ending_available_cash_usd"], "75.325")
        self.assertEqual(result["chart"]["rows_returned"], 24)
        self.assertEqual(result["chart"]["rows"][0]["hour"], 1)
        self.assertEqual(result["chart"]["rows"][-1]["hour"], 25)
        self.assertTrue(result["chart"]["sampled"])
        maximum = example(2160)
        maximum["annual_yield_apr"] = "0"
        self.assertEqual(evaluate_escrow(maximum)["settlement"]["provider_service_earned_usd"], "15120")

    def test_zero_values_are_known_while_false_and_null_authorizations_differ(self):
        payload = example()
        payload.update(annual_yield_apr="0", hourly_service_fractions=["0", "0"], refund_at_end=None)
        result = evaluate_escrow(payload)
        self.assertEqual(result["yield"]["total_accrued_asset_units"], "0")
        self.assertEqual(result["settlement"]["provider_service_owed_usd"], "0")
        self.assertEqual(result["settlement"]["unearned_liability_remaining_asset_units"], "20")
        self.assertIsNone(result["settlement"]["refund_at_end"])
        payload["release_authorized"] = False
        self.assertFalse(evaluate_escrow(payload)["broker"]["scenario_cash_floor_feasible"])
        payload["release_authorized"] = None
        self.assertIsNone(evaluate_escrow(payload)["broker"]["scenario_cash_floor_feasible"])

    def test_sampled_cumulative_points_reconcile_to_full_ledger_not_sample_row_sums(self):
        result = evaluate_escrow(example(25))
        rows = result["chart"]["rows"]
        self.assertEqual(rows[0]["cumulative_provider_service_paid_usd"], "7")
        self.assertEqual(rows[-1]["cumulative_provider_service_paid_usd"], result["settlement"]["provider_service_paid_usd"])
        self.assertEqual(rows[-1]["cumulative_buyer_service_earned_usd"], result["settlement"]["buyer_service_earned_usd"])
        self.assertEqual(rows[-1]["cumulative_broker_yield_cash_usd"], result["yield"]["broker_cash_received_usd"])
        self.assertNotEqual(sum(Decimal(row["provider_service_paid_usd"]) for row in rows),
                            Decimal(rows[-1]["cumulative_provider_service_paid_usd"]))
        for row in rows:
            self.assertEqual(Decimal(row["cumulative_provider_service_paid_usd"]), 7 * row["hour"])
            self.assertEqual(Decimal(row["cumulative_buyer_service_earned_usd"]), 10 * row["hour"])

    def test_missing_invalid_or_excessive_inputs_are_rejected_without_defaults(self):
        mutations = [
            lambda p: p.pop("liquidity"), lambda p: p.update(extra="unknown"),
            lambda p: p.update(gpu_count=True), lambda p: p.update(gpu_count="1"),
            lambda p: p.update(annual_yield_apr="NaN"), lambda p: p.update(annual_yield_apr="1.01"),
            lambda p: p.update(provider_rate=7.0), lambda p: p.update(prefunded_principal="-1"),
            lambda p: p.update(hourly_service_fractions=["1"]),
            lambda p: p.update(hourly_service_fractions=["1", "1.1"]),
            lambda p: p.update(yield_shares={"broker":"1"}),
            lambda p: p.update(yield_shares={"provider":"0", "broker":"0.9", "buyer":"0"}),
            lambda p: p.update(asset_price_usd="0.9"), lambda p: p.update(release_authorized="true"),
            lambda p: p.update(buffer_hours=3), lambda p: p.update(collateral_fraction="1.1"),
            lambda p: p.update(delivery_end="2035-03-14T02:00:01Z"),
        ]
        for mutate in mutations:
            payload = example()
            mutate(payload)
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                evaluate_escrow(payload)
        with self.assertRaises(ValueError):
            evaluate_escrow(example(2161))

    def test_contract_and_result_are_detached_and_never_claim_live_evidence(self):
        contract = escrow_contract()
        self.assertTrue(all(value is None for value in contract["template_unknown"].values()))
        contract["required_fields"].clear()
        self.assertGreater(len(escrow_contract()["required_fields"]), 10)
        payload = example()
        baseline = deepcopy(payload)
        result = evaluate_escrow(payload)
        result["chart"]["rows"][0]["hour"] = 999
        self.assertEqual(evaluate_escrow(payload)["chart"]["rows"][0]["hour"], 1)
        self.assertEqual(payload, baseline)
        for key in ("source_evidence_eligible", "inventory_verified", "firm_price_eligible", "execution_enabled"):
            self.assertFalse(result[key])
        self.assertFalse(result["asset"]["deposit_insurance_verified"])


if __name__ == "__main__":
    unittest.main()
