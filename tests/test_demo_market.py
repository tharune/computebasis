"""Bounded display scopes keep retention integrity and current permissions."""
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.connectors import SourcePolicy
from compute_pricing.control.reporting import SnapshotStore, SnapshotStoreError


KEY = "offline-demo-read-client-0123456789"
AUTH = {"Authorization": "Bearer " + KEY}


def policy(source, enabled=True):
    return SourcePolicy(source, enabled=enabled, rights_status="allowed",
        rights_evidence="independently-invented-test-permission", verified_by="review:example",
        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        max_age_s=86400)


def capture(store, source="getdeploying", filters=None, amount="2.7", observed=None):
    now = dt.datetime.now(dt.timezone.utc)
    return store.put(kind="market_collection", input_payload={"source_id": source, "filters": filters or {}},
        output_payload={"source_id": source, "raw_metadata": {"captured_at": now.isoformat()},
            "observations": [{"id": "invented-display-row", "source_id": source,
                "kind": "aggregate_advertised_index", "price": {"amount": amount, "currency": "USD", "unit": "gpu_hour"},
                "observed_at": (observed or now).isoformat(), "expires_at": (now + dt.timedelta(days=1)).isoformat()}],
            "catalog_records": [], "coverage": {"complete": True}, "execution_enabled": False},
        versions={"adapter": "invented-offline/1"})


class DemoMarketTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "decisions.sqlite"
        self.store = SnapshotStore(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def test_latest_scope_canonical_order_and_page_budget(self):
        capture(self.store, filters={"region": "north", "max_pages": 1}, amount="2")
        latest = capture(self.store, filters={"max_pages": 3, "region": "north"}, amount="3")
        capture(self.store, filters={"region": "south"}, amount="4")
        selected = self.store.requested_collection_scan([
            {"source_id": "getdeploying", "filters": {"region": "north", "max_pages": 9}},
            {"source_id": "getdeploying", "filters": {"region": "north"}},
            {"source_id": "ecb", "filters": {}},
        ])
        self.assertEqual([row.digest for row in selected.snapshots], [latest.digest])
        self.assertEqual(selected.scan_limit, 2)
        self.assertEqual(selected.rows_scanned, 1)
        self.assertFalse(selected.has_older_history)

    def test_requested_selection_detects_selected_payload_tampering(self):
        saved = capture(self.store)
        document = saved.to_dict()["document"]
        document["output"]["observations"][0]["price"]["amount"] = "99"
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TRIGGER snapshots_no_update")
            connection.execute("UPDATE snapshots SET canonical_document=? WHERE digest=?",
                (json.dumps(document, sort_keys=True, separators=(",", ":")), saved.digest))
        with self.assertRaisesRegex(SnapshotStoreError, "snapshot_integrity_failed"):
            self.store.requested_collection_scan([{"source_id": "getdeploying", "filters": {}}])

    def test_requested_population_rejects_malformed_or_unbounded_inputs(self):
        for value in (None, (), [{"source_id": "getdeploying"}], [{"source_id": "../x", "filters": {}}],
                      [{"source_id": "getdeploying", "filters": []}],
                      [{"source_id": "getdeploying", "filters": {}}] * 33):
            with self.subTest(value=value), self.assertRaises(SnapshotStoreError):
                self.store.requested_collection_scan(value)

    def test_display_limits_population_no_network_and_no_price_admission(self):
        capture(self.store)
        capture(self.store, "azure", amount="99")
        policies = {name: policy(name) for name in ("getdeploying", "azure")}
        plan = [{"source_id": name, "filters": {}} for name in policies]
        with TestClient(create_app(api_key=KEY, store_path=self.path, source_policies=policies,
                                  collection_plan=plan)) as client, patch("compute_pricing.control.api.app.collect_source") as fetch:
            self.assertEqual(client.get("/v1/demo/market").status_code, 401)
            response = client.get("/v1/demo/market", headers=AUTH)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual({row["source_id"] for row in result["observations"]}, {"getdeploying"})
            self.assertEqual({row["source_id"] for row in result["sources"]}, {"getdeploying", "ecb", "energinet_day_ahead"})
            self.assertFalse(result["coverage"]["all_market_sources"])
            self.assertFalse(result["coverage"]["full_history_integrity_scan"])
            self.assertFalse(result["coverage"]["selection_is_benchmark_weighting"])
            self.assertFalse(result["execution_enabled"])
            self.assertIn("commitment_curves", result)
            fetch.assert_not_called()

    def test_current_revocation_and_age_still_apply(self):
        capture(self.store, observed=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3))
        plan = [{"source_id": "getdeploying", "filters": {}}]
        for enabled in (True, False):
            with TestClient(create_app(api_key=KEY, store_path=self.path,
                    source_policies={"getdeploying": policy("getdeploying", enabled)}, collection_plan=plan)) as client:
                response = client.get("/v1/demo/market", headers=AUTH)
                self.assertEqual(response.status_code, 200, response.text)
                rows = response.json()["observations"]
                if enabled:
                    self.assertTrue(rows[0]["index_stale"])
                else:
                    self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
