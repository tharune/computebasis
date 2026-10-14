"""Invented contract checks for cap attribution and retained-evidence pricing."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.connectors import SourcePolicy
from compute_pricing.control.pricing import evaluate_pricing
from compute_pricing.control.reporting import SnapshotStoreError
from compute_pricing.control.risk import CashScenario, Exposure, LossComponent, evaluate_portfolio_tail_risk
from compute_pricing.control.treasury import CashEvent

AUTH = {"Authorization": "Bearer " + "invented-public-memo-key-2468013579-abc"}


def example_request():
    t = datetime.now(timezone.utc).replace(microsecond=0)
    z = lambda value: value.isoformat().replace("+00:00", "Z")
    start = t + timedelta(days=4)
    listing = {"id": "listing:demo", "source_id": "democatalog", "source_version": "example-schema/3",
        "offer_id": "offer:demo", "lot_id": "lot:demo", "provider_group_id": "group:demo", "kind": "listing_ask", "price_side": "ask", "status": "claimed",
        "price": {"amount": "8", "currency": "USD", "unit": "gpu_hour"},
        "hardware": {"model": "example-device", "accelerator_count": "1"}, "region": {"country_code": "CA"},
        "quantity": "1", "quantity_unit": "gpu", "starts_at": z(start), "ends_at": z(start + timedelta(hours=3)),
        "observed_at": z(t - timedelta(seconds=2)), "ingested_at": z(t), "expires_at": z(t + timedelta(hours=8)),
        "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL", "verified_by": "review:demo"}}
    rules = {"democatalog": {"enabled": True, "quality": "1", "max_age_hours": "2", "half_life_hours": "2"}}
    p = {"policy_id": "policy:demo", "version": "1.0.0", "model_version": "inverse-linear/1.0.0", "registry_version": "1.0.0", "effective_at": z(t - timedelta(days=3)),
        "parameters": {"benchmark": {"estimator": "weighted_mean", "max_source_share": "1", "max_provider_share": "1", "min_observations": 1, "min_sources": 1, "min_provider_groups": 1, "source_rules": rules}}}
    entries = []
    for identity, kind, amount, on, invoice in (
        ("capacity-bill", "supplier_invoice", "0", t.date(), "invoice:capacity"),
        ("capacity-paid", "supplier_payment", "0", t.date(), "invoice:capacity"),
        ("hosting-paid", "other_outflow", "3", t.date(), None),
        ("service-bill", "buyer_invoice", "36", start.date(), "invoice:service"),
        ("service-earned", "revenue", "36", start.date(), "invoice:service"),
        ("service-paid", "buyer_receipt", "36", start.date(), "invoice:service")):
        record = {"event_id": identity, "obligation_id": "obligation:" + identity, "kind": kind, "amount": amount, "currency": "USD", "on": str(on)}
        if invoice is not None:
            record["invoice_id"] = invoice
        entries.append(record)
    return {"market": {"request_id": "request:demo", "as_of": z(t), "observations": [listing], "policy": p},
        "target": {"scope": "physical_offer", "hardware_model": "example-device", "country_code": "CA", "currency": "USD", "gpu_count": "1", "duration_hours": "3", "starts_at": listing["starts_at"], "ends_at": listing["ends_at"], "configuration": {}},
        "commercial": {"currency": "USD", "exclusive_node_gpu_count": "1", "buyer_billed_gpu_hours": "3", "buyer_rate": "12", "supplier_ask": "2", "collection_share": "1", "fee_on_collected": "0", "fee_on_gross": "0", "required_margin": "0.3", "margin_basis": "gross_billings", "market_discount": "0", "tick_size": "0.01", "cost_owners": {"hosting": "hosting-model"}, "costs": [{"id": "hosting", "channel": "hosting", "owner_model": "hosting-model", "kind": "expected_cost", "basis": "fixed_contract", "amount": "3"}]},
        "cash_template": {"minimum_cash": "0", "deal_event_ids": [e["event_id"] for e in entries], "purchase_coefficients": {"capacity-bill": "3", "capacity-paid": "3"}, "schedule": {"events": entries, "legal_entity_id": "entity:demo", "cash_account_id": "bank:demo", "currency": "USD", "opening_cash": "200", "start_date": str(t.date()), "end_date": str(start.date() + timedelta(days=2))}}}


class CapAttributionTests(unittest.TestCase):
    def test_other_cap_retains_fractional_value_when_cash_search_is_censored(self):
        req = example_request(); req["commercial"]["market_discount"] = "0.0751"
        result = evaluate_pricing(req)
        self.assertEqual(result["bid"]["reservation"], "7.3992")
        self.assertEqual(result["bid"]["submitted_limit"], "7.39")
        self.assertEqual(result["bid"]["binding_constraints"], ["market"])
        self.assertNotIn("daily_liquidity", result["caps"])
        self.assertTrue(result["cash_constraint"]["limit_censored_by_search_ceiling"])
        self.assertIsNone(result["cash_constraint"]["maximum_purchase_tick"])

    def test_cash_grid_limit_is_real_and_next_tick_fails(self):
        req = example_request(); req["cash_template"]["schedule"]["opening_cash"] = "9.04"
        result = evaluate_pricing(req)
        self.assertEqual(result["bid"]["reservation"], "2.01")
        self.assertEqual(result["bid"]["binding_constraints"], ["daily_liquidity"])
        req["commercial"]["supplier_ask"] = "2.02"
        self.assertFalse(evaluate_pricing(req)["cash_constraint"]["supplied_ask_cash_feasible"])

    def test_unusable_required_cap_or_cash_evidence_never_emits_bid(self):
        for change in (lambda r: r.pop("cash_template"), lambda r: r["commercial"].update(required_margin="1"),
                lambda r: r["market"]["policy"].update(critical_feature_ids=["credit:demo"]),
                lambda r: r["market"]["policy"]["parameters"]["benchmark"]["source_rules"]["democatalog"].update(enabled=False)):
            req = example_request(); change(req)
            result = evaluate_pricing(req)
            self.assertEqual(result["status"], "held")
            self.assertIsNone(result["bid"])
            self.assertIsNotNone(result["economics"])

    def test_optional_stress_and_subtick_are_separate_from_cash_search(self):
        req = example_request(); req["commercial"]["stress_price_cap"] = "3.731"
        result = evaluate_pricing(req)
        self.assertEqual(result["bid"]["reservation"], "3.731")
        self.assertEqual(result["bid"]["submitted_limit"], "3.73")
        self.assertEqual(result["bid"]["binding_constraints"], ["stress"])
        req["commercial"]["stress_price_cap"] = "0.0001"
        self.assertIsNone(evaluate_pricing(req)["bid"])


class RetainedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Path(self.folder.name) / "memos.sqlite"
        self.base = example_request()
        self.policy = SourcePolicy("democatalog", enabled=True, rights_status="allowed", rights_evidence="example-local-data-contract", verified_by="review:demo", max_age_s=7200,
            permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"})
        self.app = create_app(api_key=AUTH["Authorization"][7:], store_path=self.db, source_policies={"democatalog": self.policy})
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close(); self.folder.cleanup()

    def bound_request(self):
        req = deepcopy(self.base)
        saved = self.app.state.policy_repository.save({"policy": req["market"]["policy"], "feature_definitions": [], "notes": "Independently invented example"}, expected_revision=None)
        req["market"]["policy"] = saved["document"]["policy"]
        observation = req["market"]["observations"][0]
        snapshot = self.app.state.store.put(kind="market_collection", input_payload={"source_id": "democatalog", "filters": {}}, output_payload={"source_id": "democatalog", "observations": [deepcopy(observation)], "execution_enabled": False, "raw_metadata": {"captured_at": observation["ingested_at"]}}, versions={"adapter": "example/3"})
        observation["snapshot_id"] = snapshot.digest
        req["pricing_provenance"] = {"mode": "retained_market", "policy_revision": saved["revision"]}
        return req

    def memo(self, req):
        response = self.client.post("/v1/pricing/evaluate", json=req, headers=AUTH)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        replay = self.client.get("/v1/decisions/" + response.json()["snapshot_id"], headers=AUTH)
        self.assertEqual(replay.json()["document"]["output"], result)
        return result

    def assert_hold(self, result, reason):
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["bid"])
        self.assertIsNone(result["benchmark"]["price"])
        self.assertIn(reason, result["pricing_provenance"]["blockers"])

    def test_default_input_remains_visible_only_as_hypothetical_math(self):
        result = self.memo(deepcopy(self.base))
        self.assert_hold(result, "api_pricing_provenance_not_bound")
        self.assertEqual(result["scenario_diagnostics"]["benchmark"]["price"], "8")
        self.assertEqual(result["caps"]["economic_margin"], "7.4")
        self.assertNotIn("bid", result["scenario_diagnostics"])

    def test_binding_allows_only_display_fields_to_differ(self):
        req = self.bound_request()
        req["market"]["observations"][0].update(index_stale=False, execution_enabled=False)
        result = self.memo(req)
        self.assertEqual(result["status"], "indicative")
        self.assertEqual(result["bid"]["reservation"], "7.4")
        self.assertTrue(result["pricing_provenance"]["source_evidence_eligible"])
        self.assertFalse(result["firm_price_eligible"])

    def test_price_and_rights_counterfeits_do_not_match_retained_records(self):
        for change in (lambda o: o["price"].update(amount="10"), lambda o: o["rights"].update(execution="PASS")):
            req = self.bound_request(); change(req["market"]["observations"][0])
            self.assert_hold(self.memo(req), "observation_differs_from_retained_evidence")

    def test_reference_is_required_and_wrong_snapshot_is_not_source_evidence(self):
        req = self.bound_request(); req["market"]["observations"][0].pop("snapshot_id")
        self.assert_hold(self.memo(req), "observation_retained_snapshot_required")
        req = self.bound_request(); req["market"]["observations"][0]["snapshot_id"] = "f" * 64
        self.assert_hold(self.memo(req), "observation_retained_snapshot_mismatch")

    def test_current_permissions_win_over_inline_allow_and_empty_registry(self):
        req = self.bound_request()
        denied = SourcePolicy("democatalog", enabled=False, rights_status="allowed", rights_evidence="example-local-data-contract", verified_by="review:demo", max_age_s=7200, permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS"})
        for policies, reason in (({}, "external_source_not_admitted_by_server"), ({"democatalog": denied}, "server_source_permission_blocked")):
            with TestClient(create_app(api_key=AUTH["Authorization"][7:], store_path=self.db, source_policies=policies)) as client:
                response = client.post("/v1/pricing/evaluate", json=req, headers=AUTH)
                self.assertEqual(response.status_code, 200)
                self.assert_hold(response.json()["result"], reason)

    def test_another_valid_memo_kind_is_not_reported_as_broken_storage(self):
        req = self.bound_request()
        unrelated = self.app.state.store.put(kind="cash", input_payload={"mode": "invented"}, output_payload={"explanation": "example only"}, versions={"model": "example-ledger/2"})
        req["market"]["observations"][0]["snapshot_id"] = unrelated.digest
        self.assert_hold(self.memo(req), "observation_retained_snapshot_mismatch")

    def test_storage_failure_is_distinct_and_never_echoes_internal_error(self):
        req = self.bound_request()
        with patch.object(self.app.state.store, "get", side_effect=SnapshotStoreError("example-internal-store-text")):
            response = self.client.post("/v1/pricing/evaluate", json=req, headers=AUTH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "pricing_evidence_store_unavailable"})

    def test_old_saved_head_and_changed_inline_policy_are_held(self):
        req = self.bound_request(); altered = deepcopy(req)
        altered["market"]["policy"]["parameters"]["benchmark"]["source_rules"]["democatalog"]["quality"] = "0.8"
        self.assert_hold(self.memo(altered), "inline_policy_does_not_match_saved_revision")
        newer = {"policy": deepcopy(req["market"]["policy"]), "feature_definitions": [], "notes": "Example successor"}
        newer["policy"]["version"] = "1.0.1"
        self.app.state.policy_repository.save(newer, expected_revision=req["pricing_provenance"]["policy_revision"])
        self.assert_hold(self.memo(req), "saved_policy_revision_is_not_current_head")

    def test_explicit_alternative_cannot_change_bound_price(self):
        baseline = self.bound_request(); alternative = deepcopy(baseline)
        alternative["market"]["observations"][0]["price"]["amount"] = "14"
        response = self.client.post("/v1/pricing/scenarios", json={"baseline": baseline, "scenarios": [{"scenario_id": "counterfeit", "request": alternative}]}, headers=AUTH)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertEqual(result["status"], "held")
        self.assertIsNotNone(result["baseline"]["bid"])
        self.assertIsNone(result["scenarios"][0]["result"]["bid"])

    def test_present_rights_do_not_make_historical_observation_fresh(self):
        req = self.bound_request()
        short_policy = SourcePolicy("democatalog", enabled=True, rights_status="allowed", rights_evidence="example-local-data-contract", verified_by="review:demo", max_age_s=1, permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS"})
        with TestClient(create_app(api_key=AUTH["Authorization"][7:], store_path=self.db, source_policies={"democatalog": short_policy})) as client:
            response = client.post("/v1/pricing/evaluate", json=req, headers=AUTH)
            self.assertEqual(response.status_code, 200)
            self.assert_hold(response.json()["result"], "retained_observation_not_currently_fresh")


class LossAndFundingTests(unittest.TestCase):
    def test_unannotated_cash_outflow_is_not_silently_recast_as_loss(self):
        date = "2025-07-10"
        big = CashEvent("funding-out", "funding-leg", date, "other_outflow", "420", "USD")
        small = CashEvent("loss-out", "loss-leg", date, "other_outflow", "24", "USD")
        paths = [CashScenario("cash-only", (big,), (), "0.6"), CashScenario("loss-only", (small,), (LossComponent("declared", "declared-owner", "operating", "USD", "24", ("loss-out",)),), "0.4")]
        report = evaluate_portfolio_tail_risk(paths, [Exposure("example-position", "example-buyer", "example-group", "example-site", "USD", "70")], confidence="0.95", distribution_evidence_id="example-distribution", legal_entity_id="example-entity", cash_account_id="example-account", currency="USD", opening_cash="70", start_date=date, end_date="2025-07-11")
        self.assertEqual(report.expected_shortfall, Decimal("24"))
        self.assertEqual(report.cash_stress.worst_required_extra_cash, Decimal("350"))
        self.assertFalse(report.loss_attribution_completeness_verified)
        self.assertEqual(report.scenarios_without_declared_loss_components, ("cash-only",))
        self.assertEqual(dict(report.cash_events_without_loss_annotation)["cash-only"], ("funding-out",))
        self.assertIn("not_economic_loss_tail", report.cash_stress.metric_basis)


if __name__ == "__main__":
    unittest.main()
