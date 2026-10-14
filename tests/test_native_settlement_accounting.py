"""Independent invented books for unearned funding and noncash adjustments."""
from decimal import Decimal, localcontext
import unittest

from compute_pricing.control.treasury import CashEvent, evaluate_cash_payload, evaluate_cash_schedule, invoice_due_date
from compute_pricing.control.pricing.liquidity import cash_price_limit

D1, D2 = "2055-09-04", "2055-09-09"
TERMS = {"sample-advance": {"buyer_entity_id": "sample-buyer", "basis_ref": "sample-contract-use",
                            "usable_for_operations": True, "refund_terms_ref": "sample-refund-clause"}}


def entry(name, kind, amount, on=D1, **fields):
    if kind in {"buyer_advance", "advance_apply", "advance_refund"}:
        fields.setdefault("advance_account", "sample-advance")
        fields.setdefault("basis_ref", "sample-contract-use")
    if kind in {"receivable_writeoff", "buyer_credit_note", "deposit_forfeit"}:
        fields.setdefault("basis_ref", "sample-accounting-basis")
    return CashEvent(name, "economic-leg-" + name, on, kind, amount, "EUR", **fields)


def book(events=(), **settings):
    options = {"legal_entity_id": "sample-operator", "cash_account_id": "sample-cash-account",
               "currency": "EUR", "opening_cash": "0", "start_date": D1, "end_date": D2}
    options.update(settings)
    return evaluate_cash_schedule(events, **options)


class NativeSettlementAccountingTests(unittest.TestCase):
    def test_advance_funds_early_cost_while_retaining_an_unearned_liability(self):
        result = book([entry("fund", "buyer_advance", "135"), entry("cost", "expense", "92"),
            entry("pay-cost", "other_outflow", "92"), entry("refund", "advance_refund", "19", D2),
            entry("invoice", "buyer_invoice", "180", D2, invoice_id="sample-sale"),
            entry("earn", "revenue", "180", D2, invoice_id="sample-sale"),
            entry("apply", "advance_apply", "116", D2, invoice_id="sample-sale"),
            entry("balance-payment", "buyer_receipt", "64", D2, invoice_id="sample-sale")], advance_terms=TERMS)
        self.assertEqual(result.days[0].cash, 43)
        self.assertEqual(result.days[0].earned_revenue, 0)
        self.assertEqual(result.days[0].unearned_advance_liabilities, 135)
        self.assertEqual(result.days[-1].cash, 88)
        self.assertEqual(result.days[-1].earned_revenue - result.days[-1].recognized_expense, 88)
        self.assertTrue(all(not balances for balances in result.unresolved_balances.values()))
        self.assertFalse(result.accounting_extension["legal_terms_verified"])

    def test_unearned_tail_is_not_profit_even_when_cash_is_available(self):
        result = book([entry("fund", "buyer_advance", "41")], advance_terms=TERMS)
        self.assertEqual(result.days[-1].cash, 41)
        self.assertEqual(result.days[-1].earned_revenue, 0)
        self.assertEqual(result.unresolved_balances["advances"], {"sample-advance": Decimal("41")})

    def test_carried_advance_liability_does_not_recreate_opening_cash(self):
        result = book([entry("refund", "advance_refund", "31")], opening_cash="38",
            opening_advances={"sample-advance": "31"}, advance_terms=TERMS)
        self.assertEqual(result.days[-1].cash, 7)
        self.assertFalse(result.unresolved_balances["advances"])

    def test_refund_after_spending_requires_real_additional_cash(self):
        result = book([entry("fund", "buyer_advance", "41"), entry("spend", "other_outflow", "36"),
                       entry("refund", "advance_refund", "41", D2)], advance_terms=TERMS)
        self.assertEqual(result.required_extra_cash, 36)
        self.assertEqual(result.minimum_free_cash_date, D2)

    def test_basis_and_operating_refund_assertions_are_not_inferred(self):
        with self.assertRaises(ValueError):
            book([entry("fund", "buyer_advance", "41")])
        for flag in (None, False, "yes", 1):
            terms = {"sample-advance": {**TERMS["sample-advance"], "usable_for_operations": flag}}
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                book([entry("fund", "buyer_advance", "41")], advance_terms=terms)
        with self.assertRaises(ValueError):
            book([entry("fund", "buyer_advance", "41", basis_ref="different-contract")], advance_terms=TERMS)

    def test_advance_application_requires_recognized_unpaid_invoice_capacity(self):
        with self.assertRaises(ValueError):
            book([entry("fund", "buyer_advance", "41"),
                  entry("invoice", "buyer_invoice", "41", invoice_id="sample-sale"),
                  entry("apply", "advance_apply", "41", invoice_id="sample-sale")], advance_terms=TERMS)

    def test_nonpayment_loss_removes_receivable_without_inventing_cash(self):
        result = book([entry("invoice", "buyer_invoice", "155", invoice_id="sample-sale"),
            entry("earn", "revenue", "155", invoice_id="sample-sale"),
            entry("payment", "buyer_receipt", "111", invoice_id="sample-sale"),
            entry("loss", "receivable_writeoff", "44", D2, invoice_id="sample-sale")])
        self.assertEqual(result.days[-1].cash, 111)
        self.assertEqual(result.days[-1].earned_revenue, 155)
        self.assertEqual(result.days[-1].recognized_expense, 44)
        self.assertEqual(result.days[-1].noncash_receivable_losses, 44)
        self.assertFalse(result.unresolved_balances["receivables"])

    def test_receipts_before_or_after_recognition_leave_only_unpaid_earned_capacity(self):
        for receipt_first in (False, True):
            invoice = entry("invoice", "buyer_invoice", "83", invoice_id="sample-sale")
            revenue = entry("earn", "revenue", "83", invoice_id="sample-sale")
            receipt = entry("payment", "buyer_receipt", "57", invoice_id="sample-sale")
            events = [invoice, receipt, revenue] if receipt_first else [invoice, revenue, receipt]
            result = book([*events, entry("loss", "receivable_writeoff", "26", invoice_id="sample-sale")])
            self.assertEqual(result.days[-1].earned_revenue - result.days[-1].recognized_expense, 57)
            with self.subTest(receipt_first=receipt_first), self.assertRaises(ValueError):
                book([*events, entry("loss", "receivable_writeoff", "27", invoice_id="sample-sale")])

    def test_paid_recognition_is_not_available_for_another_deposit_release(self):
        with self.assertRaises(ValueError):
            book([entry("invoice", "buyer_invoice", "83", invoice_id="sample-sale"),
                  entry("earn", "revenue", "57", invoice_id="sample-sale"),
                  entry("payment", "buyer_receipt", "57", invoice_id="sample-sale"),
                  entry("deposit", "buyer_deposit", "26", advance_account="restricted-sample"),
                  entry("apply", "deposit_apply", "26", invoice_id="sample-sale", advance_account="restricted-sample")])

    def test_mixed_credit_components_reconcile_net_service_recognition_without_cash(self):
        result = book([entry("invoice", "buyer_invoice", "88", invoice_id="sample-sale"),
            entry("earn-one", "revenue", "59", invoice_id="sample-sale"),
            entry("receipt-one", "buyer_receipt", "17", invoice_id="sample-sale"),
            entry("credit", "buyer_credit_note", "23", invoice_id="sample-sale", revenue_reversal_amount="5"),
            entry("earn-two", "revenue", "11", invoice_id="sample-sale"),
            entry("receipt-two", "buyer_receipt", "48", invoice_id="sample-sale")])
        self.assertEqual(result.days[-1].earned_revenue, 65)
        self.assertEqual(result.days[-1].cash, 65)
        self.assertEqual(result.days[-1].credit_note_amount, 23)
        self.assertEqual(result.days[-1].revenue_reversals, 5)
        self.assertEqual(result.days[-1].recognized_expense, 0)

    def test_credit_reversal_cannot_erase_paid_earnings_and_zero_still_needs_invoice(self):
        for invoice, reversal in (("missing-sale", "0"), ("sample-sale", "11")):
            base = [] if invoice == "missing-sale" else [entry("invoice", "buyer_invoice", "38", invoice_id=invoice),
                entry("earn", "revenue", "11", invoice_id=invoice), entry("payment", "buyer_receipt", "11", invoice_id=invoice)]
            with self.subTest(invoice=invoice), self.assertRaises(ValueError):
                book([*base, entry("credit", "buyer_credit_note", "11", invoice_id=invoice, revenue_reversal_amount=reversal)])

    def test_forfeit_releases_segregated_cash_as_separate_nonservice_income(self):
        result = book([entry("deposit", "buyer_deposit", "37", advance_account="restricted-sample"),
            entry("forfeit", "deposit_forfeit", "11", advance_account="restricted-sample"),
            entry("refund", "deposit_refund", "26", advance_account="restricted-sample")])
        self.assertEqual(result.days[-1].cash, 11)
        self.assertEqual(result.days[-1].earned_revenue, 0)
        self.assertEqual(result.days[-1].forfeiture_income, 11)
        self.assertEqual(result.days[-1].restricted_deposits, 0)

    def test_opening_recognized_claim_credit_is_net_flow_not_historical_revenue(self):
        result = book([entry("credit", "buyer_credit_note", "7", invoice_id="carried-sale", revenue_reversal_amount="7")],
            opening_receivables={"carried-sale": "19"}, opening_earned_for_release={"carried-sale": "19"})
        self.assertEqual(result.days[-1].earned_revenue, -7)
        self.assertEqual(result.days[-1].buyer_receivables, 12)
        self.assertEqual(result.days[-1].cash, 0)

    def test_legacy_serialization_and_maximum_calendar_tail_remain_supported(self):
        old = book().to_dict()
        self.assertNotIn("accounting_extension", old)
        self.assertNotIn("unearned_advance_liabilities", old["days"][0])
        terminal = book(start_date="9999-12-31", end_date="9999-12-31", opening_cash="13")
        self.assertEqual((len(terminal.days), terminal.days[0].cash), (1, Decimal("13")))

    def test_json_envelope_admits_explicit_new_terms_without_accepting_verification_flags(self):
        packet = {"events": [vars(entry("fund", "buyer_advance", "16.75"))],
            "legal_entity_id": "sample-operator", "cash_account_id": "sample-cash-account",
            "currency": "EUR", "opening_cash": "0", "start_date": D1, "end_date": D2, "advance_terms": TERMS}
        output = evaluate_cash_payload(packet).to_dict()
        self.assertEqual(output["days"][-1]["unearned_advance_liabilities"], "16.75")
        self.assertFalse(output["accounting_extension"]["actual_settlement_verified"])
        with self.assertRaises(ValueError):
            evaluate_cash_payload({**packet, "legal_terms_verified": True})

    def test_exact_advances_refund_conserve_cash_under_short_decimal_context(self):
        large, tiny = "987654321098765432109876543210", "0.0000000000000000000000000000000000000019"
        with localcontext() as context:
            context.prec = 2
            result = book([entry("fund", "buyer_advance", tiny), entry("refund", "advance_refund", tiny)],
                          opening_cash=large, advance_terms=TERMS)
        self.assertEqual(result.days[-1].cash, Decimal(large))
        self.assertFalse(result.unresolved_balances["advances"])

    def test_calendar_preceding_uses_explicit_holidays_and_never_modified_rule(self):
        self.assertEqual(invoice_due_date("2055-09-04", net_days=0, settlement_lag_days=0,
                                         weekend_adjustment="preceding", holidays=("2055-09-04",)), "2055-09-03")
        with self.assertRaises(ValueError):
            invoice_due_date("2055-09-04", net_days=0, settlement_lag_days=0, weekend_adjustment="modified_preceding")


class NativeInverseFundingTests(unittest.TestCase):
    def test_full_invoice_nonpayment_and_advance_are_reconciled_before_inverse_funding(self):
        def row(name, kind, amount, day, **extra):
            return {"event_id": name, "obligation_id": "example-leg-" + name, "kind": kind, "amount": amount,
                    "currency": "EUR", "on": "2057-03-" + day, **extra}
        events = [row("fund", "buyer_advance", "52", "01", advance_account="example-advance", basis_ref="example-basis"),
            row("supply-invoice", "supplier_invoice", "0", "01", invoice_id="example-supplier"),
            row("supply-payment", "supplier_payment", "0", "01", invoice_id="example-supplier"),
            row("invoice", "buyer_invoice", "130", "02", invoice_id="example-sale"),
            row("recognition", "revenue", "130", "02", invoice_id="example-sale"),
            row("apply", "advance_apply", "52", "02", invoice_id="example-sale", advance_account="example-advance", basis_ref="example-basis"),
            row("receipt", "buyer_receipt", "52", "02", invoice_id="example-sale"),
            row("loss", "receivable_writeoff", "26", "02", invoice_id="example-sale", basis_ref="example-loss")]
        template = {"minimum_cash": "0", "purchase_coefficients": {"supply-invoice": "5", "supply-payment": "5"},
            "deal_event_ids": [item["event_id"] for item in events], "schedule": {
                "events": events, "legal_entity_id": "example-operator", "cash_account_id": "example-account",
                "currency": "EUR", "opening_cash": "18", "start_date": "2057-03-01", "end_date": "2057-03-02",
                "advance_terms": {"example-advance": {"buyer_entity_id": "example-buyer", "basis_ref": "example-basis",
                    "usable_for_operations": True, "refund_terms_ref": "example-refunds"}}}}
        result = cash_price_limit(template, currency="EUR", as_of="2057-03-01T00:00:00Z",
            delivery_end="2057-03-02T00:00:00Z", maximum=Decimal(80), tick=Decimal(1),
            expected_purchase_coefficient=Decimal(5), expected_fixed_outflows=Decimal(0),
            expected_collections=Decimal(104), expected_billings=Decimal(130), supplied_ask=Decimal(9))
        self.assertEqual(result["maximum_purchase_tick"], "14")
        last = result["selected_schedule"]["days"][-1]
        self.assertEqual(last["cash"], "52")
        self.assertEqual(last["noncash_receivable_losses"], "26")
        self.assertFalse(result["selected_schedule"]["unresolved_balances"]["advances"])
        self.assertEqual(result["model"], "full-ledger-monotone-tick/1.0.2")


if __name__ == "__main__":
    unittest.main()
