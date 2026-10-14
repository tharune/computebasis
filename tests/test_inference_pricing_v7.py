"""Independent task/vector floors and bounded workload crossover arithmetic."""
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.inference import evaluate_inference_payload


def sample():
    setup = {"model_id": "invented-price-model", "runtime_id": "invented-price-runtime", "runtime_version": "1.0.0",
             "hardware_model": "invented-public-price-accelerator", "precision": "fp16", "quantization": "none",
             "tensor_parallel": 1, "pipeline_parallel": 1, "data_replicas": 1,
             "context_tokens": 512, "batch_size": 2, "input_tokens_per_request": "100",
             "output_tokens_per_request": "20", "cached_input_tokens_per_request": "0"}
    return {"as_of": "2035-01-01T00:00:00Z", "policy_version": "1.0.0", "model_version": "qualified-test-inference/1.0",
            "workload": {**setup, "request_count": "100", "starts_at": "2035-01-01T00:00:00Z", "ends_at": "2035-01-01T01:00:00Z",
                         "slo": {"max_ttft_ms": "100", "max_p95_latency_ms": "200"}, "availability_fraction": "1"},
            "qualification": {"id": "qualification:invented-pricing", "status": "qualified", "evidence_sha256": "c" * 64,
                "setup": setup, "measured_at": "2034-12-31T00:00:00Z", "expires_at": "2035-01-02T00:00:00Z",
                "whole_deployment_slo_goodput_requests_per_second": "1", "measured_ttft_ms": "10", "measured_p95_latency_ms": "20",
                "memory": {"per_gpu_required_gib": "11", "per_gpu_available_gib": "21", "includes_kv_cache": True,
                           "includes_runtime_overhead": True, "bandwidth_qualification": "measured_under_declared_parallelism"}},
            "costs": {"currency": "USD", "gpu_rate_per_gpu_hour": "2", "cost_items": [
                {"id": "ops:fixed", "ownership_channel": "fixed_operations", "amount": "1", "currency": "USD", "basis": "whole_horizon"},
                {"id": "ops:variable", "ownership_channel": "variable_operations", "amount": "0.01", "currency": "USD", "basis": "per_request"}],
                "collection_share": "0.8", "fee_fraction_of_collected_revenue": "0.02", "fee_fraction_of_gross_revenue": "0.01"},
            "sale_rates": {"currency": "USD", "input_per_million": "0", "output_per_million": "0", "cached_input_per_million": "0", "request_fee": "0.1"},
            "external_route": {"source_id": "route:invented-price", "model_id": setup["model_id"], "precision": "fp16", "quantization": "none",
                "observed_at": "2034-12-31T00:00:00Z", "expires_at": "2035-01-02T00:00:00Z", "currency": "USD",
                "input_per_million": "0", "output_per_million": "0", "cached_input_per_million": "0", "request_fee": "0.05",
                "prices_include_route_fees": True, "route_fee_fraction": "0", "cost_items": [
                    {"id": "route:fixed", "ownership_channel": "routed_fixed_operations", "amount": "0.5", "currency": "USD", "basis": "whole_horizon"},
                    {"id": "route:variable", "ownership_channel": "routed_variable_operations", "amount": "0.005", "currency": "USD", "basis": "per_request"}]},
            "pricing_policy": {"required_margin": "0.2", "margin_basis": "gross_billings", "policy_capital_amount": "1",
                "task_price_tick": "0.001", "rate_ticks": {"input_per_million": "0.01", "output_per_million": "0.01", "cached_input_per_million": "0.01", "request_fee": "0.001"}}}


def result(payload=None):
    return evaluate_inference_payload(payload or sample()).to_dict()


class InferencePricingV7Tests(unittest.TestCase):
    def test_fixed_variable_cost_break_even_and_floors_use_same_horizon(self):
        output = result(); diagnostic = output["pricing_diagnostics"]
        self.assertEqual(output["local"]["total_cost"], "4")
        self.assertEqual(output["routed_comparison"]["cost"], "5")
        self.assertEqual(output["routed_comparison"]["all_in_cost"], "6")
        self.assertEqual(diagnostic["status"], "indicative")
        self.assertEqual(diagnostic["task_floors"]["expected_cost"], "4")
        self.assertEqual(diagnostic["task_floors"]["economic_cost"], "5")
        self.assertEqual(diagnostic["task_floors"]["required_margin_sell_tick"], "0.088")
        self.assertEqual(diagnostic["current_economic_profit"], "2.74")
        self.assertEqual(diagnostic["current_economic_margin"], "0.274")
        crossover = diagnostic["break_even"]
        self.assertEqual(crossover["local_fixed_cost"], "3")
        self.assertEqual(crossover["local_variable_cost_per_request"], "0.01")
        self.assertEqual(crossover["routed_fixed_cost"], "0.5")
        self.assertEqual(crossover["routed_variable_cost_per_request"], "0.055")
        self.assertEqual(crossover["whole_request_threshold"], "56")
        self.assertTrue(crossover["within_qualified_capacity"])
        self.assertEqual(crossover["qualified_request_capacity"], "3600")
        self.assertFalse(output["execution_enabled"])

    def test_upward_vector_ticks_meet_actual_required_margin_and_do_not_charge_capital_twice(self):
        payload = sample(); diagnostic = result(payload)["pricing_diagnostics"]
        vector = diagnostic["proportional_rate_vector"]["rates"]
        self.assertEqual(vector["request_fee"], "0.088")
        self.assertEqual(vector["input_per_million"], "0")
        payload["sale_rates"].update(vector)
        repriced = result(payload)["pricing_diagnostics"]
        self.assertGreaterEqual(Decimal(repriced["current_economic_margin"]), Decimal("0.2"))
        self.assertEqual(repriced["policy_capital_amount"], "1")
        payload["costs"]["cost_items"].append({"id": "capital:duplicate", "ownership_channel": "policy_capital", "amount": "1", "currency": "USD", "basis": "whole_horizon"})
        with self.assertRaises(ValidationError): result(payload)

    def test_collected_margin_has_its_declared_denominator(self):
        payload = sample(); payload["pricing_policy"]["margin_basis"] = "collected_revenue"
        diagnostic = result(payload)["pricing_diagnostics"]
        self.assertEqual(diagnostic["required_margin_factor"], "0.614")
        self.assertEqual(diagnostic["current_margin_denominator"], "8")
        self.assertEqual(diagnostic["task_floors"]["required_margin_sell_tick"], "0.082")

    def test_missing_policy_or_routed_cost_coverage_cannot_create_defaults(self):
        payload = sample(); payload.pop("pricing_policy")
        self.assertEqual(result(payload)["pricing_diagnostics"]["status"], "held")
        self.assertEqual(result(payload)["local"]["total_cost"], "4")
        payload = sample(); payload["external_route"].pop("cost_items")
        self.assertEqual(result(payload)["pricing_diagnostics"]["break_even"]["status"], "held")
        self.assertEqual(result(payload)["routed_comparison"]["operating_cost_coverage"], "not_declared_upstream_only")
        payload = sample(); payload["pricing_policy"]["rate_ticks"]["request_fee"] = None
        self.assertIn("missing:rate_ticks.request_fee", result(payload)["pricing_diagnostics"]["blockers"])

    def test_zero_requests_vector_and_impossible_denominator_hold_without_zero_floor(self):
        payload = sample(); payload["workload"]["request_count"] = "0"
        self.assertIsNone(result(payload)["pricing_diagnostics"]["task_floors"])
        self.assertEqual(result(payload)["local"]["gpu_cost_including_idle"], "2")
        payload = sample(); payload["sale_rates"]["request_fee"] = "0"
        diagnostic = result(payload)["pricing_diagnostics"]
        self.assertIsNone(diagnostic["proportional_rate_vector"])
        self.assertIn("zero_sale_vector_cannot_be_proportionally_scaled", diagnostic["blockers"])
        payload = sample(); payload["pricing_policy"]["required_margin"] = "1"
        self.assertIn("no_positive_collection_fee_margin_denominator", result(payload)["pricing_diagnostics"]["blockers"])

    def test_crossover_outside_qualified_capacity_does_not_imply_attainable_demand(self):
        payload = sample(); payload["workload"]["request_count"] = "3"
        payload["qualification"]["whole_deployment_slo_goodput_requests_per_second"] = "0.001"
        crossover = result(payload)["pricing_diagnostics"]["break_even"]
        self.assertEqual(crossover["whole_request_threshold"], "56")
        self.assertEqual(crossover["qualified_request_capacity"], "3.6")
        self.assertFalse(crossover["within_qualified_capacity"])
        self.assertEqual(crossover["status"], "outside_qualified_capacity")
        self.assertEqual(crossover["preference_within_qualified_capacity"], "routed_cheaper_at_all_feasible_whole_volumes")
        payload = sample(); payload["workload"]["request_count"] = "3"
        payload["qualification"]["whole_deployment_slo_goodput_requests_per_second"] = "0.001"
        payload["costs"]["cost_items"][1]["amount"] = "0.2"
        payload["external_route"]["cost_items"][0]["amount"] = "5"
        payload["external_route"]["cost_items"][1]["amount"] = "0"
        crossover = result(payload)["pricing_diagnostics"]["break_even"]
        self.assertEqual(crossover["status"], "outside_qualified_capacity")
        self.assertEqual(crossover["preference_within_qualified_capacity"], "local_no_more_expensive_at_all_feasible_whole_volumes")

    def test_reverse_crossover_parallel_costs_and_no_positive_crossovers(self):
        payload = sample(); payload["costs"]["cost_items"][1]["amount"] = "0.2"
        payload["external_route"]["cost_items"][0]["amount"] = "5"
        payload["external_route"]["cost_items"][1]["amount"] = "0"
        crossover = result(payload)["pricing_diagnostics"]["break_even"]
        self.assertEqual(crossover["whole_request_threshold"], "13")
        self.assertEqual(crossover["relationship"], "local_no_more_expensive_at_or_below_threshold")
        payload = sample(); payload["external_route"]["request_fee"] = "0.01"
        payload["external_route"]["cost_items"] = [{"id": "fixed:equal", "ownership_channel": "routed_fixed_operations", "amount": "3", "currency": "USD", "basis": "whole_horizon"}]
        self.assertEqual(result(payload)["pricing_diagnostics"]["break_even"]["relationship"], "equal_at_all_volumes")
        payload["external_route"]["request_fee"] = "0.001"
        self.assertEqual(result(payload)["pricing_diagnostics"]["break_even"]["relationship"], "local_no_more_expensive_at_or_below_threshold")

    def test_exact_near_tick_boundary_and_low_caller_precision_never_round_floor_down(self):
        payload = sample(); payload["workload"]["request_count"] = "1"
        payload["costs"].update(gpu_rate_per_gpu_hour="1." + "0" * 80 + "1", cost_items=[], collection_share="1", fee_fraction_of_collected_revenue="0", fee_fraction_of_gross_revenue="0")
        payload["sale_rates"]["request_fee"] = "1"
        payload["pricing_policy"].update(required_margin="0", policy_capital_amount="0", task_price_tick="0.01")
        payload["pricing_policy"]["rate_ticks"]["request_fee"] = "0.01"
        expected = result(payload)
        self.assertEqual(expected["pricing_diagnostics"]["task_floors"]["required_margin_sell_tick"], "1.01")
        self.assertEqual(expected["pricing_diagnostics"]["proportional_rate_vector"]["rates"]["request_fee"], "1.01")
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(result(payload), expected)

    def test_routed_ownership_currency_unknown_bases_and_fee_duplication_reject(self):
        for change in ("id", "currency", "channel", "basis"):
            payload = sample(); item = payload["external_route"]["cost_items"][1]
            if change == "id": item["id"] = payload["external_route"]["cost_items"][0]["id"]
            elif change == "currency": item["currency"] = "EUR"
            elif change == "channel": item["ownership_channel"] = "routing_fee"
            else: item["basis"] = "assumed_gpu_hour"
            with self.assertRaises(ValidationError): result(payload)

    def test_policy_numerical_fields_are_explicit_exact_and_not_arbitrary_formulas(self):
        for value in (0.2, True, "2e-1", "-0.1"):
            payload = sample(); payload["pricing_policy"]["required_margin"] = value
            with self.assertRaises(ValidationError): result(payload)
        payload = sample(); payload["pricing_policy"]["formula"] = "multiply every price"
        with self.assertRaises(ValidationError): result(payload)
        payload = sample(); payload["pricing_policy"]["task_price_tick"] = "0.0000000000001"
        with self.assertRaises(ValidationError): result(payload)


if __name__ == "__main__":
    unittest.main()
