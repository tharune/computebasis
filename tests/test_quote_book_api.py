"""The invented book is authenticated and cannot enter retained market evidence."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from compute_pricing.control.api import create_app
from compute_pricing.control.api.quote_book import etag_matches
from compute_pricing.control.quote_book import QuoteBook


class BookAPITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.key = "invented-book-client-credential-000004"
        self.auth = {"Authorization": "Bearer " + self.key}
        self.app = create_app(api_key=self.key, store_path=Path(self.folder.name) / "paper.sqlite")
        self.app.state.quote_book = QuoteBook(clock=lambda: 0)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_book_remains_separate_from_market_evidence_and_holdings(self):
        with patch("compute_pricing.control.api.app.collect_source") as collect:
            response = self.client.get("/v1/book", headers=self.auth)
            self.assertEqual(response.status_code, 200)
            book = response.json()
            self.assertTrue(book["simulated"])
            self.assertFalse(book["execution_enabled"])
            self.assertEqual(len(book["providers"]), 32)
            self.assertEqual(len(book["quotes"]), 192)
            self.assertTrue(all(isinstance(row["price"], str) for row in book["quotes"]))
            collect.assert_not_called()
        self.assertIsNone(self.app.state.store.latest_refresh())
        self.assertEqual(self.client.get("/v1/inventory", headers=self.auth).json()["state"]["lots"], [])

    def test_etag_reads_authenticate_even_when_the_tag_matches(self):
        response = self.client.get("/v1/book", headers=self.auth)
        etag = response.headers["etag"]
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["vary"], "Cookie, Authorization")
        self.assertEqual(self.client.get("/v1/book", headers={**self.auth, "If-None-Match": etag}).status_code, 304)
        self.assertEqual(self.client.get("/v1/book", headers={"If-None-Match": etag}).status_code, 401)
        self.assertTrue(etag_matches('"other", ' + etag.removeprefix("W/"), etag))
        self.assertTrue(etag_matches("*", etag))
        self.assertFalse(etag_matches('"other"', etag))

    def test_invalid_or_unauthorized_controls_cannot_change_the_book(self):
        before = self.app.state.quote_book.snapshot()
        invalid = ({}, {"action": None}, {"action": "trade"}, {"action": "reset", "extra": True},
                   {"action": "pause", "scenario": "price_war"}, {"action": "scenario"},
                   {"action": "scenario", "scenario": "unknown"}, {"action": "reset", "scenario": None})
        for payload in invalid:
            response = self.client.post("/v1/book/control", json=payload, headers=self.auth)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(self.app.state.quote_book.snapshot(), before)
        response = self.client.post("/v1/book/control", content=b'{"action":NaN}')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.app.state.quote_book.snapshot(), before)

    def test_controls_are_explicit_paper_mutations(self):
        result = self.client.post("/v1/book/control", json={"action": "pause"}, headers=self.auth)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["paused"])
        self.assertTrue(result.json()["simulated"])
        self.assertFalse(result.json()["execution_enabled"])
        after = self.client.get("/v1/book", headers=self.auth)
        scenario = self.client.post("/v1/book/control", json={"action": "scenario", "scenario": "price_war"}, headers=self.auth)
        self.assertEqual(scenario.status_code, 200, scenario.text)
        self.assertNotEqual(self.client.get("/v1/book", headers=self.auth).headers["etag"], after.headers["etag"])
        self.assertIsNone(self.app.state.store.latest_refresh())

    def test_browser_control_requires_exact_origin_session_scope_and_csrf(self):
        origin = "http://127.0.0.1:8877"
        fetch = {"Origin": origin, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
        app = create_app(workbench_origin=origin, store_path=Path(self.folder.name) / "browser.sqlite")
        with TestClient(app, base_url=origin) as browser:
            self.assertEqual(browser.get("/v1/book", headers=fetch).status_code, 401)
            boot = browser.post("/v1/session/bootstrap", json={}, headers=fetch)
            self.assertEqual(boot.status_code, 200)
            self.assertIn("book", boot.json()["scopes"])
            self.assertEqual(browser.post("/v1/book/control", json={"action": "pause"}, headers=fetch).status_code, 403)
            csrf = {**fetch, "X-Compute-CSRF": boot.json()["csrf_token"]}
            self.assertEqual(browser.post("/v1/book/control", json={"action": "pause"}, headers=csrf).status_code, 200)
            self.assertEqual(browser.post("/v1/book/control", json={"action": "reset"}, headers={**csrf, "Origin": "http://127.0.0.1:8878"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
