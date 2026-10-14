"""Invented deal controls exercise calendar, accounting and held-price behavior."""
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from starlette.requests import Request

from compute_pricing.control.api import create_app
from compute_pricing.control.api.demo import (
    build_demo_pricing_request, demo_contract, demo_supplier_cash_schedule,
)
from compute_pricing.control.api.provenance import PricingProvenance
from compute_pricing.control.api.sessions import request_scope
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.pricing import evaluate_pricing


def invented_inputs():
    return {
        "gpu_count": "2", "delivery_start": "2056-02-28T00:00:00Z",
        "delivery_end": "2056-03-01T00:00:00Z", "billed_utilization": "0.5",
        "supplier_rate": "1.5", "buyer_rate": "7", "reference_rate": "4.3",
        "collection_share": "0.8", "fee_on_collected": "0.02", "fee_on_gross": "0.01",
        "fixed_operating_cost": "15", "opening_cash": "120", "minimum_cash": "5",
        "required_margin": "0.1", "tick_size": "0.01",
        "payment_dates": {
            "supplier_payment_on": "2056-02-28", "buyer_invoice_on": "2056-03-01",
            "buyer_receipt_on": "2056-03-02", "operating_cost_on": "2056-02-28",
            "fees_on": "2056-03-02", "writeoff_on": "2056-03-02",
        },
    }


def evaluate(inputs):
    request = build_demo_pricing_request(inputs)
    return request, PricingProvenance(None, None, None).apply(request, evaluate_pricing(request))


class DemoScenarioTests(unittest.TestCase):
    def test_contract_is_empty_until_deliberate_sample_and_returns_fresh_objects(self):
        contract = demo_contract()
        for name, value in contract["template_unknown"].items():
            if name == "payment_dates":
                self.assertTrue(all(item is None for item in value.values()))
            else:
                self.assertIsNone(value)
        self.assertTrue(all(field["default"] is None for field in contract["fields"]))
        self.assertEqual(contract["sample"]["classification"], "synthetic")
        self.assertFalse(contract["source_evidence_eligible"])
        contract["sample"]["inputs"]["opening_cash"] = "0"
        self.assertEqual(demo_contract()["sample"]["inputs"]["opening_cash"], "500")
        with self.assertRaises(ValidationError):
            build_demo_pricing_request(contract["template_unknown"])

    def test_leap_calendar_and_full_gross_service_settlement_independent_oracle(self):
        request, result = evaluate(invented_inputs())
        self.assertEqual(request["target"]["duration_hours"], "48")
        economics = result["economics"]
        self.assertEqual(economics["supply_gpu_hours"], "96")
        self.assertEqual(economics["gross_billed_gpu_hours"], "48")
        self.assertEqual(economics["gross_billings"], "336")
        self.assertEqual(economics["expected_collections"], "268.8")
        self.assertEqual(economics["fees"], "8.736")
        self.assertEqual(economics["expected_contribution"], "101.064")
        self.assertEqual(result["caps"]["economic_margin"], "2.20275")
        ledger = demo_supplier_cash_schedule(request)
        final = ledger["days"][-1]
        self.assertEqual(Decimal(final["cash"]), Decimal("221.064"))
        self.assertEqual(Decimal(final["earned_revenue"]), Decimal("336"))
        self.assertEqual(Decimal(final["recognized_expense"]), Decimal("234.936"))
        self.assertEqual(Decimal(final["noncash_receivable_losses"]), Decimal("67.2"))
        self.assertTrue(all(not balances for balances in ledger["unresolved_balances"].values()))

    def test_no_market_claim_or_submitted_bid_even_with_positive_math(self):
        request, result = evaluate(invented_inputs())
        row = request["market"]["observations"][0]
        self.assertEqual(row["rights"]["benchmark"], "FAIL")
        self.assertEqual(row["extensions"]["classification"], "synthetic")
        self.assertFalse(row["extensions"]["admitted_api"])
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["bid"])
        self.assertIsNone(result["benchmark"]["price"])
        self.assertNotIn("market", result["caps"])
        self.assertFalse(result["pricing_provenance"]["source_evidence_eligible"])
        self.assertFalse(result["executable"])
        self.assertFalse(result["firm_price_eligible"])
        changed = invented_inputs(); changed["reference_rate"] = "900"
        _, other = evaluate(changed)
        self.assertEqual(result["caps"], other["caps"])
        self.assertEqual(result["economics"]["expected_contribution"], other["economics"]["expected_contribution"])

    def test_binding_cash_tick_actual_rate_shortage_and_no_false_unbounded_limit(self):
        request, result = evaluate(invented_inputs())
        cash = result["cash_constraint"]
        self.assertEqual(cash["maximum_purchase_tick"], "0.95")
        self.assertFalse(cash["supplied_ask_cash_feasible"])
        self.assertEqual(cash["supplied_ask_required_extra_cash"], "52.736")
        actual = demo_supplier_cash_schedule(request)
        self.assertEqual(actual["required_extra_cash_for_floor"], "52.736")
        self.assertFalse(actual["cash_floor_feasible"])
        self.assertNotEqual(actual["minimum_free_cash"], cash["selected_schedule"]["minimum_free_cash"])
        next_tick = invented_inputs(); next_tick["supplier_rate"] = "0.96"
        self.assertFalse(demo_supplier_cash_schedule(build_demo_pricing_request(next_tick))["cash_floor_feasible"])
        rich = invented_inputs(); rich["opening_cash"] = "1000"
        _, funded = evaluate(rich)
        self.assertTrue(funded["cash_constraint"]["limit_censored_by_search_ceiling"])
        self.assertIsNone(funded["cash_constraint"]["maximum_purchase_tick"])
        self.assertNotIn("daily_liquidity", funded["caps"])

    def test_same_day_incoming_cash_does_not_hide_prior_outgoing_gap(self):
        inputs = invented_inputs()
        inputs["payment_dates"]["buyer_invoice_on"] = "2056-02-28"
        inputs["payment_dates"]["buyer_receipt_on"] = "2056-02-28"
        inputs["payment_dates"]["fees_on"] = "2056-02-28"
        inputs["payment_dates"]["writeoff_on"] = "2056-03-01"
        actual = demo_supplier_cash_schedule(build_demo_pricing_request(inputs))
        first = actual["days"][0]
        self.assertEqual(Decimal(first["cash"]), Decimal("221.064"))
        self.assertEqual(Decimal(first["minimum_ordered_free_cash"]), Decimal("-47.736"))
        self.assertEqual(actual["required_extra_cash_for_floor"], "52.736")

    def test_user_knobs_drive_coefficients_billings_cost_and_margin(self):
        _, baseline = evaluate(invented_inputs())
        doubled = invented_inputs(); doubled["gpu_count"] = "4"
        request, result = evaluate(doubled)
        self.assertEqual(result["economics"]["purchase_cost_coefficient"], "192")
        self.assertEqual(result["economics"]["gross_billings"], "672")
        self.assertTrue(all(value == "192" for value in request["cash_template"]["purchase_coefficients"].values()))
        lower = invented_inputs(); lower["billed_utilization"] = "0.25"
        _, reduced = evaluate(lower)
        self.assertEqual(reduced["economics"]["supply_gpu_hours"], "96")
        self.assertEqual(reduced["economics"]["gross_billings"], "168")
        self.assertLess(Decimal(reduced["caps"]["economic_margin"]), Decimal(baseline["caps"]["economic_margin"]))
        expensive = invented_inputs(); expensive["fixed_operating_cost"] = "30"
        _, result = evaluate(expensive)
        self.assertEqual(Decimal(result["economics"]["expected_contribution"]), Decimal("86.064"))
        demanding = invented_inputs(); demanding["required_margin"] = "0.2"
        _, result = evaluate(demanding)
        self.assertLess(Decimal(result["caps"]["economic_margin"]), Decimal(baseline["caps"]["economic_margin"]))
        self.assertGreater(Decimal(result["ask"]["required_margin"]), Decimal(baseline["ask"]["required_margin"]))

    def test_zero_and_full_collection_settle_and_actual_cash_exists_when_cap_search_is_held(self):
        for q in ("0", "1"):
            inputs = invented_inputs(); inputs["collection_share"] = q
            request, result = evaluate(inputs)
            actual = demo_supplier_cash_schedule(request)
            self.assertTrue(all(not values for values in actual["unresolved_balances"].values()))
            if q == "0":
                self.assertNotIn("cash_constraint", result)
                self.assertTrue(actual["days"])
                self.assertEqual(Decimal(actual["days"][-1]["noncash_receivable_losses"]), Decimal("336"))
            else:
                self.assertFalse(any(e["kind"] == "receivable_writeoff" for e in request["cash_template"]["schedule"]["events"]))

    def test_invalid_exact_inputs_dates_and_unregistered_fields_fail_explicitly(self):
        for name, value in (("gpu_count", "2.5"), ("buyer_rate", 7), ("collection_share", "1.01"),
                            ("supplier_rate", "NaN"), ("buyer_rate", "7e0"), ("billed_utilization", "0"),
                            ("tick_size", "0.0000000000001"), ("opening_cash", None),
                            ("delivery_start", "2056-02-28T00:00:00+00:00")):
            inputs = invented_inputs(); inputs[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ValidationError):
                build_demo_pricing_request(inputs)
        for mutation in (
            lambda p: p.update(unknown_price_premium="2"),
            lambda p: p.pop("collection_share"),
            lambda p: p["payment_dates"].pop("fees_on"),
            lambda p: p["payment_dates"].update(buyer_receipt_on="2056-02-27"),
            lambda p: p["payment_dates"].update(buyer_invoice_on="2056-03-03"),
            lambda p: p["payment_dates"].update(writeoff_on="2056-02-28"),
            lambda p: p["payment_dates"].update(fees_on="2056-02-30"),
            lambda p: p.update(delivery_end=p["delivery_start"]),
            lambda p: p.update(delivery_end="2056-02-28T00:00:01Z"),
        ):
            inputs = invented_inputs(); mutation(inputs)
            with self.assertRaises(ValidationError): build_demo_pricing_request(inputs)

    def test_input_ownership_and_precision_do_not_depend_on_caller_state(self):
        inputs = invented_inputs(); original = deepcopy(inputs)
        expected = build_demo_pricing_request(inputs)
        actual = demo_supplier_cash_schedule(expected)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(build_demo_pricing_request(inputs), expected)
            self.assertEqual(demo_supplier_cash_schedule(expected), actual)
        self.assertEqual(inputs, original)
        inputs["payment_dates"]["fees_on"] = "2056-03-05"
        self.assertEqual(expected["demo_scenario"]["inputs"], original)

    def test_deliberate_contract_sample_is_held_and_cash_is_not_a_record_of_actual_balances(self):
        request, result = evaluate(demo_contract()["sample"]["inputs"])
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["bid"])
        actual = demo_supplier_cash_schedule(request)
        self.assertEqual(actual["classification"], "synthetic")
        self.assertFalse(actual["source_evidence_eligible"])
        self.assertFalse(actual["execution_enabled"])


class DemoScenarioAPITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.key = "invented-demo-api-client-key-000002"
        self.auth = {"Authorization": "Bearer " + self.key}
        self.app = create_app(api_key=self.key, store_path=Path(self.folder.name) / "scenarios.sqlite")
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def post_scenario(self, inputs):
        response = self.client.post("/v1/demo/scenario", json=inputs, headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_authenticated_contract_is_unknown_until_explicit_sample(self):
        self.assertEqual(self.client.get("/v1/demo/contract").status_code, 401)
        self.assertEqual(self.client.get("/v1/demo/contract", headers={"Authorization": "Bearer invented-wrong-key"}).status_code, 401)
        response = self.client.get("/v1/demo/contract", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), demo_contract())
        self.assertIsNone(response.json()["template_unknown"]["supplier_rate"])
        self.assertEqual(response.json()["sample"]["classification"], "synthetic")
        unauthorized = self.client.post("/v1/demo/scenario", content=b'{"bad":NaN}',
                                        headers={"Content-Type": "application/json"})
        self.assertEqual(unauthorized.status_code, 401)

    def test_full_held_provenance_and_exact_immutable_replay(self):
        inputs = invented_inputs()
        receipt = self.post_scenario(inputs)
        output = receipt["result"]
        self.assertEqual(output["status"], "held")
        self.assertIsNone(output["bid"])
        self.assertIsNone(output["benchmark"]["price"])
        self.assertFalse(output["pricing_provenance"]["source_evidence_eligible"])
        self.assertIn("api_declared_scenario_not_admitted_source_evidence", output["pricing_provenance"]["blockers"])
        self.assertFalse(output["executable"])
        self.assertFalse(output["firm_price_eligible"])
        self.assertFalse(receipt["execution_enabled"])
        self.assertEqual(output["demo_scenario"]["inputs"], inputs)
        self.assertEqual(output["scenario_supplier_cash_schedule"]["required_extra_cash_for_floor"], "52.736")
        replay_url = "/v1/decisions/" + receipt["snapshot_id"]
        first_replay = self.client.get(replay_url, headers=self.auth)
        self.assertEqual(first_replay.status_code, 200)
        document = first_replay.json()["document"]
        self.assertEqual(document["kind"], "pricing")
        self.assertEqual(document["output"], output)
        self.assertEqual(document["input"], build_demo_pricing_request(inputs))
        repeated = self.post_scenario(deepcopy(inputs))
        self.assertEqual(repeated["snapshot_id"], receipt["snapshot_id"])
        inputs["opening_cash"] = "350"
        altered = self.post_scenario(inputs)
        self.assertNotEqual(altered["snapshot_id"], receipt["snapshot_id"])
        self.assertEqual(self.client.get(replay_url, headers=self.auth).json(), first_replay.json())

    def test_sample_cash_control_changes_funding_without_changing_economic_margin(self):
        inputs = self.client.get("/v1/demo/contract", headers=self.auth).json()["sample"]["inputs"]
        self.assertEqual(inputs["opening_cash"], "500")
        baseline = self.post_scenario(inputs)["result"]
        inputs["opening_cash"] = "650"
        funded = self.post_scenario(inputs)["result"]
        self.assertEqual(baseline["economics"]["economic_margin"], funded["economics"]["economic_margin"])
        self.assertEqual(baseline["caps"]["economic_margin"], funded["caps"]["economic_margin"])
        self.assertEqual(baseline["economics"]["expected_contribution"], funded["economics"]["expected_contribution"])
        self.assertEqual(baseline["scenario_supplier_cash_schedule"]["required_extra_cash_for_floor"], "97.905496")
        self.assertEqual(funded["scenario_supplier_cash_schedule"]["required_extra_cash_for_floor"], "0")
        self.assertFalse(baseline["scenario_supplier_cash_schedule"]["cash_floor_feasible"])
        self.assertTrue(funded["scenario_supplier_cash_schedule"]["cash_floor_feasible"])
        self.assertEqual(funded["cash_constraint"]["supplied_ask_required_extra_cash"], "0")
        for output in (baseline, funded):
            self.assertEqual(output["status"], "held")
            self.assertIsNone(output["bid"])

    def test_unknown_null_blank_and_missing_scenario_inputs_are_422(self):
        cases = [{}, demo_contract()["template_unknown"]]
        for mutation in (
            lambda p: p.update(supplier_rate=""),
            lambda p: p.update(opening_cash=None),
            lambda p: p.update(undocumented_fee="0.1"),
            lambda p: p["payment_dates"].update(supplier_payment_on=""),
            lambda p: p["payment_dates"].pop("fees_on"),
        ):
            inputs = invented_inputs(); mutation(inputs); cases.append(inputs)
        for inputs in cases:
            with self.subTest(inputs=inputs):
                response = self.client.post("/v1/demo/scenario", json=inputs, headers=self.auth)
                self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post("/v1/demo/scenario", content="null",
                                    headers={**self.auth, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422, response.text)

    def test_browser_scenario_uses_evaluate_scope_and_current_csrf(self):
        site = "http://127.0.0.1:8876"
        fetch = {"Origin": site, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
        browser_app = create_app(workbench_origin=site, store_path=Path(self.folder.name) / "browser.sqlite")
        with TestClient(browser_app, base_url=site) as browser:
            self.assertEqual(browser.get("/v1/demo/contract", headers=fetch).status_code, 401)
            boot = browser.post("/v1/session/bootstrap", json={}, headers=fetch)
            self.assertEqual(boot.status_code, 200, boot.text)
            csrf = boot.json()["csrf_token"]
            self.assertIn("evaluate", boot.json()["scopes"])
            self.assertEqual(request_scope(Request({"type": "http", "path": "/v1/demo/scenario", "method": "POST", "headers": []})), "evaluate")
            self.assertEqual(browser.get("/v1/demo/contract", headers=fetch).status_code, 200)
            for headers in (fetch, {**fetch, "X-Compute-CSRF": "0" * 64},
                            {**fetch, "X-Compute-CSRF": csrf, "Origin": "http://127.0.0.1:8877"}):
                self.assertEqual(browser.post("/v1/demo/scenario", json=invented_inputs(), headers=headers).status_code, 403)
            response = browser.post("/v1/demo/scenario", json=invented_inputs(), headers={**fetch, "X-Compute-CSRF": csrf})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIsNone(response.json()["result"]["bid"])
            snapshot = response.json()["snapshot_id"]
            replay = browser.get("/v1/decisions/" + snapshot, headers=fetch)
            self.assertEqual(replay.json()["document"]["output"], response.json()["result"])


if __name__ == "__main__":
    unittest.main()
