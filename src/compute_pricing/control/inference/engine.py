"""Measured whole-deployment inference economics; no inference API calls.

Technical qualification is a supplied, versioned evidence claim. This kernel
does not infer goodput from model memory, GPU names, FLOPS or token prices and
does not verify supplier credit, privacy controls or permission to execute.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
import json
import re
from typing import Any, Mapping

from .._numbers import calculation_precision, canonical_json, digest, number, text_number
from ..domain import ValidationError, utc_instant
from ..domain.spec import ID_PATTERN

SETUP_FIELDS = (
    "model_id", "runtime_id", "runtime_version", "hardware_model", "precision", "quantization",
    "tensor_parallel", "pipeline_parallel", "data_replicas", "context_tokens", "batch_size",
    "input_tokens_per_request", "output_tokens_per_request", "cached_input_tokens_per_request",
)
SLO_FIELDS = ("max_ttft_ms", "max_p95_latency_ms")
RATE_FIELDS = ("input_per_million", "output_per_million", "cached_input_per_million", "request_fee")
MILLION = Decimal(1000000)


@dataclass(frozen=True)
class InferenceResult:
    """Canonical encoded contents make the returned snapshot immutable."""
    document_json: str

    @property
    def status(self) -> str:
        return json.loads(self.document_json)["status"]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.document_json)


def _missing(record, required, prefix):
    if not isinstance(record, Mapping):
        return ["missing:" + prefix]
    return [f"missing:{prefix}.{key}" for key in required if record.get(key) is None]


def _count(raw, label, *, positive=False):
    value = number(raw, label, positive=positive)
    if value != value.to_integral_value():
        raise ValidationError(f"{label}: whole count required")
    return value


def _integer(raw, label, *, maximum=10000):
    if type(raw) is not int or not 1 <= raw <= maximum:
        raise ValidationError(f"{label}: positive bounded integer required")
    return raw


def _currency(raw):
    if not isinstance(raw, str) or not re.fullmatch(r"[A-Z]{3}", raw):
        raise ValidationError("currency: uppercase three-letter code required")
    return raw


def _money_rates(raw, currency):
    if _currency(raw["currency"]) != currency:
        raise ValidationError("rates: currency mismatch; no implicit conversion")
    return {key: number(raw[key], "rates." + key) for key in RATE_FIELDS}


def _token_bill(rates, requests, input_tokens, output_tokens, cached_tokens):
    uncached = input_tokens - cached_tokens
    return requests * (uncached * rates["input_per_million"] / MILLION
                       + output_tokens * rates["output_per_million"] / MILLION
                       + cached_tokens * rates["cached_input_per_million"] / MILLION
                       + rates["request_fee"])


def evaluate_inference_payload(payload: Mapping[str, Any]) -> InferenceResult:
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        return _evaluate(payload)


def _evaluate(payload):
    if not isinstance(payload, Mapping):
        raise ValidationError("inference: object required")
    blockers = _missing(payload, ("as_of", "policy_version", "model_version", "workload", "qualification", "costs", "sale_rates"), "inference")
    workload, qualification, costs, sale = (payload.get(key) for key in ("workload", "qualification", "costs", "sale_rates"))
    blockers += _missing(workload, SETUP_FIELDS + ("request_count", "starts_at", "ends_at", "slo", "availability_fraction"), "workload")
    blockers += _missing(qualification, ("id", "status", "evidence_sha256", "setup", "measured_at", "expires_at", "whole_deployment_slo_goodput_requests_per_second", "measured_ttft_ms", "measured_p95_latency_ms", "memory"), "qualification")
    blockers += _missing(costs, ("currency", "gpu_rate_per_gpu_hour", "cost_items", "collection_share", "fee_fraction_of_collected_revenue", "fee_fraction_of_gross_revenue"), "costs")
    blockers += _missing(sale, ("currency",) + RATE_FIELDS, "sale_rates")
    if isinstance(workload, Mapping):
        blockers += _missing(workload.get("slo"), SLO_FIELDS, "workload.slo")
    if isinstance(qualification, Mapping):
        blockers += _missing(qualification.get("setup"), SETUP_FIELDS, "qualification.setup")
        blockers += _missing(qualification.get("memory"), ("per_gpu_required_gib", "per_gpu_available_gib", "includes_kv_cache", "includes_runtime_overhead", "bandwidth_qualification"), "qualification.memory")
    result = {"status": "held" if blockers else "indicative", "blockers": blockers,
              "execution_enabled": False, "warnings": ["supplied_technical_evidence_is_not_independent_validation", "privacy_and_supplier_credit_require_separate_review", "indicative_costing_not_firm_quote"],
              "policy_version": payload.get("policy_version"), "model_version": payload.get("model_version"),
              "as_of": payload.get("as_of"), "input_sha256": digest(payload), "local": None, "routed_comparison": None}
    if blockers:
        return InferenceResult(canonical_json(result))
    for key in ("policy_version", "model_version"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValidationError("inference: explicit version strings required")
    now = utc_instant(payload["as_of"])
    start, end = utc_instant(workload["starts_at"]), utc_instant(workload["ends_at"])
    delta = end - start
    seconds = Decimal((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds) / MILLION
    if seconds <= 0:
        raise ValidationError("workload: positive calendar interval required")
    for key in ("model_id", "runtime_id", "runtime_version", "hardware_model", "precision", "quantization"):
        if not isinstance(workload[key], str) or not workload[key].strip():
            raise ValidationError("workload: explicit setup labels required")
    parallel = [_integer(workload[key], key) for key in ("tensor_parallel", "pipeline_parallel", "data_replicas")]
    context = _integer(workload["context_tokens"], "context_tokens", maximum=2147483647)
    _integer(workload["batch_size"], "batch_size")
    inputs, outputs, cache = [_count(workload[key], key) for key in ("input_tokens_per_request", "output_tokens_per_request", "cached_input_tokens_per_request")]
    requests = _count(workload["request_count"], "request_count")
    if cache > inputs:
        raise ValidationError("workload: cached input cannot exceed total input")
    if inputs + outputs > context:
        blockers.append("context_limit_exceeded")
    for key in SETUP_FIELDS:
        if qualification["setup"][key] != workload[key]:
            blockers.append("benchmark_setup_mismatch:" + key)
    if qualification["status"] != "qualified" or not isinstance(qualification["evidence_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", qualification["evidence_sha256"]):
        blockers.append("benchmark_evidence_not_qualified")
    measured, expires = utc_instant(qualification["measured_at"]), utc_instant(qualification["expires_at"])
    if measured > now or expires <= now or expires <= measured:
        blockers.append("benchmark_not_current")
    if measured > start or expires < end:
        blockers.append("benchmark_does_not_cover_service_interval")
    memory = qualification["memory"]
    if number(memory["per_gpu_required_gib"], "required memory", positive=True) > number(memory["per_gpu_available_gib"], "available memory", positive=True):
        blockers.append("per_gpu_memory_exceeded")
    if memory["includes_kv_cache"] is not True or memory["includes_runtime_overhead"] is not True:
        blockers.append("incomplete_per_gpu_memory_budget")
    if memory["bandwidth_qualification"] != "measured_under_declared_parallelism":
        blockers.append("parallel_bandwidth_not_qualified")
    for observed_key, maximum_key in (("measured_ttft_ms", "max_ttft_ms"), ("measured_p95_latency_ms", "max_p95_latency_ms")):
        if number(qualification[observed_key], observed_key) > number(workload["slo"][maximum_key], maximum_key, positive=True):
            blockers.append("benchmark_slo_failed:" + observed_key)
    gpu_count = Decimal(parallel[0] * parallel[1] * parallel[2])
    availability = number(workload["availability_fraction"], "availability_fraction", fraction=True)
    rps = number(qualification["whole_deployment_slo_goodput_requests_per_second"], "measured goodput", positive=True)
    usable_seconds = seconds * availability
    request_capacity = rps * usable_seconds
    if requests > request_capacity:
        blockers.append("measured_request_and_token_capacity_exceeded")
    if blockers:
        result.update(status="held", blockers=sorted(set(blockers)))
        return InferenceResult(canonical_json(result))
    currency = _currency(costs["currency"])
    sale_prices = _money_rates(sale, currency)
    billed = _token_bill(sale_prices, requests, inputs, outputs, cache)
    collection = number(costs["collection_share"], "collection_share", fraction=True)
    collected = billed * collection
    collected_fee = number(costs["fee_fraction_of_collected_revenue"], "collected revenue fee", fraction=True)
    gross_fee = number(costs["fee_fraction_of_gross_revenue"], "gross revenue fee", fraction=True)
    fees = collected * collected_fee + billed * gross_fee
    hours = seconds / Decimal(3600)
    gpu_cost = number(costs["gpu_rate_per_gpu_hour"], "gpu rate") * hours * gpu_count
    cost_lines = [{"id": "gpu_allocation", "basis": "all_allocated_gpu_hours", "amount": text_number(gpu_cost)}]
    other = Decimal(0)
    seen = {"gpu_allocation"}
    seen_ids = {"gpu_allocation"}
    if not isinstance(costs["cost_items"], list) or len(costs["cost_items"]) > 1000:
        raise ValidationError("cost_items: bounded array required")
    for item in costs["cost_items"]:
        if _missing(item, ("id", "ownership_channel", "amount", "currency", "basis"), "cost_item"):
            raise ValidationError("cost_item: explicit ownership, unit and amount required")
        channel = item["ownership_channel"]
        if not isinstance(channel, str) or not channel or channel in seen:
            raise ValidationError("cost_item: each cost channel has one owner")
        identity = item["id"]
        if not isinstance(identity, str) or not re.fullmatch(ID_PATTERN, identity) or identity in seen_ids:
            raise ValidationError("cost_item: unique canonical IDs, including generated entries, required")
        seen_ids.add(identity)
        seen.add(channel)
        if _currency(item["currency"]) != currency:
            raise ValidationError("cost_item: currency mismatch")
        multipliers = {"whole_horizon": Decimal(1), "per_request": requests, "per_gpu_hour": hours * gpu_count}
        if item["basis"] not in multipliers:
            raise ValidationError("cost_item: unsupported cost basis")
        amount = number(item["amount"], "cost item amount") * multipliers[item["basis"]]
        other += amount
        cost_lines.append({"id": item["id"], "ownership_channel": channel, "basis": item["basis"], "amount": text_number(amount)})
    local_cost = gpu_cost + other
    result["local"] = {
        "currency": currency, "allocated_gpu_count": text_number(gpu_count), "horizon_hours": text_number(hours),
        "usable_seconds": text_number(usable_seconds), "request_capacity": text_number(request_capacity),
        "output_token_capacity": text_number(request_capacity * outputs), "input_token_capacity": text_number(request_capacity * inputs),
        "served_requests": text_number(requests), "uncached_input_tokens": text_number(requests * (inputs - cache)),
        "cached_input_tokens": text_number(requests * cache), "output_tokens": text_number(requests * outputs),
        "billed_revenue": text_number(billed), "expected_collected_revenue": text_number(collected),
        "distribution_fees": text_number(fees), "gpu_cost_including_idle": text_number(gpu_cost),
        "cost_lines": cost_lines, "total_cost": text_number(local_cost),
        "expected_contribution": text_number(collected - fees - local_cost),
        "margin_on_gross_billings": text_number((collected - fees - local_cost) / billed) if billed else None,
        "qualification_id": qualification["id"], "qualification_sha256": qualification["evidence_sha256"],
        "throughput_basis": "measured_whole_deployment_slo_goodput_not_multiplied_by_parallelism_or_batch",
    }
    route = payload.get("external_route")
    route_blockers = _missing(route, ("currency",) + RATE_FIELDS + ("prices_include_route_fees", "route_fee_fraction", "source_id", "model_id", "precision", "quantization", "observed_at", "expires_at"), "external_route")
    result["routed_comparison"] = {"status": "held", "blockers": route_blockers, "cost": None}
    if not route_blockers:
        if type(route["prices_include_route_fees"]) is not bool:
            raise ValidationError("external_route: fee inclusion must be explicit boolean")
        route_fee = number(route["route_fee_fraction"], "route fee", fraction=True)
        if route["prices_include_route_fees"] and route_fee != 0:
            raise ValidationError("external_route: routing fee is already included")
        comparisons = []
        if any(route[key] != workload[key] for key in ("model_id", "precision", "quantization")):
            comparisons.append("external_model_or_precision_or_quantization_not_compatible")
        if utc_instant(route["observed_at"]) > now or utc_instant(route["expires_at"]) <= now:
            comparisons.append("external_route_not_current")
        if utc_instant(route["observed_at"]) > start or utc_instant(route["expires_at"]) < end:
            comparisons.append("external_rate_does_not_cover_service_interval")
        if comparisons:
            result["routed_comparison"]["blockers"] = comparisons
        else:
            base = _token_bill(_money_rates(route, currency), requests, inputs, outputs, cache)
            routed_cost = base * (Decimal(1) + route_fee)
            result["routed_comparison"] = {"status": "indicative", "blockers": [], "source_id": route["source_id"],
                "cost": text_number(routed_cost), "route_fee": text_number(base * route_fee),
                "expected_contribution": text_number(collected - fees - routed_cost),
                "local_cost_minus_routed_cost": text_number(local_cost - routed_cost),
                "privacy_slo_and_provider_route_qualification": "not_verified",
                "rate_basis": "supplied_snapshot_rates_no_firm_service_commitment"}
    return InferenceResult(canonical_json(result))


evaluate_inference = evaluate_inference_payload
