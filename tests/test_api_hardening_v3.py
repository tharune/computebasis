"""Adversarial offline boundary and concurrent collection checks; invented data."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import datetime as dt
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from fastapi import HTTPException
from starlette.requests import Request
from compute_pricing.control.api import create_app
from compute_pricing.control.api.app import MAX_CONCURRENT_COLLECTIONS, MAX_REQUEST_DEPTH, MAX_REQUEST_NODES
from compute_pricing.control.connectors import ConnectorError, SourcePolicy
from compute_pricing.control.reporting import SnapshotStoreError

KEY = "invented-backend-boundary-test-key-123456"
AUTH = {"Authorization": "Bearer " + KEY}
JSON_AUTH = {**AUTH, "Content-Type": "application/json"}


def policy(name="getdeploying"):
    return SourcePolicy(name, enabled=True, rights_status="allowed", rights_evidence="invented-review",
        verified_by="review:invented", max_age_s=14 * 86400, min_interval_s=0,
        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"})


def batch(source="getdeploying"):
    now = dt.datetime.now(dt.timezone.utc)
    output = {"source_id": source, "raw_metadata": {"captured_at": now.isoformat().replace("+00:00", "Z")},
        "observations": [], "catalog_records": [], "coverage": {"complete": False}, "execution_enabled": False}
    return SimpleNamespace(source_id=source, to_dict=lambda: output)


class APIHardeningTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "snapshots.sqlite"
        self.app = create_app(api_key=KEY, store_path=self.path,
            source_policies={"getdeploying": policy(), "azure": policy("azure")})
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_escaped_surrogates_fail_before_collection_or_snapshot(self):
        with patch("compute_pricing.control.api.app.collect_source") as collect:
            for body in (b'{"source_ids":["\\ud800"]}',
                         b'{"requests":[{"source_id":"getdeploying","filters":{"\\udfff":"x"}}]}'):
                response = self.client.post("/v1/market/refresh", content=body, headers=JSON_AUTH)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), {"detail": "invalid_json_unicode"})
            collect.assert_not_called()
        self.assertIsNone(self.app.state.store.latest_refresh())

    def test_deep_and_wide_json_are_bounded_before_evaluation(self):
        nested = 0
        for _ in range(MAX_REQUEST_DEPTH + 1):
            nested = [nested]
        with patch("compute_pricing.control.api.app._evaluate_pricing") as evaluate:
            response = self.client.post("/v1/pricing/evaluate", json={"unknown": nested}, headers=AUTH)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], "request_nesting_limit")
            response = self.client.post("/v1/pricing/evaluate", json={"unknown": [0] * MAX_REQUEST_NODES}, headers=AUTH)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], "request_structure_limit")
            evaluate.assert_not_called()

    def test_valid_unicode_stays_exact_in_replay(self):
        payload = {"extensions": {"description": "invented model \U0001f642"}}
        with patch("compute_pricing.control.api.app._evaluate_pricing", return_value={"execution_enabled": False}):
            response = self.client.post("/v1/pricing/evaluate", json=payload, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        replay = self.client.get("/v1/decisions/" + response.json()["snapshot_id"], headers=AUTH).json()
        self.assertEqual(replay["document"]["input"], payload)

    def test_null_and_invalid_source_ids_cannot_trigger_default_collection(self):
        with patch("compute_pricing.control.api.app.collect_source") as collect:
            for payload in ({"source_ids": None}, {"source_ids": ["a" * 65]}, {"source_ids": ["http://invented.invalid"]},
                            {"requests": [{"source_id": "Invalid source", "filters": {}}]}):
                self.assertEqual(self.client.post("/v1/market/refresh", json=payload, headers=AUTH).status_code, 422)
            collect.assert_not_called()

    def test_collection_admission_is_shared_between_refresh_and_single_collect(self):
        entered = threading.Barrier(MAX_CONCURRENT_COLLECTIONS + 1, timeout=5)
        release = threading.Event()
        calls, guard = [], threading.Lock()

        def blocked(source, *args, **kwargs):
            with guard:
                calls.append(source)
            entered.wait()
            if not release.wait(5):
                raise RuntimeError("invented timeout")
            return batch(source)

        def post(number):
            path, payload = ("/v1/market/refresh", {"source_ids": ["getdeploying"]}) if number == 0 else ("/v1/sources/getdeploying/collect", {})
            return self.client.post(path, json=payload, headers=AUTH)

        with patch("compute_pricing.control.api.app.collect_source", side_effect=blocked), ThreadPoolExecutor(max_workers=MAX_CONCURRENT_COLLECTIONS) as executor:
            futures = [executor.submit(post, number) for number in range(MAX_CONCURRENT_COLLECTIONS)]
            try:
                entered.wait()
                overflow = self.client.post("/v1/market/refresh", json={"source_ids": ["getdeploying"]}, headers=AUTH)
                self.assertEqual(overflow.status_code, 429)
                self.assertEqual(overflow.json()["detail"], "collection_capacity_exceeded")
                self.assertEqual(overflow.headers["retry-after"], "1")
                self.assertEqual(len(calls), MAX_CONCURRENT_COLLECTIONS)
            finally:
                release.set()
            self.assertTrue(all(future.result(timeout=5).status_code == 200 for future in futures))
        with patch("compute_pricing.control.api.app.collect_source", return_value=batch()):
            self.assertEqual(post(1).status_code, 200)

    def test_unexpected_source_failure_is_isolated_and_diagnostics_are_scrubbed(self):
        def collect(source, *args, **kwargs):
            if source == "azure":
                raise RuntimeError("invented-private-url-and-credential")
            return batch(source)
        with patch("compute_pricing.control.api.app.collect_source", side_effect=collect):
            response = self.client.post("/v1/market/refresh", json={"requests": [
                {"source_id": "azure", "filters": {"region": "invented-region"}},
                {"source_id": "getdeploying", "filters": {}}]}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["updated"]), 1)
        self.assertEqual(response.json()["failed"][0]["reason"], "source_collection_failed")
        self.assertNotIn("invented-private-url", response.text)
        with patch("compute_pricing.control.api.app.collect_source", side_effect=ConnectorError("https://invented.invalid/?secret=private")):
            response = self.client.post("/v1/sources/getdeploying/collect", json={}, headers=AUTH)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "source_collection_failed"})

    def test_storage_failure_releases_collection_admission(self):
        with patch("compute_pricing.control.api.app.collect_source", return_value=batch()):
            with patch.object(self.app.state.store, "put", side_effect=SnapshotStoreError("snapshot_integrity_failed")):
                response = self.client.post("/v1/sources/getdeploying/collect", json={}, headers=AUTH)
            self.assertEqual(response.status_code, 503)
            for _ in range(MAX_CONCURRENT_COLLECTIONS + 1):
                self.assertEqual(self.client.post("/v1/sources/getdeploying/collect", json={}, headers=AUTH).status_code, 200)

    def test_cancelled_request_does_not_release_slot_while_read_still_runs(self):
        entered = threading.Barrier(MAX_CONCURRENT_COLLECTIONS + 1, timeout=5)
        release, finished = threading.Event(), threading.Event()
        calls, completed, guard = [], [], threading.Lock()
        persisted, persisted_calls = threading.Event(), []
        original_put = self.app.state.store.put

        def durable_put(*args, **kwargs):
            result = original_put(*args, **kwargs)
            if kwargs.get("kind") == "market_collection":
                with guard:
                    persisted_calls.append(result)
                    if len(persisted_calls) >= MAX_CONCURRENT_COLLECTIONS:
                        persisted.set()
            return result

        def blocked(source, *args, **kwargs):
            with guard:
                calls.append(source)
                number = len(calls)
            if number <= MAX_CONCURRENT_COLLECTIONS:
                entered.wait()
                if not release.wait(5):
                    raise RuntimeError("invented timeout")
                with guard:
                    completed.append(number)
                    if len(completed) == MAX_CONCURRENT_COLLECTIONS:
                        finished.set()
            return batch(source)

        async def scenario():
            # Cancel the route coroutine itself, independently of HTTP clients'
            # task-group shielding, while its blocking worker remains active.
            endpoint = next(route.endpoint for route in self.app.routes if route.path == "/v1/sources/{source_id}/collect")
            def request():
                async def receive():
                    return {"type": "http.request", "body": b"{}", "more_body": False}
                return Request({"type": "http", "headers": [(b"content-type", b"application/json")]}, receive)
            tasks = [asyncio.create_task(endpoint("getdeploying", request())) for _ in range(MAX_CONCURRENT_COLLECTIONS)]
            try:
                await asyncio.to_thread(entered.wait)
                tasks[0].cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tasks[0]
                self.assertFalse(finished.is_set())
                with self.assertRaises(HTTPException) as failure:
                    await endpoint("getdeploying", request())
                self.assertEqual(failure.exception.status_code, 429)
                self.assertEqual(len(calls), MAX_CONCURRENT_COLLECTIONS)
            finally:
                release.set()
                await asyncio.gather(*tasks[1:], return_exceptions=True)
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))
                # Mock-source completion precedes the real snapshot write. A
                # cancelled route retains its worker through that durable write;
                # wait for it before removing the temporary database in teardown.
                self.assertTrue(await asyncio.to_thread(persisted.wait, 5))
            self.assertIn("snapshot_id", await endpoint("getdeploying", request()))

        with patch("compute_pricing.control.api.app.collect_source", side_effect=blocked), patch.object(self.app.state.store, "put", side_effect=durable_put):
            asyncio.run(scenario())

    def test_direct_store_rejects_unpaired_unicode_and_bad_configuration_is_explicit(self):
        for bad in ({"bad": "\ud800"}, {"\udfff": "bad"}):
            with self.assertRaises(SnapshotStoreError):
                self.app.state.store.put(kind="pricing", input_payload=bad, output_payload={}, versions={"model": "invented"})
        for plan in ({}, [{"source_id": "getdeploying", "filters": {"bad": "\ud800"}}]):
            with self.assertRaises(ValueError):
                create_app(api_key=KEY, store_path=self.path, collection_plan=plan)
        with self.assertRaises(ValueError):
            create_app(api_key=KEY, store_path=self.path, source_policies={"getdeploying": policy("azure")})
        with self.assertRaises(ValueError):
            create_app(api_key=KEY, store_path=self.path, source_policies=[])
        with self.assertRaises(ValueError):
            create_app(api_key=KEY, store_path=self.path, local_instance_id=1)

    def test_cancelled_queued_collection_cannot_start_later_and_releases_capacity(self):
        queued = []
        endpoint = next(route.endpoint for route in self.app.routes if route.path == "/v1/sources/{source_id}/collect")
        def request():
            async def receive():
                return {"type": "http.request", "body": b"{}", "more_body": False}
            return Request({"type": "http", "headers": [(b"content-type", b"application/json")]}, receive)

        async def scenario():
            entered = asyncio.Event()
            async def deferred(function, *args):
                queued.append((function, args))
                entered.set()
                await asyncio.Future()
            with patch("compute_pricing.control.api.app.run_in_threadpool", side_effect=deferred):
                task = asyncio.create_task(endpoint("getdeploying", request()))
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        with patch("compute_pricing.control.api.app.collect_source", return_value=batch()) as collect:
            asyncio.run(scenario())
            for function, args in queued:
                with self.assertRaisesRegex(ConnectorError, "collection_request_cancelled"):
                    function(*args)
            collect.assert_not_called()
            for _ in range(MAX_CONCURRENT_COLLECTIONS + 1):
                self.assertIn("snapshot_id", asyncio.run(endpoint("getdeploying", request())))


if __name__ == "__main__":
    unittest.main()
