"""Independent inverse-pricing and full cash-path checks with invented terms."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.pricing import evaluate_pricing


def pricing_packet():
    observation = {
        "id": "observation:invented", "source_id": "source:invented", "source_version": "feed/1",
        "kind": "listing_ask", "price_side": "ask", "offer_id": "offer:invented",
        "lot_id": "lot:invented", "provider_group_id": "group:invented", "status": "claimed",
        "price": {"amount": "2", "currency": "USD", "unit": "gpu_hour"},
        "hardware": {"model": "invented-gpu", "accelerator_count": "1"},
        "region": {"country_code": "US"}, "quantity": "1", "quantity_unit": "gpu",
        "starts_at": "2026-01-03T00:00:00Z", "ends_at": "2026-01-03T10:00:00Z",
        "observed_at": "2026-01-01T00:00:00Z", "ingested_at": "2026-01-01T00:00:01Z",
        "expires_at": "2026-01-01T02:00:00Z",
        "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL", "verified_by": "review:invented"},
    }
    benchmark_policy = {"estimator": "weighted_median", "max_source_share": "1", "max_provider_share": "1",
                        "min_observations": 1, "min_sources": 1, "min_provider_groups": 1,
                        "source_rules": {"source:invented": {"enabled": True, "quality": "1", "max_age_hours": "24", "half_life_hours": "24"}}}
    def event(identity, kind, amount, on="2026-01-01", **extra):
        return {"event_id": identity, "obligation_id": "leg:" + identity, "on": on,
                "kind": kind, "amount": amount, "currency": "USD", **extra}
    events = [event("supplier-invoice", "supplier_invoice", "0", invoice_id="invoice:supply"),
              event("supplier-pay", "supplier_payment", "0", invoice_id="invoice:supply"),
              event("cost-pay", "other_outflow", "2.672"),
              event("buyer-invoice", "buyer_invoice", "21.6", "2026-01-04", invoice_id="invoice:buyer"),
              event("buyer-pay", "buyer_receipt", "21.6", "2026-01-04", invoice_id="invoice:buyer")]
    return {"market": {"request_id": "request:invented", "as_of": "2026-01-01T01:00:00Z", "observations": [observation],
                       "policy": {"policy_id": "policy:invented", "version": "1.0.0", "model_version": "inverse-linear/1.0.0", "registry_version": "1.0.0", "effective_at": "2026-01-01T00:00:00Z", "parameters": {"benchmark": benchmark_policy}}},
            "target": {"scope": "physical_offer", "currency": "USD", "hardware_model": "invented-gpu", "country_code": "US", "gpu_count": "1", "duration_hours": "10", "starts_at": observation["starts_at"], "ends_at": observation["ends_at"], "configuration": {}},
            "commercial": {"currency": "USD", "exclusive_node_gpu_count": "1", "buyer_billed_gpu_hours": "8", "buyer_rate": "3", "supplier_ask": "1", "collection_share": "0.9", "fee_on_collected": "0.02", "fee_on_gross": "0.01", "required_margin": "0.1", "margin_basis": "gross_billings", "tick_size": "0.01", "market_discount": "0",
                           "cost_owners": {"operations": "operations-v1", "capital": "capital-v1"},
                           "costs": [{"id": "operations", "channel": "operations", "owner_model": "operations-v1", "amount": "2", "basis": "fixed_contract", "kind": "expected_cost"}, {"id": "capital", "channel": "capital", "owner_model": "capital-v1", "amount": "0.4", "basis": "fixed_contract", "kind": "policy_capital"}]},
            "cash_template": {"minimum_cash": "0", "deal_event_ids": [event["event_id"] for event in events],
                              "purchase_coefficients": {"supplier-invoice": "10", "supplier-pay": "10"},
                              "schedule": {"events": events, "legal_entity_id": "entity:invented", "cash_account_id": "bank:invented", "currency": "USD", "opening_cash": "12", "start_date": "2026-01-01", "end_date": "2026-01-04"}}}


class PricingTests(unittest.TestCase):
    def test_independent_golden_inverse_price_and_daily_cash(self):
        result = evaluate_pricing(pricing_packet())
        self.assertEqual(result["status"], "indicative")
        self.assertEqual(result["caps"]["economic_margin"], "1.6128")
        self.assertEqual(result["bid"]["submitted_limit"], "0.93")
        self.assertEqual(result["cash_constraint"]["minimum_free_cash"], "0.028")
        self.assertEqual(result["ask"]["sell_floor_tick"], "2.01")
        self.assertEqual(result["economics"]["economic_profit"], "8.528")
        self.assertFalse(result["executable"])
        self.assertFalse(result["firm_price_eligible"])

    def test_more_opening_cash_makes_economic_constraint_bind(self):
        packet = pricing_packet()
        packet["cash_template"]["schedule"]["opening_cash"] = "100"
        result = evaluate_pricing(packet)
        self.assertEqual(result["bid"]["submitted_limit"], "1.61")
        self.assertEqual(result["bid"]["reservation"], "1.61")  # feasible tick grid also constrains cash search

    def test_supplied_supplier_ask_drives_sell_floor_not_our_bid(self):
        packet = pricing_packet()
        packet["commercial"]["supplier_ask"] = "1.5"
        result = evaluate_pricing(packet)
        self.assertEqual(result["bid"]["submitted_limit"], "0.93")
        self.assertEqual(result["ask"]["sell_floor_tick"], "2.82")
        self.assertFalse(result["bid"]["supplier_ask_within_caps"])

    def test_collection_denominator_is_explicit(self):
        packet = pricing_packet()
        packet["commercial"]["margin_basis"] = "collected_revenue"
        result = evaluate_pricing(packet)
        self.assertEqual(result["caps"]["economic_margin"], "1.6368")
        self.assertEqual(result["economics"]["margin_denominator"], "21.6")

    def test_missing_or_unverified_cash_cannot_produce_usable_bid(self):
        packet = pricing_packet()
        packet.pop("cash_template")
        self.assertEqual(evaluate_pricing(packet)["status"], "held")
        packet["liquidity_points"] = []
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)

    def test_cash_coefficients_and_collections_must_match_economics(self):
        for mutate in (lambda p: p["cash_template"]["purchase_coefficients"].update({"supplier-pay": "1", "supplier-invoice": "1"}),
                       lambda p: p["cash_template"]["schedule"]["events"][-1].update(amount="20"),
                       lambda p: p["cash_template"].update(deal_event_ids=[])):
            packet = pricing_packet()
            mutate(packet)
            with self.assertRaises(ValidationError):
                evaluate_pricing(packet)

    def test_full_settlement_horizon_and_residuals_required(self):
        packet = pricing_packet()
        packet["cash_template"]["schedule"]["end_date"] = "2026-01-03"
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)
        packet = pricing_packet()
        packet["cash_template"]["schedule"]["events"].append({"event_id": "deposit", "obligation_id": "leg:deposit", "kind": "buyer_deposit", "on": "2026-01-01", "amount": "50", "currency": "USD", "advance_account": "escrow:invented"})
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)

    def test_deposit_cannot_pay_supplier_before_earned_release(self):
        packet = pricing_packet()
        packet["cash_template"]["schedule"]["opening_cash"] = "0"
        result = evaluate_pricing(packet)
        self.assertEqual(result["cash_constraint"]["status"], "infeasible_at_zero")
        self.assertEqual(result["status"], "held")

    def test_fee_margin_impossibility_and_nonpayment_double_count(self):
        packet = pricing_packet()
        packet["commercial"]["required_margin"] = "1"
        self.assertIn("no_feasible_collection_fee_margin_denominator", evaluate_pricing(packet)["hold_reasons"])
        packet = pricing_packet()
        packet["commercial"]["costs"][0]["channel"] = "buyer_nonpayment"
        packet["commercial"]["cost_owners"]["buyer_nonpayment"] = "operations-v1"
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)

    def test_cost_ownership_duplicates_and_wrong_units_rejected(self):
        for mutate in (lambda p: p["commercial"]["costs"].append(copy.deepcopy(p["commercial"]["costs"][0])),
                       lambda p: p["commercial"].update(currency="EUR"),
                       lambda p: p["commercial"].update(exclusive_node_gpu_count="4"),
                       lambda p: p["commercial"].update(buyer_billed_gpu_hours="11"),
                       lambda p: p["commercial"].update(supplier_ask=1.1)):
            packet = pricing_packet()
            mutate(packet)
            with self.assertRaises(ValidationError):
                evaluate_pricing(packet)

    def test_policy_and_critical_features_fail_closed(self):
        packet = pricing_packet()
        packet["market"]["policy"]["critical_feature_ids"] = ["credit:score"]
        self.assertEqual(evaluate_pricing(packet)["status"], "held")
        packet = pricing_packet()
        packet["market"]["policy"]["expires_at"] = packet["market"]["as_of"]
        with self.assertRaises(ValidationError):
            evaluate_pricing(packet)

    def test_input_detached_and_hash_changes_with_terms(self):
        packet = pricing_packet()
        untouched = copy.deepcopy(packet)
        first = evaluate_pricing(packet)
        self.assertEqual(packet, untouched)
        packet["commercial"]["supplier_ask"] = "1.1"
        self.assertNotEqual(first["decision_hash"], evaluate_pricing(packet)["decision_hash"])

    def test_real_api_pricing_round_trip(self):
        from fastapi.testclient import TestClient
        from compute_pricing.control.api import create_app
        with tempfile.TemporaryDirectory() as folder:
            key = "invented-auth-key-for-offline-tests-1234"
            with TestClient(create_app(api_key=key, store_path=Path(folder) / "snapshots.sqlite")) as client:
                result = client.post("/v1/pricing/evaluate", json=pricing_packet(), headers={"Authorization": "Bearer " + key})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["result"]["bid"]["submitted_limit"], "0.93")
                self.assertEqual(client.get("/v1/decisions/" + result.json()["snapshot_id"], headers={"Authorization": "Bearer " + key}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
