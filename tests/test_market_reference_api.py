"""The retained study survives the complete authenticated persistence path."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from compute_pricing.control.api import create_app


def unbound_request():
    return {"source_scopes": [{"source_id": "getdeploying", "filters": {}}], "policy_revision": "0" * 64,
        "cohort": {"scope": "aggregate_reference", "hardware_model": "invented-api-device", "hardware_memory_gib": None,
            "currency": "USD", "native_unit": "gpu_hour", "price_side": "ask", "country_code": None,
            "configuration": {}, "starts_at": None, "ends_at": None, "gpu_count": None,
            "aggregate_terms": {"billing_type": "ON_DEMAND", "reservation_months": None},
            "observation_period": "invented-window"}}


class RetainedReferenceAPITests(unittest.TestCase):
    def test_authenticated_held_result_persists_and_replays_without_vendor_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            key = "invented-retained-api-client-000008"
            auth = {"Authorization": "Bearer " + key}
            app = create_app(api_key=key, store_path=Path(directory) / "paper.sqlite")
            with TestClient(app) as client, patch("compute_pricing.control.api.app.collect_source") as collect:
                self.assertEqual(client.get("/v1/market/reference/contract").status_code, 401)
                self.assertEqual(client.post("/v1/market/reference/evaluate", json=unbound_request()).status_code, 401)
                self.assertEqual(client.get("/v1/market/reference/contract", headers=auth).status_code, 200)
                response = client.post("/v1/market/reference/evaluate", json=unbound_request(), headers=auth)
                self.assertEqual(response.status_code, 200, response.text)
                receipt = response.json()
                self.assertEqual(receipt["result"]["status"], "held")
                self.assertIn("saved_policy_revision_not_found", receipt["result"]["hold_reasons"])
                self.assertIsNone(receipt["result"]["reference"])
                self.assertFalse(receipt["result"]["source_evidence_eligible"])
                saved = client.get("/v1/decisions/" + receipt["snapshot_id"], headers=auth).json()
                self.assertEqual(saved["document"]["kind"], "market_reference")
                self.assertEqual(saved["document"]["input"], unbound_request())
                self.assertEqual(saved["document"]["output"], receipt["result"])
                collect.assert_not_called()
                self.assertIsNone(app.state.store.latest_refresh())

    def test_browser_study_requires_csrf_before_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            origin = "http://127.0.0.1:8894"
            fetch = {"Origin": origin, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
            app = create_app(workbench_origin=origin, store_path=Path(directory) / "browser.sqlite")
            with TestClient(app, base_url=origin) as client:
                boot = client.post("/v1/session/bootstrap", json={}, headers=fetch)
                self.assertEqual(boot.status_code, 200)
                self.assertEqual(client.post("/v1/market/reference/evaluate", json=unbound_request(), headers=fetch).status_code, 403)
                response = client.post("/v1/market/reference/evaluate", json=unbound_request(),
                    headers={**fetch, "X-Compute-CSRF": boot.json()["csrf_token"]})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertFalse(response.json()["execution_enabled"])


if __name__ == "__main__":
    unittest.main()
