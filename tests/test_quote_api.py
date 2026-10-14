"""Authenticated quote studies preserve declared-evidence and replay boundaries."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from starlette.requests import Request

from compute_pricing.control._numbers import digest
from compute_pricing.control.api import create_app
from compute_pricing.control.api.sessions import request_scope
from compute_pricing.control.market_quotes import quote_contract
from test_market_quotes import book


class QuoteStudyAPITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.key = "invented-quote-api-client-key-000003"
        self.auth = {"Authorization": "Bearer " + self.key}
        self.app = create_app(api_key=self.key, store_path=Path(self.folder.name) / "quotes.sqlite")
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_contract_requires_auth_and_empty_intake_does_not_seed_a_book(self):
        self.assertEqual(self.client.get("/v1/quotes/contract").status_code, 401)
        response = self.client.get("/v1/quotes/contract", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        contract = response.json()
        self.assertEqual(contract, quote_contract())
        self.assertFalse(contract["missing_is_known"])
        self.assertFalse(contract["firm_price_eligible"])
        self.assertFalse(contract["inventory_verified"])
        self.assertFalse(contract["execution_enabled"])
        self.assertFalse(contract["source_evidence_eligible"])
        self.assertNotIn("best_bid", contract)
        self.assertNotIn("best_ask", contract)
        self.assertNotIn("midpoint", contract)
        blank = self.client.post("/v1/quotes/evaluate", json={}, headers=self.auth)
        self.assertEqual(blank.status_code, 422, blank.text)
        template = contract["template_unknown"]
        self.assertIsNone(template["as_of"])
        self.assertIsNone(template["max_age_seconds"])
        self.assertIsNone(template["target"]["quantity"])
        self.assertEqual(template["quotes"], [])
        self.assertTrue(all(value is None for value in template["target"]["configuration"].values()))
        self.assertTrue(all(value is None for value in template["target"]["cost_scope"].values()))
        self.assertIsNone(contract["quote_template_unknown"]["price"])
        self.assertTrue(all(value is None for value in contract["quote_template_unknown"]["rights"].values()))
        unpriced = self.client.post("/v1/quotes/evaluate", json=template, headers=self.auth)
        self.assertEqual(unpriced.status_code, 422, unpriced.text)
        template["target"]["quantity"] = "99"
        contract["quote_template_unknown"]["rights"]["execution"] = "PASS"
        fresh = self.client.get("/v1/quotes/contract", headers=self.auth).json()
        self.assertIsNone(fresh["template_unknown"]["target"]["quantity"])
        self.assertIsNone(fresh["quote_template_unknown"]["rights"]["execution"])

    def test_midpoint_declared_evidence_false_and_hash_bound_immutable_replay(self):
        request = book()
        response = self.client.post("/v1/quotes/evaluate", json=request, headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        receipt = response.json()
        output = receipt["result"]
        self.assertEqual(output["midpoint"], "6.2")
        self.assertEqual(output["best_bid"]["price"], "6")
        self.assertEqual(output["best_ask"]["price"], "6.4")
        self.assertEqual(output["source_evidence_basis"], "caller_declared_not_server_admitted")
        for gate in ("source_evidence_eligible", "firm_price_eligible", "inventory_verified", "tradable", "execution_enabled"):
            self.assertFalse(output[gate])
        self.assertFalse(receipt["execution_enabled"])
        self.assertEqual(output["input_hash"], digest(request))
        self.assertEqual(output["decision_hash"], digest({key: value for key, value in output.items() if key != "decision_hash"}))
        replay_url = "/v1/decisions/" + receipt["snapshot_id"]
        replay = self.client.get(replay_url, headers=self.auth)
        self.assertEqual(replay.status_code, 200)
        document = replay.json()["document"]
        self.assertEqual(document["kind"], "quote_study")
        self.assertEqual(document["input"], request)
        self.assertEqual(document["output"], output)
        repeated = self.client.post("/v1/quotes/evaluate", json=deepcopy(request), headers=self.auth)
        self.assertEqual(repeated.json()["snapshot_id"], receipt["snapshot_id"])
        request["quotes"][1]["price"] = "6.1"
        changed = self.client.post("/v1/quotes/evaluate", json=request, headers=self.auth)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["result"]["midpoint"], "6.25")
        self.assertNotEqual(changed.json()["snapshot_id"], receipt["snapshot_id"])
        self.assertEqual(self.client.get(replay_url, headers=self.auth).json(), replay.json())

    def test_unauthorized_quote_writes_are_401_before_json_or_kernel_processing(self):
        for headers in ({}, {"Authorization": "Bearer invented-wrong-client-key"},
                        {"Authorization": "Basic " + self.key}):
            response = self.client.post("/v1/quotes/evaluate", content=b'{"price":NaN}',
                                        headers={**headers, "Content-Type": "application/json"})
            self.assertEqual(response.status_code, 401, response.text)

    def test_malformed_unknown_and_nonexact_input_is_422_known_unknown_terms_are_held(self):
        mutations = (
            lambda p: p.pop("max_age_seconds"),
            lambda p: p.update(target=None),
            lambda p: p.update(unregistered_proxy_price="2"),
            lambda p: p["quotes"][0].update(price=5.8),
            lambda p: p["quotes"][0].update(price="5.8e0"),
            lambda p: p["quotes"][0]["rights"].pop("benchmark"),
        )
        for mutate in mutations:
            request = book(); mutate(request)
            response = self.client.post("/v1/quotes/evaluate", json=request, headers=self.auth)
            self.assertEqual(response.status_code, 422, response.text)
        request = book(); request["target"]["configuration"]["privacy_class"] = None
        response = self.client.post("/v1/quotes/evaluate", json=request, headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["result"]["status"], "held")
        self.assertIsNone(response.json()["result"]["midpoint"])
        self.assertIn("configuration_privacy_class_unknown", response.json()["result"]["hold_reasons"])

    def test_browser_quote_evaluate_requires_same_origin_current_csrf_and_explicit_scope(self):
        site = "http://127.0.0.1:8883"
        fetch = {"Origin": site, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
        browser_app = create_app(workbench_origin=site, store_path=Path(self.folder.name) / "browser-quotes.sqlite")
        with TestClient(browser_app, base_url=site) as browser:
            self.assertEqual(browser.get("/v1/quotes/contract", headers=fetch).status_code, 401)
            boot = browser.post("/v1/session/bootstrap", json={}, headers=fetch)
            self.assertEqual(boot.status_code, 200, boot.text)
            self.assertIn("evaluate", boot.json()["scopes"])
            csrf = boot.json()["csrf_token"]
            scope_request = Request({"type": "http", "path": "/v1/quotes/evaluate", "method": "POST", "headers": []})
            self.assertEqual(request_scope(scope_request), "evaluate")
            self.assertEqual(browser.get("/v1/quotes/contract", headers=fetch).status_code, 200)
            for headers in (fetch, {**fetch, "X-Compute-CSRF": "0" * 64},
                            {**fetch, "X-Compute-CSRF": csrf, "Origin": "http://127.0.0.1:8884"}):
                response = browser.post("/v1/quotes/evaluate", json=book(), headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
            response = browser.post("/v1/quotes/evaluate", json=book(), headers={**fetch, "X-Compute-CSRF": csrf})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["result"]["midpoint"], "6.2")
            replay = browser.get("/v1/decisions/" + response.json()["snapshot_id"], headers=fetch)
            self.assertEqual(replay.json()["document"]["output"], response.json()["result"])


if __name__ == "__main__":
    unittest.main()
