"""Fresh invented scope/ledger tests; no source data or calibration estimates."""
from copy import deepcopy
from decimal import localcontext
import unittest

from compute_pricing.control.portfolio import evaluate_portfolio_payload
from test_portfolio_v7 import sample, event, codes


def scope_row(report, scope, member):
    return next(row for row in report["ledger_exposure_floor"]["scope_comparisons"]
                if (row["scope"], row["member_id"]) == (scope, member))


class GrossLedgerFloorTests(unittest.TestCase):
    def test_small_declared_supplier_amount_does_not_mask_advance(self):
        payload = sample()
        for row in payload["exposures"]:
            if row["entity_id"] == "supplier:invented":
                row["amount"] = "0.5"
        for row in payload["limits"]:
            if row["scope"] == "entity" and row["member_id"] == "supplier:invented":
                row["maximum_amount"] = "5.25"
        output = evaluate_portfolio_payload(payload)
        supplier = scope_row(output, "entity", "supplier:invented")
        self.assertEqual((supplier["declared_amount"], supplier["floor_amount"], supplier["maximum_amount"]), ("1.5", "10", "5.25"))
        self.assertIn("declared_exposure_below_ledger_floor", codes(output))
        self.assertIn("ledger_exposure_floor_above_limit", codes(output))
        self.assertFalse(output["exposures"]["admitted"])
        self.assertTrue(output["exposures"]["declared_measures_admitted"])
        self.assertFalse(output["checks"]["exposure"])

    def test_full_prefix_schedule_retains_peaks_without_adding_separate_peak_times(self):
        output = evaluate_portfolio_payload(sample())
        self.assertEqual(output["status"], "indicative", output["blockers"])
        self.assertEqual(output["versions"]["model"], "shared-portfolio-candidate/1.1.0")
        self.assertEqual(scope_row(output, "entity", "buyer:forward")["floor_amount"], "12")
        self.assertEqual(scope_row(output, "site", "site:invented")["floor_amount"], "12")
        self.assertEqual(output["cash"]["days"][-1]["buyer_receivables"], "0")
        liability = output["ledger_exposure_floor"]["restricted_deposit_liabilities"][0]
        self.assertEqual(liability["peak_amount"], "4")
        self.assertEqual(liability["entity_id"], "buyer:forward")
        self.assertFalse(output["firm_price_eligible"])
        self.assertFalse(output["execution_enabled"])

    def test_delayed_settlements_make_overlapping_asset_floor_larger(self):
        payload = sample()
        payload["cash"]["end_date"] = "2035-01-05"
        for row in payload["cash"]["events"]:
            if row["kind"] in {"buyer_receipt", "deposit_apply", "prepaid_apply"}:
                row["on"] = "2035-01-05"
        output = evaluate_portfolio_payload(payload)
        self.assertEqual(scope_row(output, "currency", "USD")["floor_amount"], "42")

    def test_unknown_prior_assets_and_liabilities_are_not_assigned_to_candidate(self):
        for field, kind, reference in (
            ("opening_receivables", "buyer_receipt", {"invoice_id": "prior:invoice"}),
            ("opening_deposits", "deposit_refund", {"advance_account": "prior:deposit"}),
        ):
            payload = sample()
            key = next(iter(reference.values()))
            payload["cash"][field] = {key: "2.125"}
            clearing = event("prior:clear", kind, "2.125", "2035-01-01", **reference)
            payload["cash"]["events"].insert(0, clearing)
            payload["baseline_cash_event_ids"] = [clearing["event_id"]]
            output = evaluate_portfolio_payload(payload)
            self.assertTrue(output["checks"]["cash"], output["blockers"])
            self.assertIn("ledger_exposure_baseline_attribution_missing", codes(output))
            self.assertFalse(output["ledger_exposure_floor"]["complete_attribution"])

    def test_conflicting_group_mapping_and_missing_limits_hold(self):
        payload = sample(); payload["exposures"][0]["group_id"] = "group:alternative"
        output = evaluate_portfolio_payload(payload)
        self.assertIn("ledger_exposure_group_missing_or_ambiguous", codes(output))
        self.assertFalse(output["checks"]["exposure"])
        payload = sample(); payload["limits"] = []
        self.assertIn("ledger_exposure_floor_limit_missing", codes(evaluate_portfolio_payload(payload)))

    def test_exact_long_asset_balance_survives_low_caller_precision_and_detaches(self):
        payload = sample()
        exact = "10." + "0" * 84 + "7"
        payload["supplies"][0]["purchase_cost"] = exact
        for row in payload["cash"]["events"]:
            if row["event_id"].startswith("cash:supply-"):
                row["amount"] = exact
        original = deepcopy(payload)
        with localcontext() as context:
            context.prec = 3
            output = evaluate_portfolio_payload(payload)
        self.assertEqual(scope_row(output, "entity", "supplier:invented")["floor_amount"], exact)
        output["ledger_exposure_floor"]["scope_comparisons"][0]["witness"]["on"] = "changed"
        self.assertEqual(payload, original)
        self.assertNotEqual(evaluate_portfolio_payload(payload)["ledger_exposure_floor"]["scope_comparisons"][0]["witness"]["on"], "changed")


if __name__ == "__main__":
    unittest.main()
