"""Behavioral checks for exact cash, restrictions, advance and facility tails."""

import sys
import unittest
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compute_pricing.control.treasury import (AffineCashPoint, CashEvent, Facility, Reserve,
    affine_purchase_price_cap, calendar_periods, calendar_unit_hours,
    evaluate_cash_payload, evaluate_cash_schedule, invoice_due_date)


def event(key, on, kind, amount, **kwargs):
    return CashEvent(key, f"obligation-{key}", on, kind, amount, "USD", **kwargs)


def ledger(events=(), **kwargs):
    defaults = dict(legal_entity_id="operator-a", cash_account_id="bank-a", currency="USD",
                    opening_cash="0", start_date="2024-01-01", end_date="2024-01-03")
    defaults.update(kwargs)
    return evaluate_cash_schedule(events, **defaults)


def facility(**kwargs):
    defaults = dict(facility_id="credit-a", currency="USD", committed_limit="100",
        opening_outstanding="0", opening_drawn_total="0", opening_accrued_interest="0",
        annual_rate="0", available_from="2024-01-01", maturity_date="2024-01-03",
        day_count="ACT/365F", revolving=True)
    defaults.update(kwargs)
    return Facility(**defaults)


class DailyCashTests(unittest.TestCase):
    def test_actual_calendar_and_explicit_invoice_trigger(self):
        self.assertEqual(calendar_unit_hours("2024-02-01", "2024-03-01", quantity=1), Decimal("696"))
        self.assertEqual(calendar_unit_hours("2024-01-01", "2024-02-01", quantity=1), Decimal("744"))
        self.assertEqual(calendar_periods("2024-01-15", "2024-03-03"),
            (("2024-01-15", "2024-02-01"), ("2024-02-01", "2024-03-01"), ("2024-03-01", "2024-03-03")))
        self.assertEqual(invoice_due_date("2024-01-31", net_days=45, settlement_lag_days=2,
            weekend_adjustment="following", holidays=("2024-03-18",)), "2024-03-19")

    def test_deposit_and_supplier_prepay_roll_forward_reconciles_once(self):
        events = [event("deposit", "2024-01-01", "buyer_deposit", "30", advance_account="buyer-a"),
            event("prepay", "2024-01-01", "supplier_prepayment", "40", advance_account="supplier-a"),
            event("invoice", "2024-01-02", "buyer_invoice", "100", invoice_id="sale-a"),
            event("earned", "2024-01-02", "revenue", "100", invoice_id="sale-a"),
            event("apply", "2024-01-02", "deposit_apply", "30", invoice_id="sale-a", advance_account="buyer-a"),
            event("receipt", "2024-01-02", "buyer_receipt", "70", invoice_id="sale-a"),
            event("cost", "2024-01-02", "expense", "60"),
            event("supplier-invoice", "2024-01-02", "supplier_invoice", "60", invoice_id="cost-a"),
            event("supplier-apply", "2024-01-02", "prepaid_apply", "40", invoice_id="cost-a", advance_account="supplier-a"),
            event("supplier-pay", "2024-01-02", "supplier_payment", "20", invoice_id="cost-a")]
        result = ledger(events, opening_cash="40")
        self.assertEqual(result.days[0].cash, 0)
        self.assertEqual(result.days[0].restricted_deposits, 30)
        self.assertEqual(result.days[-1].cash, 80)
        self.assertEqual(result.days[-1].earned_revenue - result.days[-1].recognized_expense, 40)
        self.assertTrue(all(not balances for balances in result.unresolved_balances.values()))
        self.assertEqual(result.to_dict()["days"][-1]["cash"], "80")

    def test_refund_of_segregated_deposit_does_not_charge_free_cash_twice(self):
        result = ledger([event("deposit", "2024-01-01", "buyer_deposit", "20", advance_account="buyer-a"),
                         event("refund", "2024-01-02", "deposit_refund", "20", advance_account="buyer-a")], opening_cash="10")
        self.assertEqual([row.cash for row in result.days], [Decimal("10")] * 3)
        self.assertEqual(result.days[-1].restricted_deposits, 0)

    def test_invoice_not_receipt_or_earned_cash(self):
        result = ledger([event("invoice", "2024-01-01", "buyer_invoice", "100", invoice_id="invoice-a"),
                         event("earned", "2024-01-01", "revenue", "100", invoice_id="invoice-a")])
        self.assertEqual(result.days[-1].cash, 0)
        self.assertEqual(result.days[-1].buyer_receivables, 100)
        self.assertEqual(result.days[-1].earned_revenue, 100)

    def test_unearned_or_overcollected_deposit_application_rejected(self):
        setup = [event("deposit", "2024-01-01", "buyer_deposit", "30", advance_account="buyer-a"),
                 event("invoice", "2024-01-02", "buyer_invoice", "100", invoice_id="invoice-a")]
        application = event("apply", "2024-01-02", "deposit_apply", "30", advance_account="buyer-a", invoice_id="invoice-a")
        with self.assertRaisesRegex(ValueError, "earned"):
            ledger([*setup, application])
        earned = event("earned", "2024-01-02", "revenue", "100", invoice_id="invoice-a")
        with self.assertRaisesRegex(ValueError, "unsettled invoice"):
            ledger([*setup, earned, application, event("receipt", "2024-01-02", "buyer_receipt", "100", invoice_id="invoice-a")])

    def test_duplicate_obligation_cannot_be_renamed_to_duplicate_cash(self):
        first = event("out-a", "2024-01-01", "other_outflow", "20")
        second = CashEvent("out-b", first.obligation_id, "2024-01-02", "other_outflow", "20", "USD")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            ledger([first, second])

    def test_horizon_includes_late_payment_and_leap_calendar(self):
        events = [event("cost", "2024-02-01", "other_outflow", "80"),
            event("invoice", "2024-02-01", "buyer_invoice", "100", invoice_id="invoice-a"),
            event("receipt", "2024-03-20", "buyer_receipt", "100", invoice_id="invoice-a")]
        result = ledger(events, opening_cash="60", start_date="2024-02-01", end_date="2024-03-20")
        self.assertEqual(len(result.days), 49)
        self.assertEqual(result.required_extra_cash, 20)
        self.assertEqual(result.days[-1].cash, 80)
        with self.assertRaisesRegex(ValueError, "omits an event"):
            ledger(events, start_date="2024-02-01", end_date="2024-02-29")

    def test_revolver_replenishes_but_term_facility_does_not(self):
        events = [event("draw", "2024-01-01", "facility_draw", "80"),
            event("repay", "2024-01-02", "facility_repay", "40"),
            event("draw-again", "2024-01-02", "facility_draw", "40")]
        self.assertEqual(ledger(events, facility=facility()).days[1].drawable_undrawn, 20)
        with self.assertRaisesRegex(ValueError, "undrawn"):
            ledger(events, facility=facility(revolving=False))
        past_draws = facility(revolving=False, opening_outstanding="20", opening_drawn_total="100")
        with self.assertRaisesRegex(ValueError, "undrawn"):
            ledger([event("draw-new", "2024-01-01", "facility_draw", "1")], facility=past_draws)

    def test_facility_bounds_maturity_and_undrawn_is_not_cash(self):
        result = ledger(facility=facility())
        self.assertEqual(result.days[0].cash, 0)
        self.assertEqual(result.days[0].drawable_undrawn, 100)
        self.assertEqual(result.days[-1].drawable_undrawn, 0)
        with self.assertRaises(ValueError):
            ledger([event("draw", "2024-01-03", "facility_draw", "1")], facility=facility())
        with self.assertRaises(ValueError):
            ledger([event("repay", "2024-01-01", "facility_repay", "1")], facility=facility())
        with self.assertRaises(ValueError):
            ledger([event("draw", "2024-01-01", "facility_draw", "80"),
                    event("release", "2024-01-01", "facility_release", "30")], facility=facility())
        self.assertTrue(ledger([event("draw", "2024-01-01", "facility_draw", "1")], facility=facility()).maturity_breach)
        with self.assertRaisesRegex(ValueError, "maturity"):
            ledger(facility=facility(), end_date="2024-01-02")

    def test_shared_facility_cannot_be_drawn_for_two_full_candidates(self):
        events = [event("deal-a-draw", "2024-01-01", "facility_draw", "60"),
                  event("deal-a-pay", "2024-01-01", "other_outflow", "60"),
                  event("deal-b-draw", "2024-01-01", "facility_draw", "60"),
                  event("deal-b-pay", "2024-01-01", "other_outflow", "60")]
        with self.assertRaisesRegex(ValueError, "undrawn"):
            ledger(events, facility=facility())

    def test_actual_day_count_interest_applied_once(self):
        for convention, rate in (("ACT/365F", "0.365"), ("ACT/360", "0.36")):
            events = [event("draw", "2024-01-01", "facility_draw", "100"),
                event("interest", "2024-01-02", "facility_interest", "0.1"),
                event("repay", "2024-01-02", "facility_repay", "100")]
            result = ledger(events, opening_cash="1", facility=facility(day_count=convention, annual_rate=rate))
            self.assertEqual(result.days[-1].cash, Decimal("0.9"))
            self.assertEqual(result.days[-1].accrued_interest, 0)
            self.assertFalse(result.maturity_breach)

    def test_same_day_ordered_trough_and_nonoverlapping_reserves(self):
        result = ledger([event("spend", "2024-01-01", "other_outflow", "80"),
                         event("receipt", "2024-01-01", "other_inflow", "100")], opening_cash="20")
        self.assertEqual(result.days[0].cash, 40)
        self.assertEqual(result.required_extra_cash, 60)
        reserves = [Reserve("reserve-a", "refund-a", "5", "2024-01-01", "2024-01-03"),
                    Reserve("reserve-b", "refund-a", "5", "2024-01-02", "2024-01-04")]
        with self.assertRaisesRegex(ValueError, "overlapping"):
            ledger(reserves=reserves)
        restricted_reserve = Reserve("reserve-c", "deposit:buyer-a", "20", "2024-01-01", "2024-01-04")
        with self.assertRaisesRegex(ValueError, "restricted deposit"):
            ledger([event("deposit", "2024-01-01", "buyer_deposit", "20", advance_account="buyer-a")], reserves=[restricted_reserve])

    def test_exact_string_currency_and_calendar_validation(self):
        for invalid in (1.2, "NaN", "1e3", "Infinity", "-1", True):
            with self.assertRaises(ValueError):
                event("bad", "2024-01-01", "other_outflow", invalid)
        with self.assertRaises(ValueError):
            CashEvent("bad", "bad-obligation", "2024-01-01", "other_outflow", "1", "UNKNOWN")
        with self.assertRaises(ValueError):
            event("bad", "2024-02-30", "other_outflow", "1")
        with self.assertRaises(ValueError):
            ledger([CashEvent("eur", "eur-obligation", "2024-01-01", "other_outflow", "1", "EUR")])
        with self.assertRaises(ValueError):
            ledger(opening_cash=1.2)
        with self.assertRaises(ValueError):
            ledger(opening_deposits=[])

    def test_affine_cap_uses_signing_and_daily_trough_without_future_receipt(self):
        result = affine_purchase_price_cap([
            AffineCashPoint("sign", "2024-01-01", "60", "30"),
            AffineCashPoint("settlement", "2024-01-10", "1000", "100")],
            minimum_cash="0", maximum_search_price="20")
        self.assertEqual(result.maximum_purchase_price, 2)
        self.assertEqual(result.binding_point_id, "sign")
        failed = affine_purchase_price_cap([AffineCashPoint("baseline", "2024-01-01", "-1", "0")],
            minimum_cash="0", maximum_search_price="20")
        self.assertFalse(failed.feasible_at_zero)
        self.assertIsNone(failed.maximum_purchase_price)

    def test_tiny_cash_amount_is_not_rounded_out_of_large_balance(self):
        large = "1234567890123456789012345678901234567890"
        tiny = "0.000000000000000000000000000000000000001"
        result = ledger([event("tiny", "2024-01-01", "other_inflow", tiny)], opening_cash=large)
        self.assertEqual(format(result.days[-1].cash, "f"), large + ".000000000000000000000000000000000000001")

    def test_opening_earned_release_cannot_be_recognized_again(self):
        result = ledger([event("release", "2024-01-01", "deposit_apply", "40", invoice_id="invoice-a", advance_account="buyer-a")],
                        opening_receivables={"invoice-a": "100"}, opening_earned_for_release={"invoice-a": "40"}, opening_deposits={"buyer-a": "40"})
        self.assertEqual(result.days[-1].cash, 40)
        with self.assertRaisesRegex(ValueError, "revenue exceeds"):
            ledger([event("earned", "2024-01-01", "revenue", "100", invoice_id="invoice-a")],
                   opening_receivables={"invoice-a": "100"}, opening_earned_for_release={"invoice-a": "40"})

    def test_json_envelope_preserves_exact_values_and_rejects_unknown_terms(self):
        payload = dict(events=[], legal_entity_id="operator-a", cash_account_id="bank-a", currency="USD",
                       opening_cash="0.1234567890123456789", start_date="2024-01-01", end_date="2024-01-01")
        self.assertEqual(evaluate_cash_payload(payload).days[0].cash, Decimal(payload["opening_cash"]))
        with self.assertRaises(ValueError):
            evaluate_cash_payload({**payload, "opening_cash": 0.1})
        with self.assertRaisesRegex(ValueError, "unregistered"):
            evaluate_cash_payload({**payload, "automatic_unrestricted_deposit": True})
        with self.assertRaisesRegex(ValueError, "known named fields"):
            evaluate_cash_payload({**payload, "events": [{"price": "1", "borrow": True}]})


if __name__ == "__main__":
    unittest.main()
