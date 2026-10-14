"""Fresh paper-state provenance examples, independent of retained source records."""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.inventory import InventoryError, InventoryStore, evaluate_inventory, validate_inventory

START, END = "2037-03-02T00:00:00Z", "2037-03-09T00:00:00Z"


def paper_state():
    return {"schema_version": "paper-inventory/1.0", "sites": [{"site_id": "example-site"}],
            "lots": [{"lot_id": "example-lot", "site_id": "example-site", "unit_kind": "cpu",
                      "unit_ids": ["example-unit"], "start_at": START, "end_at": END}],
            "positions": [{"position_id": "example-sale", "lot_id": "example-lot", "unit_ids": ["example-unit"],
                           "status": "sold", "start_at": START, "end_at": END}]}


class PaperProvenanceTests(unittest.TestCase):
    def test_legacy_state_is_not_silently_rewritten_or_verified(self):
        normalized = validate_inventory(paper_state())
        self.assertNotIn("provenance", normalized)
        self.assertEqual(validate_inventory(normalized), normalized)
        output = evaluate_inventory(normalized, as_of=START)
        self.assertEqual(output["provenance"], "unspecified")
        self.assertEqual(output["asset_verification"], "caller_declared_unverified")

    def test_marked_synthetic_preview_cannot_create_persisted_revision(self):
        raw = paper_state(); raw["provenance"] = "synthetic"
        preview = evaluate_inventory(raw, as_of=START)
        self.assertEqual(preview["provenance"], "synthetic")
        self.assertIn("synthetic_inventory_is_preview_only", preview["warnings"])
        with tempfile.TemporaryDirectory() as directory:
            store = InventoryStore(Path(directory) / "example.sqlite")
            with self.assertRaises(InventoryError):
                store.put(expected_revision=0, state=raw)
            self.assertEqual(store.get(as_of=START)["revision"], 0)
            raw["provenance"] = "declared"
            saved = store.put(expected_revision=0, state=raw)
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(InventoryStore(store.path).get(as_of=START)["provenance"], "declared")
            self.assertFalse(saved["execution_enabled"])

    def test_contract_presence_is_reported_without_contract_authentication(self):
        raw = paper_state()
        missing = evaluate_inventory(raw, as_of=START)
        self.assertEqual(missing["position_evidence"]["sold_position_ids_without_contract"], ["example-sale"])
        raw["positions"][0]["contract_id"] = "example-contract"
        present = evaluate_inventory(raw, as_of=START)
        self.assertEqual(present["position_evidence"]["sold_position_ids_without_contract"], [])
        self.assertFalse(present["position_evidence"]["contract_references_verified"])
        for marker in (False, None, 7, "authenticated", {}):
            raw["provenance"] = marker
            with self.assertRaises(InventoryError):
                validate_inventory(raw)

    def test_authenticated_route_enforces_marker_without_funding_or_collection(self):
        raw = paper_state(); raw["provenance"] = "synthetic"
        key = "invented-provenance-api-key-123456789"
        headers = {"Authorization": "Bearer " + key}
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(api_key=key, store_path=Path(directory) / "route.sqlite", source_policies={})
            with TestClient(app) as client:
                preview = client.post("/v1/inventory/evaluate", headers=headers, json={"state": raw, "as_of": START})
                self.assertEqual(preview.status_code, 200)
                self.assertFalse(preview.json()["persisted"])
                refused = client.put("/v1/inventory", headers=headers, json={"expected_revision": 0, "state": raw})
                self.assertEqual(refused.status_code, 422)
                self.assertEqual(refused.json()["detail"], "synthetic_inventory_cannot_be_persisted")
                self.assertEqual(client.get("/v1/inventory", headers=headers).json()["revision"], 0)


if __name__ == "__main__":
    unittest.main()
