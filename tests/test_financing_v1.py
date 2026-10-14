"""Independent borrowing-base, collection, waterfall and weighted-tail checks."""

from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
import sys
import unittest
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compute_pricing.control.financing import (BorrowingFacility, BorrowingPolicy, Collection, Pledge, Receivable,
    ReceivableExclusion, WaterfallPolicy, evaluate_borrowing_base, evaluate_financing_payload, evaluate_waterfall)
from compute_pricing.control.risk import CashScenario, Exposure, LossComponent, evaluate_portfolio_tail_risk
from compute_pricing.control.treasury import CashEvent


def receivable(key="invoice-a", amount="100", debtor="debtor-a", group="group-a", **kwargs):
    values = dict(economic_id=key, legal_entity_id="operator-a", currency="USD", debtor_entity_id=debtor,
        debtor_group_id=group, outstanding_amount=amount, issue_date="2024-01-01", due_date="2024-01-03",
        evidence_expiry_date="2025-01-01", acceptance_confirmed=True, acceptance_date="2024-01-01",
        assignability_verified=True, acceptance_evidence_id=f"accept-{key}", eligibility_evidence_id=f"eligible-{key}",
        legal_evidence_id=f"legal-{key}", ownership_evidence_id=f"own-{key}", exclusions=())
    values.update(kwargs)
    return Receivable(**values)


def facility(**kwargs):
    values = dict(facility_id="facility-a", legal_entity_id="operator-a", collection_account_id="lockbox-a", currency="USD", committed_limit="200",
        outstanding_principal="50", accrued_interest="0", annual_rate="0", day_count="ACT/365F",
        available_from="2024-01-01", maturity_date="2024-01-03")
    values.update(kwargs)
    return BorrowingFacility(**values)


def policy(**kwargs):
    values = dict(policy_version="policy-a", advance_rate="0.8", haircut="0.1", maximum_debtor_fraction="1",
        maximum_group_fraction="1", concentration_denominator="pre_concentration_eligible", reserve_amount="5",
        maximum_overdue_days=0, maximum_age_days=90)
    values.update(kwargs)
    return BorrowingPolicy(**values)


def base(rows, **kwargs):
    defaults = dict(pledges=(), facility=facility(), policy=policy(), as_of="2024-01-01", pledge_registry_evidence_id="registry-a")
    defaults.update(kwargs)
    return evaluate_borrowing_base(rows, **defaults)


class FinancingTests(unittest.TestCase):
    def test_explicit_haircut_advance_reserve_commitment_and_undrawn(self):
        report = base([receivable()])
        # 100 * (1 - .1) * .8 - 5 = 67; already drawn 50 leaves 17.
        self.assertEqual(report.borrowing_base, 67)
        self.assertEqual(report.drawable_undrawn, 17)
        self.assertEqual(report.principal_deficiency, 0)
        capped = base([receivable()], facility=facility(committed_limit="60"))
        self.assertEqual(capped.current_credit_limit, 60)
        self.assertEqual(capped.drawable_undrawn, 10)
        self.assertFalse(report.execution_eligible)

    def test_acceptance_legal_eligibility_and_registry_missing_fail_closed(self):
        for row in (receivable(acceptance_confirmed=False), receivable(acceptance_evidence_id=None),
                    receivable(assignability_verified=False), receivable(legal_evidence_id=None),
                    receivable(eligibility_evidence_id=None), receivable(ownership_evidence_id=None),
                    receivable(acceptance_date="2024-01-02")):
            result = base([row])
            self.assertEqual(result.borrowing_base, 0)
            self.assertEqual(result.principal_deficiency, 50)
        self.assertEqual(base([receivable()], pledge_registry_evidence_id=None).borrowing_base, 0)

    def test_dispute_dilution_are_disjoint_and_not_haircut_twice(self):
        exclusions = (ReceivableExclusion("dispute-a", "dispute-loss-a", "dispute", "20"),
                      ReceivableExclusion("dilution-a", "dilution-loss-a", "dilution", "10"))
        report = base([receivable(exclusions=exclusions)], policy=policy(advance_rate="1", haircut="0", reserve_amount="0"))
        self.assertEqual(report.eligible_before_concentration, 70)
        self.assertEqual(report.borrowing_base, 70)
        with self.assertRaisesRegex(ValueError, "ownership"):
            receivable(exclusions=(exclusions[0], ReceivableExclusion("renamed", "dispute-loss-a", "dilution", "20")))
        with self.assertRaisesRegex(ValueError, "exceed"):
            receivable(exclusions=(ReceivableExclusion("large", "large-loss", "dispute", "101"),))

    def test_economic_invoice_cannot_be_double_pledged_even_renamed_facility(self):
        with self.assertRaisesRegex(ValueError, "pledged twice"):
            base([receivable()], pledges=(Pledge("invoice-a", "facility-a", "pledge-a"), Pledge("invoice-a", "facility-b", "pledge-b")))
        result = base([receivable()], pledges=(Pledge("invoice-a", "facility-b", "pledge-b"),))
        self.assertIn("pledged_to_other_facility", result.exclusions["invoice-a"])
        with self.assertRaisesRegex(ValueError, "unique"):
            base([receivable(), receivable()])

    def test_age_expiry_overdue_currency_and_maturity_are_explicit(self):
        self.assertEqual(base([receivable(evidence_expiry_date="2024-01-02")], as_of="2024-01-02").borrowing_base, 0)
        self.assertEqual(base([receivable()], as_of="2024-01-04").drawable_undrawn, 0)
        self.assertEqual(base([receivable()], as_of="2024-01-03").maturity_call, 50)
        with self.assertRaisesRegex(ValueError, "currency"):
            base([receivable(currency="EUR")])
        with self.assertRaises(ValueError):
            policy(advance_rate="1.01")
        with self.assertRaises(ValueError):
            policy(maximum_overdue_days=True)

    def test_debtor_and_group_concentration_use_declared_denominator(self):
        rows = [receivable("invoice-a", "150", "debtor-a", "group-a"), receivable("invoice-b", "50", "debtor-b", "group-b")]
        report = base(rows, policy=policy(advance_rate="1", haircut="0", reserve_amount="0", maximum_debtor_fraction="0.5", maximum_group_fraction="0.5"))
        self.assertEqual(report.eligible_before_concentration, 200)
        self.assertEqual(report.eligible_after_concentration, 150)
        self.assertEqual(report.concentration_excess, 50)
        grouped = base([rows[0], replace(rows[1], debtor_group_id="group-a")], policy=policy(advance_rate="1", haircut="0", reserve_amount="0", maximum_debtor_fraction="0.5", maximum_group_fraction="0.5"))
        self.assertEqual(grouped.eligible_after_concentration, 100)

    def waterfall(self, collections, **kwargs):
        values = dict(receivables=(receivable(),), pledges=(Pledge("invoice-a", "facility-a", "pledge-a"),),
            facility=facility(), policy=WaterfallPolicy("waterfall-a", "10", ("reserve", "interest", "principal", "residual")),
            collections=collections, opening_cash="0", start_date="2024-01-01", end_date="2024-01-03", as_of="2024-01-03", mode="forecast", pledge_registry_evidence_id="registry-a")
        values.update(kwargs)
        return evaluate_waterfall(**values)

    def collection(self, key="collection-a", amount="100", on="2024-01-02", status="scheduled"):
        return Collection(key, f"leg-{key}", "invoice-a", on, "operator-a", "lockbox-a", "USD", amount, status, f"evidence-{key}")

    def test_waterfall_collection_pays_interest_principal_and_reserve_once(self):
        report = self.waterfall((self.collection(),), facility=facility(outstanding_principal="60", accrued_interest="5"))
        day = report.days[1]
        self.assertEqual((day.reserve_held, day.interest_paid, day.principal_paid, day.residual_distributed), (10, 5, 60, 25))
        self.assertEqual(report.ending_principal, 0)
        self.assertEqual(report.uncollected_receivables, {})
        self.assertTrue(report.scheduled_cash_assumed)
        self.assertFalse(report.execution_eligible)

    def test_scheduled_receipt_is_not_cleared_bank_cash_and_missing_cash_calls(self):
        report = self.waterfall((self.collection(),), mode="cleared_only")
        self.assertEqual(report.ending_principal, 50)
        self.assertEqual(report.maximum_maturity_shortfall, 50)
        self.assertEqual(report.final_reserve_shortfall, 10)
        self.assertEqual(report.uncollected_receivables, {"invoice-a": Decimal("100")})
        with self.assertRaisesRegex(ValueError, "future collection"):
            self.waterfall((self.collection(status="cleared"),), as_of="2024-01-01")

    def test_collection_duplicates_overcollection_and_tail_omission_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.waterfall((self.collection(), self.collection()))
        with self.assertRaisesRegex(ValueError, "exceeds unpaid"):
            self.waterfall((self.collection(amount="101"),))
        with self.assertRaisesRegex(ValueError, "horizon"):
            self.waterfall((), end_date="2024-01-02")
        with self.assertRaisesRegex(ValueError, "legal/acceptance"):
            self.waterfall((), receivables=(receivable(eligibility_evidence_id=None),))
        with self.assertRaisesRegex(ValueError, "account"):
            self.waterfall((replace(self.collection(), cash_account_id="inaccessible-bank"),))

    def test_waterfall_actual_days_accrue_interest_before_late_collection(self):
        # 50 principal at 36.5% ACT/365F produces exactly .05/day on day 1.
        report = self.waterfall((self.collection(amount="60"),), facility=facility(annual_rate="0.365"),
            policy=WaterfallPolicy("waterfall-a", "0", ("interest", "principal", "reserve", "residual")))
        self.assertEqual(report.days[1].interest_paid, Decimal("0.05"))
        self.assertEqual(report.days[1].principal_paid, 50)
        self.assertEqual(report.days[1].residual_distributed, Decimal("9.95"))

    def test_json_adapter_returns_versioned_exact_values_and_rejects_unknown_fields(self):
        packet = json.loads(json.dumps(dict(operation="borrowing_base", receivables=[asdict(receivable())], pledges=[],
            facility=asdict(facility()), policy=asdict(policy()), as_of="2024-01-01", pledge_registry_evidence_id="registry-a")))
        result = evaluate_financing_payload(packet)
        self.assertEqual(result["model_version"], "receivable-financing-v1")
        self.assertEqual(result["borrowing_base"], "67.00")
        self.assertFalse(result["execution_eligible"])
        with self.assertRaisesRegex(ValueError, "unregistered"):
            evaluate_financing_payload({**packet, "automatic_loan_draw": True})
        with self.assertRaises(ValueError):
            evaluate_financing_payload({**packet, "facility": {**packet["facility"], "committed_limit": 200.0}})
        waterfall = {**packet, "operation": "waterfall", "policy": asdict(WaterfallPolicy("waterfall-a", "10", ("reserve", "interest", "principal", "residual"))),
            "pledges": [asdict(Pledge("invoice-a", "facility-a", "pledge-a"))], "collections": [asdict(self.collection())],
            "opening_cash": "0", "start_date": "2024-01-01", "end_date": "2024-01-03", "mode": "forecast"}
        result = evaluate_financing_payload(json.loads(json.dumps(waterfall)))
        self.assertEqual(result["ending_principal"], "0")
        self.assertTrue(result["scheduled_cash_assumed"])


class TailRiskTests(unittest.TestCase):
    def scenario(self, key, probability, loss):
        events = () if loss == "0" else (CashEvent(f"cash-{key}", f"loss-leg-{key}", "2024-01-01", "other_outflow", loss, "USD"),)
        losses = () if loss == "0" else (LossComponent(f"loss-{key}", "common-loss-component", "operating", "USD", loss, (f"cash-{key}",)),)
        return CashScenario(key, events, losses, probability)

    def assess(self, scenarios, confidence="0.90", **kwargs):
        values = dict(confidence=confidence, distribution_evidence_id="supplied-distribution-a", legal_entity_id="operator-a", cash_account_id="bank-a", currency="USD", opening_cash="100", start_date="2024-01-01", end_date="2024-01-02")
        values.update(kwargs)
        return evaluate_portfolio_tail_risk(scenarios, [Exposure("position-a", "debtor-a", "group-a", "site-a", "USD", "100")], **values)

    def test_discrete_weighted_var_es_includes_fractional_boundary(self):
        paths = [self.scenario("zero", "0.8", "0"), self.scenario("medium", "0.15", "40"), self.scenario("high", "0.05", "100")]
        report = self.assess(paths)
        self.assertEqual(report.expected_loss, 11)
        self.assertEqual(report.value_at_risk, 40)
        # Top 10% contains 5% at 100 and only 5% of the 15% atom at 40.
        self.assertEqual(report.expected_shortfall, 70)
        self.assertEqual(report.worst_loss, 100)
        self.assertFalse(report.calibration_verified)
        self.assertFalse(report.execution_eligible)

    def test_exact_cdf_boundary_zero_probability_and_single_atom(self):
        paths = [self.scenario("zero", "0.9", "0"), self.scenario("high", "0.1", "100"), self.scenario("unused", "0", "9999")]
        report = self.assess(paths)
        self.assertEqual(report.value_at_risk, 0)
        self.assertEqual(report.expected_shortfall, 100)
        self.assertEqual(report.worst_loss, 100)
        atom = self.assess([self.scenario("one", "1", "7")], confidence="0.99")
        self.assertEqual((atom.expected_loss, atom.value_at_risk, atom.expected_shortfall), (7, 7, 7))

    def test_incomplete_weights_confidence_currency_and_overlapping_losses_reject(self):
        with self.assertRaisesRegex(ValueError, "normalized"):
            self.assess([CashScenario("missing", ())])
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.assess([self.scenario("a", "0.5", "1")])
        with self.assertRaises(ValueError):
            self.assess([self.scenario("a", "1", "1")], confidence="1")
        with self.assertRaisesRegex(ValueError, "currencies"):
            self.assess([CashScenario("eur", (), (LossComponent("eur-loss", "eur-owner", "operating", "EUR", "1", ()),), "1")])
        original = self.scenario("a", "1", "1")
        with self.assertRaisesRegex(ValueError, "ownership"):
            CashScenario("overlap", original.events, (*original.losses, LossComponent("renamed", "common-loss-component", "refund", "USD", "1", ())), "1")


if __name__ == "__main__":
    unittest.main()
