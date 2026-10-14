"""Independent declared scenarios exercise costing, funding and stress boundaries."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from compute_pricing.control._numbers import digest
from compute_pricing.control.demo_pricing import demo_contract, demo_scenarios, evaluate_demo_pricing
from compute_pricing.control.domain import ValidationError


def manual_case():
    p = demo_scenarios()[0]["inputs"]
    p["capacity"].update(gpus_per_node=2, node_count=1, starts_at="2048-02-28T00:00:00Z", ends_at="2048-03-01T00:00:00Z")
    p["pricing"].update(supplier_rate="2", variable_low="2", variable_high="2", buyer_rate="5",
        billed_utilization="0.75", collection_share="0.8", fee_on_collected="0.01", fee_on_gross="0.02",
        required_margin="0.1", target_margin="0.2", fixed_operating_cost="7", risk_allowance_per_gpu_hour="0.125")
    p["pricing"]["power"].update(idle_watts_per_gpu="0", load_watts_per_gpu="0", shared_it_watts="0", pue="1", tariff_per_kwh="0")
    p["settlement"].update(mode="upfront", down_payment_fraction="1", financing_apr="0.365")
    p["treasury"].update(opening_cash="1000", minimum_cash="0", supplier_payment_on="2048-02-28",
        supplier_balance_on="2048-03-01", buyer_invoice_on="2048-03-01", buyer_receipt_on="2048-03-02",
        operating_cost_on="2048-02-28", fees_on="2048-03-02", writeoff_on="2048-03-02")
    return p


class DemoPricingEngineTests(unittest.TestCase):
    def test_three_deliberate_examples_are_complete_and_cash_feasible_not_executable(self):
        expected = [("H100", "A", "milestone"), ("L40S", "C", "milestone"), ("A4000", "D", "hourly_escrow")]
        for case, (model, grade, mode) in zip(demo_scenarios(), expected):
            with self.subTest(model=model):
                result = evaluate_demo_pricing(case["inputs"])
                self.assertEqual(result["status"], "scenario_estimate")
                self.assertEqual(result["quality"]["grade"], grade)
                self.assertEqual(result["terms"]["settlement"]["mode"], mode)
                self.assertTrue(result["summary"]["cash_feasible"])
                self.assertGreater(Decimal(result["summary"]["purchase_ceiling"]), 0)
                self.assertGreater(Decimal(result["summary"]["target_ask"]), Decimal(result["summary"]["sell_floor"]))
                self.assertIsNone(result["pricing"]["bid"])
                self.assertFalse(result["pricing"]["pricing_provenance"]["source_evidence_eligible"])
                for key in ("source_evidence_eligible", "physical_price_eligible", "firm_price_eligible", "execution_enabled"):
                    self.assertFalse(result[key])
                self.assertTrue(all(not values for values in result["cash"]["unresolved_balances"].values()))

    def test_actual_leap_calendar_finance_and_capital_have_independent_manual_oracle(self):
        result = evaluate_demo_pricing(manual_case())
        summary = result["summary"]
        # 2 GPUs * 48 calendar hours; 75% billed * $5, 80% collected.
        self.assertEqual(summary["gross_billings"], "360")
        self.assertEqual(summary["expected_collections"], "288")
        self.assertEqual(summary["financing_carry_fraction"], "0.002")
        self.assertEqual(summary["capital_budget"], "12")
        # $192 supply + $.384 deposit financing + $7 operating + $10.08 fees.
        self.assertEqual(summary["operating_contribution"], "78.536")
        self.assertEqual(summary["expected_profit"], "66.536")
        self.assertEqual(summary["net_cash_flow"], "78.536")
        cap = Decimal("222.92") / Decimal("96.192")
        self.assertAlmostEqual(Decimal(result["pricing"]["caps"]["economic_margin"]), cap, places=25)
        self.assertEqual(Decimal(result["cash"]["days"][-1]["earned_revenue"]), Decimal("360"))
        self.assertEqual(Decimal(result["cash"]["days"][-1]["cash"]), Decimal("1078.536"))
        self.assertEqual(Decimal(result["cash"]["days"][-1]["noncash_receivable_losses"]), Decimal("72"))

    def test_power_inclusion_changes_cost_once_and_pue_changes_actual_allocated_energy(self):
        p = demo_scenarios()[0]["inputs"]
        excluded = evaluate_demo_pricing(p)
        p["pricing"]["power"]["inclusion"] = "included"
        included = evaluate_demo_pricing(p)
        cost = Decimal(excluded["power"]["facility_power_cost"])
        self.assertEqual(included["summary"]["power_rate"], "0")
        self.assertEqual(included["power"]["facility_power_cost"], excluded["power"]["facility_power_cost"])
        self.assertEqual(Decimal(included["summary"]["expected_profit"]) - Decimal(excluded["summary"]["expected_profit"]), cost)
        self.assertEqual(Decimal(included["summary"]["net_cash_flow"]) - Decimal(excluded["summary"]["net_cash_flow"]), cost)
        p["pricing"]["power"].update(inclusion="excluded", pue="2.38")
        doubled = evaluate_demo_pricing(p)
        self.assertEqual(Decimal(doubled["power"]["facility_power_cost"]), cost * 2)

    def test_pricing_utilization_capacity_risk_and_cash_knobs_drive_results(self):
        p = manual_case(); baseline = evaluate_demo_pricing(p)
        p["pricing"]["risk_allowance_per_gpu_hour"] = "0.25"
        extra_risk = evaluate_demo_pricing(p)
        self.assertEqual(Decimal(extra_risk["summary"]["expected_profit"]), Decimal("54.536"))
        self.assertEqual(extra_risk["summary"]["net_cash_flow"], baseline["summary"]["net_cash_flow"])
        self.assertEqual(extra_risk["summary"]["cash_required"], str(Decimal(baseline["summary"]["cash_required"]) + 12))
        p = manual_case(); p["treasury"]["opening_cash"] = "10"
        poor = evaluate_demo_pricing(p)
        self.assertFalse(poor["summary"]["cash_feasible"])
        self.assertEqual(poor["summary"]["expected_profit"], baseline["summary"]["expected_profit"])
        self.assertGreater(Decimal(poor["summary"]["cash_shortfall"]), 0)
        p = manual_case(); p["pricing"]["billed_utilization"] = "0.5"
        fewer_sales = evaluate_demo_pricing(p)
        self.assertEqual(fewer_sales["summary"]["gross_billings"], "240")
        self.assertEqual(fewer_sales["pricing"]["economics"]["supply_gpu_hours"], "96")
        p = manual_case(); p["capacity"]["node_count"] = 2
        doubled = evaluate_demo_pricing(p)
        self.assertEqual(doubled["summary"]["gross_billings"], "720")
        self.assertEqual(doubled["pricing"]["economics"]["supply_gpu_hours"], "192")

    def test_hourly_customer_principal_yield_and_provider_collateral_never_become_revenue(self):
        p = demo_scenarios()[2]["inputs"]; baseline = evaluate_demo_pricing(p)
        p["settlement"].update(prefunded_principal="900", provider_collateral_usd="800", yield_apr="0.2")
        larger = evaluate_demo_pricing(p)
        self.assertEqual(larger["summary"], baseline["summary"])
        final = baseline["cash"]["days"][-1]
        self.assertEqual(Decimal(final["earned_revenue"]), Decimal(baseline["summary"]["gross_billings"]))
        self.assertEqual(Decimal(final["restricted_deposits"]), 0)
        self.assertGreater(Decimal(larger["escrow"]["yield"]["total_accrued_asset_units"]), Decimal(baseline["escrow"]["yield"]["total_accrued_asset_units"]))
        self.assertIsNone(baseline["summary"]["irr"])

    def test_hourly_mark_release_service_and_prefunding_fail_without_usable_cash_claim(self):
        mutations = [lambda p: p["settlement"].update(release_authorized=False),
            lambda p: p["settlement"].update(prefunded_principal="1"),
            lambda p: p["settlement"].update(liquidity="illiquid"),
            lambda p: p["settlement"].update(service_fraction="0.9"),
            lambda p: p["settlement"].update(asset_kind="stable_asset", asset_unit="SIM", asset_price_usd="0.7", depeg_status="depegged")]
        for change in mutations:
            p = demo_scenarios()[2]["inputs"]; change(p)
            result = evaluate_demo_pricing(p)
            self.assertEqual(result["status"], "held")
            self.assertIsNone(result["summary"]["purchase_ceiling"])
            self.assertIsNone(result["cash"])
            self.assertTrue(result["hold_reasons"])
        p = demo_scenarios()[2]["inputs"]; p["settlement"]["mode"] = "milestone"
        self.assertIn("illustrative_weak_grade_requires_hourly_restricted_escrow", evaluate_demo_pricing(p)["hold_reasons"])

    def test_unknown_template_has_no_price_and_known_schema_rejects_bad_inputs(self):
        contract = demo_contract()
        result = evaluate_demo_pricing(contract["template"])
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["summary"]["purchase_ceiling"])
        paths = {field["path"] for field in contract["fields"]}
        self.assertIn("settlement.buyer_label", paths)
        self.assertIn("pricing.power.payer", paths)
        self.assertIn("capacity.colocation", paths)
        fields = {field["path"]: field for field in contract["fields"]}
        for path in ("pricing.power.cost_owner", "pricing.risk_cost_owner", "settlement.collateral_owner"):
            self.assertFalse(fields[path]["editable"])
        self.assertTrue(fields["pricing.power.payer"]["editable"])
        self.assertEqual(contract["template"]["pricing"]["power"]["cost_owner"], "allocated-power-cost/1.0.0")
        self.assertEqual(contract["template"]["pricing"]["risk_cost_owner"], "demo:declared-capital-budget")
        self.assertIsNone(contract["template"]["pricing"]["supplier_rate"])
        self.assertIn("not a calibrated", fields["provider.credit_score"]["help"])
        for change in (lambda p: p["pricing"].update(buyer_rate=4.2),
                       lambda p: p["provider"]["ratings"].update(sla=5),
                       lambda p: p["capacity"].update(node_count=1.5),
                       lambda p: p["pricing"].update(unknown_premium="3"),
                       lambda p: p["capacity"].update(starts_at="2027-02-01T00:01:00Z", ends_at="2027-03-03T00:01:00Z")):
            p = demo_scenarios()[0]["inputs"]; change(p)
            with self.assertRaises(ValidationError): evaluate_demo_pricing(p)

    def test_declared_volatility_and_collection_stresses_are_not_fitted_forward_prices(self):
        p = manual_case(); p["surface"]["annual_volatility"] = "0"
        flat = evaluate_demo_pricing(p)["surface"]
        self.assertEqual({point["rate"] for point in flat["points"]}, {"2"})
        p["surface"]["annual_volatility"] = "0.6"
        surface = evaluate_demo_pricing(p)["surface"]
        first = [row for row in surface["points"] if row["tenor_days"] == "1"]
        self.assertLess(Decimal(first[0]["rate"]), Decimal(first[1]["rate"]))
        self.assertLess(Decimal(first[1]["rate"]), Decimal(first[2]["rate"]))
        collection = [row for row in surface["collection_sensitivity_points"] if row["tenor_days"] == "1"]
        self.assertGreater(Decimal(collection[0]["economic_cap"]), Decimal(collection[-1]["economic_cap"]))
        self.assertFalse(surface["calibrated"])
        self.assertFalse(surface["cash_feasibility_recomputed_for_surface"])
        self.assertIn("no fitted volatility", surface["label"])
        p["surface"]["collection_shocks"] = ["NaN"]
        with self.assertRaises(ValidationError): evaluate_demo_pricing(p)

    def test_live_retained_context_requires_same_model_usd_gpu_hour_and_never_changes_caps(self):
        p = manual_case(); baseline = evaluate_demo_pricing(p)
        context = {"source_evidence_eligible": True, "status": "indicative_reference", "cohort": {"hardware_model": "H100", "currency": "USD"},
                   "reference": {"amount": "19", "currency": "USD", "unit": "gpu_hour"}}
        admitted = evaluate_demo_pricing(p, market_reference=context)
        self.assertEqual(admitted["live_reference"]["status"], "context_only")
        self.assertEqual(admitted["summary"], baseline["summary"])
        self.assertFalse(admitted["live_reference"]["used_as_purchase_cap"])
        for change in (lambda x: x["cohort"].update(hardware_model="L40S"), lambda x: x["reference"].update(unit="million_tokens"),
                       lambda x: x["reference"].update(currency="EUR"), lambda x: x.update(source_evidence_eligible=False)):
            wrong = deepcopy(context); change(wrong)
            self.assertEqual(evaluate_demo_pricing(p, market_reference=wrong)["live_reference"]["status"], "held")

    def test_fresh_ownership_precision_receipt_hash_and_complete_agreement_terms(self):
        p = manual_case(); original = deepcopy(p); expected = evaluate_demo_pricing(p)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(evaluate_demo_pricing(p), expected)
        self.assertEqual(p, original)
        self.assertEqual(expected["input_hash"], digest(p))
        result_without_hash = deepcopy(expected); result_without_hash.pop("decision_hash")
        self.assertEqual(expected["decision_hash"], digest(result_without_hash))
        agreement = expected["agreement_terms"]
        self.assertEqual(agreement["capacity"]["total_gpu_count"], 2)
        self.assertEqual(agreement["pricing"]["currency"], "USD")
        self.assertEqual(agreement["pricing"]["price_unit"], "gpu_hour")
        self.assertEqual(agreement["settlement"]["buyer_label"], p["settlement"]["buyer_label"])
        self.assertFalse(agreement["legal_entitlements_verified"])
        contract = demo_contract(); contract["scenarios"][0]["inputs"]["provider"]["label"] = "changed"
        self.assertNotEqual(demo_contract()["scenarios"][0]["inputs"]["provider"]["label"], "changed")


if __name__ == "__main__":
    unittest.main()
