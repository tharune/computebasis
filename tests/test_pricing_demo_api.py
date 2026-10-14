"""Declared demo inputs persist through authenticated receipt-bound PDF routes."""
from copy import deepcopy
import datetime as dt
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader
from starlette.requests import Request

from compute_pricing.control._numbers import digest
from compute_pricing.control.api import create_app
from compute_pricing.control.api.live_market import configured_market
from compute_pricing.control.api.pricing_demo import demo_references
from compute_pricing.control.api.sessions import request_scope
from compute_pricing.control.demo_pricing import demo_contract
from compute_pricing.control.demo_pricing.agreement import MARKING
from compute_pricing.control.connectors import SourcePolicy
from compute_pricing.control.reporting.store import canonical_document


class PricingDemoAPITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.key = "invented-pricing-demo-reader-token-0032"
        self.auth = {"Authorization": "Bearer " + self.key}
        self.app = create_app(api_key=self.key, store_path=Path(self.folder.name) / "pricing.sqlite")
        self.client = TestClient(self.app)
        self.no_collection = patch("compute_pricing.control.api.app.collect_source", side_effect=AssertionError("Demo must read retained evidence only"))
        self.collect = self.no_collection.start()

    def tearDown(self):
        self.client.close()
        self.no_collection.stop()
        self.folder.cleanup()

    def post_case(self, inputs):
        response = self.client.post("/v1/pricing/demo/evaluate", headers=self.auth, json=inputs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_contract_and_three_cases_persist_exact_decisions_and_distinct_three_page_pdfs(self):
        response = self.client.get("/v1/pricing/demo/contract", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        contract = response.json()
        self.assertEqual(contract, demo_contract())
        self.assertIsNone(contract["template"]["pricing"]["supplier_rate"])
        snapshots, pdfs = [], []
        for case in contract["scenarios"]:
            with self.subTest(case=case["id"]):
                inputs = case["inputs"]
                receipt = self.post_case(inputs)
                identity, result = receipt["snapshot_id"], receipt["result"]
                snapshots.append(identity)
                self.assertEqual(result["status"], "scenario_estimate")
                self.assertFalse(receipt["execution_enabled"])
                self.assertIsNone(result["pricing"]["bid"])
                self.assertFalse(result["source_evidence_eligible"])
                self.assertFalse(result["firm_price_eligible"])
                self.assertEqual(result["live_references"]["references"], [])
                self.assertIsNone(result["live_references"]["midpoint"])
                self.assertIsNone(result["live_references"]["bid"])
                unsigned = {key: value for key, value in result.items() if key != "decision_hash"}
                self.assertEqual(result["decision_hash"], digest(unsigned))
                replay = self.client.get("/v1/decisions/" + identity, headers=self.auth)
                self.assertEqual(replay.status_code, 200, replay.text)
                document = replay.json()["document"]
                self.assertEqual(document["kind"], "demo_pricing")
                self.assertEqual(document["input"], inputs)
                self.assertEqual(document["output"], result)
                self.assertEqual(identity, hashlib.sha256(canonical_document(document, max_bytes=2 * 1024 * 1024).encode()).hexdigest())
                pdf = self.client.get("/v1/pricing/demo/" + identity + "/agreement.pdf", headers=self.auth)
                self.assertEqual(pdf.status_code, 200, pdf.text if pdf.status_code != 200 else "")
                self.assertTrue(pdf.content.startswith(b"%PDF-"))
                self.assertEqual(pdf.headers["content-type"], "application/pdf")
                self.assertEqual(pdf.headers["cache-control"], "no-store")
                self.assertEqual(pdf.headers["x-content-type-options"], "nosniff")
                pdfs.append(pdf.content)
                reader = PdfReader(BytesIO(pdf.content))
                self.assertEqual(len(reader.pages), 3)
                text = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
                for page in reader.pages:
                    self.assertIn(MARKING, page.extract_text())
                    self.assertIn(identity[:12], page.extract_text())
                for value in (inputs["capacity"]["model"], inputs["provider"]["label"], inputs["settlement"]["buyer_label"],
                              "USD " + inputs["pricing"]["supplier_rate"] + " / GPU-hour", "Opening / minimum cash", "Power model"):
                    self.assertIn(value, text)
                self.assertIn("Governing law: UNRESOLVED", text)
                self.assertIn("Signatures: NOT EXECUTED", text)
        self.assertEqual(len(set(snapshots)), 3)
        self.assertEqual(len(set(pdfs)), 3)
        self.collect.assert_not_called()

    def test_edited_names_prices_and_receipts_do_not_rewrite_old_decisions(self):
        inputs = demo_contract()["scenarios"][0]["inputs"]
        first = self.post_case(inputs)
        route = "/v1/decisions/" + first["snapshot_id"]
        replay_before = self.client.get(route, headers=self.auth).json()
        inputs["provider"]["label"] = "Invented Elm Supplier"
        inputs["settlement"]["buyer_label"] = "Invented Lantern Buyer"
        inputs["pricing"]["buyer_rate"] = "4.8"
        second = self.post_case(inputs)
        self.assertNotEqual(second["snapshot_id"], first["snapshot_id"])
        self.assertNotEqual(second["result"]["summary"]["expected_profit"], first["result"]["summary"]["expected_profit"])
        self.assertEqual(self.client.get(route, headers=self.auth).json(), replay_before)
        pdf = self.client.get("/v1/pricing/demo/" + second["snapshot_id"] + "/agreement.pdf", headers=self.auth)
        self.assertEqual(pdf.status_code, 200)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        self.assertIn("Invented Elm Supplier", text)
        self.assertIn("Invented Lantern Buyer", text)

    def test_auth_unknown_invalid_wrong_kind_and_incomplete_agreement_boundaries(self):
        inputs = demo_contract()["scenarios"][0]["inputs"]
        for method, path in (("get", "/v1/pricing/demo/contract"), ("get", "/v1/pricing/demo/references?hardware_model=H100"),
                ("get", "/v1/pricing/demo/" + "0" * 64 + "/agreement.pdf")):
            self.assertEqual(getattr(self.client, method)(path).status_code, 401)
        self.assertEqual(self.client.post("/v1/pricing/demo/evaluate", json=inputs).status_code, 401)
        invalid = deepcopy(inputs); invalid["pricing"]["supplier_rate"] = 2.45
        self.assertEqual(self.client.post("/v1/pricing/demo/evaluate", headers=self.auth, json=invalid).status_code, 422)
        self.assertEqual(self.client.post("/v1/pricing/demo/evaluate", headers=self.auth, json=demo_contract()["template"]).status_code, 422)
        for identity in ("0" * 64, "invalid-hash"):
            self.assertEqual(self.client.get("/v1/pricing/demo/" + identity + "/agreement.pdf", headers=self.auth).status_code, 404)
        wrong = self.app.state.store.put(kind="pricing", input_payload={"independently_invented": True}, output_payload={}, versions={"test": "1"})
        self.assertEqual(self.client.get("/v1/pricing/demo/" + wrong.digest + "/agreement.pdf", headers=self.auth).status_code, 404)
        partial = deepcopy(inputs); partial["pricing"]["buyer_rate"] = None
        held = self.post_case(partial)
        self.assertEqual(held["result"]["status"], "held")
        self.assertIsNone(held["result"]["summary"]["purchase_ceiling"])
        self.assertEqual(self.client.get("/v1/pricing/demo/" + held["snapshot_id"] + "/agreement.pdf", headers=self.auth).status_code, 422)
        malformed = self.app.state.store.put(kind="demo_pricing", input_payload={"classification": "synthetic"},
            output_payload={"classification": "synthetic", "execution_enabled": False, "firm_price_eligible": False}, versions={"test": "1"})
        self.assertEqual(self.client.get("/v1/pricing/demo/" + malformed.digest + "/agreement.pdf", headers=self.auth).status_code, 422)
        self.collect.assert_not_called()

    def test_browser_evaluation_requires_scope_same_origin_and_current_csrf(self):
        site = "http://127.0.0.1:8931"
        headers = {"Origin": site, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
        app = create_app(workbench_origin=site, store_path=Path(self.folder.name) / "browser.sqlite")
        inputs = demo_contract()["scenarios"][2]["inputs"]
        with TestClient(app, base_url=site) as browser:
            self.assertEqual(browser.get("/v1/pricing/demo/contract", headers=headers).status_code, 401)
            boot = browser.post("/v1/session/bootstrap", json={}, headers=headers)
            self.assertEqual(boot.status_code, 200, boot.text)
            self.assertIn("evaluate", boot.json()["scopes"])
            scope = request_scope(Request({"type": "http", "path": "/v1/pricing/demo/evaluate", "method": "POST", "headers": []}))
            self.assertEqual(scope, "evaluate")
            csrf = boot.json()["csrf_token"]
            for attempt in (headers, {**headers, "X-Compute-CSRF": "0" * 64}, {**headers, "X-Compute-CSRF": csrf, "Origin": "http://127.0.0.1:8932"}):
                self.assertEqual(browser.post("/v1/pricing/demo/evaluate", headers=attempt, json=inputs).status_code, 403)
            response = browser.post("/v1/pricing/demo/evaluate", headers={**headers, "X-Compute-CSRF": csrf}, json=inputs)
            self.assertEqual(response.status_code, 200, response.text)
            pdf = browser.get("/v1/pricing/demo/" + response.json()["snapshot_id"] + "/agreement.pdf", headers=headers)
            self.assertEqual(pdf.status_code, 200)
        self.collect.assert_not_called()

    def test_pricing_reads_latest_exact_configured_scope_and_never_full_collection_history(self):
        policy = SourcePolicy("getdeploying", enabled=True, rights_status="allowed",
            rights_evidence="independently-invented-api-test-permission", verified_by="review:example-only",
            permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"}, max_age_s=86400)
        plan = [{"source_id": "getdeploying", "filters": {"example_scope": "configured"}}]
        app = create_app(api_key=self.key, store_path=Path(self.folder.name) / "configured.sqlite",
            source_policies={"getdeploying": policy}, collection_plan=plan)
        now = dt.datetime.now(dt.timezone.utc)

        def capture(scope, amount):
            return app.state.store.put(kind="market_collection", input_payload={"source_id": "getdeploying", "filters": {"example_scope": scope}},
                output_payload={"source_id": "getdeploying", "raw_metadata": {"captured_at": now.isoformat()},
                    "observations": [{"id": "invented-configured-reference", "source_id": "getdeploying", "kind": "listing_ask",
                        "hardware": {"model": "H100"}, "price": {"amount": amount, "unit": "gpu_hour", "currency": "USD"},
                        "observed_at": now.isoformat(), "expires_at": (now + dt.timedelta(hours=12)).isoformat(),
                        "extensions": {"classification": "synthetic", "billing_type": "invented test listing"}}],
                    "catalog_records": [], "coverage": {"complete": False}, "execution_enabled": False}, versions={"test": "independent/1"})

        capture("configured", "5.19")
        latest = capture("configured", "5.61")
        capture("outside", "991")
        with TestClient(app) as client, patch.object(app.state.store, "latest_collection_scan", side_effect=AssertionError("No full history scan")), \
                patch.object(app.state.store, "requested_collection_scan", wraps=app.state.store.requested_collection_scan) as requested:
            refs = client.get("/v1/pricing/demo/references?hardware_model=H100", headers=self.auth)
            self.assertEqual(refs.status_code, 200, refs.text)
            self.assertEqual([row["amount"] for row in refs.json()["references"]], ["5.61"])
            self.assertEqual(refs.json()["references"][0]["snapshot_id"], latest.digest)
            coverage = refs.json()["source_index_coverage"]
            self.assertEqual(coverage["population"], "explicit_configured_display_scopes")
            self.assertEqual(coverage["observation_row_limit"], 10000)
            self.assertFalse(coverage["full_history_integrity_scan"])
            self.assertFalse(coverage["all_market_sources"])
            evaluated = client.post("/v1/pricing/demo/evaluate", json=demo_contract()["scenarios"][0]["inputs"], headers=self.auth)
            self.assertEqual(evaluated.status_code, 200, evaluated.text)
            self.assertEqual(evaluated.json()["result"]["live_references"]["references"][0]["amount"], "5.61")
            self.assertTrue(all(call.args == (plan,) for call in requested.call_args_list))
            self.assertEqual(requested.call_count, 2)
        self.collect.assert_not_called()

    def test_empty_configured_population_stays_offline_and_row_limit_default_is_unchanged(self):
        with patch.object(self.app.state.store, "latest_collection_scan", side_effect=AssertionError("No history for empty configured plan")):
            refs = self.client.get("/v1/pricing/demo/references?hardware_model=H100", headers=self.auth)
            self.assertEqual(refs.status_code, 200)
            self.assertEqual(refs.json()["references"], [])
            self.assertEqual(refs.json()["source_index_coverage"]["requested_scope_count"], 0)
            self.post_case(demo_contract()["scenarios"][1]["inputs"])
            default = configured_market(self.app.state.store, {}, [])
            larger = configured_market(self.app.state.store, {}, [], row_limit=10000)
            self.assertEqual(default["coverage"]["observation_row_limit"], 1000)
            self.assertEqual(larger["coverage"]["observation_row_limit"], 10000)
            for limit in (0, -1, 10001, True, "1000", 1.5):
                with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "invalid_index_row_limit"):
                    configured_market(self.app.state.store, {}, [], row_limit=limit)
        self.collect.assert_not_called()


class DemoReferenceDisplayTests(unittest.TestCase):
    def test_catalog_native_instance_price_is_context_only_and_keeps_currency_and_gpu_count(self):
        packet = {"observations": [], "catalog_records": [
            {"source_id": "invented-catalog-feed", "provider": "Example Meter Catalog", "kind": "gpu_vm_reference",
             "gpu_name": "nvidia-h100", "native_price": {"amount": "24.83", "unit": "instance_hour", "currency": "EUR"},
             "gpu_count": 6, "billing_mode": "declared reserved commitment", "provider_location": "Example East",
             "catalog_observed_at": "2046-03-20T12:00:00Z", "index_stale": False, "snapshot_id": "c" * 64},
            {"source_id": "invented-catalog-feed", "kind": "gpu_vm_reference", "gpu_name": "H100 SXM",
             "native_price": {"amount": "9.1", "unit": "instance_hour", "currency": "USD"}, "index_stale": False}],
            "coverage": {"market_complete": False}, "as_of": "2046-03-20T12:00:00Z"}
        result = demo_references(packet, "H100")
        self.assertEqual(result["matched_rows"], 1)
        row = result["references"][0]
        self.assertEqual((row["amount"], row["currency"], row["unit"]), ("24.83", "EUR", "instance_hour"))
        self.assertIn("6 published GPUs", row["terms"])
        self.assertFalse(row["stale"])
        self.assertFalse(row["comparable_to_scenario_verified"])
        self.assertFalse(row["firm_price_eligible"])
        self.assertIsNone(result["midpoint"])
        self.assertIsNone(result["bid"])

    def test_explicit_model_aliases_preserve_configuration_native_units_staleness_and_no_quotes(self):
        def row(model, unit, currency, *, stale=False, kind="listing_ask"):
            return {"source_id": "invented-display-source", "hardware": {"model": model},
                "price": {"amount": "7.31", "unit": unit, "currency": currency}, "kind": kind,
                "index_stale": stale, "observed_at": "2046-03-19T12:00:00Z", "snapshot_id": "b" * 64,
                "extensions": {"billing_type": "declared commitment", "reservation_months": 7}}
        packet = {"observations": [row("nvidia-h100", "gpu_hour", "USD"), row("H100", "node_hour", "EUR", stale=True),
            row("H100 SXM", "gpu_hour", "USD"), row("H100 80GB", "gpu_hour", "USD"),
            row("L40S", "gpu_hour", "USD"), row("H100", "gpu_hour", "USD", kind="model_token_price")],
            "coverage": {"market_complete": False}, "as_of": "2046-03-19T12:00:00Z"}
        before = deepcopy(packet)
        result = demo_references(packet, "H100")
        self.assertEqual(result["matched_rows"], 2)
        self.assertEqual([(r["unit"], r["currency"]) for r in result["references"]], [("gpu_hour", "USD"), ("node_hour", "EUR")])
        self.assertFalse(result["references"][0]["stale"])
        self.assertTrue(result["references"][1]["stale"])
        self.assertEqual(result["references"][1]["status"], "stale reference")
        self.assertTrue(all(not r["comparable_to_scenario_verified"] for r in result["references"]))
        self.assertIsNone(result["midpoint"])
        self.assertIsNone(result["bid"])
        self.assertFalse(result["firm_price_eligible"])
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(demo_references(packet, "nvidia-h100")["matched_rows"], 2)
        self.assertEqual(demo_references(packet, "H100 SXM")["matched_rows"], 1)
        self.assertEqual(packet, before)


if __name__ == "__main__":
    unittest.main()
