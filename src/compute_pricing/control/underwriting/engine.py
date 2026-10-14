"""Bounded dynamic evidence completeness, independent of financial eligibility.

Verified is a caller assertion backed by qualified evidence pointers. This code
does not authenticate documents, grant permissions, interpret legal terms,
estimate creditworthiness, or activate any factor in a monetary calculation.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from decimal import Decimal
import re
from typing import Any

from compute_pricing.control._numbers import canonical_json, digest
from compute_pricing.control.domain import ValidationError, exact_decimal, parse_evidence_ref, utc_instant
from compute_pricing.control.domain.spec import ID_PATTERN, OWNING_PATHS, VERSION_PATTERN

SCHEMA_VERSION = "underwriting-assessment/1.0"
MODEL_VERSION = "declared-evidence-coverage/1.0.0"
SCOPE_OPTIONS = ("inference", "resale", "forward", "hedging", "securitization")
STATUSES = ("declared", "verified", "missing", "stale", "conflicted", "invalid", "not_applicable")
MAX_REQUIREMENTS = 256
MAX_BYTES = 524288
_ID = re.compile(ID_PATTERN)


def _fail(code):
    raise ValidationError("underwriting:" + code)


def _id(value):
    if not isinstance(value, str) or len(value) > 128 or not _ID.fullmatch(value):
        _fail("canonical_id_required")
    return value


def _text(value, *, maximum=2048, nonempty=True):
    if not isinstance(value, str) or len(value) > maximum or nonempty and not value.strip():
        _fail("bounded_text_required")
    return value


def _tree(value, depth=0, budget=None):
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > 30000 or depth > 20:
        _fail("input_tree_limit")
    if isinstance(value, dict):
        for key, item in value.items():
            _text(key, maximum=2048)
            _tree(item, depth + 1, budget)
    elif isinstance(value, list):
        for item in value:
            _tree(item, depth + 1, budget)
    elif isinstance(value, str):
        _text(value, maximum=16384, nonempty=False)
    elif value is not None and type(value) not in {bool, int}:
        _fail("exact_json_values_required")
    elif type(value) is int and abs(value) > 2147483647:
        _fail("bounded_integer_required")


def _record(raw, fields, required):
    if not isinstance(raw, dict) or not set(required) <= set(raw):
        _fail("record_fields_required")
    extensions = raw.get("extensions", {})
    if not isinstance(extensions, dict):
        _fail("extensions_object_required")
    extensions = dict(extensions)
    for key in set(raw) - set(fields) - {"extensions"}:
        if key in extensions:
            _fail("extension_collision")
        extensions[key] = raw[key]
    return {**{key: raw[key] for key in fields if key in raw}, "extensions": extensions}


def _unique_ids(values, *, allow_empty=False):
    if not isinstance(values, list) or len(values) > 64 or not values and not allow_empty:
        _fail("bounded_id_list_required")
    parsed = [_id(value) for value in values]
    if len(set(parsed)) != len(parsed):
        _fail("duplicate_identity")
    return parsed


def _definition(raw):
    fields = {"requirement_id", "ownership_id", "group", "title", "description", "scopes", "required", "value_type", "unit", "subject_kind", "owning_path", "owner_model", "evidence_scope", "allow_not_applicable", "minimum", "maximum", "allowed_values"}
    required = fields - {"ownership_id", "description", "minimum", "maximum", "allowed_values"}
    row = _record(raw, fields, required)
    for key in ("requirement_id", "group", "subject_kind", "owner_model"):
        _id(row[key])
    row["ownership_id"] = _id(row.get("ownership_id", row["requirement_id"]))
    _text(row["title"], maximum=256)
    row["description"] = _text(row.get("description", row["title"]))
    row["scopes"] = _unique_ids(row["scopes"])
    if type(row["required"]) is not bool or type(row["allow_not_applicable"]) is not bool:
        _fail("explicit_boolean_required")
    if row["value_type"] not in {"decimal", "integer", "string", "boolean"} or row["owning_path"] not in OWNING_PATHS:
        _fail("typed_ownership_required")
    if row["unit"] is not None:
        _text(row["unit"], maximum=128)
    row["evidence_scope"] = _unique_ids(row["evidence_scope"])
    for key in ("minimum", "maximum"):
        if row.get(key) is not None:
            exact_decimal(row[key])
            if row["value_type"] not in {"decimal", "integer"}:
                _fail("numeric_bounds_require_numeric_type")
    if row.get("minimum") is not None and row.get("maximum") is not None and Decimal(row["minimum"]) > Decimal(row["maximum"]):
        _fail("inverted_bounds")
    categories = row.get("allowed_values", [])
    if not isinstance(categories, list) or len(categories) > 64:
        _fail("bounded_categories_required")
    for category in categories:
        _text(category, maximum=512)
    if len(set(categories)) != len(categories) or categories and row["value_type"] != "string":
        _fail("unambiguous_string_categories_required")
    row["allowed_values"] = categories
    return row


def _value_blockers(value, unit, definition):
    if value is None:
        return ["missing_value"]
    if unit != definition["unit"]:
        return ["registered_unit_mismatch"]
    kind = definition["value_type"]
    try:
        if kind in {"decimal", "integer"}:
            number = exact_decimal(value)
            if kind == "integer" and number != number.to_integral_value():
                return ["whole_decimal_string_required"]
            if definition.get("minimum") is not None and number < Decimal(definition["minimum"]):
                return ["below_registered_bound"]
            if definition.get("maximum") is not None and number > Decimal(definition["maximum"]):
                return ["above_registered_bound"]
        elif kind == "boolean":
            if type(value) is not bool:
                return ["registered_boolean_required"]
        elif not isinstance(value, str) or not value.strip():
            return ["registered_nonempty_string_required"]
        elif definition["allowed_values"] and value not in definition["allowed_values"]:
            return ["outside_registered_categories"]
    except ValidationError:
        return ["exact_decimal_string_required"]
    return []


def _evidence_record(raw):
    fields = {"requirement_id", "subject_id", "status", "value", "unit", "valid_from", "valid_until", "reviewed_by", "evidence", "not_applicable_reason"}
    row = _record(raw, fields, {"requirement_id", "status"})
    _id(row["requirement_id"])
    if row["status"] not in STATUSES:
        _fail("unsupported_evidence_status")
    for key in ("subject_id", "reviewed_by"):
        if row.get(key) is not None:
            _id(row[key])
    for key in ("valid_from", "valid_until"):
        if row.get(key) is not None:
            utc_instant(row[key])
    if row.get("valid_from") is not None and row.get("valid_until") is not None and utc_instant(row["valid_from"]) >= utc_instant(row["valid_until"]):
        _fail("positive_evidence_interval_required")
    if row.get("unit") is not None:
        _text(row["unit"], maximum=128)
    if row.get("not_applicable_reason") is not None:
        _text(row["not_applicable_reason"])
    refs = row.get("evidence", [])
    if not isinstance(refs, list) or len(refs) > 8:
        _fail("bounded_evidence_refs_required")
    row["evidence"] = [parse_evidence_ref(ref).to_dict() for ref in refs]
    ids = [ref["id"] for ref in row["evidence"]]
    if len(set(ids)) != len(ids):
        _fail("duplicate_evidence_ref")
    return row


def _qualified_refs(refs, definition, subject, now):
    qualified, findings = [], []
    required_scope = set(definition["evidence_scope"]) | {"subject:" + subject}
    for raw in refs:
        reasons = []
        if raw["status"] != "verified" or not raw.get("artifact_sha256") or not raw.get("verifier"):
            reasons.append("evidence_verification_or_artifact_missing")
        if utc_instant(raw["accessed_at"]) > now or raw.get("event_at") and utc_instant(raw["event_at"]) > now:
            reasons.append("future_evidence")
        if raw.get("expires_at") is None:
            reasons.append("evidence_expiry_missing")
        elif utc_instant(raw["expires_at"]) <= now:
            reasons.append("expired_evidence")
        if not required_scope <= set(raw["scope"]):
            reasons.append("evidence_scope_or_subject_mismatch")
        permission = raw.get("permission")
        if (not permission or permission["status"] != "allowed" or permission["observe"] != "PASS"
                or permission["retain"] != "PASS" or not permission.get("verified_by")):
            reasons.append("evidence_observe_retain_rights_not_qualified")
        elif permission.get("expires_at") and utc_instant(permission["expires_at"]) <= now:
            reasons.append("expired_evidence_permission")
        if not reasons:
            qualified.append(raw["id"])
        findings.append({"evidence_id": raw["id"], "blockers": reasons})
    return qualified, findings


def assess_underwriting(payload: dict[str, Any]) -> dict[str, Any]:
    """Assess caller-defined completeness at one UTC instant, without persistence."""
    _tree(payload)
    if len(canonical_json(payload).encode("utf-8")) > MAX_BYTES:
        _fail("input_size_limit")
    fields = {"schema_version", "request_id", "as_of", "requirements_version", "scopes", "subjects", "requirements", "evidence"}
    request = _record(payload, fields, fields)
    if request["schema_version"] != SCHEMA_VERSION:
        _fail("unsupported_schema")
    _id(request["request_id"])
    _text(request["requirements_version"], maximum=40)
    if not re.fullmatch(VERSION_PATTERN, request["requirements_version"]):
        _fail("semantic_requirements_version_required")
    now = utc_instant(request["as_of"])
    scopes = set(_unique_ids(request["scopes"]))
    if not isinstance(request["subjects"], dict) or len(request["subjects"]) > 64:
        _fail("bounded_subjects_required")
    subjects = {_id(kind): _id(subject) for kind, subject in request["subjects"].items()}
    for key in ("requirements", "evidence"):
        if not isinstance(request[key], list) or len(request[key]) > MAX_REQUIREMENTS:
            _fail("bounded_requirements_and_evidence_required")
    if not request["requirements"]:
        _fail("nonempty_requirements_required")
    definitions = [_definition(raw) for raw in request["requirements"]]
    supplied = [_evidence_record(raw) for raw in request["evidence"]]
    ids = [row["requirement_id"] for row in definitions]
    owners = [row["ownership_id"] for row in definitions]
    supplied_ids = [row["requirement_id"] for row in supplied]
    if len(set(ids)) != len(ids) or len(set(owners)) != len(owners) or len(set(supplied_ids)) != len(supplied_ids):
        _fail("duplicate_requirement_evidence_or_ownership")
    refs_by_id = {}
    for row in supplied:
        for ref in row["evidence"]:
            encoded = canonical_json(ref)
            if ref["id"] in refs_by_id and refs_by_id[ref["id"]] != encoded:
                _fail("conflicting_evidence_ref_identity")
            refs_by_id[ref["id"]] = encoded
    by_id = {row["requirement_id"]: row for row in supplied}
    rows, blocked, summary = [], [], Counter()
    for definition in definitions:
        identity = definition["requirement_id"]
        evidence = by_id.get(identity)
        applicable = bool(scopes.intersection(definition["scopes"]))
        subject = subjects.get(definition["subject_kind"])
        row = {key: definition[key] for key in ("requirement_id", "ownership_id", "group", "title", "description", "required", "value_type", "unit", "subject_kind", "owning_path", "owner_model")}
        row.update(applicable=applicable, subject_id=subject, status="out_of_scope" if not applicable else "missing", blockers=[], value=deepcopy(evidence.get("value")) if evidence else None, supplied_unit=evidence.get("unit") if evidence else None, evidence_ids=[], evidence_findings=[], not_applicable_reason=evidence.get("not_applicable_reason") if evidence else None)
        if applicable:
            if subject is None:
                row["blockers"].append("missing_subject_identity")
            if evidence is None:
                row["blockers"].append("missing_requirement_evidence")
            else:
                row["status"] = evidence["status"]
                if evidence.get("subject_id") != subject or subject is None:
                    row["blockers"].append("evidence_subject_mismatch")
                if evidence["status"] in {"missing", "stale", "conflicted", "invalid", "declared"}:
                    row["blockers"].append("evidence_status:" + evidence["status"])
                if evidence["status"] != "not_applicable":
                    row["blockers"].extend(_value_blockers(evidence.get("value"), evidence.get("unit"), definition))
                elif (not definition["allow_not_applicable"] or not evidence.get("not_applicable_reason")
                      or not evidence["not_applicable_reason"].strip() or evidence.get("value") is not None):
                    row["blockers"].append("not_applicable_requires_allowed_reviewed_reason_and_null_value")
                if evidence.get("reviewed_by") is None:
                    row["blockers"].append("missing_review_owner")
                if evidence.get("valid_from") is None or evidence.get("valid_until") is None:
                    row["blockers"].append("missing_evidence_validity_interval")
                elif utc_instant(evidence["valid_from"]) > now:
                    row["blockers"].append("evidence_not_yet_valid")
                    row["status"] = "invalid"
                elif utc_instant(evidence["valid_until"]) <= now:
                    row["blockers"].append("expired_evidence_interval")
                    row["status"] = "stale"
                if subject is not None:
                    qualified, findings = _qualified_refs(evidence["evidence"], definition, subject, now)
                    row.update(evidence_ids=qualified, evidence_findings=findings)
                    if not qualified:
                        row["blockers"].append("no_current_scope_matching_qualified_evidence")
                        if findings and all(any(reason in {"expired_evidence", "expired_evidence_permission"} for reason in finding["blockers"]) for finding in findings):
                            row["status"] = "stale"
                if row["status"] in {"verified", "not_applicable"} and row["blockers"]:
                    row["status"] = "unverified"
            if definition["required"]:
                summary["required_total"] += 1
                if row["blockers"]:
                    summary["required_blocked"] += 1
                    blocked.append({"requirement_id": identity, "reasons": list(row["blockers"])})
                elif row["status"] == "not_applicable":
                    summary["required_not_applicable"] += 1
                else:
                    summary["required_covered"] += 1
            else:
                summary["optional_total"] += 1
        rows.append(row)
    empty_scopes = sorted(scope for scope in scopes if not any(scope in definition["scopes"] and definition["required"] for definition in definitions))
    if empty_scopes:
        blocked.append({"requirement_id": None, "reasons": ["scope_has_no_required_requirements:" + scope for scope in empty_scopes]})
    preserved = bool(request["extensions"] or any(row["extensions"] for row in definitions + supplied))
    result = {"schema_version": SCHEMA_VERSION, "status": "held" if blocked else "complete_for_declared_requirements",
              "request_id": request["request_id"], "as_of": request["as_of"], "scopes": sorted(scopes),
              "summary": {**{key: summary[key] for key in ("required_total", "required_covered", "required_not_applicable", "required_blocked", "optional_total")}, "by_status": dict(sorted(Counter(row["status"] for row in rows if row["applicable"]).items()))},
              "rows": rows, "blockers": blocked, "unused_evidence_ids": sorted(set(supplied_ids) - {row["requirement_id"] for row in rows if row["applicable"]}),
              "warnings": ["caller_verified_evidence_pointers_not_independent_authenticity_verification", "complete_only_for_declared_versioned_requirements_not_all_possible_risks", "covered_value_does_not_imply_substantive_eligibility_or_favorable_terms", "no_pricing_factor_calibration_or_monetary_activation", "not_a_firm_quote_or_execution_permission"],
              "versions": {"model": MODEL_VERSION, "schema": SCHEMA_VERSION, "requirements": request["requirements_version"]},
              "requirements_hash": digest(definitions),
              "execution_enabled": False, "monetary_effects_enabled": False, "persisted": False, "input_hash": digest(payload)}
    if preserved:
        result["warnings"].append("extensions_retained_in_input_hash_but_not_used_in_assessment")
    result["assessment_hash"] = digest(result)
    return result
