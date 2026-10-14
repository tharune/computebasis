"""Independent policy controls and immutable persistence; no live collection."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.policies import PolicyConflict, PolicyRepository, validate_document
from compute_pricing.control.policies.repository import PolicyStoreError

KEY = "invented-policy-boundary-key-1234567890"
AUTH = {"Authorization": "Bearer " + KEY}
ROOT = Path(__file__).resolve().parents[1]


def sample():
    return json.loads((ROOT / "src/compute_pricing/control/workbench/assets/synthetic-policy-document.json").read_text())


class PolicyV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite"
        self.repository = PolicyRepository(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_values_and_feature_ownership_survive_replay_restart(self):
        document = sample()
        document["policy"]["parameters"]["benchmark"]["source_rules"]["source:invented"]["quality"] = "0.12345678901234567890123456789"
        result = self.repository.save(document, expected_revision=None)
        self.assertEqual(result["status"], "saved")
        replay = PolicyRepository(self.path).get(result["revision"])
        self.assertEqual(replay["document"], result["document"])
        self.assertFalse(replay["execution_enabled"])
        self.assertEqual(replay["calibration_state"], "unvalidated")
        self.assertEqual(replay["document"]["feature_definitions"][0]["owning_path"], "loss")

    def test_save_idempotency_is_exact_and_does_not_mutate_prior_versions(self):
        one = self.repository.save(sample(), expected_revision=None)
        two = self.repository.save(sample(), expected_revision=None)
        self.assertEqual(two["status"], "existing")
        self.assertEqual(one["revision"], two["revision"])
        changed = sample()
        changed["notes"] = "different invented notes"
        with self.assertRaises(PolicyConflict):
            self.repository.save(changed, expected_revision=one["revision"])
        self.assertEqual(len(self.repository.list()["entries"]), 1)

    def test_successors_require_correct_predecessor_and_increasing_semver(self):
        first = self.repository.save(sample(), expected_revision=None)
        next_document = sample()
        next_document["policy"]["version"] = "1.0.1"
        with self.assertRaises(PolicyConflict):
            self.repository.save(next_document, expected_revision=None)
        successor = self.repository.save(next_document, expected_revision=first["revision"])
        self.assertNotEqual(first["revision"], successor["revision"])
        next_document["policy"]["version"] = "0.9.0"
        with self.assertRaises(PolicyConflict):
            self.repository.save(next_document, expected_revision=successor["revision"])

    def test_concurrent_successors_cannot_lose_an_update(self):
        first = self.repository.save(sample(), expected_revision=None)
        def write(notes):
            candidate = sample()
            candidate["policy"]["version"] = "1.1.0"
            candidate["notes"] = notes
            try:
                return self.repository.save(candidate, expected_revision=first["revision"])["status"]
            except PolicyConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(write, ("invented A", "invented B")))
        self.assertEqual(sorted(results), ["conflict", "saved"])
        self.assertEqual(len(self.repository.list()["entries"]), 2)

    def test_indexed_metadata_corruption_fails_read_and_successor(self):
        for column, value in (("version", "0.0.1"), ("policy_id", "policy:altered")):
            with self.subTest(column=column), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "policies.sqlite"
                repository = PolicyRepository(path)
                first = repository.save(sample(), expected_revision=None)
                with sqlite3.connect(path) as connection:
                    connection.execute("DROP TRIGGER policies_no_update")
                    connection.execute(f"UPDATE policy_documents SET {column}=?", (value,))
                with self.assertRaises(PolicyStoreError):
                    repository.get(first["revision"])
                with self.assertRaises(PolicyStoreError):
                    repository.list()
                candidate = sample(); candidate["policy"]["version"] = "0.5.0"
                with self.assertRaises(PolicyStoreError):
                    repository.save(candidate, expected_revision=first["revision"])
                # Corrupt identity indexes cannot make an existing policy look
                # like a new empty policy to a caller with no predecessor.
                with self.assertRaises(PolicyStoreError):
                    repository.save(candidate, expected_revision=None)
                with sqlite3.connect(path) as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM policy_documents").fetchone()[0], 1)

    def test_changed_feature_definitions_require_a_successor_registry(self):
        first = self.repository.save(sample(), expected_revision=None)
        document = sample(); document["policy"]["version"] = "1.0.1"
        document["feature_definitions"][0]["required"] = True
        with self.assertRaisesRegex(PolicyConflict, "successor_registry"):
            self.repository.save(document, expected_revision=first["revision"])
        document["policy"]["registry_version"] = "1.0.1"
        self.assertEqual(self.repository.save(document, expected_revision=first["revision"])["status"], "saved")

    def test_policy_parameters_and_required_feature_definitions_fail_closed(self):
        cases = []
        for name, value in (("max_source_share", "0"), ("max_provider_share", "1.01"), ("min_sources", True), ("estimator", "unregistered")):
            document = sample()
            document["policy"]["parameters"]["benchmark"][name] = value
            cases.append(document)
        document = sample(); document["policy"]["parameters"]["regional_multiplier"] = "1.2"; cases.append(document)
        document = sample(); document["policy"]["critical_feature_ids"] = ["unregistered:factor"]; cases.append(document)
        document = sample(); document["feature_definitions"] *= 2; cases.append(document)
        document = sample(); document["policy"]["model_version"] = "arbitrary-expression"; cases.append(document)
        document = sample(); document["policy"]["version"] = "01.0.0"; cases.append(document)
        for document in cases:
            with self.subTest(document=document), self.assertRaises(ValidationError):
                validate_document(document)

    def test_source_rule_contract_has_exact_numbers_without_rights_activation(self):
        for bad in (0.5, "1e-2", "-1", "0"):
            document = sample(); document["policy"]["parameters"]["benchmark"]["source_rules"]["source:invented"]["quality"] = bad
            with self.assertRaises(ValidationError): validate_document(document)
        document = sample(); document["policy"]["parameters"]["benchmark"]["source_rules"]["source:invented"]["execution"] = True
        with self.assertRaises(ValidationError): validate_document(document)

    def test_documents_are_defensively_copied_and_bounded(self):
        document = sample()
        result = self.repository.save(document, expected_revision=None)
        document["notes"] = "mutated"
        result["document"]["notes"] = "mutated again"
        self.assertEqual(self.repository.get(result["revision"])["document"]["notes"], sample()["notes"])
        document = sample(); document["notes"] = "x" * 4097
        with self.assertRaises(ValidationError): validate_document(document)
        document = sample(); document["feature_definitions"] = document["feature_definitions"] * 129
        with self.assertRaises(ValidationError): validate_document(document)

    def test_append_only_triggers_and_corruption_refusal(self):
        entry = self.repository.save(sample(), expected_revision=None)
        with sqlite3.connect(self.path) as connection:
            for query in ("DELETE FROM policy_documents", "UPDATE policy_documents SET document='{}'"):
                with self.assertRaises(sqlite3.IntegrityError): connection.execute(query)
            connection.execute("DROP TRIGGER policies_no_update")
            connection.execute("UPDATE policy_documents SET document='{}'")
        with self.assertRaises(PolicyStoreError): self.repository.get(entry["revision"])

    def test_explicit_bounded_history(self):
        entry = self.repository.save(sample(), expected_revision=None)
        document = sample(); document["policy"]["version"] = "1.0.1"
        self.repository.save(document, expected_revision=entry["revision"])
        page = self.repository.list(limit=1)
        self.assertTrue(page["truncated"])
        self.assertEqual(len(page["entries"]), 1)

    def test_authenticated_api_validation_save_conflict_and_replay(self):
        app = create_app(api_key=KEY, store_path=self.path)
        with TestClient(app) as client:
            self.assertEqual(client.get("/v1/policies").status_code, 401)
            checked = client.post("/v1/policies/validate", json={"document": sample()}, headers=AUTH)
            self.assertEqual(checked.status_code, 200)
            self.assertEqual(client.get("/v1/policies", headers=AUTH).json()["entries"], [])
            created = client.post("/v1/policies", json={"expected_revision": None, "document": sample()}, headers=AUTH)
            self.assertEqual(created.status_code, 200)
            entry = created.json()
            self.assertEqual(client.get("/v1/policies/"+entry["revision"], headers=AUTH).status_code, 200)
            document = sample(); document["notes"] = "changed"
            self.assertEqual(client.post("/v1/policies", json={"expected_revision": entry["revision"], "document": document}, headers=AUTH).status_code, 409)
            self.assertIn("owning_paths", client.get("/v1/policies", headers=AUTH).json()["feature_schema"])

    def test_api_preserves_duplicate_key_and_unicode_guards(self):
        with TestClient(create_app(api_key=KEY, store_path=self.path)) as client:
            headers = {**AUTH, "Content-Type": "application/json"}
            for body in (b'{"document":{},"document":{}}', b'{"document":"\\ud800"}'):
                self.assertIn(client.post("/v1/policies/validate", content=body, headers=headers).status_code, (400, 422))

    def test_parse_boundary_is_pure_and_rejects_duplicate_keys(self):
        with TestClient(create_app(api_key=KEY, store_path=self.path)) as client:
            body = '{"market":{"exact":"0.12345678901234567890123456789"}}'
            headers = {**AUTH, "Content-Type": "application/json"}
            response = client.post("/v1/requests/parse", content=body, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["request"]["market"]["exact"], "0.12345678901234567890123456789")
            self.assertEqual(response.json()["boundary_validation"], "json_only")
            self.assertFalse(response.json()["execution_enabled"])
            self.assertEqual(client.post("/v1/requests/parse", content='{"x":1,"x":2}', headers=headers).status_code, 400)
            self.assertEqual(self.repository.list()["entries"], [])


if __name__ == "__main__":
    unittest.main()
