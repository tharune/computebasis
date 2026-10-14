"""Whole nodes, calendar hours and prepaid cash reconcile independently."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from compute_pricing.control.api import create_app
from compute_pricing.control.api.book_deal import (
    book_deal_contract, book_deal_sample_inputs, build_book_deal,
)
from compute_pricing.control.api.demo import demo_supplier_cash_schedule
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.pricing import evaluate_pricing
from compute_pricing.control.quote_book import QuoteBook


def inputs():
    return {"book_revision": 'W/"independent-test-frame"', "quote_id": "invented-deal-lot",
        "nodes": 2, "supplier_invoice_basis": "single_full_contract_invoice", "buyer_rate": "4",
        "billed_utilization": "0.5", "collection_share": "0.9", "fee_on_collected": "0",
        "fee_on_gross": "0", "fixed_operating_cost": "0", "opening_cash": "20000",
        "minimum_cash": "0", "required_margin": "0.1", "tick_size": "0.01",
        "payment_dates": {"deposit_on": "2028-02-11", "supplier_invoice_on": "2028-02-29",
            "buyer_invoice_on": "2028-03-29", "buyer_receipt_on": "2028-03-31",
            "operating_cost_on": "2028-02-29", "fees_on": "2028-03-31", "writeoff_on": "2028-03-31"}}


def frame():
    return {"meta": {"as_of": "2028-02-10"}, "quotes": [{"id": "invented-deal-lot",
        "provider_id": "invented-deal-supplier", "eligible": True, "synthetic": True,
        "price": "2.6", "currency": "USD", "price_unit": "gpu_hour", "gpus_per_node": 4,
        "nodes": 4, "moq": 2, "available": "2028-02-29", "months": 1, "down_payment": "0.2",
        "payment_days": 10, "gpu": "H100", "country": "US", "location": "Imaginary Facility",
        "interconnect": "Declared fixture fabric", "cooling": "Declared fixture air",
        "lead_weeks": 2, "expires": "2028-02-20"}],
        "models": [{"gpu": "H100", "reference": "3.1"}]}


def build(payload=None, book=None):
    return build_book_deal(payload or inputs(), book or frame(), inputs()["book_revision"])


class BookDealTests(unittest.TestCase):
    def test_contract_has_no_auto_economic_or_payment_defaults(self):
        contract = book_deal_contract()
        self.assertTrue(all(value is None for key, value in contract["template"].items() if key != "payment_dates"))
        self.assertTrue(all(value is None for value in contract["template"]["payment_dates"].values()))
        self.assertFalse(contract["source_evidence_eligible"])

    def test_exact_leap_day_whole_nodes_full_term_and_owned_costs(self):
        payload, book = inputs(), frame()
        before = deepcopy((payload, book))
        request = build(payload, book)
        result = evaluate_pricing(request)
        self.assertEqual((payload, book), before)
        self.assertEqual(request["target"]["gpu_count"], "8")
        self.assertEqual(request["target"]["duration_hours"], "696")
        self.assertEqual(request["commercial"]["exclusive_node_gpu_count"], "4")
        self.assertEqual(result["economics"]["supply_gpu_hours"], "5568")
        self.assertEqual(result["economics"]["gross_billings"], "11136")
        self.assertEqual(result["economics"]["expected_collections"], "10022.4")
        self.assertEqual(result["economics"]["expected_contribution"], "-4454.4")
        self.assertEqual(request["demo_scenario"]["book_binding"]["supplier_balance_due_on"], "2028-03-10")

    def test_deposit_is_cash_once_and_application_is_not_a_second_expense(self):
        request = build()
        result = demo_supplier_cash_schedule(request)
        by_date = {row["on"]: row for row in result["days"]}
        self.assertEqual(Decimal(by_date["2028-02-11"]["cash"]), Decimal("17104.64"))
        self.assertEqual(Decimal(by_date["2028-03-10"]["cash"]), Decimal("5523.2"))
        last = result["days"][-1]
        self.assertEqual(Decimal(last["cash"]), Decimal("15545.6"))
        self.assertEqual(Decimal(last["recognized_expense"]), Decimal("14476.8") + Decimal("1113.6"))
        self.assertEqual(Decimal(last["earned_revenue"]) - Decimal(last["recognized_expense"]), Decimal("-4454.4"))
        self.assertEqual(Decimal(last["noncash_receivable_losses"]), Decimal("1113.6"))
        self.assertTrue(all(not value for value in result["unresolved_balances"].values()))

    def test_zero_full_and_fractional_deposit_conserve_total_supplier_cash(self):
        for fraction in ("0", "0.2", "1"):
            book = frame(); book["quotes"][0]["down_payment"] = fraction
            request = build(book=book)
            coefficients = request["cash_template"]["purchase_coefficients"]
            cash_coefficient = sum((Decimal(coefficients.get(row["event_id"], "0"))
                for row in request["cash_template"]["schedule"]["events"]
                if row["kind"] in {"supplier_payment", "supplier_prepayment"}), Decimal(0))
            self.assertEqual(cash_coefficient, Decimal("5568"))
            self.assertTrue(all(not value for value in demo_supplier_cash_schedule(request)["unresolved_balances"].values()))

    def test_capacity_unknowns_stale_revision_and_override_attempts_rejected(self):
        for changes in ({"nodes": 1}, {"nodes": 5}, {"nodes": "2"}, {"nodes": True},
                {"book_revision": "other"}, {"supplier_ask": "0"}, {"supplier_invoice_basis": "monthly"}):
            payload = inputs(); payload.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                build(payload)
        for key, value in (("eligible", False), ("synthetic", False), ("currency", "EUR")):
            book = frame(); book["quotes"][0][key] = value
            with self.assertRaises(ValidationError):
                build(book=book)
        for key, value in (("deposit_on", "2028-03-01"), ("supplier_invoice_on", "2028-02-28"),
                ("buyer_invoice_on", "2028-02-09")):
            payload = inputs(); payload["payment_dates"][key] = value
            with self.assertRaises(ValidationError):
                build(payload)

    def test_scenario_reference_never_creates_a_market_bid_or_inventory(self):
        request = build()
        result = evaluate_pricing(request)
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["bid"])
        self.assertFalse(result["firm_price_eligible"])
        self.assertFalse(result["executable"])


class BookDealAPITests(unittest.TestCase):
    def test_local_browser_handoff_requires_csrf_and_accepts_explicit_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            origin = "http://127.0.0.1:8893"
            fetch = {"Origin": origin, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
            app = create_app(workbench_origin=origin, store_path=Path(directory) / "browser.sqlite")
            app.state.quote_book = QuoteBook(clock=lambda: 0)
            with TestClient(app, base_url=origin) as client:
                bootstrap = client.post("/v1/session/bootstrap", headers=fetch, json={})
                self.assertEqual(bootstrap.status_code, 200)
                book = client.get("/v1/book", headers=fetch)
                payload = book_deal_sample_inputs(book.json(), book.headers["etag"])
                self.assertEqual(client.post("/v1/book/deal/evaluate", headers=fetch, json=payload).status_code, 403)
                csrf = {**fetch, "X-Compute-CSRF": bootstrap.json()["csrf_token"]}
                result = client.post("/v1/book/deal/evaluate", headers=csrf, json=payload)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertFalse(result.json()["execution_enabled"])

    def test_auth_revisions_persisted_receipt_and_no_vendor_or_inventory_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            key = "invented-book-deal-client-000007"
            auth = {"Authorization": "Bearer " + key}
            app = create_app(api_key=key, store_path=Path(directory) / "paper.sqlite")
            app.state.quote_book = QuoteBook(clock=lambda: 0)
            with TestClient(app) as client, patch("compute_pricing.control.api.app.collect_source") as collect:
                self.assertEqual(client.get("/v1/book/deal/contract").status_code, 401)
                self.assertEqual(client.post("/v1/book/deal/evaluate", json={}).status_code, 401)
                book = client.get("/v1/book", headers=auth)
                payload = book_deal_sample_inputs(book.json(), book.headers["etag"])
                response = client.post("/v1/book/deal/evaluate", headers=auth, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                packet = response.json(); result = packet["result"]
                self.assertEqual(result["book_binding"]["quote_id"], payload["quote_id"])
                self.assertEqual(result["status"], "held")
                self.assertFalse(result["firm_price_eligible"])
                self.assertIsNone(result["bid"])
                self.assertEqual(client.get("/v1/inventory", headers=auth).json()["state"]["lots"], [])
                client.post("/v1/book/control", json={"action": "scenario", "scenario": "price_war"}, headers=auth)
                self.assertEqual(client.post("/v1/book/deal/evaluate", headers=auth, json=payload).status_code, 409)
                saved = client.get("/v1/decisions/" + packet["snapshot_id"], headers=auth).json()
                self.assertEqual(saved["document"]["output"], result)
                collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
