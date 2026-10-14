"""Invented public model metadata; no network, credentials or model downloads."""

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.connectors import ConnectorError, SourcePolicy
from compute_pricing.control.connectors.huggingface import huggingface_query, parse_huggingface
from compute_pricing.control.connectors.transport import RawResponse


def policy(**changes):
    values = dict(source_id="huggingface", enabled=True, rights_status="allowed", rights_evidence="invented-public-catalog-review",
        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        verified_by="invented-reviewer", attribution="Hugging Face public catalog; model-specific license claims unverified", max_age_s=3600)
    values.update(changes)
    return SourcePolicy(**values)


def item(**changes):
    values = dict(id="invented-author/new-model", author="invented-author", private=False, gated="manual", sha="invented-revision",
        lastModified="2025-03-01T10:30:00.000Z", createdAt="2025-01-01T00:00:00Z", pipeline_tag="text-generation", library_name="invented-runtime",
        tags=["license:apache-2.0", "future-tag"], cardData={"license": "apache-2.0", "future_card_field": "unknown"}, new_field={"claimed_speed": "999"})
    values.update(changes)
    return values


def raw(payload, captured_at="2026-10-14T12:00:00Z"):
    body = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
    return RawResponse("huggingface", captured_at, "/api/models", 200, {"content-type": "application/json"}, body)


class ModelMetadataTests(unittest.TestCase):
    def test_metadata_keeps_provenance_but_never_enters_prices_or_qualification(self):
        response = raw([item()])
        result = parse_huggingface(response, policy()).to_dict()
        self.assertEqual(result["observations"], [])
        record = result["catalog_records"][0]
        self.assertEqual(record["kind"], "model_metadata")
        self.assertIsNone(record["price"])
        self.assertFalse(record["qualification_verified"])
        self.assertFalse(record["price_eligible"])
        self.assertEqual(record["repository_last_modified_at"], "2025-03-01T10:30:00Z")
        self.assertEqual(record["observed_at"], "2026-10-14T12:00:00Z")
        self.assertEqual(record["expires_at"], "2026-10-14T13:00:00Z")
        self.assertEqual(record["evidence"]["artifact_sha256"], response.sha256)
        self.assertEqual(record["extensions"]["source_row"]["new_field"], {"claimed_speed": "999"})
        self.assertEqual(record["gated"], "manual")
        self.assertEqual(record["license_tags"], ["apache-2.0"])
        self.assertEqual(record["card_metadata"]["future_card_field"], "unknown")

    def test_unknown_license_private_and_source_dates_are_not_defaulted(self):
        result = parse_huggingface(raw([item(tags=[], cardData=None, private=None, gated=None, lastModified=None, createdAt=None)]), policy()).catalog_records[0]
        self.assertIsNone(result["private"])
        self.assertIsNone(result["repository_last_modified_at"])
        self.assertIsNone(result["card_license"])
        self.assertEqual(result["license_tags"], [])
        self.assertFalse(result["qualification_verified"])

    def test_new_model_ids_do_not_need_a_static_allowlist(self):
        payload = [item(id="invented-author/new-release-one"), item(id="invented-author/new-release-two")]
        records = parse_huggingface(raw(payload), policy()).catalog_records
        self.assertEqual(len(records), 2)
        self.assertNotEqual(records[0]["id"], records[1]["id"])

    def test_bounded_results_never_claim_catalog_completeness(self):
        for payload in ([], [item()], [item(id=f"invented-author/model-{i}") for i in range(100)]):
            result = parse_huggingface(raw(payload), policy())
            self.assertFalse(result.coverage["complete"])
            self.assertFalse(result.coverage["all_models"])
            self.assertEqual(result.coverage["compute_price_observations"], 0)
        with self.assertRaisesRegex(ConnectorError, "budget"):
            parse_huggingface(raw([item(id=f"invented-author/model-{i}") for i in range(101)]), policy())

    def test_explicit_scope_and_no_authenticated_file_routes(self):
        filters = {"author": "invented-author", "pipeline_tag": "text-generation", "limit": 25, "full": True}
        self.assertEqual(huggingface_query(filters), {"author": "invented-author", "pipeline_tag": "text-generation", "limit": "25", "full": "true"})
        for changes in ({"limit": 101}, {"limit": True}, {"author": "../private"}, {"pipeline_tag": "unregistered"}, {"full": False}):
            with self.subTest(changes=changes), self.assertRaises(ConnectorError):
                huggingface_query({**filters, **changes})
        with self.assertRaises(ConnectorError):
            huggingface_query({**filters, "token": "not-a-real-secret"})
        with self.assertRaises(ConnectorError):
            huggingface_query({"author": "invented-author"})

    def test_private_records_invalid_visibility_and_duplicate_models_fail_closed(self):
        for payload in ([item(private=True)], [item(private="false")], [item(), item()], [item(gated="unknown-gate")], [item(gated=1)], {"data": [item()]}):
            with self.subTest(payload=payload), self.assertRaises(ConnectorError):
                parse_huggingface(raw(payload), policy())

    def test_invalid_and_future_repository_times_do_not_become_current_evidence(self):
        for changes in ({"lastModified": "2026-10-15T00:00:00Z"}, {"lastModified": "2026-02-30T00:00:00Z"}, {"createdAt": "2025-04-01T00:00:00Z"}):
            with self.subTest(changes=changes), self.assertRaises(ConnectorError):
                parse_huggingface(raw([item(**changes)]), policy())

    def test_duplicate_json_keys_nan_and_malformed_cards_reject(self):
        for body in ('[{"id":"a","id":"b"}]', '[{"id":"a","new_field":NaN}]'):
            with self.subTest(body=body), self.assertRaises(ConnectorError):
                parse_huggingface(raw(body), policy())
        with self.assertRaises(ConnectorError):
            parse_huggingface(raw([item(cardData="not metadata")]), policy())

    def test_missing_metadata_admission_cannot_be_waived_by_source_name(self):
        for changes in ({"enabled": False}, {"permissions": {"observe": "PASS", "retain": "PASS"}}, {"rights_status": "pending"}):
            with self.subTest(changes=changes), self.assertRaises(ConnectorError):
                parse_huggingface(raw([item()]), policy(**changes))
        with self.assertRaisesRegex(ConnectorError, "source_policy_mismatch"):
            parse_huggingface(raw([item()]), policy(source_id="getdeploying"))

    def test_returning_metadata_does_not_mutate_source_inputs(self):
        original = [item()]
        copy_before = copy.deepcopy(original)
        result = parse_huggingface(raw(original), policy()).to_dict()
        result["catalog_records"][0]["card_metadata"]["license"] = "changed"
        self.assertEqual(original, copy_before)
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
