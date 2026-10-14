"""Independent public studies preserve auth, snapshots and synthetic boundaries."""
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.inventory import InventoryStore, InventoryError
from test_curve_economics import comparison_book
from test_hedge_economics import study
from test_power_economics import allocation


class BackendStudyAPITests(unittest.TestCase):
    def test_authenticated_model_discovery_and_replay(self):
        key = "public-local-study-client-0123456789012"
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(api_key=key,
                store_path=Path(directory)/"decisions.sqlite")) as client:
            auth = {"Authorization": "Bearer " + key}
            for route in ("/v1/curves/contract", "/v1/power/contract", "/v1/hedges/contract", "/v1/market/curves"):
                self.assertEqual(client.get(route).status_code, 401)
                response = client.get(route, headers=auth)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertFalse(response.json()["execution_enabled"])
            for route, request in (("/v1/curves/evaluate", comparison_book()), ("/v1/power/evaluate", allocation()), ("/v1/hedges/evaluate", study())):
                first = client.post(route, json=request, headers=auth)
                self.assertEqual(first.status_code, 200, first.text)
                again = client.post(route, json=request, headers=auth)
                self.assertEqual(first.json()["snapshot_id"], again.json()["snapshot_id"])
                self.assertEqual(first.json()["versions"]["evaluation.model"], first.json()["result"]["model_version"])

    def test_missing_or_synthetic_inventory_cannot_create_a_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InventoryStore(Path(directory)/"inventory.sqlite")
            bare = {"schema_version": "paper-inventory/1.0", "sites": [], "lots": [], "positions": []}
            for packet in (bare, {**bare, "provenance": "synthetic"}):
                with self.assertRaises(InventoryError): store.put(expected_revision=0, state=packet)
            self.assertEqual(store.get(as_of="2059-01-01T00:00:00Z")["revision"], 0)
            result = store.put(expected_revision=0, state={**bare, "provenance": "declared"})
            self.assertEqual(result["revision"], 1)


if __name__ == "__main__": unittest.main()
