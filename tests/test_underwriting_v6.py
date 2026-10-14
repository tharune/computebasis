"""Independent synthetic completeness and authenticated boundary regressions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.underwriting import assess_underwriting, underwriting_template

KEY = "invented-underwriting-boundary-key-1234567890"
AUTH = {"Authorization": "Bearer " + KEY}
NOW = "2035-02-01T00:00:00Z"


def requirement(identity="supply:proof", **changes):
    return {"requirement_id": identity, "group": "supply", "title": "Invented supply requirement",
            "scopes": ["resale"], "required": True, "value_type": "decimal", "unit": "GiB",
            "subject_kind": "lot", "owning_path": "constraint", "owner_model": "review:supply",
            "evidence_scope": [identity], "allow_not_applicable": False, **changes}


def evidence(identity="supply:proof", **changes):
    return {"requirement_id": identity, "subject_id": "lot:invented", "status": "verified",
            "value": "48.13579135791357913579135791357", "unit": "GiB",
            "valid_from": "2035-01-01T00:00:00Z", "valid_until": "2035-03-01T00:00:00Z",
            "reviewed_by": "reviewer:invented", "evidence": [{"id": "evidence:" + identity,
                "source_id": "source:invented", "artifact_sha256": "a" * 64,
                "event_at": "2035-01-01T00:00:00Z", "accessed_at": "2035-01-02T00:00:00Z",
                "expires_at": "2035-03-01T00:00:00Z", "status": "verified", "verifier": "reviewer:invented",
                "scope": [identity, "subject:lot:invented"],
                "permission": {"status": "allowed", "observe": "PASS", "retain": "PASS",
                               "benchmark": "UNKNOWN", "execution": "FAIL", "verified_by": "rights:invented"}}],
            **changes}


def request():
    return {"schema_version": "underwriting-assessment/1.0", "request_id": "request:invented",
            "as_of": NOW, "requirements_version": "1.0.0", "scopes": ["resale"],
            "subjects": {"lot": "lot:invented"}, "requirements": [requirement()], "evidence": [evidence()]}


class UnderwritingV6Tests(unittest.TestCase):
    def test_exact_current_scoped_inputs_count_coverage_but_never_grant_authority(self):
        result = assess_underwriting(request())
        self.assertEqual(result["status"], "complete_for_declared_requirements")
        self.assertEqual(result["summary"]["required_covered"], 1)
        self.assertEqual(result["rows"][0]["value"], "48.13579135791357913579135791357")
        self.assertEqual(result["rows"][0]["evidence_ids"], ["evidence:supply:proof"])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["monetary_effects_enabled"])
        self.assertFalse(result["persisted"])
        self.assertIn("covered_value_does_not_imply_substantive_eligibility_or_favorable_terms", result["warnings"])
        self.assertEqual(result, assess_underwriting(request()))

    def test_catalog_covers_every_requested_family_and_each_scope_without_fake_inputs(self):
        template = underwriting_template()
        groups = {row["group"] for row in template["requirements"]}
        self.assertEqual(len(template["requirements"]), 112)
        self.assertEqual(len(groups), 17)
        self.assertTrue({"supplier", "buyer", "hardware", "facility", "operations", "geography", "security", "privacy", "inference", "forward", "risk", "hedging", "financing", "securitization", "attribution"} <= groups)
        self.assertIsNone(template["request"]["as_of"])
        self.assertEqual(template["request"]["subjects"], {})
        self.assertEqual(template["request"]["evidence"], [])
        for scope in template["scope_options"]:
            payload = template["request"]
            payload.update(request_id="request:empty", as_of=NOW, scopes=[scope])
            result = assess_underwriting(payload)
            self.assertEqual(result["status"], "held")
            self.assertGreater(result["summary"]["required_blocked"], 0)
            self.assertEqual(result["summary"]["required_covered"], 0)

    def test_template_and_results_are_detached_without_global_mutation(self):
        template = underwriting_template()
        template["requirements"][0]["title"] = "mutated"
        self.assertNotEqual(underwriting_template()["requirements"][0]["title"], "mutated")
        payload = request(); result = assess_underwriting(payload)
        result["rows"][0]["value"] = "mutated"
        self.assertEqual(payload, request())
        payload["evidence"][0]["value"] = {"invented": [1]}
        held = assess_underwriting(payload)
        self.assertEqual(held["status"], "held")
        held["rows"][0]["value"]["invented"][0] = 2
        self.assertEqual(payload["evidence"][0]["value"]["invented"], [1])

    def test_default_accelerator_count_is_positive_whole_and_retains_declared_coverage(self):
        count = next(row for row in underwriting_template()["requirements"] if row["requirement_id"] == "hardware:count")
        self.assertEqual(count["value_type"], "integer")
        self.assertEqual(count["minimum"], "1")
        payload = request(); payload["requirements"] = [count]
        payload["evidence"] = [evidence("hardware:count", unit="accelerators_per_node")]
        for value in ("0", "0.5"):
            payload["evidence"][0]["value"] = value
            self.assertEqual(assess_underwriting(payload)["status"], "held")
        payload["evidence"][0]["value"] = "1"
        self.assertEqual(assess_underwriting(payload)["summary"]["required_covered"], 1)

    def test_missing_unknown_declared_conflicted_and_invalid_remain_held(self):
        for status in ("declared", "missing", "conflicted", "invalid", "stale"):
            payload = request(); payload["evidence"][0]["status"] = status
            result = assess_underwriting(payload)
            self.assertEqual(result["status"], "held")
            self.assertEqual(result["summary"]["required_blocked"], 1)
        payload = request(); payload["evidence"] = []
        self.assertEqual(assess_underwriting(payload)["rows"][0]["status"], "missing")

    def test_zero_false_are_present_values_and_numeric_types_do_not_coerce(self):
        payload = request(); payload["evidence"][0]["value"] = "0"
        self.assertEqual(assess_underwriting(payload)["summary"]["required_covered"], 1)
        payload["requirements"][0].update(value_type="boolean", unit=None)
        payload["evidence"][0].update(value=False, unit=None)
        self.assertEqual(assess_underwriting(payload)["summary"]["required_covered"], 1)
        for value in (True, "1e3", "NaN", 24):
            payload = request(); payload["evidence"][0]["value"] = value
            self.assertEqual(assess_underwriting(payload)["status"], "held")
        payload = request(); payload["evidence"][0]["value"] = 24.5
        with self.assertRaises(ValidationError): assess_underwriting(payload)

    def test_unit_categories_integer_bounds_and_ownership_are_explicit(self):
        payload = request(); payload["evidence"][0]["unit"] = "GB"
        row = assess_underwriting(payload)["rows"][0]
        self.assertIn("registered_unit_mismatch", row["blockers"])
        self.assertEqual(row["unit"], "GiB")
        self.assertEqual(row["supplied_unit"], "GB")
        payload = request(); payload["requirements"][0].update(value_type="integer", minimum="25")
        self.assertEqual(assess_underwriting(payload)["status"], "held")
        payload["evidence"][0]["value"] = "24"
        self.assertIn("below_registered_bound", assess_underwriting(payload)["rows"][0]["blockers"])
        payload = request(); payload["requirements"][0].update(value_type="string", unit=None, allowed_values=["accepted", "rejected"])
        payload["evidence"][0].update(value="unknown", unit=None)
        self.assertEqual(assess_underwriting(payload)["status"], "held")
        payload["requirements"][0]["owning_path"] = "arbitrary_multiplier"
        with self.assertRaises(ValidationError): assess_underwriting(payload)

    def test_expired_future_intervals_and_refs_do_not_upcast_to_verified(self):
        mutations = (
            lambda row: row.update(valid_until=NOW),
            lambda row: row.update(valid_from="2035-02-02T00:00:00Z"),
            lambda row: row["evidence"][0].update(expires_at=NOW),
            lambda row: row["evidence"][0].update(accessed_at="2035-02-02T00:00:00Z"),
            lambda row: row["evidence"][0].update(event_at="2035-02-02T00:00:00Z"),
        )
        for mutate in mutations:
            payload = request(); mutate(payload["evidence"][0])
            self.assertEqual(assess_underwriting(payload)["status"], "held")
        payload = request(); payload["evidence"][0]["evidence"][0]["expires_at"] = NOW
        self.assertEqual(assess_underwriting(payload)["rows"][0]["status"], "stale")

    def test_rights_and_document_scope_subject_and_review_owner_all_required(self):
        mutations = (
            lambda row: row.update(subject_id="lot:other"),
            lambda row: row.update(reviewed_by=None),
            lambda row: row["evidence"][0].update(scope=["supply:proof"]),
            lambda row: row["evidence"][0].update(scope=["subject:lot:invented"]),
            lambda row: row["evidence"][0].update(artifact_sha256=None),
            lambda row: row["evidence"][0].update(verifier=None),
            lambda row: row["evidence"][0].update(status="claimed"),
            lambda row: row["evidence"][0]["permission"].update(retain="UNKNOWN"),
            lambda row: row["evidence"][0]["permission"].update(expires_at=NOW),
        )
        for mutate in mutations:
            payload = request(); mutate(payload["evidence"][0])
            self.assertEqual(assess_underwriting(payload)["status"], "held")
        payload = request(); payload["subjects"] = {}
        self.assertEqual(assess_underwriting(payload)["status"], "held")

    def test_null_blank_subject_is_missing_without_an_invented_identity(self):
        omitted = request(); omitted["subjects"] = {}
        blank = request(); blank["subjects"] = {"lot": None}
        self.assertEqual(assess_underwriting(blank)["rows"], assess_underwriting(omitted)["rows"])
        self.assertIn("missing_subject_identity", assess_underwriting(blank)["rows"][0]["blockers"])
        blank["subjects"]["lot"] = "lot:invented"
        self.assertEqual(assess_underwriting(blank)["status"], "complete_for_declared_requirements")
        for invalid in (0, 1, False):
            blank["subjects"]["lot"] = invalid
            with self.assertRaises(ValidationError): assess_underwriting(blank)

    def test_not_applicable_requires_explicit_permission_reason_and_current_evidence(self):
        payload = request(); row = payload["evidence"][0]
        row.update(status="not_applicable", value=None, not_applicable_reason="The independently reviewed service excludes this physical component.")
        self.assertEqual(assess_underwriting(payload)["status"], "held")
        payload["requirements"][0]["allow_not_applicable"] = True
        result = assess_underwriting(payload)
        self.assertEqual(result["status"], "complete_for_declared_requirements")
        self.assertEqual(result["summary"]["required_not_applicable"], 1)
        self.assertEqual(result["summary"]["required_covered"], 0)
        for key in ("not_applicable_reason", "reviewed_by", "valid_until"):
            changed = copy.deepcopy(payload); changed["evidence"][0][key] = None
            self.assertEqual(assess_underwriting(changed)["status"], "held")

    def test_scope_selection_optional_gaps_and_unknowns_are_visible(self):
        payload = request()
        payload["requirements"].append(requirement("other:proof", required=False))
        payload["requirements"].append(requirement("future:proof", scopes=["forward"]))
        result = assess_underwriting(payload)
        self.assertEqual(result["status"], "complete_for_declared_requirements")
        self.assertEqual(result["summary"]["optional_total"], 1)
        self.assertEqual(result["rows"][2]["status"], "out_of_scope")
        payload["scopes"] = ["custom_scope"]
        self.assertEqual(assess_underwriting(payload)["status"], "held")
        payload["requirements"].append(requirement("custom:proof", scopes=["custom_scope"]))
        payload["evidence"].append(evidence("custom:proof"))
        self.assertEqual(assess_underwriting(payload)["status"], "complete_for_declared_requirements")
        self.assertIn("supply:proof", assess_underwriting(payload)["unused_evidence_ids"])

    def test_duplicate_id_alias_or_conflicting_document_identity_cannot_hide_gaps(self):
        for field in ("requirements", "evidence"):
            payload = request(); payload[field] *= 2
            with self.assertRaises(ValidationError): assess_underwriting(payload)
        payload = request(); payload["requirements"][0]["ownership_id"] = "economic:same"
        payload["requirements"].append(requirement("alias:proof", ownership_id="economic:same"))
        with self.assertRaises(ValidationError): assess_underwriting(payload)
        payload = request(); payload["requirements"].append(requirement("other:proof"))
        other = evidence("other:proof"); other["evidence"][0]["id"] = "evidence:supply:proof"
        payload["evidence"].append(other)
        with self.assertRaises(ValidationError): assess_underwriting(payload)

    def test_more_fewer_fields_custom_registered_factors_and_extensions_do_not_change_money(self):
        payload = request(); base = assess_underwriting(payload)
        payload["extras"] = {"weight": "99999", "arbitrary_formula": "multiply everything"}
        payload["requirements"][0]["extensions"] = {"weight": "0.9"}
        changed = assess_underwriting(payload)
        self.assertEqual(changed["summary"], base["summary"])
        self.assertNotEqual(changed["input_hash"], base["input_hash"])
        self.assertNotEqual(changed["requirements_hash"], base["requirements_hash"])
        self.assertIn("extensions_retained_in_input_hash_but_not_used_in_assessment", changed["warnings"])
        self.assertFalse(changed["monetary_effects_enabled"])
        for bad in (float("nan"), float("inf"), 0.25):
            payload["extras"] = bad
            with self.assertRaises(ValidationError): assess_underwriting(payload)

    def test_bounded_empty_and_malformed_inputs_rejected(self):
        cases = []
        payload = request(); payload["requirements"] = []; cases.append(payload)
        payload = request(); payload["requirements"] *= 257; cases.append(payload)
        payload = request(); payload["scopes"] = []; cases.append(payload)
        payload = request(); payload["requirements_version"] = "01.0.0"; cases.append(payload)
        payload = request(); payload["evidence"][0]["valid_from"] = "2035-01-01T00:00:00+00:00"; cases.append(payload)
        payload = request(); payload["extensions"] = {"large": "x" * 17000}; cases.append(payload)
        for payload in cases:
            with self.assertRaises(ValidationError): assess_underwriting(payload)

    def test_authenticated_http_strict_json_and_no_snapshot_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(api_key=KEY, store_path=Path(directory) / "state.sqlite")
            client = TestClient(app)
            for route in ("/v1/underwriting/template", "/v1/underwriting/assess"):
                response = client.get(route) if route.endswith("template") else client.post(route, content=b"{malformed")
                self.assertEqual(response.status_code, 401)
            self.assertEqual(client.get("/v1/underwriting/template", headers=AUTH).status_code, 200)
            response = client.post("/v1/underwriting/assess", headers=AUTH, json=request())
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["persisted"])
            self.assertNotIn("snapshot_id", response.json())
            duplicate = json.dumps(request()).replace('"as_of":', '"as_of":"2035-01-01T00:00:00Z","as_of":', 1)
            self.assertEqual(client.post("/v1/underwriting/assess", headers={**AUTH, "Content-Type": "application/json"}, content=duplicate).status_code, 400)
            payload = request(); payload["evidence"][0]["value"] = 1.1
            self.assertEqual(client.post("/v1/underwriting/assess", headers=AUTH, json=payload).status_code, 422)
            payload = request(); payload["subjects"] = {}
            held = client.post("/v1/underwriting/assess", headers=AUTH, json=payload)
            self.assertEqual(held.status_code, 200)
            self.assertEqual(held.json()["status"], "held")


if __name__ == "__main__":
    unittest.main()
