"""Independent index scope, revocation, integrity and partial-refresh checks."""
import datetime as dt
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.connectors import ConnectorError, SourcePolicy
from compute_pricing.control.reporting import SnapshotStoreError

KEY = "offline-index-example-auth-1234567890"
AUTH = {"Authorization": "Bearer " + KEY}


def policy(name="getdeploying", enabled=True):
    return SourcePolicy(name, enabled=enabled, rights_status="allowed", rights_evidence="invented-test-scope",
                        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
                        max_age_s=14 * 86400, verified_by="review:invented")


def batch(source="getdeploying", price="2.3", scope="a"):
    now = dt.datetime.now(dt.timezone.utc)
    observed = now - dt.timedelta(days=8)
    expiry = now + dt.timedelta(days=1)
    rows = [{"id": "row:" + scope, "source_id": source, "kind": "aggregate_advertised_index",
             "price": {"amount": price, "currency": "USD", "unit": "gpu_hour"},
             "observed_at": observed.isoformat().replace("+00:00", "Z"),
             "expires_at": expiry.isoformat().replace("+00:00", "Z")}]
    output = {"source_id": source, "raw_metadata": {"captured_at": now.isoformat().replace("+00:00", "Z")},
              "observations": rows, "catalog_records": [], "coverage": {"complete": True}, "execution_enabled": False}
    return SimpleNamespace(source_id=source, to_dict=lambda: output)


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "snapshots.sqlite"
        self.app = create_app(api_key=KEY, store_path=self.path, source_policies={"getdeploying": policy(), "azure": policy("azure")},
                              collection_plan=[{"source_id": "getdeploying", "filters": {}}])
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_index_auth_and_get_has_no_network_or_synthetic_fill(self):
        with patch("compute_pricing.control.api.app.collect_source") as collect:
            self.assertEqual(self.client.get("/v1/market/index").status_code, 401)
            result = self.client.get("/v1/market/index", headers=AUTH).json()
            self.assertEqual(result["observations"], [])
            self.assertEqual(result["snapshots"], [])
            collect.assert_not_called()

    def test_manual_refresh_snapshots_and_latest_scope_change(self):
        with patch("compute_pricing.control.api.app.collect_source", return_value=batch()):
            response = self.client.post("/v1/market/refresh", json={"source_ids": ["getdeploying"]}, headers=AUTH)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["updated"]), 1)
        with patch("compute_pricing.control.api.app.collect_source", return_value=batch(price="3.1")):
            self.client.post("/v1/market/refresh", json={"source_ids": ["getdeploying"]}, headers=AUTH)
        result = self.client.get("/v1/market/index", headers=AUTH).json()
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"][0]["price"]["amount"], "3.1")
        self.assertFalse(result["observations"][0]["index_stale"])

    def test_independent_regions_not_overwritten_and_budget_is_not_scope(self):
        store = self.app.state.store
        for region, max_pages, amount in (("region-a", 1, "1"), ("region-b", 1, "2"), ("region-a", 3, "3")):
            store.put(kind="market_collection", input_payload={"source_id": "azure", "filters": {"region": region, "max_pages": max_pages}},
                      output_payload=batch("azure", amount, region).to_dict(), versions={"adapter": "test-v1"})
        records = self.client.get("/v1/market/index", headers=AUTH).json()["observations"]
        self.assertEqual({record["price"]["amount"] for record in records}, {"2", "3"})
        self.assertEqual(len(records), 2)

    def test_rights_revocation_hides_retained_rows(self):
        store = self.app.state.store
        store.put(kind="market_collection", input_payload={"filters": {}}, output_payload=batch().to_dict(), versions={"adapter": "test"})
        denied_app = create_app(api_key=KEY, store_path=self.path, source_policies={"getdeploying": policy(enabled=False)})
        with TestClient(denied_app) as client:
            self.assertEqual(client.get("/v1/market/index", headers=AUTH).json()["observations"], [])

    def test_partial_failure_retains_previous_success_and_other_sources_refresh(self):
        def collect(source, *args, **kwargs):
            if source == "azure":
                raise ConnectorError("network_request_failed")
            return batch(source)
        with patch("compute_pricing.control.api.app.collect_source", side_effect=collect):
            result = self.client.post("/v1/market/refresh", json={"requests": [{"source_id": "azure", "filters": {"region": "invented"}}, {"source_id": "getdeploying", "filters": {}}]}, headers=AUTH).json()
        self.assertEqual(len(result["updated"]), 1)
        self.assertEqual(result["failed"][0]["reason"], "network_request_failed")
        self.assertTrue(result["partial_refresh"])
        self.assertEqual(len(self.client.get("/v1/market/index", headers=AUTH).json()["observations"]), 1)

    def test_invalid_and_duplicate_requests_no_network(self):
        packets = ({"source_ids": ["azure"], "requests": []}, {"requests": [{"source_id": "azure", "filters": {}}] * 2}, {"source_ids": ["azure", "azure"]}, {"requests": []})
        with patch("compute_pricing.control.api.app.collect_source") as collect:
            for packet in packets:
                self.assertEqual(self.client.post("/v1/market/refresh", json=packet, headers=AUTH).status_code, 422)
            collect.assert_not_called()

    def test_integrity_failure_is_not_returned_as_indexed_data(self):
        with patch.object(self.app.state.store, "latest_collection_scan", side_effect=SnapshotStoreError("snapshot_integrity_failed")):
            response = self.client.get("/v1/market/index", headers=AUTH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "snapshot_store_unavailable")

    def test_scan_limit_explicit_and_invalid_limit_rejected(self):
        self.assertEqual(self.app.state.store.latest_collections(), ())
        for limit in (0, True, 3000):
            with self.assertRaises(SnapshotStoreError):
                self.app.state.store.latest_collections(scan_limit=limit)

    def test_current_policy_tightening_cannot_rejuvenate_old_observations(self):
        self.app.state.store.put(kind="market_collection", input_payload={"filters": {}}, output_payload=batch().to_dict(), versions={"adapter": "test"})
        import dataclasses
        tighter = dataclasses.replace(policy(), max_age_s=86400)
        with TestClient(create_app(api_key=KEY, store_path=self.path, source_policies={"getdeploying": tighter})) as client:
            records = client.get("/v1/market/index", headers=AUTH).json()["observations"]
            self.assertTrue(records[0]["index_stale"])

    def test_repeated_failure_is_new_attempt_after_intervening_success(self):
        request = {"source_ids": ["getdeploying"]}
        with patch("compute_pricing.control.api.app.collect_source", side_effect=ConnectorError("network_request_failed")):
            first = self.client.post("/v1/market/refresh", json=request, headers=AUTH).json()
        with patch("compute_pricing.control.api.app.collect_source", return_value=batch()):
            self.client.post("/v1/market/refresh", json=request, headers=AUTH)
        with patch("compute_pricing.control.api.app.collect_source", side_effect=ConnectorError("network_request_failed")):
            last = self.client.post("/v1/market/refresh", json=request, headers=AUTH).json()
        result = self.client.get("/v1/market/index", headers=AUTH).json()
        self.assertNotEqual(first["snapshot_id"], last["snapshot_id"])
        self.assertEqual(result["last_refresh"]["snapshot_id"], last["snapshot_id"])
        self.assertEqual(result["last_refresh"]["document"]["output"]["failed"][0]["reason"], "network_request_failed")

    def test_bounded_history_declares_possible_hidden_independent_scopes(self):
        store = self.app.state.store
        store.put(kind="market_collection", input_payload={"filters": {"region": "invented-older-region"}},
                  output_payload=batch("azure", "99").to_dict(), versions={"adapter": "invented"})
        for number in range(512):
            store.put(kind="market_collection", input_payload={"filters": {}},
                      output_payload=batch(price=str(number)).to_dict(), versions={"adapter": "invented"})
        scan = store.latest_collection_scan(scan_limit=2)
        self.assertTrue(scan.has_older_history)
        self.assertEqual(scan.rows_scanned, 2)
        result = self.client.get("/v1/market/index", headers=AUTH).json()
        self.assertTrue(result["coverage"]["history_scan_truncated"])
        self.assertTrue(result["coverage"]["possible_missing_scopes"])
        self.assertEqual(result["coverage"]["history_rows_scanned"], 512)
        self.assertIn("collection_history_scan_truncated_scopes_may_be_missing", result["warnings"])
        azure = next(source for source in result["sources"] if source["source_id"] == "azure")
        self.assertEqual(azure["observed_liveness"], "not_found_in_bounded_history")

    def test_exact_scan_boundary_does_not_falsely_claim_truncation(self):
        for number in range(2):
            self.app.state.store.put(kind="market_collection", input_payload={"filters": {}},
                output_payload=batch(price=str(number)).to_dict(), versions={"adapter": "invented"})
        scan = self.app.state.store.latest_collection_scan(scan_limit=2)
        self.assertFalse(scan.has_older_history)
        self.assertEqual(scan.rows_scanned, 2)
        self.assertEqual(len(scan.snapshots), 1)

    def test_malformed_or_mismatched_collection_packets_fail_closed(self):
        packets = []
        invalid = batch().to_dict()
        invalid["observations"] = [None]
        packets.append(({}, invalid))
        invalid = batch().to_dict()
        invalid["observations"][0]["source_id"] = "azure"
        packets.append(({}, invalid))
        packets.append(({"source_id": "azure"}, batch().to_dict()))
        invalid = batch().to_dict()
        invalid["execution_enabled"] = True
        packets.append(({}, invalid))
        packets.append(({"filters": []}, batch().to_dict()))
        for number, (inputs, output) in enumerate(packets):
            with self.subTest(number=number):
                app = create_app(api_key=KEY, store_path=Path(self.folder.name) / f"invalid-{number}.sqlite",
                                 source_policies={"getdeploying": policy()})
                app.state.store.put(kind="market_collection", input_payload=inputs, output_payload=output, versions={"adapter": "invented"})
                with TestClient(app) as client:
                    response = client.get("/v1/market/index", headers=AUTH)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "snapshot_store_unavailable"})

    def test_malformed_refresh_packet_cannot_crash_or_enter_index(self):
        self.app.state.store.put(kind="market_refresh", input_payload={},
            output_payload={"failed": "invented malformed packet", "execution_enabled": False}, versions={"adapter": "invented"})
        response = self.client.get("/v1/market/index", headers=AUTH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "snapshot_store_unavailable"})

    def test_current_policy_metadata_age_is_distinct_from_repository_age(self):
        now = dt.datetime.now(dt.timezone.utc)
        stamp = lambda value: value.isoformat().replace("+00:00", "Z")
        output = {"source_id": "huggingface", "raw_metadata": {"captured_at": stamp(now)}, "observations": [],
                  "catalog_records": [{"id": "invented-old-observation", "kind": "model_metadata", "observed_at": stamp(now - dt.timedelta(days=2)),
                        "expires_at": stamp(now + dt.timedelta(days=10))},
                      {"id": "invented-current-observation", "kind": "model_metadata", "observed_at": stamp(now),
                        "repository_last_modified_at": "2021-01-01T00:00:00Z", "expires_at": stamp(now + dt.timedelta(days=10))}],
                  "execution_enabled": False}
        self.app.state.store.put(kind="market_collection", input_payload={"filters": {}}, output_payload=output, versions={"adapter": "invented"})
        import dataclasses
        app = create_app(api_key=KEY, store_path=self.path,
            source_policies={"huggingface": dataclasses.replace(policy("huggingface"), max_age_s=86400)})
        with TestClient(app) as client:
            records = client.get("/v1/market/index", headers=AUTH).json()["catalog_records"]
        self.assertTrue(records[0]["index_stale"])
        self.assertFalse(records[1]["index_stale"])


if __name__ == "__main__":
    unittest.main()
