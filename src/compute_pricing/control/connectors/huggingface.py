"""Bounded public model metadata discovery; no prices, weights or qualification."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from decimal import Decimal
from typing import Any, Mapping

from .transport import ConnectorError, RawResponse, SourcePolicy, parse_utc, utc_string

MAX_MODELS = 100
SOURCE_VERSION = "public-model-metadata/1.0"


def huggingface_query(filters: Mapping[str, Any] | None) -> dict[str, str]:
    """Explicit author/LLM discovery scope; no authenticated or file routes."""
    if not isinstance(filters, Mapping) or set(filters) != {"author", "pipeline_tag", "limit", "full"}:
        raise ConnectorError("model_metadata_explicit_scope_required")
    author = filters["author"]
    if not isinstance(author, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", author):
        raise ConnectorError("model_metadata_author_invalid")
    if filters["pipeline_tag"] != "text-generation":
        raise ConnectorError("model_metadata_pipeline_scope_not_admitted")
    if type(filters["limit"]) is not int or not 1 <= filters["limit"] <= MAX_MODELS:
        raise ConnectorError("model_metadata_limit_invalid")
    if filters["full"] is not True and filters["full"] != "true":
        raise ConnectorError("model_metadata_full_scope_required")
    return {"author": author, "pipeline_tag": "text-generation", "limit": str(filters["limit"]), "full": "true"}


def _decode(raw: RawResponse):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ConnectorError("model_metadata_duplicate_json_key")
            result[key] = value
        return result
    def invalid(_):
        raise ConnectorError("model_metadata_nonfinite_json")
    try:
        return json.loads(raw.body.decode("utf-8"), object_pairs_hook=pairs, parse_float=Decimal, parse_constant=invalid)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ConnectorError):
            raise
        raise ConnectorError("model_metadata_invalid_json") from None


def _timestamp(value: Any, *, captured: dt.datetime) -> str | None:
    if value is None:
        return None
    parsed = parse_utc(value)
    if parsed > captured:
        raise ConnectorError("model_metadata_future_repository_time")
    return utc_string(parsed)


def parse_huggingface(raw: RawResponse, policy: SourcePolicy):
    """Catalog rights cover discovery only, never model licensing or serving.

    A fresh catalog snapshot can describe an unchanged older repository. Its
    capture time is the metadata observation time; repository modification time
    remains a distinct source field and is not a performance measurement.
    """
    # Lazy import avoids a registration cycle with the adapter dispatcher.
    from .adapters import ConnectorBatch, _permission
    if raw.source_id != "huggingface" or policy.source_id != "huggingface":
        raise ConnectorError("source_policy_mismatch")
    captured = parse_utc(raw.captured_at)
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, captured)
    payload = _decode(raw)
    if not isinstance(payload, list) or len(payload) > MAX_MODELS:
        raise ConnectorError("model_metadata_shape_or_budget_changed")
    seen, catalog = set(), []
    for item in payload:
        if not isinstance(item, dict):
            raise ConnectorError("model_metadata_record_invalid")
        model_id = item.get("id")
        if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?", model_id) or len(model_id) > 256:
            raise ConnectorError("model_metadata_identity_invalid")
        if model_id in seen:
            raise ConnectorError("model_metadata_duplicate_identity")
        seen.add(model_id)
        private = item.get("private")
        if private is not None and type(private) is not bool:
            raise ConnectorError("model_metadata_visibility_invalid")
        if private is True:
            # Unexpected private content is not retained or returned by this source.
            raise ConnectorError("private_model_metadata_not_admitted")
        gated = item.get("gated")
        if gated is not None and not (type(gated) is bool or isinstance(gated, str) and gated in {"auto", "manual"}):
            raise ConnectorError("model_metadata_gating_invalid")
        tags = item.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 1024 or any(not isinstance(tag, str) or len(tag) > 256 for tag in tags):
            raise ConnectorError("model_metadata_tags_invalid")
        card = item.get("cardData")
        if card is not None and not isinstance(card, dict):
            raise ConnectorError("model_metadata_card_invalid")
        for field in ("author", "pipeline_tag", "library_name", "sha"):
            if item.get(field) is not None and (not isinstance(item[field], str) or len(item[field]) > 256):
                raise ConnectorError("model_metadata_label_invalid")
        modified = _timestamp(item.get("lastModified"), captured=captured)
        created = _timestamp(item.get("createdAt"), captured=captured)
        if created is not None and modified is not None and parse_utc(created) > parse_utc(modified):
            raise ConnectorError("model_metadata_repository_time_inverted")
        license_tags = [tag[len("license:"):] for tag in tags if tag.startswith("license:")]
        record = {
            "id": "huggingface-" + hashlib.sha256(model_id.encode()).hexdigest()[:24],
            "source_id": "huggingface", "source_version": SOURCE_VERSION,
            "kind": "model_metadata", "model_id": model_id, "author": item.get("author"),
            "pipeline_tag": item.get("pipeline_tag"), "library_name": item.get("library_name"),
            "repository_revision": item.get("sha"), "repository_last_modified_at": modified,
            "repository_created_at": created, "observed_at": raw.captured_at,
            "ingested_at": raw.captured_at, "expires_at": utc_string(captured + dt.timedelta(seconds=policy.max_age_s)),
            "private": private, "gated": gated, "license_tags": license_tags,
            "card_license": card.get("license") if card is not None else None,
            "card_metadata": card, "tags": tags, "price": None, "status": "claimed",
            "price_eligible": False, "qualification_verified": False, "execution_enabled": False,
            "model_license_status": "declared_metadata_not_independent_permission_review",
            "rights": _permission(policy), "admission_scope": "public_catalog_metadata_discovery_only",
            "evidence": {"artifact_sha256": raw.sha256, "locator": raw.endpoint_path, "accessed_at": raw.captured_at},
            "extensions": {"source_row": dict(item), "attribution": policy.attribution,
                           "unknown_fields_unpriced": True, "weights_or_private_files_downloaded": False},
        }
        catalog.append(record)
    return ConnectorBatch("huggingface", raw.metadata(), (), tuple(catalog), warnings=(
        "public_model_metadata_not_compute_price_or_runtime_qualification",
        "model_card_license_and_gating_require_separate_permission_review",
        "single_bounded_response_not_complete_global_or_author_catalog"), coverage={
            "complete": False, "coverage_kind": "bounded_public_model_metadata_response",
            "rows_received": len(payload), "rows_accepted": len(catalog), "maximum_records": MAX_MODELS,
            "cap_reached_possible": bool(payload), "pagination_status": "not_followed_or_verified",
            "request_count": 1, "all_models": False, "compute_price_observations": 0})
