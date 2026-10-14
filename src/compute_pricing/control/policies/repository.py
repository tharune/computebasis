"""Immutable local policy versions with optimistic concurrency and exact numbers."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re

from compute_pricing.control.benchmark import evaluate_benchmark
from compute_pricing.control.domain import FeatureRegistry, ValidationError, parse_feature_definition, parse_policy_snapshot
from compute_pricing.control.reporting import SnapshotStore

BENCHMARK_FIELDS = {"estimator", "max_source_share", "max_provider_share", "min_observations", "min_sources", "min_provider_groups", "source_rules"}
RULE_FIELDS = {"enabled", "quality", "max_age_hours", "half_life_hours"}
MAX_BYTES = 262144
MAX_VERSIONS = 10000


class PolicyConflict(ValueError):
    """A version or predecessor does not match the immutable local policy head."""


class PolicyStoreError(RuntimeError):
    """Stored configuration failed its integrity or contract checks."""


def _encoded(value):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise ValidationError("policy_document_size_limit")
        return text
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("invalid_policy_document") from None


def validate_document(document):
    """Register feature ownership and benchmark controls without pricing new factors."""
    if not isinstance(document, dict) or set(document) != {"policy", "feature_definitions", "notes"}:
        raise ValidationError("policy_document_fields_required")
    if not isinstance(document["notes"], str) or len(document["notes"]) > 4096:
        raise ValidationError("bounded_policy_notes_required")
    definitions = document["feature_definitions"]
    if not isinstance(definitions, list) or len(definitions) > 256:
        raise ValidationError("bounded_feature_definitions_required")
    _encoded(document)
    policy = parse_policy_snapshot(document["policy"])
    _version(policy.version)
    _version(policy.registry_version)
    if policy.model_version != "inverse-linear/1.0.0":
        raise ValidationError("unsupported_pricing_model")
    parameters = policy.to_dict()["parameters"]
    if set(parameters) != {"benchmark"} or not isinstance(parameters["benchmark"], dict):
        raise ValidationError("explicit_benchmark_parameters_required")
    benchmark = parameters["benchmark"]
    if set(benchmark) != BENCHMARK_FIELDS:
        raise ValidationError("unsupported_benchmark_parameter")
    rules = benchmark["source_rules"]
    if not isinstance(rules, dict) or len(rules) > 128 or any(not isinstance(rule, dict) or set(rule) != RULE_FIELDS for rule in rules.values()):
        raise ValidationError("bounded_explicit_source_rules_required")
    # The real kernel validates the exact control ranges. Empty evidence cannot
    # manufacture a benchmark or activate a calibrated policy.
    evaluate_benchmark([], {"scope": "aggregate_reference", "hardware_model": "policy-validation",
                           "currency": "USD", "gpu_count": "1", "duration_hours": "1"}, benchmark, policy.effective_at)
    parsed = tuple(parse_feature_definition(definition) for definition in definitions)
    registry = FeatureRegistry(policy.registry_version, parsed)
    if not set(policy.critical_feature_ids) <= {definition.feature_id for definition in registry.definitions}:
        raise ValidationError("critical_feature_definition_required")
    normalized = {"policy": policy.to_dict(), "feature_definitions": [definition.to_dict() for definition in parsed], "notes": document["notes"]}
    _encoded(normalized)
    return {"document": normalized, "calibration_state": "unvalidated", "execution_enabled": False,
            "warnings": ["source_weights_and_thresholds_are_caller_policy_not_calibrated_estimates",
                         "feature_registration_does_not_activate_monetary_effects",
                         "source_rules_do_not_grant_observe_retain_or_execution_rights"]}


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value) or len(value) > 32:
        raise ValidationError("bounded_semantic_version_required")
    return tuple(int(part) for part in value.split("."))


class PolicyRepository:
    def __init__(self, path: Path):
        # Reuse the existing external-only path, file permissions and connections.
        self.store = SnapshotStore(path)
        with self.store._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS policy_documents (sequence INTEGER PRIMARY KEY, policy_id TEXT NOT NULL, version TEXT NOT NULL, revision TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, document TEXT NOT NULL, UNIQUE(policy_id,version))")
            connection.execute("CREATE TRIGGER IF NOT EXISTS policies_no_update BEFORE UPDATE ON policy_documents BEGIN SELECT RAISE(ABORT,'policies_append_only'); END")
            connection.execute("CREATE TRIGGER IF NOT EXISTS policies_no_delete BEFORE DELETE ON policy_documents BEGIN SELECT RAISE(ABORT,'policies_append_only'); END")

    def _entry(self, row):
        if row is None:
            return None
        try:
            revision, created, raw, indexed_id, indexed_version = row
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != revision:
                raise ValueError("invalid_hash")
            document = json.loads(raw)
            if _encoded(document) != raw:
                raise ValueError("invalid_canonical_document")
            validated = validate_document(document)
            policy = document["policy"]
            if indexed_id != policy["policy_id"] or indexed_version != policy["version"]:
                raise ValueError("invalid_indexed_metadata")
        except (ValueError, TypeError, KeyError, ArithmeticError, UnicodeError, RecursionError):
            raise PolicyStoreError("policy_integrity_failed") from None
        return {"revision": revision, "created_at": created, "policy_id": policy["policy_id"], "version": policy["version"], **validated}

    def get(self, revision):
        if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValidationError("invalid_policy_revision")
        with self.store._connect() as connection:
            row = connection.execute("SELECT revision,created_at,document,policy_id,version FROM policy_documents WHERE revision=?", (revision,)).fetchone()
        return self._entry(row)

    def list(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError("invalid_policy_list_limit")
        with self.store._connect() as connection:
            rows = connection.execute("SELECT revision,created_at,document,policy_id,version FROM policy_documents ORDER BY sequence DESC LIMIT ?", (limit + 1,)).fetchall()
        return {"entries": [self._entry(row) for row in rows[:limit]], "limit": limit, "truncated": len(rows) > limit, "execution_enabled": False}

    def save(self, document, *, expected_revision):
        if expected_revision is not None and (not isinstance(expected_revision, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_revision)):
            raise ValidationError("invalid_policy_predecessor")
        checked = validate_document(document)
        normalized = checked["document"]
        policy = normalized["policy"]
        version = _version(policy["version"])
        raw = _encoded(normalized)
        revision = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT revision,created_at,document,policy_id,version FROM policy_documents WHERE (policy_id=? OR json_extract(document,'$.policy.policy_id')=?) AND (version=? OR json_extract(document,'$.policy.version')=?)", (policy["policy_id"], policy["policy_id"], policy["version"], policy["version"])).fetchone()
            if existing:
                entry = self._entry(existing)
                if existing[0] != revision or existing[2] != raw:
                    raise PolicyConflict("policy_version_is_immutable")
                return {**entry, "status": "existing"}
            prior = connection.execute("SELECT revision,created_at,document,policy_id,version FROM policy_documents WHERE policy_id=? OR json_extract(document,'$.policy.policy_id')=? ORDER BY sequence DESC LIMIT 1", (policy["policy_id"], policy["policy_id"])).fetchone()
            # Resolve and verify the expected predecessor by its content hash too;
            # an altered index must not hide the caller's current head.
            expected = connection.execute("SELECT revision,created_at,document,policy_id,version FROM policy_documents WHERE revision=?", (expected_revision,)).fetchone() if expected_revision else None
            if expected:
                self._entry(expected)
            previous = self._entry(prior)["document"] if prior else None
            if (prior[0] if prior else None) != expected_revision:
                raise PolicyConflict("policy_predecessor_changed")
            if previous and _version(previous["policy"]["version"]) >= version:
                raise PolicyConflict("policy_successor_version_required")
            if previous:
                old_registry = _version(previous["policy"]["registry_version"])
                new_registry = _version(policy["registry_version"])
                if new_registry < old_registry or previous["feature_definitions"] != normalized["feature_definitions"] and new_registry <= old_registry:
                    raise PolicyConflict("feature_changes_require_successor_registry_version")
            if connection.execute("SELECT count(*) FROM policy_documents").fetchone()[0] >= MAX_VERSIONS:
                raise ValidationError("policy_history_limit")
            connection.execute("INSERT INTO policy_documents(policy_id,version,revision,created_at,document) VALUES(?,?,?,?,?)", (policy["policy_id"], policy["version"], revision, now, raw))
        return {**self._entry((revision, now, raw, policy["policy_id"], policy["version"])), "status": "saved"}
