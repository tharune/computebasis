"""Current retained evidence updates, conditional reads and bounded sessions."""
import asyncio
import datetime as dt
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.api.live_market import MarketReader, MarketStreams, cache_lifetime, market_events
from test_demo_market import AUTH, KEY, capture, policy


class CurrentMarketFlowTests(unittest.TestCase):
    def test_separate_loopback_frontend_proxy_preserves_exact_host_origin_and_csrf(self):
        origin = "http://127.0.0.1:5173"
        metadata = {"Host": "127.0.0.1:5173", "Origin": origin, "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
        app = create_app(store_path=self.path, workbench_origin=origin)
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            self.assertEqual(client.post("/v1/session/bootstrap", json={}, headers={**metadata, "Host": "127.0.0.1:8000"}).status_code, 403)
            response = client.post("/v1/session/bootstrap", json={}, headers=metadata)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/v1/market/current", headers=metadata).status_code, 200)
            self.assertEqual(client.post("/v1/requests/parse", json={}, headers=metadata).status_code, 403)
            self.assertEqual(client.post("/v1/requests/parse", json={}, headers={**metadata, "X-Compute-CSRF": response.json()["csrf_token"]}).status_code, 200)

    def test_cache_deadline_preserves_record_expiry_and_source_age(self):
        now = dt.datetime(2053, 7, 1, tzinfo=dt.timezone.utc)
        packet = {"as_of": "2053-07-01T00:00:00Z", "snapshots": [], "catalog_records": [],
            "observations": [{"source_id": "getdeploying", "observed_at": "2053-06-30T00:00:12Z",
                "expires_at": "2053-07-01T00:00:09.125Z", "rights": {"expires_at": "2053-07-01T00:00:07Z"}}]}
        self.assertEqual(cache_lifetime(packet, {"getdeploying": policy("getdeploying")}, now=now), 7)
        self.assertEqual(cache_lifetime(packet, {"getdeploying": policy("getdeploying")}, now=now + dt.timedelta(seconds=8)), 0)
        packet["observations"][0]["rights"]["expires_at"] = None
        self.assertEqual(cache_lifetime(packet, {"getdeploying": policy("getdeploying")}, now=now), 9.125)
        packet["observations"][0]["expires_at"] = None
        self.assertEqual(cache_lifetime(packet, {"getdeploying": policy("getdeploying")}, now=now), 12)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "decisions.sqlite"
        self.policies = {"getdeploying": policy("getdeploying"), "azure": policy("azure")}
        self.plan = [{"source_id": name, "filters": {}} for name in self.policies]
        self.app = create_app(api_key=KEY, store_path=self.path, source_policies=self.policies, collection_plan=self.plan)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_current_read_keeps_all_configured_sources_and_no_vendor_request(self):
        capture(self.app.state.store)
        capture(self.app.state.store, "azure", amount="8")
        with patch("compute_pricing.control.api.app.collect_source") as collect:
            self.assertEqual(self.client.get("/v1/market/current").status_code, 401)
            response = self.client.get("/v1/market/current", headers=AUTH)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual({row["source_id"] for row in result["observations"]}, {"getdeploying", "azure"})
            self.assertEqual(result["schema_version"], "current-market/1.0")
            self.assertFalse(result["coverage"]["all_market_sources"])
            self.assertFalse(result["coverage"]["full_history_integrity_scan"])
            self.assertEqual(result["cache_max_age_seconds"], 60)
            self.assertIn("Cookie", response.headers["vary"])
            collect.assert_not_called()

    def test_conditional_read_auth_and_new_retained_price_invalidate_revision(self):
        capture(self.app.state.store)
        first = self.client.get("/v1/market/current", headers=AUTH)
        tag = first.headers["etag"]
        self.assertEqual(self.client.get("/v1/market/current", headers={"If-None-Match": tag}).status_code, 401)
        same = self.client.get("/v1/market/current", headers={**AUTH, "If-None-Match": tag})
        self.assertEqual(same.status_code, 304)
        self.assertEqual(same.content, b"")
        capture(self.app.state.store, amount="4.125")
        changed = self.client.get("/v1/market/current", headers={**AUTH, "If-None-Match": tag})
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.headers["etag"], tag)
        self.assertEqual(changed.json()["observations"][0]["price"]["amount"], "4.125")

    def test_time_only_does_not_rewrite_revision_and_policy_revocation_is_immediate(self):
        capture(self.app.state.store)
        clock = [10.0]
        policies = self.app.state.market_reader.policies
        reader = MarketReader(self.app.state.store, policies, self.plan, lambda: {}, clock=lambda: clock[0])
        first = reader.read()
        self.assertIs(reader.read(), first)
        clock[0] += 61
        self.assertEqual(reader.read().revision, first.revision)
        policies["getdeploying"] = replace(policies["getdeploying"], enabled=False)
        denied = reader.read()
        self.assertNotEqual(denied.revision, first.revision)
        import json
        self.assertEqual(json.loads(denied.body)["observations"], [])

    def test_event_contract_no_vendor_payload_and_leases_release(self):
        capture(self.app.state.store)
        with patch("compute_pricing.control.api.app.collect_source") as collect:
            response = self.client.get("/v1/market/events?lease_seconds=1", headers=AUTH)
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            self.assertIn("event: market_update", response.text)
            self.assertIn('"view_endpoint":"/v1/market/current"', response.text)
            self.assertIn("event: stream_renew", response.text)
            self.assertNotIn('"observations":', response.text)
            self.assertEqual(self.app.state.market_streams.active, 0)
            collect.assert_not_called()

    def test_event_capacity_invalid_leases_and_idempotent_release(self):
        streams = self.app.state.market_streams
        permits = [streams.acquire() for _ in range(streams.maximum)]
        try:
            self.assertEqual(self.client.get("/v1/market/events?lease_seconds=1", headers=AUTH).status_code, 429)
        finally:
            for permit in permits:
                permit.release(); permit.release()
        self.assertEqual(streams.active, 0)
        for lease in (0, 61):
            self.assertEqual(self.client.get(f"/v1/market/events?lease_seconds={lease}", headers=AUTH).status_code, 422)
        self.assertEqual(self.client.get("/v1/market/events?lease_seconds=1").status_code, 401)

    def test_midstream_auth_revocation_stops_before_returning_a_view(self):
        class Request:
            async def is_disconnected(self):
                return False
        async def reject(request):
            raise HTTPException(401, detail="offline-revoked-session")
        async def read_view(function):
            self.fail("revoked stream must not read evidence")
        async def run():
            streams = MarketStreams()
            permit = streams.acquire()
            chunks = [chunk async for chunk in market_events(Request(), None, permit,
                lease_seconds=1, read_view=read_view, authorize=reject)]
            self.assertIn("event: session_expired", "".join(chunks))
            self.assertEqual(streams.active, 0)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
