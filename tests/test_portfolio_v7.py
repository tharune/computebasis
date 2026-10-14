"""Invented shared portfolio: positive profit is not proof of funding/capacity."""
import copy
from pathlib import Path
from decimal import Decimal
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.portfolio import evaluate_portfolio_payload, portfolio_template
from compute_pricing.control.underwriting import underwriting_template

NOW = "2035-01-01T00:00:00Z"


def event(identity, kind, amount, on="2035-01-03", **extra):
    return {"event_id": identity, "obligation_id": "obligation:" + identity,
            "kind": kind, "amount": amount, "on": on, "currency": "USD", **extra}


def technical_request():
    setup = {"model_id": "model:invented", "runtime_id": "runtime:invented", "runtime_version": "1.0.0",
             "hardware_model": "Invented Public Accelerator", "precision": "fp16", "quantization": "none",
             "tensor_parallel": 1, "pipeline_parallel": 1, "data_replicas": 1,
             "context_tokens": 128, "batch_size": 1, "input_tokens_per_request": "20",
             "output_tokens_per_request": "10", "cached_input_tokens_per_request": "0"}
    return {"as_of": NOW, "policy_version": "policy:invented", "model_version": "qualified-inference/1.0.0",
            "workload": {**setup, "request_count": "2", "starts_at": NOW, "ends_at": "2035-01-01T01:00:00Z",
                         "slo": {"max_ttft_ms": "100", "max_p95_latency_ms": "200"}, "availability_fraction": "1"},
            "qualification": {"id": "qualification:invented", "status": "qualified", "evidence_sha256": "a" * 64,
                  "setup": setup, "measured_at": "2034-12-31T00:00:00Z", "expires_at": "2035-01-04T00:00:00Z",
                  "whole_deployment_slo_goodput_requests_per_second": "1", "measured_ttft_ms": "10", "measured_p95_latency_ms": "20",
                  "memory": {"per_gpu_required_gib": "7", "per_gpu_available_gib": "19", "includes_kv_cache": True,
                             "includes_runtime_overhead": True, "bandwidth_qualification": "measured_under_declared_parallelism"}},
            "costs": {"currency": "USD", "gpu_rate_per_gpu_hour": "1", "cost_items": [], "collection_share": "1",
                      "fee_fraction_of_collected_revenue": "0", "fee_fraction_of_gross_revenue": "0"},
            "sale_rates": {"currency": "USD", "input_per_million": "0", "output_per_million": "0", "cached_input_per_million": "0", "request_fee": "4"}}


def review(kind):
    template = underwriting_template()
    subjects = {row["subject_kind"]: "subject:" + row["subject_kind"] for row in template["requirements"]}
    subjects.update(lot="lot:invented", site="site:invented", supplier="supplier:invented", buyer="buyer:" + kind,
                    transaction="route:" + kind, portfolio="portfolio:invented", workload="route:" + kind)
    evidence = []
    for row in template["requirements"]:
        if kind not in row["scopes"]:
            continue
        subject = subjects[row["subject_kind"]]
        evidence.append({"requirement_id": row["requirement_id"], "subject_id": subject,
                         "status": "verified", "value": "1" if row["value_type"] in {"decimal", "integer"} else "Invented independent review assertion",
                         "unit": row["unit"], "valid_from": "2034-12-30T00:00:00Z", "valid_until": "2035-01-04T00:00:00Z",
                         "reviewed_by": "reviewer:invented", "evidence": [{"id": "evidence:" + kind + ":" + row["requirement_id"],
                              "source_id": "source:invented", "artifact_sha256": ("a" if row["requirement_id"] == "inference:benchmark" else "b") * 64, "verifier": "reviewer:invented",
                              "accessed_at": "2034-12-30T00:00:00Z", "expires_at": "2035-01-04T00:00:00Z", "status": "verified",
                              "scope": [*row["evidence_scope"], "subject:" + subject], "permission": {"status": "allowed",
                                  "observe": "PASS", "retain": "PASS", "benchmark": "UNKNOWN", "execution": "FAIL", "verified_by": "rights:invented"}}]})
    return {"schema_version": template["schema_version"], "request_id": "review:" + kind, "as_of": NOW,
            "requirements_version": template["requirements_version"], "scopes": [kind], "subjects": subjects,
            "requirements": template["requirements"], "evidence": evidence}


def sample():
    supply_events = [event("cash:supply-prepay", "supplier_prepayment", "10", "2035-01-01", advance_account="prepaid:supply"),
                     event("cash:supply-invoice", "supplier_invoice", "10", invoice_id="invoice:supply"),
                     event("cash:supply-apply", "prepaid_apply", "10", invoice_id="invoice:supply", advance_account="prepaid:supply"),
                     event("cash:supply-expense", "expense", "10")]
    routes, reservations, route_events = [], [], []
    for index, kind in enumerate(("inference", "resale", "forward"), 1):
        amount = "8" if kind == "inference" else "12"
        events = [event("cash:" + kind + "-invoice", "buyer_invoice", amount, invoice_id="invoice:" + kind),
                  event("cash:" + kind + "-revenue", "revenue", amount, invoice_id="invoice:" + kind)]
        if kind == "forward":
            events.extend([event("cash:forward-deposit", "buyer_deposit", "4", "2035-01-01", advance_account="deposit:forward"),
                           event("cash:forward-apply", "deposit_apply", "4", invoice_id="invoice:forward", advance_account="deposit:forward"),
                           event("cash:forward-receipt", "buyer_receipt", "8", invoice_id="invoice:forward")])
        else:
            events.append(event("cash:" + kind + "-receipt", "buyer_receipt", amount, invoice_id="invoice:" + kind))
        if kind == "resale":
            events.extend([event("cash:resale-cost", "other_outflow", "3"), event("cash:resale-expense", "expense", "3")])
        start = "2035-01-02T00:00:00Z" if kind == "forward" else NOW
        end = "2035-01-01T01:00:00Z" if kind == "inference" else "2035-01-03T00:00:00Z"
        reservations.append({"reservation_id": "reservation:" + kind, "allocation_id": "route:" + kind, "lot_id": "lot:invented",
                             "unit_ids": ["gpu:" + str(index)], "start_at": start, "end_at": end})
        routes.append({"route_id": "route:" + kind, "kind": kind, "buyer_entity_id": "buyer:" + kind,
                       "reservation_id": "reservation:" + kind, "cash_event_ids": [row["event_id"] for row in events],
                       "exposure_ids": ["exposure:" + kind + ":supplier", "exposure:" + kind + ":buyer"],
                       "economics": {"currency": "USD", "gross_billings": amount, "expected_collections": amount,
                                     "distribution_fees": "1" if kind == "resale" else "0", "nonpurchase_cost": "2" if kind == "resale" else "0", "policy_capital": "1" if kind == "resale" else "0"},
                       "supply_cost_allocations": [{"supply_id": "supply:invented", "amount": "1" if kind == "inference" else "3"}],
                       "inference_request": technical_request() if kind == "inference" else None,
                       "underwriting_request_id": "review:" + kind})
        route_events.extend(events)
    exposures = [{"exposure_id": "exposure:" + kind + ":" + role, "entity_id": "supplier:invented" if role == "supplier" else "buyer:" + kind,
                  "group_id": "group:supplier" if role == "supplier" else "group:" + kind, "site_id": "site:invented", "currency": "USD", "amount": "4" if role == "supplier" else "8" if kind == "inference" else "12"}
                 for kind in ("inference", "resale", "forward") for role in ("supplier", "buyer")]
    memberships = {("entity", row["entity_id"]) for row in exposures} | {("group", row["group_id"]) for row in exposures} | {("site", "site:invented"), ("currency", "USD")}
    limits = [{"limit_id": "limit:" + scope + ":" + member.lower(), "scope": scope, "member_id": member, "currency": "USD",
               "maximum_amount": str(sum((Decimal(row["amount"]) for row in exposures if scope in {"site", "currency"} or row[scope + "_id"] == member), Decimal(0)))}
              for scope, member in sorted(memberships)]
    return {"schema_version": "portfolio-assessment/1.0", "request_id": "portfolio:invented", "as_of": NOW, "policy_version": "policy:invented",
            "cash": {"legal_entity_id": "operator:invented", "cash_account_id": "account:invented", "currency": "USD", "opening_cash": "10",
                     "start_date": "2035-01-01", "end_date": "2035-01-03", "events": supply_events + route_events, "reserves": []},
            "capacity": {"lots": [{"lot_id": "lot:invented", "site_id": "site:invented", "unit_kind": "gpu", "unit_ids": ["gpu:1", "gpu:2", "gpu:3"],
                                    "start_at": NOW, "end_at": "2035-01-03T00:00:00Z", "supplier_entity_id": "supplier:invented",
                                    "hardware_model": "Invented Public Accelerator", "accelerators_per_unit": "1"}],
                         "reservations": reservations, "maintenance": [], "baseline_allocation_ids": []},
            "routes": routes, "supplies": [{"supply_id": "supply:invented", "lot_id": "lot:invented", "purchase_cost": "10", "currency": "USD", "cash_event_ids": [row["event_id"] for row in supply_events]}],
            "baseline_cash_event_ids": [], "baseline_exposure_ids": [], "exposures": exposures, "limits": limits,
            "underwriting_requests": [review(kind) for kind in ("inference", "resale", "forward")], "minimum_free_cash": "0"}


def codes(result):
    return {row["code"] for row in result["blockers"]}


class PortfolioV7Tests(unittest.TestCase):
    def test_three_routes_share_one_cash_capacity_and_cost_owner_no_unearned_profit(self):
        result = evaluate_portfolio_payload(sample())
        self.assertEqual(result["status"], "indicative", result["blockers"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["economics"]["expected_collections"], "32")
        self.assertEqual(result["economics"]["total_supply_cost"], "10")
        self.assertEqual(result["economics"]["unallocated_supply_cost"], "3")
        self.assertEqual(result["economics"]["expected_contribution"], "19")
        self.assertEqual(result["economics"]["economic_profit"], "18")
        self.assertEqual(result["cash"]["days"][-1]["cash"], "29")
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["firm_price_eligible"])
        self.assertEqual(result, evaluate_portfolio_payload(sample()))

    def test_profitable_combined_routes_cannot_reuse_signing_cash_or_restricted_deposit(self):
        payload = sample(); payload["cash"]["opening_cash"] = "6"
        result = evaluate_portfolio_payload(payload)
        self.assertEqual(result["economics"]["expected_contribution"], "19")
        self.assertEqual(result["status"], "held")
        self.assertIn("shared_cash_below_required_floor", codes(result))
        self.assertEqual(result["cash"]["required_extra_cash"], "4")
        self.assertEqual(result["cash"]["days"][0]["restricted_deposits"], "4")

    def test_baseline_obligations_consume_same_cash_and_limit_headroom(self):
        payload = sample(); baseline = event("cash:baseline", "other_outflow", "1", "2035-01-01")
        payload["cash"]["events"].insert(0, baseline); payload["baseline_cash_event_ids"] = [baseline["event_id"]]
        payload["exposures"].append({"exposure_id": "exposure:baseline", "entity_id": "supplier:invented", "group_id": "group:supplier", "site_id": "site:invented", "currency": "USD", "amount": "1"})
        payload["baseline_exposure_ids"] = ["exposure:baseline"]
        result = evaluate_portfolio_payload(payload)
        self.assertIn("shared_cash_below_required_floor", codes(result))
        self.assertIn("missing_or_breached_shared_portfolio_limits", codes(result))
        self.assertFalse(result["checks"]["exposure"])

    def test_inference_resale_forward_and_maintenance_share_physical_units(self):
        payload = sample(); payload["capacity"]["reservations"][1]["unit_ids"] = ["gpu:1"]
        self.assertIn("shared_capacity_overlap_or_invalid_ledger", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["capacity"]["maintenance"] = [{"maintenance_id": "maintenance:invented", "lot_id": "lot:invented", "unit_ids": ["gpu:1"], "start_at": NOW, "end_at": "2035-01-01T00:30:00Z"}]
        self.assertFalse(evaluate_portfolio_payload(payload)["checks"]["capacity"])

    def test_forward_cutover_is_half_open_and_unknown_reservations_are_not_ignored(self):
        payload = sample(); inference = payload["capacity"]["reservations"][0]
        payload["capacity"]["reservations"][2].update(unit_ids=["gpu:1"], start_at=inference["end_at"])
        self.assertTrue(evaluate_portfolio_payload(payload)["checks"]["capacity"])
        payload["capacity"]["reservations"].append({"reservation_id": "reservation:unknown", "allocation_id": "allocation:unknown", "lot_id": "lot:invented", "unit_ids": ["gpu:2"], "start_at": "2035-01-01T01:00:00Z", "end_at": "2035-01-02T00:00:00Z"})
        self.assertIn("unowned_capacity_allocation", codes(evaluate_portfolio_payload(payload)))

    def test_full_supply_and_facility_tail_is_mandatory(self):
        payload = sample(); payload["capacity"]["lots"][0]["end_at"] = "2036-01-01T00:00:00Z"
        self.assertIn("cash_horizon_omits_supply_tail", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["cash"]["facility"] = {"facility_id": "facility:invented", "currency": "USD", "committed_limit": "10", "opening_outstanding": "0", "opening_drawn_total": "0", "opening_accrued_interest": "0", "annual_rate": "0", "available_from": "2035-01-01", "maturity_date": "2035-01-04", "day_count": "ACT/365F", "revolving": True}
        self.assertIn("invalid_shared_cash_schedule", codes(evaluate_portfolio_payload(payload)))

    def test_currency_entity_site_and_uncovered_limits_do_not_net_implicitly(self):
        for change in ("currency", "buyer", "site", "limits"):
            payload = sample()
            if change == "currency": payload["exposures"][0]["currency"] = "EUR"
            elif change == "buyer": payload["routes"][0]["buyer_entity_id"] = "buyer:unknown"
            elif change == "site": payload["exposures"][0]["site_id"] = "site:unknown"
            else: payload["limits"] = []
            result = evaluate_portfolio_payload(payload)
            self.assertEqual(result["status"], "held")
            self.assertFalse(result["checks"]["exposure"])

    def test_each_cash_exposure_supply_cost_and_reservation_has_unique_global_owner(self):
        payload = sample(); payload["routes"][1]["cash_event_ids"].append(payload["routes"][0]["cash_event_ids"][0])
        self.assertIn("cash_events_must_have_one_global_owner", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["routes"][1]["exposure_ids"].append(payload["routes"][0]["exposure_ids"][0])
        self.assertIn("exposures_must_have_one_global_owner", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["routes"][1]["supply_cost_allocations"][0]["amount"] = "20"
        self.assertIn("supplier_cost_allocated_more_than_once", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["routes"][1]["reservation_id"] = payload["routes"][0]["reservation_id"]
        self.assertIn("reservation_claimed_by_multiple_routes", codes(evaluate_portfolio_payload(payload)))

    def test_route_receipt_fee_cost_and_entire_supply_cost_reconcile_to_global_ledger(self):
        for field in ("expected_collections", "distribution_fees", "nonpurchase_cost"):
            payload = sample(); payload["routes"][1]["economics"][field] = "7"
            self.assertIn("route_cash_and_economics_do_not_reconcile", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["supplies"][0]["purchase_cost"] = "9"
        self.assertIn("supplier_cash_and_expense_do_not_reconcile", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["routes"][0]["economics"]["gross_billings"] = "1"
        self.assertIn("collections_exceed_gross_billings", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["routes"][1]["economics"]["gross_billings"] = "100"
        self.assertIn("gross_invoices_earned_revenue_do_not_reconcile", codes(evaluate_portfolio_payload(payload)))
        payload = sample()
        row = next(event for event in payload["cash"]["events"] if event["event_id"] == "cash:resale-revenue")
        row["amount"] = "1"
        self.assertFalse(evaluate_portfolio_payload(payload)["checks"]["economic_reconciliation"])

    def test_financing_draw_is_not_earned_route_revenue(self):
        payload = sample(); payload["cash"]["events"].append(event("cash:fake-finance", "other_inflow", "99"))
        payload["routes"][0]["cash_event_ids"].append("cash:fake-finance")
        result = evaluate_portfolio_payload(payload)
        self.assertIn("route_cannot_own_supply_or_financing_cash", codes(result))
        self.assertEqual(result["economics"]["expected_collections"], "32")

    def test_credit_and_deposit_legs_cannot_move_between_route_owners(self):
        payload = sample()
        moved = "cash:resale-receipt"
        payload["routes"][1]["cash_event_ids"].remove(moved)
        payload["routes"][0]["cash_event_ids"].append(moved)
        self.assertIn("invoice_crosses_economic_owners", codes(evaluate_portfolio_payload(payload)))
        payload = sample()
        moved = "cash:forward-deposit"
        payload["routes"][2]["cash_event_ids"].remove(moved)
        payload["baseline_cash_event_ids"] = [moved]
        self.assertIn("advance_crosses_economic_owners", codes(evaluate_portfolio_payload(payload)))

    def test_shared_facility_cannot_fund_duplicate_draws_and_requires_actual_draw_events(self):
        payload = sample()
        payload["cash"]["facility"] = {"facility_id": "facility:invented", "currency": "USD", "committed_limit": "5", "opening_outstanding": "0", "opening_drawn_total": "0", "opening_accrued_interest": "0", "annual_rate": "0", "available_from": "2035-01-01", "maturity_date": "2035-01-03", "day_count": "ACT/365F", "revolving": True}
        payload["cash"]["opening_cash"] = "5"
        result = evaluate_portfolio_payload(payload)
        self.assertIn("shared_cash_below_required_floor", codes(result))
        draws = [event("cash:draw-one", "facility_draw", "5", "2035-01-01"), event("cash:draw-two", "facility_draw", "5", "2035-01-01")]
        payload["cash"]["events"][0:0] = draws
        payload["baseline_cash_event_ids"] = [row["event_id"] for row in draws]
        self.assertIn("invalid_shared_cash_schedule", codes(evaluate_portfolio_payload(payload)))

    def test_inference_must_match_owned_physical_setup_horizon_and_monetary_denominators(self):
        payload = sample(); payload["capacity"]["lots"][0]["accelerators_per_unit"] = None
        self.assertIn("inference_physical_accelerator_mapping_unknown", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["capacity"]["lots"][0]["hardware_model"] = "Another invented device"
        self.assertIn("inference_setup_does_not_match_reserved_capacity", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["routes"][0]["supply_cost_allocations"][0]["amount"] = "2"
        self.assertIn("inference_economics_do_not_reconcile_to_shared_portfolio", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["routes"][0]["inference_request"]["qualification"]["expires_at"] = NOW
        self.assertIn("inference_economics_or_qualification_held", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["routes"][0]["inference_request"]["policy_version"] = "policy:different"
        self.assertIn("inference_setup_does_not_match_reserved_capacity", codes(evaluate_portfolio_payload(payload)))

    def test_missing_stale_wrong_subject_or_weakened_underwriting_core_remains_held(self):
        payload = sample(); payload["underwriting_requests"] = []
        self.assertFalse(evaluate_portfolio_payload(payload)["checks"]["evidence"])
        payload = sample(); payload["underwriting_requests"][0]["evidence"][0]["valid_until"] = NOW
        self.assertIn("route_underwriting_evidence_missing_or_held", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["underwriting_requests"][0]["subjects"]["lot"] = "lot:wrong"
        self.assertFalse(evaluate_portfolio_payload(payload)["checks"]["evidence"])
        payload = sample()
        for row in payload["underwriting_requests"][0]["requirements"]:
            if row["requirement_id"] == "supplier:identity": row["required"] = False
        self.assertIn("route_underwriting_scope_subject_or_required_core_mismatch", codes(evaluate_portfolio_payload(payload)))
        payload = sample(); payload["underwriting_requests"][0]["subjects"]["portfolio"] = "portfolio:unrelated"
        self.assertFalse(evaluate_portfolio_payload(payload)["checks"]["evidence"])
        payload = sample()
        benchmark = next(row for row in payload["underwriting_requests"][0]["evidence"] if row["requirement_id"] == "inference:benchmark")
        benchmark["evidence"][0]["artifact_sha256"] = "c" * 64
        self.assertIn("inference_benchmark_not_bound_to_underwriting_evidence", codes(evaluate_portfolio_payload(payload)))

    def test_residual_idle_cost_is_preserved_and_no_margin_or_probability_is_invented(self):
        result = evaluate_portfolio_payload(sample())
        self.assertEqual(result["economics"]["unallocated_supply_cost"], "3")
        self.assertNotIn("probability_of_profit", result)
        self.assertNotIn("optimal_bid", result)
        self.assertFalse(result["firm_price_eligible"])
        payload = sample(); payload["routes"][1]["economics"]["policy_capital"] = "100"
        self.assertIn("candidate_economic_profit_negative", codes(evaluate_portfolio_payload(payload)))

    def test_precision_and_result_detachment_versions_are_exact(self):
        payload = sample(); payload["routes"][1]["economics"]["policy_capital"] = "0.12345678901234567890123456789"
        result = evaluate_portfolio_payload(payload)
        self.assertEqual(result["economics"]["economic_profit"], "18.87654321098765432109876543211")
        snapshot = copy.deepcopy(payload)
        result["underwriting"][0]["rows"][0]["title"] = "mutated"
        self.assertEqual(payload, snapshot)
        changed = copy.deepcopy(payload); changed["policy_version"] = "policy:successor"
        self.assertNotEqual(result["input_hash"], evaluate_portfolio_payload(changed)["input_hash"])

    def test_blank_unknown_and_extra_inputs_remain_explicitly_held_or_unused(self):
        template = portfolio_template()
        self.assertEqual(template["request"]["routes"], [])
        self.assertIsNone(template["request"]["cash"]["opening_cash"])
        self.assertEqual(evaluate_portfolio_payload(template["request"])["status"], "held")
        payload = sample(); payload["unregistered_weight"] = "0.8"
        result = evaluate_portfolio_payload(payload)
        self.assertEqual(result["unused_fields"], ["unregistered_weight"])
        self.assertEqual(result["economics"]["expected_contribution"], "19")
        for value in (0.1, float("nan"), float("inf")):
            payload["extensions"] = {"bad": value}
            with self.assertRaises(ValidationError): evaluate_portfolio_payload(payload)
        payload = sample(); payload["routes"].append(copy.deepcopy(payload["routes"][0]))
        with self.assertRaises(ValidationError): evaluate_portfolio_payload(payload)


if __name__ == "__main__":
    unittest.main()
