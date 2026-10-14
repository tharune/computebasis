"""Distinct funding/loss measures and date-only gross exposure admission."""
from copy import deepcopy
from decimal import Decimal
import unittest
from compute_pricing.control.portfolio import evaluate_portfolio_payload
from compute_pricing.control.risk import CashScenario, Exposure, LossComponent, evaluate_portfolio_tail_risk
from compute_pricing.control.treasury import CashEvent
from test_portfolio_v7 import sample


class SettlementRiskBoundaries(unittest.TestCase):
    def test_refundable_advance_funding_is_separate_from_economic_loss(self):
        events = tuple(CashEvent(key, "obligation:"+key, day, kind, amount, "USD", **extra)
            for key, day, kind, amount, extra in (
                ("cash:received", "2054-08-03", "buyer_advance", "22", {"advance_account": "advance:one", "basis_ref": "basis:usable"}),
                ("cash:spent", "2054-08-03", "other_outflow", "22", {}),
                ("cash:returned", "2054-08-04", "advance_refund", "22", {"advance_account": "advance:one", "basis_ref": "basis:usable"})))
        declared = LossComponent("loss:asserted", "ownership:loss", "buyer_credit", "USD", "3", ("cash:returned",))
        scenario = CashScenario("scenario:refund", events, (declared,), probability="1")
        report = evaluate_portfolio_tail_risk((scenario,),
            (Exposure("exposure:one", "buyer:one", "group:one", "site:one", "USD", "22"),),
            confidence="0.9", distribution_evidence_id="distribution:declared", legal_entity_id="entity:operator",
            cash_account_id="cash:account", currency="USD", opening_cash="7", start_date="2054-08-03", end_date="2054-08-04",
            advance_terms={"advance:one": {"buyer_entity_id": "buyer:one", "basis_ref": "basis:usable",
                "usable_for_operations": True, "refund_terms_ref": "terms:refund"}})
        self.assertEqual(report.cash_stress.worst_required_extra_cash, Decimal(15))
        self.assertEqual(report.expected_shortfall, Decimal(3))
        self.assertFalse(report.calibration_verified)

    def test_daily_exposure_floor_cannot_be_reduced_by_reordering_same_day(self):
        request = sample()
        before = evaluate_portfolio_payload(request)
        changed = deepcopy(request)
        changed["cash"]["events"].sort(key=lambda event: (event["on"], event["kind"] == "prepaid_apply"))
        after = evaluate_portfolio_payload(changed)
        def amounts(packet):
            return {(row["scope"], row["member_id"], row["currency"]): row["floor_amount"]
                for row in packet["ledger_exposure_floor"]["scope_comparisons"]}
        self.assertEqual(amounts(before), amounts(after))
        self.assertEqual(before["cash"]["days"][-1]["cash"], after["cash"]["days"][-1]["cash"])


if __name__ == "__main__": unittest.main()
