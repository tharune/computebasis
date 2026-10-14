"""Fresh invented workloads for conditional economic supplier-rate limits."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from compute_pricing.control.domain import ValidationError
from compute_pricing.control.inference import evaluate_inference_payload


def candidate():
    setup = {"model_id": "model:budget-demo", "runtime_id": "runtime:budget-demo", "runtime_version": "2.0.0",
        "hardware_model": "accelerator:budget-demo", "precision": "bf16", "quantization": "none",
        "tensor_parallel": 2, "pipeline_parallel": 1, "data_replicas": 1, "context_tokens": 512, "batch_size": 5,
        "input_tokens_per_request": "96", "output_tokens_per_request": "24", "cached_input_tokens_per_request": "0"}
    return {"as_of": "2038-07-08T00:00:00Z", "policy_version": "2.0.0", "model_version": "economic-budget-demo/1.0",
        "workload": {**setup, "request_count": "12000", "starts_at": "2038-07-08T00:00:00Z",
            "ends_at": "2038-07-08T02:00:00Z", "availability_fraction": "0.25",
            "slo": {"max_ttft_ms": "500", "max_p95_latency_ms": "2500"}},
        "qualification": {"id": "evidence:budget-demo", "status": "qualified", "evidence_sha256": "e" * 64,
            "setup": deepcopy(setup), "measured_at": "2038-07-07T00:00:00Z", "expires_at": "2038-07-09T00:00:00Z",
            "whole_deployment_slo_goodput_requests_per_second": "10", "measured_ttft_ms": "120", "measured_p95_latency_ms": "900",
            "memory": {"per_gpu_required_gib": "12", "per_gpu_available_gib": "32", "includes_kv_cache": True,
                "includes_runtime_overhead": True, "bandwidth_qualification": "measured_under_declared_parallelism"}},
        "costs": {"currency": "USD", "gpu_rate_per_gpu_hour": "3", "collection_share": "0.9",
            "fee_fraction_of_collected_revenue": "0.03", "fee_fraction_of_gross_revenue": "0.015", "cost_items": [
                {"id": "cost:fixed", "ownership_channel": "fixed_platform", "amount": "7", "currency": "USD", "basis": "whole_horizon"},
                {"id": "cost:request", "ownership_channel": "request_platform", "amount": "0.0005", "currency": "USD", "basis": "per_request"}]},
        "sale_rates": {"currency": "USD", "input_per_million": "0", "output_per_million": "0",
            "cached_input_per_million": "0", "request_fee": "0.0075"},
        "pricing_policy": {"required_margin": "0.18", "margin_basis": "gross_billings", "policy_capital_amount": "4",
            "task_price_tick": "0.00001", "rate_ticks": {"input_per_million": "0.01", "output_per_million": "0.01",
                "cached_input_per_million": "0.01", "request_fee": "0.00001"}},
        "supplier_ceiling_policy": {"buy_tick_per_gpu_hour": "0.05", "nonpurchase_costs_complete": True,
            "nonpurchase_costs_rate_independent": True}}


def evaluate(payload):
    return evaluate_inference_payload(payload).to_dict()


def ceiling(payload):
    return evaluate(payload)["pricing_diagnostics"]["supplier_buy_ceiling"]


class SupplierEconomicBudgetTests(unittest.TestCase):
    def test_declared_gross_margin_budget_and_capital_are_owned_once(self):
        cap = ceiling(candidate())
        # 90*(.9*(1-.03)-.015-.18)-13-4 = 44.02;
        # two accelerators for two hours, independent of the .25 availability.
        self.assertEqual(cap["signed_supplier_budget"], "44.02")
        self.assertEqual(cap["allocated_gpu_hours"], "4")
        self.assertEqual(cap["nonpurchase_expected_cost"], "13")
        self.assertEqual(cap["policy_capital_amount"], "4")
        self.assertEqual(cap["required_margin_ceiling_per_gpu_hour"], "11.005")
        self.assertEqual(cap["required_margin_buy_tick_ceiling"], "11")
        self.assertEqual(cap["supplier_cost_owner"], "gpu_allocation")
        for flag in ("cash_funding_assessed", "market_qualified_bid", "firm_price_eligible", "execution_enabled"):
            self.assertFalse(cap[flag])

    def test_last_affordable_buy_tick_meets_margin_and_next_tick_fails(self):
        payload = candidate()
        payload["costs"]["gpu_rate_per_gpu_hour"] = ceiling(payload)["required_margin_buy_tick_ceiling"]
        at_limit = evaluate(payload)["pricing_diagnostics"]
        self.assertGreaterEqual(Decimal(at_limit["current_economic_margin"]), Decimal("0.18"))
        payload["costs"]["gpu_rate_per_gpu_hour"] = "11.05"
        over_limit = evaluate(payload)["pricing_diagnostics"]
        self.assertLess(Decimal(over_limit["current_economic_margin"]), Decimal("0.18"))
        self.assertFalse(over_limit["supplier_buy_ceiling"]["current_base_gpu_quote_meets_required_margin"])
        self.assertEqual(over_limit["supplier_buy_ceiling"]["signed_supplier_budget"], "44.02")

    def test_capacity_and_batch_do_not_discount_payable_gpu_hours(self):
        payload = candidate()
        original = ceiling(payload)
        payload["workload"]["availability_fraction"] = "0.9"
        payload["workload"]["batch_size"] = 8
        payload["qualification"]["setup"]["batch_size"] = 8
        self.assertEqual(ceiling(payload), original)

    def test_collection_adjusted_margin_is_distinct_from_gross_margin(self):
        payload = candidate()
        payload["pricing_policy"]["margin_basis"] = "collected_revenue"
        cap = ceiling(payload)
        self.assertEqual(cap["signed_supplier_budget"], "45.64")
        self.assertEqual(cap["required_margin_ceiling_per_gpu_hour"], "11.41")
        self.assertEqual(cap["required_margin_buy_tick_ceiling"], "11.4")

    def test_negative_budget_is_held_while_exact_zero_stays_explicit(self):
        payload = candidate()
        payload["costs"]["cost_items"][0]["amount"] = "60"
        cap = ceiling(payload)
        self.assertEqual(cap["signed_supplier_budget"], "-8.98")
        self.assertEqual(cap["status"], "held")
        self.assertFalse(cap["nonnegative_supplier_rate_feasible"])
        self.assertIsNone(cap["required_margin_buy_tick_ceiling"])
        payload["costs"]["cost_items"][0]["amount"] = "51.02"
        cap = ceiling(payload)
        self.assertTrue(cap["nonnegative_supplier_rate_feasible"])
        self.assertEqual(cap["required_margin_buy_tick_ceiling"], "0")
        self.assertFalse(cap["market_qualified_bid"])

    def test_incomplete_unknown_and_rate_dependent_operating_costs_hold(self):
        for field in ("nonpurchase_costs_complete", "nonpurchase_costs_rate_independent"):
            for value in (False, None):
                payload = candidate()
                payload["supplier_ceiling_policy"][field] = value
                cap = ceiling(payload)
                self.assertEqual(cap["status"], "held")
                self.assertIsNone(cap["required_margin_buy_tick_ceiling"])
        for field in ("pricing_policy", "supplier_ceiling_policy"):
            payload = candidate()
            payload.pop(field)
            self.assertIsNone(ceiling(payload)["required_margin_ceiling_per_gpu_hour"])
        payload = candidate()
        payload["supplier_ceiling_policy"]["buy_tick_per_gpu_hour"] = None
        self.assertEqual(ceiling(payload)["status"], "held")

    def test_price_sensitive_costs_need_their_own_explicit_owner_and_reprice(self):
        payload = candidate()
        payload["costs"]["cost_items"].append({"id": "cost:site", "ownership_channel": "site_services",
            "amount": "1.75", "currency": "USD", "basis": "per_gpu_hour"})
        cap = ceiling(payload)
        self.assertEqual(cap["nonpurchase_expected_cost"], "20")
        self.assertEqual(cap["signed_supplier_budget"], "37.02")
        payload["supplier_ceiling_policy"]["nonpurchase_costs_rate_independent"] = False
        self.assertIsNone(ceiling(payload)["required_margin_buy_tick_ceiling"])
        payload = candidate()
        payload["costs"]["cost_items"].append({"id": "capital:again", "ownership_channel": "policy_capital",
            "amount": "4", "currency": "USD", "basis": "whole_horizon"})
        with self.assertRaises(ValidationError):
            evaluate(payload)

    def test_zero_volume_sale_and_infeasible_collection_margin_do_not_quote(self):
        for case in ("volume", "sale", "margin"):
            payload = candidate()
            if case == "volume": payload["workload"]["request_count"] = "0"
            elif case == "sale": payload["sale_rates"]["request_fee"] = "0"
            else: payload["pricing_policy"]["required_margin"] = "1"
            self.assertEqual(ceiling(payload)["status"], "held")
            self.assertIsNone(ceiling(payload)["required_margin_buy_tick_ceiling"])

    def test_boundary_below_buy_tick_is_conservative_under_small_decimal_context(self):
        payload = candidate()
        payload["costs"].update(collection_share="1", fee_fraction_of_collected_revenue="0", fee_fraction_of_gross_revenue="0")
        payload["workload"]["request_count"] = "1"
        payload["sale_rates"]["request_fee"] = "4"
        payload["costs"]["cost_items"] = [{"id": "cost:tiny", "ownership_channel": "rounding_test",
            "amount": "0." + "0" * 70 + "7", "currency": "USD", "basis": "whole_horizon"}]
        payload["pricing_policy"].update(required_margin="0", policy_capital_amount="0")
        payload["supplier_ceiling_policy"]["buy_tick_per_gpu_hour"] = "0.02"
        normal = evaluate(payload)
        self.assertEqual(normal["pricing_diagnostics"]["supplier_buy_ceiling"]["required_margin_buy_tick_ceiling"], "0.98")
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(evaluate(payload), normal)

    def test_supplier_policy_requires_exact_positive_tick_and_boolean_claims(self):
        for value in (True, 0.05, "0", "-0.05", "5e-2", "0.0000000000001"):
            payload = candidate()
            payload["supplier_ceiling_policy"]["buy_tick_per_gpu_hour"] = value
            with self.assertRaises(ValidationError):
                evaluate(payload)
        payload = candidate()
        payload["supplier_ceiling_policy"]["nonpurchase_costs_rate_independent"] = "yes"
        with self.assertRaises(ValidationError):
            evaluate(payload)
        payload = candidate()
        payload["supplier_ceiling_policy"]["silently_assume_funding"] = True
        with self.assertRaises(ValidationError):
            evaluate(payload)


if __name__ == "__main__":
    unittest.main()
