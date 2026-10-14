"""Bounded anonymous Models API discovery for local advertised-cost comparison.

No model calls, provider endpoints, raw response archive or access resale exist.
Top-level rates remain claims about current default conditions; pricing overrides
are retained as conditions, never applied without a workload and request instant.
"""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any, Mapping

from .transport import ConnectorError, ReadOnlyTransport, ReadRequest, SOURCE_SPECS, SourcePolicy

SOURCE_ID = "openrouter"
MAX_LIMIT = 100
MAX_PAGES = 3
MAX_OFFSET = 10000
INPUT_MODALITIES = frozenset({"text", "image", "audio", "file", "video"})
OUTPUT_MODALITIES = frozenset({"text", "image", "video", "audio", "speech", "transcription", "embeddings", "rerank", "decisions"})


def openrouter_filters(filters: Mapping[str, Any] | None) -> dict[str, Any]:
    if filters is not None and not isinstance(filters, Mapping):
        raise ConnectorError("openrouter_invalid_filters")
    options = dict(filters or {})
    if set(options) - {"q", "input_modalities", "output_modalities", "offset", "limit", "max_pages"}:
        raise ConnectorError("openrouter_filter_not_admitted")
    for key, default, maximum in (("offset", 0, MAX_OFFSET), ("limit", 100, MAX_LIMIT), ("max_pages", 1, MAX_PAGES)):
        value = options.get(key, default)
        if type(value) is not int or not (0 if key == "offset" else 1) <= value <= maximum:
            raise ConnectorError("openrouter_collection_budget_invalid")
        options[key] = value
    if "q" in options and (not isinstance(options["q"], str) or not options["q"].strip() or len(options["q"]) > 128 or any(ord(char) < 32 for char in options["q"])):
        raise ConnectorError("openrouter_search_invalid")
    for key, admitted in (("input_modalities", INPUT_MODALITIES), ("output_modalities", OUTPUT_MODALITIES)):
        if key in options:
            value = options[key]
            if not isinstance(value, str):
                raise ConnectorError("openrouter_modality_invalid")
            values = value.split(",")
            if len(set(values)) != len(values) or not values or (value != "all" and any(item not in admitted for item in values)):
                raise ConnectorError("openrouter_modality_invalid")
    return options


def openrouter_request(filters: Mapping[str, Any] | None) -> ReadRequest:
    options = openrouter_filters(filters)
    query = urllib.parse.urlencode({key: value for key, value in options.items() if key != "max_pages"})
    return ReadRequest(SOURCE_SPECS[SOURCE_ID], "https://openrouter.ai/api/v1/models?" + query)


def collect_openrouter(policy: SourcePolicy, transport: ReadOnlyTransport, filters: Mapping[str, Any] | None):
    from .adapters import ConnectorBatch, json_payload, parse_openrouter
    options = openrouter_filters(filters)
    if policy.source_id != SOURCE_ID:
        raise ConnectorError("source_policy_mismatch")
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, transport.clock())
    request = openrouter_request(options)
    query = {key: str(value) for key, value in options.items() if key != "max_pages"}
    pages, observations, catalog, seen, price_exclusions = [], [], [], set(), []
    total_bytes, complete, current_offset, reported_total = 0, False, options["offset"], None
    warnings = []
    for page in range(options["max_pages"]):
        if page:
            transport.wait_for_source(SOURCE_ID, max_wait_s=transport.max_wait_s)
        raw = transport.fetch(request, policy)
        payload = json_payload(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ConnectorError("model_catalog_shape_changed")
        if len(payload["data"]) > options["limit"]:
            raise ConnectorError("openrouter_response_exceeds_requested_limit")
        total_bytes += len(raw.body)
        if total_bytes > 8 * 1024 * 1024:
            raise ConnectorError("openrouter_collection_size_budget")
        if "total_count" in payload:
            count = payload["total_count"]
            if type(count) is not int or count < 0 or count < current_offset + len(payload["data"]):
                raise ConnectorError("openrouter_count_contract_changed")
            if reported_total is not None and count != reported_total:
                warnings.append("catalog_population_changed_during_pagination")
            reported_total = count
        batch = parse_openrouter(raw, policy)
        for record in batch.catalog_records:
            if record["model_id"] in seen:
                raise ConnectorError("duplicate_model_across_pages")
            seen.add(record["model_id"])
            architecture = record["metadata"].get("architecture")
            if isinstance(architecture, dict):
                for key in ("input_modalities", "output_modalities"):
                    expected = query.get(key, "text" if key == "output_modalities" else "all")
                    actual = architecture.get(key)
                    if actual is not None and (not isinstance(actual, list) or any(not isinstance(item, str) for item in actual)):
                        raise ConnectorError("openrouter_architecture_shape_changed")
                    if actual is not None and expected != "all" and not set(expected.split(",")) & set(actual):
                        raise ConnectorError("openrouter_response_scope_mismatch")
            catalog.append(record)
        observations.extend(batch.observations)
        price_exclusions.extend(batch.coverage["price_exclusions"])
        pages.append(raw.metadata())
        warnings.extend(batch.warnings)
        links = payload.get("links")
        if links is None:
            warnings.append("provider_pagination_metadata_missing_completeness_unknown")
            break
        if not isinstance(links, dict) or "next" not in links or (links["next"] is not None and not isinstance(links["next"], str)):
            raise ConnectorError("openrouter_pagination_shape_changed")
        if links["next"] is None:
            complete = True
            if reported_total is not None and current_offset + len(payload["data"]) != reported_total:
                raise ConnectorError("openrouter_inconsistent_terminal_count")
            break
        candidate = ReadRequest(SOURCE_SPECS[SOURCE_ID], urllib.parse.urljoin("https://openrouter.ai", links["next"]))
        parts = candidate.validate()
        next_query = dict(urllib.parse.parse_qsl(parts.query))
        if set(next_query) != set(query) or any(next_query[key] != value for key, value in query.items() if key != "offset"):
            raise ConnectorError("openrouter_pagination_scope_changed")
        try:
            next_offset = int(next_query["offset"])
        except (KeyError, ValueError):
            raise ConnectorError("openrouter_pagination_cursor_invalid") from None
        if str(next_offset) != next_query["offset"] or next_offset != current_offset + len(payload["data"]) or next_offset <= current_offset or next_offset > MAX_OFFSET:
            raise ConnectorError("openrouter_pagination_cursor_invalid")
        current_offset, request = next_offset, candidate
    if not complete:
        warnings.append("partial_scoped_catalog_not_full_model_index")
    if "catalog_population_changed_during_pagination" in warnings:
        complete = False
    metadata = {**pages[0], "pages": pages, "total_bytes": total_bytes,
        "sha256": hashlib.sha256("|".join(item["sha256"] for item in pages).encode()).hexdigest(),
        "sha256_scope": "ordered_page_content_hashes", "raw_body_retained": False}
    return ConnectorBatch(SOURCE_ID, metadata, tuple(observations), tuple(catalog),
        warnings=tuple(dict.fromkeys(warnings)), coverage={"complete": complete,
            "completion_basis": "provider_next_page_contract" if complete else "bounded_partial_or_missing_pagination_metadata",
            "scope": {key: value for key, value in options.items() if key != "max_pages"},
            "initial_offset": options["offset"], "reported_total_count": reported_total,
            "request_count": len(pages), "rows_received": len(catalog), "rows_accepted": len(catalog),
            "maximum_records": options["limit"] * options["max_pages"], "pagination_truncated": not complete,
            "gpu_hour_benchmark_eligible": False, "all_model_universe": False,
            "price_coverage_complete": complete and all(row["price_status"] == "advertised_token_rates" for row in catalog),
            "models_with_token_rates": sum(row["price_eligible"] for row in catalog),
            "models_without_token_rates": sum(not row["price_eligible"] for row in catalog),
            "models_with_partial_token_rates": sum(row["price_status"] == "partial_token_rates" for row in catalog),
            "invalid_price_model_count": len(price_exclusions),
            "invalid_price_dimension_count": sum(len(row["invalid_dimensions"]) for row in price_exclusions),
            "price_exclusions": price_exclusions,
            "admission_scope": "local_catalog_cost_comparison_no_access_resale_or_raw_redistribution"})
