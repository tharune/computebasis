"""Invented measured-deployment examples; no model serving or paid requests."""
import copy
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.inference import evaluate_inference_payload
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.inference.engine import SETUP_FIELDS


def fixture():
    workload = {"model_id": "invented-model-v1", "runtime_id": "invented-runtime", "runtime_version": "1.0", "hardware_model": "invented-accelerator", "precision": "bf16", "quantization": "none", "tensor_parallel": 2, "pipeline_parallel": 1, "data_replicas": 2, "context_tokens": 1024, "batch_size": 8, "input_tokens_per_request": "100", "output_tokens_per_request": "50", "cached_input_tokens_per_request": "40", "request_count": "100", "availability_fraction": "1", "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-01-01T01:00:00Z", "slo": {"max_ttft_ms": "200", "max_p95_latency_ms": "2000"}}
    return {"as_of": "2026-01-01T00:00:00Z", "policy_version": "1.0.0", "model_version": "measured-inference-v1", "workload": workload,
        "qualification": {"id": "benchmark-invented", "status": "qualified", "evidence_sha256": "ab" * 32, "setup": {key: workload[key] for key in SETUP_FIELDS}, "measured_at": "2025-12-31T00:00:00Z", "expires_at": "2026-01-02T00:00:00Z", "whole_deployment_slo_goodput_requests_per_second": "2", "measured_ttft_ms": "100", "measured_p95_latency_ms": "1500", "memory": {"per_gpu_required_gib": "20", "per_gpu_available_gib": "24", "includes_kv_cache": True, "includes_runtime_overhead": True, "bandwidth_qualification": "measured_under_declared_parallelism"}},
        "costs": {"currency": "USD", "gpu_rate_per_gpu_hour": "1.5", "collection_share": "0.9", "fee_fraction_of_collected_revenue": "0.02", "fee_fraction_of_gross_revenue": "0.01", "cost_items": [{"id": "fixed-ops", "ownership_channel": "ops-fixed", "amount": "0.1", "currency": "USD", "basis": "whole_horizon"}, {"id": "metered-ops", "ownership_channel": "ops-metered", "amount": "0.001", "currency": "USD", "basis": "per_request"}]},
        "sale_rates": {"currency": "USD", "input_per_million": "10", "output_per_million": "20", "cached_input_per_million": "2", "request_fee": "0.03"},
        "external_route": {"source_id": "invented-route", "model_id": workload["model_id"], "precision": workload["precision"], "quantization": workload["quantization"], "observed_at": "2025-12-31T23:00:00Z", "expires_at": "2026-01-01T02:00:00Z", "currency": "USD", "input_per_million": "1", "output_per_million": "2", "cached_input_per_million": "0.2", "request_fee": "0.001", "prices_include_route_fees": True, "route_fee_fraction": "0"}}


class InferenceV1Tests(unittest.TestCase):
    def evaluate(self, payload=None):
        return evaluate_inference_payload(payload or fixture()).to_dict()

    def test_whole_deployment_cost_capacity_and_billing_golden(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "indicative")
        self.assertFalse(result["execution_enabled"])
        local = result["local"]
        self.assertEqual(local["allocated_gpu_count"], "4")
        self.assertEqual(local["gpu_cost_including_idle"], "6")
        self.assertEqual(local["request_capacity"], "7200")
        self.assertEqual(local["input_token_capacity"], "720000")
        self.assertEqual(local["output_token_capacity"], "360000")
        self.assertEqual(local["billed_revenue"], "3.168")
        self.assertEqual(local["expected_collected_revenue"], "2.8512")
        self.assertEqual(local["distribution_fees"], "0.088704")
        self.assertEqual(local["total_cost"], "6.2")
        self.assertEqual(local["expected_contribution"], "-3.437504")
        self.assertEqual(result["routed_comparison"]["cost"], "0.1168")
        self.assertEqual(result["routed_comparison"]["expected_contribution"], "2.645696")

    def test_no_replica_or_batch_multiplier_on_measured_goodput(self):
        raw = fixture()
        raw["workload"]["request_count"] = "7201"
        result = self.evaluate(raw)
        self.assertEqual(result["status"], "held")
        self.assertIn("measured_request_and_token_capacity_exceeded", result["blockers"])
        self.assertIsNone(result["local"])

    def test_availability_reduces_capacity_but_allocation_cost_still_full(self):
        raw = fixture()
        raw["workload"]["availability_fraction"] = "0.5"
        self.assertEqual(self.evaluate(raw)["local"]["gpu_cost_including_idle"], "6")
        self.assertEqual(self.evaluate(raw)["local"]["request_capacity"], "3600")

    def test_every_runtime_model_hardware_quantization_setup_field_must_match(self):
        for key in SETUP_FIELDS:
            raw = fixture()
            value = raw["qualification"]["setup"][key]
            raw["qualification"]["setup"][key] = value + 1 if type(value) is int else value + "-different"
            with self.subTest(key=key):
                result = self.evaluate(raw)
                self.assertEqual(result["status"], "held")
                self.assertIn("benchmark_setup_mismatch:" + key, result["blockers"])

    def test_current_and_service_interval_benchmark_coverage_required(self):
        for changes in ({"measured_at": "2026-01-01T00:00:01Z"}, {"expires_at": "2026-01-01T00:00:00Z"}, {"expires_at": "2026-01-01T00:30:00Z"}, {"status": "claimed"}, {"evidence_sha256": "not-evidence"}):
            raw = fixture()
            raw["qualification"].update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(self.evaluate(raw)["status"], "held")

    def test_memory_kv_overhead_and_bandwidth_fail_closed(self):
        for changes in ({"per_gpu_required_gib": "25"}, {"includes_kv_cache": False}, {"includes_runtime_overhead": False}, {"bandwidth_qualification": "assumed_from_gpu_spec"}):
            raw = fixture()
            raw["qualification"]["memory"].update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(self.evaluate(raw)["status"], "held")

    def test_slo_failure_or_context_overflow_never_prices(self):
        for key, value in (("measured_ttft_ms", "201"), ("measured_p95_latency_ms", "2001")):
            raw = fixture()
            raw["qualification"][key] = value
            self.assertEqual(self.evaluate(raw)["status"], "held")
        raw = fixture()
        raw["workload"]["context_tokens"] = 128
        raw["qualification"]["setup"]["context_tokens"] = 128
        self.assertIn("context_limit_exceeded", self.evaluate(raw)["blockers"])

    def test_missing_values_are_held_and_zero_is_preserved(self):
        raw = fixture()
        raw["qualification"]["whole_deployment_slo_goodput_requests_per_second"] = None
        self.assertEqual(self.evaluate(raw)["status"], "held")
        raw = fixture()
        raw["workload"]["request_count"] = "0"
        result = self.evaluate(raw)
        self.assertEqual(result["local"]["billed_revenue"], "0")
        self.assertIsNone(result["local"]["margin_on_gross_billings"])
        self.assertEqual(result["local"]["gpu_cost_including_idle"], "6")

    def test_token_cache_counts_are_partitioned_once(self):
        raw = fixture()
        local = self.evaluate(raw)["local"]
        self.assertEqual(local["uncached_input_tokens"], "6000")
        self.assertEqual(local["cached_input_tokens"], "4000")
        raw["workload"]["cached_input_tokens_per_request"] = "101"
        with self.assertRaises(ValidationError):
            self.evaluate(raw)

    def test_inexact_rates_invalid_currency_and_double_cost_ownership_reject(self):
        for value in (1.5, True, "1e-6"):
            raw = fixture()
            raw["costs"]["gpu_rate_per_gpu_hour"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.evaluate(raw)
        raw = fixture()
        raw["sale_rates"]["currency"] = "EUR"
        with self.assertRaises(ValidationError):
            self.evaluate(raw)
        raw = fixture()
        raw["costs"]["cost_items"].append(copy.deepcopy(raw["costs"]["cost_items"][0]))
        with self.assertRaises(ValidationError):
            self.evaluate(raw)

    def test_routing_fees_do_not_repeat_included_fees(self):
        raw = fixture()
        raw["external_route"]["route_fee_fraction"] = "0.1"
        with self.assertRaises(ValidationError):
            self.evaluate(raw)
        raw["external_route"]["prices_include_route_fees"] = False
        result = self.evaluate(raw)
        self.assertEqual(result["routed_comparison"]["route_fee"], "0.01168")
        self.assertEqual(result["routed_comparison"]["cost"], "0.12848")

    def test_optional_route_missing_or_stale_preserves_local_calculation(self):
        raw = fixture()
        raw.pop("external_route")
        result = self.evaluate(raw)
        self.assertEqual(result["status"], "indicative")
        self.assertEqual(result["routed_comparison"]["status"], "held")
        raw = fixture()
        raw["external_route"]["expires_at"] = raw["as_of"]
        self.assertEqual(self.evaluate(raw)["routed_comparison"]["status"], "held")

    def test_adaptive_money_precision_and_caller_context_independence(self):
        raw = fixture()
        amount = "1." + "2345678901" * 11
        raw["costs"]["gpu_rate_per_gpu_hour"] = amount
        baseline = self.evaluate(raw)
        with localcontext() as context:
            context.prec = 300
            expected = Decimal(amount) * 4
        self.assertEqual(Decimal(baseline["local"]["gpu_cost_including_idle"]), expected)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.evaluate(raw), baseline)

    def test_result_is_immutable_reproducible_and_hash_changes_with_input(self):
        raw = fixture()
        result = evaluate_inference_payload(raw)
        with self.assertRaises(FrozenInstanceError):
            result.document_json = "{}"
        altered = result.to_dict()
        altered["local"]["total_cost"] = "0"
        self.assertEqual(result.to_dict()["local"]["total_cost"], "6.2")
        self.assertEqual(result, evaluate_inference_payload(raw))
        raw["sale_rates"]["request_fee"] = "0.04"
        self.assertNotEqual(self.evaluate(raw)["input_sha256"], result.to_dict()["input_sha256"])

    def test_large_declared_context_remains_dynamic_with_matching_measurement(self):
        raw = fixture()
        raw["workload"]["context_tokens"] = 131072
        raw["qualification"]["setup"]["context_tokens"] = 131072
        self.assertEqual(self.evaluate(raw)["status"], "indicative")

    def test_cost_ids_cannot_conflict_with_generated_or_other_entries(self):
        for identity in ("gpu_allocation", "fixed-ops"):
            raw = fixture()
            raw["costs"]["cost_items"][1]["id"] = identity
            with self.subTest(identity=identity), self.assertRaises(ValidationError):
                self.evaluate(raw)

    def test_routed_model_configuration_and_future_rate_coverage_required(self):
        for updates in ({"model_id": "another-model"}, {"precision": "fp32"}, {"quantization": "int4"}, {"expires_at": "2026-01-01T00:30:00Z"}):
            raw = fixture()
            raw["external_route"].update(updates)
            with self.subTest(updates=updates):
                result = self.evaluate(raw)
                self.assertEqual(result["status"], "indicative")
                self.assertEqual(result["routed_comparison"]["status"], "held")
                self.assertIsNone(result["routed_comparison"]["cost"])


if __name__ == "__main__":
    unittest.main()
