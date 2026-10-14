"""Offline authenticated API tests; collection uses a synthetic injected transport."""
import datetime as dt
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from compute_pricing.control import __version__
from compute_pricing.control.api import create_app
from compute_pricing.control.connectors import ReadOnlyTransport, SourcePolicy
from compute_pricing.control.reporting import SnapshotStoreError
from compute_pricing.control.api.app import MAX_REQUEST_BYTES

KEY = "synthetic-local-development-key-1234567890"
AUTH = {"Authorization": "Bearer " + KEY}
NOW = dt.datetime(2026, 10, 14, 12, tzinfo=dt.timezone.utc)
CSV = ("gpu_slug,date,billing_type,reservation_months,min_price,max_price,median_price,provider_median_price,provider_count,offering_count\n"
       "synthetic-accelerator,2026-10-05,ON_DEMAND,,1.25,4.50,2.30,2.20,2,3\n"
       "synthetic-accelerator,2026-10-12,ON_DEMAND,,1.25,4.50,2.30,2.40,2,3\n")
CASH = {"events": [], "legal_entity_id": "synthetic-entity", "cash_account_id": "synthetic-bank",
        "currency": "USD", "opening_cash": "0.1234567890123456789012345678901234",
        "start_date": "2026-10-01", "end_date": "2026-10-02"}


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compute-api-tests-")
        self.path = Path(self.temp.name) / "snapshots.sqlite"
        self.calls = []
        def exchange(*args):
            self.calls.append(args)
            return 200, {"content-type": "text/csv"}, CSV.encode()
        resolver = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]
        self.transport = ReadOnlyTransport(clock=lambda: NOW, resolver=resolver, exchange=exchange)
        self.policy = SourcePolicy("getdeploying", enabled=True, rights_status="allowed", rights_evidence="synthetic-license",
            permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
            verified_by="synthetic-reviewer", max_age_s=14 * 86400, min_interval_s=0)
        self.app = create_app(api_key=KEY, store_path=self.path, source_policies={"getdeploying": self.policy}, transport=self.transport)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_health_is_metadata_only_startup_does_not_collect(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], __version__)
        self.assertFalse(response.json()["execution_enabled"])
        self.assertEqual(self.calls, [])
        self.assertNotIn(str(self.path), response.text)
        self.assertEqual(self.client.get("/docs").status_code, 404)

    def test_strong_explicit_key_required(self):
        for key in (None, "", "short", "a" * 31, "a" * 31 + "\n", "☃" * 32):
            with self.subTest(key=key), self.assertRaises(ValueError):
                create_app(api_key=key, store_path=self.path)

    def test_authentication_before_json_processing(self):
        for path in ("/v1/pricing/evaluate", "/v1/pricing/scenarios", "/v1/cash/evaluate", "/v1/sources/getdeploying/collect",
                     "/v1/inference/evaluate", "/v1/calibration/evaluate", "/v1/financing/evaluate"):
            with self.subTest(path=path):
                response = self.client.post(path, content=b'{"bad":NaN}', headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "unauthorized"})
        for header in ("Bearer wrong-secret", "Basic " + KEY, "Bearer " + KEY + " "):
            self.assertEqual(self.client.get("/v1/sources", headers={"Authorization": header}).status_code, 401)
        self.assertEqual(self.calls, [])

    def test_schema_and_source_status_authenticated_and_readonly(self):
        schema = self.client.get("/v1/contracts/schema", headers=AUTH)
        self.assertEqual(schema.status_code, 200)
        self.assertIn("MarketObservation", schema.json()["$defs"])
        status = self.client.get("/v1/sources", headers=AUTH)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(self.calls, [])
        source = next(item for item in status.json()["sources"] if item["source_id"] == "getdeploying")
        self.assertTrue(source["can_attempt_read"])
        self.assertFalse(source["execution_enabled"])

    def test_duplicate_keys_nan_inf_json_array_and_bad_content_type(self):
        for body in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e9999}', '{bad'):
            response = self.client.post("/v1/pricing/evaluate", content=body, headers={**AUTH, "Content-Type": "application/json"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"detail": "invalid_json"})
        self.assertEqual(self.client.post("/v1/cash/evaluate", json=[], headers=AUTH).status_code, 422)
        self.assertEqual(self.client.post("/v1/cash/evaluate", content="{}", headers=AUTH).status_code, 415)

    def test_body_size_and_invalid_header_limits(self):
        response = self.client.post("/v1/cash/evaluate", content=b"a" * (MAX_REQUEST_BYTES + 1), headers={**AUTH, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        response = self.client.post("/v1/cash/evaluate", content="{}", headers={**AUTH, "Content-Type": "application/json", "Content-Length": "invalid"})
        self.assertEqual(response.status_code, 400)

    def test_pricing_snapshot_and_replay_are_idempotent(self):
        payload = {"market": {"dynamic": "synthetic"}, "target": {}, "commercial": {}, "liquidity_points": []}
        fake = {"bid": "1.1234567890123456789012345678901234", "ask_min": "1.50", "execution_enabled": False,
                "versions": {"model": "synthetic-pricing/2.0.0", "policy": "1.3.0"}}
        with patch("compute_pricing.control.api.app._evaluate_pricing", return_value=fake) as evaluate:
            first = self.client.post("/v1/pricing/evaluate", json=payload, headers=AUTH)
            second = self.client.post("/v1/pricing/evaluate", json=payload, headers=AUTH)
            self.assertEqual(evaluate.call_count, 2)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["snapshot_id"], second.json()["snapshot_id"])
        self.assertEqual(first.json()["versions"]["evaluation.model"], "synthetic-pricing/2.0.0")
        loaded = self.client.get("/v1/decisions/" + first.json()["snapshot_id"], headers=AUTH)
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["document"]["input"], payload)
        self.assertEqual(loaded.json()["document"]["output"], first.json()["result"])
        self.assertEqual(first.json()["result"]["status"], "held")
        self.assertIsNone(first.json()["result"]["bid"])

    def test_invalid_pricing_diagnostics_do_not_echo_input(self):
        with patch("compute_pricing.control.api.app._evaluate_pricing", side_effect=ValueError("private-sensitive-invalid-value")):
            response = self.client.post("/v1/pricing/evaluate", json={"x": "private-sensitive-invalid-value"}, headers=AUTH)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "invalid_pricing_input"})

    def test_real_pricing_path_recalculates_dynamic_benchmark_inputs(self):
        observation = {"id": "synthetic-observation", "source_id": "synthetic-source", "source_version": "1.0",
            "kind": "aggregate_advertised_index", "price_side": "mark", "price": {"amount": "2.20", "currency": "USD", "unit": "gpu_hour"},
            "hardware": {"model": "synthetic-new-accelerator"}, "observed_at": "2026-10-05T00:00:00Z",
            "ingested_at": "2026-10-14T00:00:00Z", "expires_at": "2026-10-19T00:00:00Z", "status": "claimed",
            "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL", "verified_by": "synthetic-reviewer"},
            "extensions": {"billing_type": "ON_DEMAND", "reservation_months": None}}
        payload = {"market": {"request_id": "synthetic-pricing-request", "as_of": "2026-10-14T00:00:00Z", "observations": [observation],
            "policy": {"policy_id": "synthetic-policy", "version": "1.0.0", "registry_version": "1.0.0", "model_version": "synthetic-policy-model", "effective_at": "2026-10-01T00:00:00Z",
                "parameters": {"benchmark": {"estimator": "weighted_mean", "max_source_share": "1", "max_provider_share": "1",
                    "min_observations": 1, "min_sources": 1, "min_provider_groups": 1,
                    "source_rules": {"synthetic-source": {"enabled": True, "quality": "1", "max_age_hours": "336", "half_life_hours": "168"}}}}}},
            "target": {"scope": "aggregate_reference", "hardware_model": "synthetic-new-accelerator", "currency": "USD", "gpu_count": "1", "duration_hours": "24",
                       "aggregate_terms": {"billing_type": "ON_DEMAND", "reservation_months": None}}}
        first = self.client.post("/v1/pricing/evaluate", json=payload, headers=AUTH)
        self.assertEqual(first.status_code, 200)
        self.assertIsNone(first.json()["result"]["benchmark"]["price"])
        self.assertEqual(first.json()["result"]["scenario_diagnostics"]["benchmark"]["price"], "2.2")
        self.assertFalse(first.json()["result"]["firm_price_eligible"])
        self.assertEqual(first.json()["versions"]["evaluation.model"], "inverse-linear/1.0.0")
        observation["price"]["amount"] = "3.10"
        second = self.client.post("/v1/pricing/evaluate", json=payload, headers=AUTH)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["result"]["scenario_diagnostics"]["benchmark"]["price"], "3.1")
        self.assertNotEqual(first.json()["snapshot_id"], second.json()["snapshot_id"])

    def test_real_cash_evaluator_preserves_precision_and_rejects_float(self):
        response = self.client.post("/v1/cash/evaluate", json=CASH, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["days"][0]["cash"], CASH["opening_cash"])
        invalid = self.client.post("/v1/cash/evaluate", json={**CASH, "opening_cash": 0.1}, headers=AUTH)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json(), {"detail": "invalid_cash_input"})

    def test_only_manual_admitted_collection_latest_complete_week(self):
        response = self.client.post("/v1/sources/getdeploying/collect", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["selection"]["history_rows_received"], 2)
        self.assertEqual(result["selection"]["selected_observed_at"], "2026-10-05T00:00:00Z")
        self.assertEqual(result["observations"][0]["price"]["amount"], "2.20")
        self.assertEqual(result["observations"][0]["status"], "claimed")
        self.assertFalse(response.json()["execution_enabled"])
        loaded = self.client.get("/v1/decisions/" + response.json()["snapshot_id"], headers=AUTH)
        self.assertEqual(loaded.json()["document"]["kind"], "market_collection")

    def test_missing_rights_retention_and_unknown_source_block_before_network(self):
        response = self.client.post("/v1/sources/unknown/collect", headers=AUTH)
        self.assertEqual(response.status_code, 409)
        policies = {"getdeploying": SourcePolicy("getdeploying", enabled=True, rights_status="allowed", rights_evidence="synthetic",
            permissions={"observe":"PASS", "benchmark":"PASS", "retain":"UNKNOWN"}, verified_by="synthetic-reviewer", max_age_s=86400)}
        with TestClient(create_app(api_key=KEY, store_path=self.path, source_policies=policies, transport=self.transport)) as client:
            blocked = client.post("/v1/sources/getdeploying/collect", headers=AUTH)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(self.calls, [])

    def test_pure_research_routes_snapshot_versions_and_generic_errors(self):
        for kind, wrapper in (("inference", "_evaluate_inference"), ("calibration", "_evaluate_calibration"), ("financing", "_evaluate_financing"), ("pricing_scenarios", "_evaluate_scenarios")):
            path = "/v1/pricing/scenarios" if kind == "pricing_scenarios" else "/v1/" + kind + "/evaluate"
            with self.subTest(kind=kind):
                result = {"status": "research_only", "model_version": "synthetic-model-v1", "execution_eligible": False}
                with patch("compute_pricing.control.api.app." + wrapper, return_value=result):
                    response = self.client.post(path, json={"synthetic": "input"}, headers=AUTH)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["execution_enabled"])
                self.assertEqual(response.json()["versions"]["evaluation.model"], "synthetic-model-v1")
                replay = self.client.get("/v1/decisions/" + response.json()["snapshot_id"], headers=AUTH)
                self.assertEqual(replay.json()["document"]["kind"], kind)
                with patch("compute_pricing.control.api.app." + wrapper, side_effect=ValueError("sensitive-value")):
                    invalid = self.client.post(path, json={}, headers=AUTH)
                self.assertEqual(invalid.status_code, 422)
                self.assertEqual(invalid.json(), {"detail": "invalid_" + kind + "_input"})

    def test_real_calibration_endpoint_and_invalid_financing_shape(self):
        from test_calibration_v1 import fixture
        response = self.client.post("/v1/calibration/evaluate", json=fixture(), headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["result"]["live_pricing_eligible"])
        self.assertEqual(response.json()["versions"]["evaluation.model"], "research-hedonic-log-ols/1.0.0")
        for path in ("/v1/financing/evaluate", "/v1/pricing/scenarios"):
            invalid = self.client.post(path, json={}, headers=AUTH)
            self.assertEqual(invalid.status_code, 422)
        unknown_inference = self.client.post("/v1/inference/evaluate", json={}, headers=AUTH)
        self.assertEqual(unknown_inference.status_code, 200)
        self.assertEqual(unknown_inference.json()["result"]["status"], "held")
        self.assertIsNone(unknown_inference.json()["result"]["local"])
        self.assertEqual(self.calls, [])

    def test_snapshot_errors_and_absent_execution_routes(self):
        self.assertEqual(self.client.get("/v1/decisions/invalid", headers=AUTH).status_code, 400)
        self.assertEqual(self.client.get("/v1/decisions/" + "a" * 64, headers=AUTH).status_code, 404)
        self.assertEqual(self.client.post("/v1/orders", json={}, headers=AUTH).status_code, 404)
        with patch.object(self.app.state.store, "put", side_effect=SnapshotStoreError("private-path")), patch("compute_pricing.control.api.app._evaluate_pricing", return_value={}):
            response = self.client.post("/v1/pricing/evaluate", json={}, headers=AUTH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "snapshot_store_unavailable"})


if __name__ == "__main__":
    unittest.main()
