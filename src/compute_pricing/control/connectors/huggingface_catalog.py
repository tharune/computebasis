"""Anonymous public deployment-recipe discovery; never a deployment adapter.

Recipes are publisher claims, not benchmark, model-license, capacity or price
approval. No executable configuration, environment variables or raw rows are
retained, and no weights or serving endpoint is accessed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import urllib.parse
from typing import Any, Mapping

from .transport import ConnectorError, RawResponse, ReadOnlyTransport, ReadRequest, SOURCE_SPECS, SourcePolicy, parse_utc, utc_string

SOURCE_ID = "huggingface_catalog"
MAX_MODELS, MAX_RECIPES, MAX_RECIPES_PER_MODEL = 100, 500, 64
# Versioned query semantics, not model IDs or economic assumptions.
ACCELERATORS = frozenset({"cpu", "gpu", "neuron"})
ENGINES = frozenset({"llamacpp", "tei", "vllm", "sglang"})
TASKS = frozenset({"any-to-any", "audio-classification", "automatic-speech-recognition", "custom",
    "feature-extraction", "fill-mask", "image-classification", "image-segmentation", "image-text-to-text",
    "object-detection", "question-answering", "sentence-similarity", "summarization", "table-question-answering",
    "text-classification", "text-generation", "text-ranking", "text-to-image", "token-classification", "translation",
    "zero-shot-classification"})


def _text(value: Any, code: str, *, maximum=256, optional=False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ConnectorError(code)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ConnectorError(code) from None
    return value


def catalog_filters(filters: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(filters, Mapping) or set(filters) - {"task", "accelerator", "engine", "license", "search", "limit"}:
        raise ConnectorError("recipe_catalog_explicit_scope_required")
    options = dict(filters)
    if not any(key in options for key in ("task", "accelerator", "engine", "license", "search")):
        raise ConnectorError("recipe_catalog_explicit_scope_required")
    if type(options.get("limit")) is not int or not 1 <= options["limit"] <= MAX_MODELS:
        raise ConnectorError("recipe_catalog_limit_invalid")
    for key, values in (("task", TASKS), ("accelerator", ACCELERATORS), ("engine", ENGINES)):
        if key in options and (not isinstance(options[key], str) or options[key] not in values):
            raise ConnectorError("recipe_catalog_filter_not_admitted")
    for key in ("license", "search"):
        if key in options:
            _text(options[key], "recipe_catalog_filter_invalid", maximum=128)
    return options


def catalog_request(filters: Mapping[str, Any] | None) -> ReadRequest:
    query = urllib.parse.urlencode(catalog_filters(filters))
    return ReadRequest(SOURCE_SPECS[SOURCE_ID], "https://endpoints.huggingface.co/api/v1/catalog/list?" + query)


def parse_catalog(raw: RawResponse, policy: SourcePolicy, *, filters: Mapping[str, Any]):
    from .adapters import ConnectorBatch, _permission, json_payload
    if raw.source_id != SOURCE_ID or policy.source_id != SOURCE_ID:
        raise ConnectorError("source_policy_mismatch")
    captured = parse_utc(raw.captured_at)
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, captured)
    options, payload = catalog_filters(filters), json_payload(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or len(payload["items"]) > options["limit"]:
        raise ConnectorError("recipe_catalog_shape_or_limit_changed")
    records, seen_models, seen_recipes, exclusions = [], set(), set(), []
    recipe_count = 0
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise ConnectorError("recipe_catalog_model_invalid")
        if item.get("private") is not None and type(item["private"]) is not bool:
            raise ConnectorError("recipe_catalog_visibility_invalid")
        if item.get("private") is True:
            raise ConnectorError("private_recipe_catalog_not_admitted")
        model_id = _text(item.get("repoId"), "recipe_catalog_identity_invalid")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", model_id) or model_id in seen_models:
            raise ConnectorError("recipe_catalog_identity_invalid")
        seen_models.add(model_id)
        name = _text(item.get("modelName"), "recipe_catalog_label_invalid")
        author = _text(item.get("authorName"), "recipe_catalog_label_invalid")
        license_name = _text(item.get("license"), "recipe_catalog_license_invalid")
        task = _text(item.get("task"), "recipe_catalog_task_invalid")
        if any(options[key] != actual for key, actual in (("task", task), ("license", license_name)) if key in options):
            raise ConnectorError("recipe_catalog_response_scope_mismatch")
        created = parse_utc(item.get("createdAt"))
        if created > captured:
            raise ConnectorError("recipe_catalog_future_source_time")
        recipes = item.get("recipes")
        if not isinstance(recipes, list) or len(recipes) > MAX_RECIPES_PER_MODEL:
            raise ConnectorError("recipe_catalog_recipe_shape_or_budget")
        recipe_count += len(recipes)
        if recipe_count > MAX_RECIPES:
            raise ConnectorError("recipe_catalog_recipe_budget")
        selected = []
        for recipe in recipes:
            if not isinstance(recipe, dict):
                raise ConnectorError("recipe_catalog_recipe_invalid")
            recipe_id = _text(recipe.get("publicId"), "recipe_catalog_recipe_identity_invalid", maximum=128)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", recipe_id) or recipe_id in seen_recipes:
                raise ConnectorError("recipe_catalog_recipe_identity_invalid")
            seen_recipes.add(recipe_id)
            accelerator = _text(recipe.get("accelerator"), "recipe_catalog_recipe_label_invalid")
            engine = _text(recipe.get("engineType"), "recipe_catalog_recipe_label_invalid")
            revision = _text(recipe.get("revision"), "recipe_catalog_revision_invalid", optional=True)
            gguf_file = _text(recipe.get("ggufFile"), "recipe_catalog_gguf_invalid", maximum=1024, optional=True)
            if any(options[key] != actual for key, actual in (("accelerator", accelerator), ("engine", engine)) if key in options):
                exclusions.append({"model_id": model_id, "recipe_id": recipe_id, "reason": "outside_requested_recipe_scope"})
                continue
            selected.append({"recipe_id": recipe_id, "accelerator": accelerator, "engine": engine,
                "gguf_file": gguf_file, "repository_revision": revision,
                "revision_is_immutable_commit_claim": bool(revision and re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", revision)),
                "unknown_field_names": sorted(set(recipe) - {"publicId", "accelerator", "engineType", "ggufFile", "revision"}),
                "price": None, "physical_accelerator_count": None, "performance_verified": False,
                "qualification_verified": False, "execution_enabled": False})
        records.append({"id": "recipe-model-" + hashlib.sha256(model_id.encode()).hexdigest()[:24],
            "source_id": SOURCE_ID, "source_version": "public-model-recipes/1.0", "kind": "model_recipe_metadata",
            "model_id": model_id, "name": name, "author": author, "license_claim": license_name, "task": task,
            "catalog_created_at": utc_string(created), "observed_at": raw.captured_at, "ingested_at": raw.captured_at,
            "expires_at": utc_string(captured + dt.timedelta(seconds=policy.max_age_s)), "status": "claimed",
            "recipes": selected, "price": None, "price_eligible": False, "gpu_hour_benchmark_eligible": False,
            "qualification_verified": False, "execution_enabled": False,
            "model_license_status": "catalog_license_label_not_permission_review",
            "admission_scope": "public_recipe_metadata_local_discovery_no_deployment_or_raw_redistribution",
            "rights": _permission(policy), "attribution": policy.attribution,
            "evidence": {"artifact_sha256": raw.sha256, "locator": raw.endpoint_path, "accessed_at": raw.captured_at},
            "unknown_field_names": sorted(set(item) - {"repoId", "modelName", "authorName", "license", "task", "createdAt", "recipes"})})
    return ConnectorBatch(SOURCE_ID, {**raw.metadata(), "raw_body_retained": False}, (), tuple(records), warnings=(
        "publisher_recipe_claims_not_independent_performance_or_model_license_approval",
        "catalog_metadata_contains_no_price_capacity_or_physical_gpu_count",
        "single_bounded_response_not_complete_model_catalog"), coverage={"complete": False,
            "scope": options, "request_count": 1, "models_received": len(payload["items"]), "models_accepted": len(records),
            "rows_received": len(payload["items"]), "rows_accepted": len(records), "maximum_models": options["limit"],
            "recipes_received": recipe_count, "recipes_selected": sum(len(row["recipes"]) for row in records),
            "maximum_recipes": MAX_RECIPES, "recipe_exclusions": exclusions,
            "completion_basis": "bounded_no_verified_pagination_contract", "all_model_universe": False,
            "compute_price_observations": 0, "gpu_hour_benchmark_eligible": False})


def collect_catalog(policy: SourcePolicy, transport: ReadOnlyTransport, filters: Mapping[str, Any] | None):
    if policy.source_id != SOURCE_ID:
        raise ConnectorError("source_policy_mismatch")
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, transport.clock())
    options = catalog_filters(filters)
    raw = transport.fetch(catalog_request(options), policy)
    return parse_catalog(raw, policy, filters=options)
