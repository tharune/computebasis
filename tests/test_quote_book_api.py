"""The quote-book endpoints: authenticated, CSRF-protected, conditional, and nothing is persisted."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.api.sessions import request_scope
from starlette.requests import Request

KEY = "k" * 40
AUTH = {"Authorization": "Bearer " + KEY}
ORIGIN = "http://127.0.0.1:8765"
BROWSER = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}


class QuoteBookApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Path(self.directory.name) / "store.sqlite"
        self.app = create_app(api_key=KEY, store_path=self.store)
        self.client = TestClient(self.app)

    def test_both_routes_require_authentication(self):
        self.assertEqual(self.client.get("/v1/book").status_code, 401)
        self.assertEqual(self.client.post("/v1/book/control", json={"action": "pause"}).status_code, 401)

    def test_snapshot_is_marked_simulated_and_never_cached(self):
        response = self.client.get("/v1/book", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.headers["etag"].startswith('W/"book-'))
        self.assertIs(response.json()["simulated"], True)

    def test_a_matching_tag_gets_304_and_a_moved_market_gets_a_body(self):
        first = self.client.get("/v1/book", headers=AUTH)
        again = self.client.get("/v1/book", headers={**AUTH, "If-None-Match": first.headers["etag"]})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b"")
        self.assertEqual(again.headers["etag"], first.headers["etag"])
        self.client.post("/v1/book/control", json={"action": "scenario", "scenario": "price_war"}, headers=AUTH)
        changed = self.client.get("/v1/book", headers={**AUTH, "If-None-Match": first.headers["etag"]})
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.headers["etag"], first.headers["etag"])

    def test_control_validates_strictly(self):
        for body in ({}, {"action": "explode"}, {"action": "scenario"}, {"action": "scenario", "scenario": "nope"},
                     {"action": "pause", "scenario": "price_war"}, {"action": "pause", "extra": 1}, {"action": 5},
                     {"action": "scenario", "scenario": 5}):
            self.assertEqual(self.client.post("/v1/book/control", json=body, headers=AUTH).status_code, 422, body)
        self.assertEqual(self.client.post("/v1/book/control", content=b"[]", headers={**AUTH, "Content-Type": "application/json"}).status_code in (400, 422), True)
        self.assertEqual(self.client.post("/v1/book/control", content=b'{"action":"pause"}', headers={**AUTH, "Content-Type": "text/plain"}).status_code, 415)

    def test_control_changes_the_market_and_reports_state(self):
        result = self.client.post("/v1/book/control", json={"action": "pause"}, headers=AUTH)
        self.assertEqual(result.status_code, 200)
        self.assertEqual((result.json()["paused"], result.json()["simulated"], result.json()["execution_enabled"]), (True, True, False))
        self.assertTrue(self.client.get("/v1/book", headers=AUTH).json()["meta"]["paused"])
        self.assertFalse(self.client.post("/v1/book/control", json={"action": "resume"}, headers=AUTH).json()["paused"])

    def test_the_simulation_writes_nothing_to_the_snapshot_store(self):
        def rows():
            with sqlite3.connect(self.store) as db:
                return {name: db.execute(f"select count(*) from {name}").fetchone()[0]
                        for (name,) in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
        before = rows()
        self.client.get("/v1/book", headers=AUTH)
        for body in ({"action": "scenario", "scenario": "downgrade"}, {"action": "reset"}):
            self.client.post("/v1/book/control", json=body, headers=AUTH)
        self.assertEqual(rows(), before)

    def test_the_market_is_built_only_when_first_used(self):
        self.assertIsNone(getattr(self.app.state, "quote_book", None))
        self.client.get("/v1/book", headers=AUTH)
        self.assertIsNotNone(self.app.state.quote_book)

    def test_the_browser_scope_is_explicit(self):
        scope = lambda method, path: request_scope(Request({"type": "http", "method": method, "path": path, "headers": []}))
        self.assertEqual(scope("POST", "/v1/book/control"), "book")
        self.assertEqual(scope("GET", "/v1/book"), "read")
        self.assertEqual(scope("POST", "/v1/book/other"), "unsupported")
        self.assertEqual(scope("PUT", "/v1/book/control"), "unsupported")


class QuoteBookBrowserSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app(store_path=Path(self.directory.name) / "store.sqlite", workbench_origin=ORIGIN)
        self.client = TestClient(self.app, base_url=ORIGIN)

    def test_a_browser_session_needs_its_csrf_token_to_drive_the_simulation(self):
        self.assertEqual(self.client.get("/v1/book", headers=BROWSER).status_code, 401)
        csrf = self.client.post("/v1/session/bootstrap", json={}, headers=BROWSER).json()["csrf_token"]
        self.assertEqual(self.client.get("/v1/book", headers=BROWSER).status_code, 200)
        body = {"action": "scenario", "scenario": "supply_shock"}
        self.assertEqual(self.client.post("/v1/book/control", json=body, headers=BROWSER).status_code, 403)
        self.assertEqual(self.client.post("/v1/book/control", json=body, headers={**BROWSER, "X-Compute-CSRF": "0" * 64}).status_code, 403)
        self.assertEqual(self.client.post("/v1/book/control", json=body, headers={**BROWSER, "X-Compute-CSRF": csrf}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
