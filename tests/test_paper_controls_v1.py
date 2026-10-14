"""Price/expiry/role binding, idempotent paper state and forward milestones."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compute_pricing.control.execution import Actor, DecisionSnapshot, PaperJournal, approve_snapshot
from compute_pricing.control.contracts import BankReceipt, ForwardEvidence, ForwardTerms, assess_forward_readiness
from compute_pricing.control.capacity import CapacityLot, Reservation
from compute_pricing.control.treasury import evaluate_cash_schedule


NOW = "2024-01-01T00:00:00Z"
LATER = "2024-01-01T00:10:00Z"
EXPIRY = "2024-01-01T01:00:00Z"
VERSIONS = {"schema": "1", "policy": "policy-a", "model": "model-a", "data": "data-a", "features": "features-a"}


def snapshot(**kwargs):
    values = dict(proposer_id="proposer-a", as_of=NOW, expires_at=EXPIRY, amount="100",
                  currency="USD", versions=VERSIONS, economic_inputs={"bid": "2.01", "cash_min": "30"})
    values.update(kwargs)
    return DecisionSnapshot.create(**values)


def actor(key, roles, limit="100"):
    return Actor(key, roles, "USD", limit)


def approved_journal():
    journal = PaperJournal()
    journal.create("intent-a", snapshot())
    journal.hold("intent-a", ("cash-hold-a", "capacity-hold-a"))
    journal.approve("intent-a", actor("risk-a", ("risk_approver",)), role="risk_approver", now=NOW, expires_at=EXPIRY, active_versions=VERSIONS)
    journal.approve("intent-a", actor("treasury-a", ("treasury_approver",)), role="treasury_approver", now=NOW, expires_at=EXPIRY, active_versions=VERSIONS)
    return journal


class PaperControlsTests(unittest.TestCase):
    def test_snapshot_detaches_nested_inputs_and_hashes_every_version(self):
        inputs, versions = {"cost": "1", "rows": [{"qty": 2}]}, dict(VERSIONS)
        original = snapshot(economic_inputs=inputs, versions=versions)
        inputs["rows"][0]["qty"] = 999
        versions["policy"] = "changed"
        exported = original.to_dict()
        exported["economic_inputs"]["rows"][0]["qty"] = 888
        self.assertEqual(original.to_dict()["economic_inputs"]["rows"][0]["qty"], 2)
        self.assertNotEqual(snapshot(economic_inputs={"cost": "1", "rows": [{"qty": 3}]}).snapshot_hash, original.snapshot_hash)
        with self.assertRaisesRegex(ValueError, "hash"):
            DecisionSnapshot(original.canonical_json, "0" * 64)
        with self.assertRaisesRegex(ValueError, "Decimal strings"):
            snapshot(economic_inputs={"bid": 1.2})

    def test_proposer_role_limit_currency_and_expiry_enforced(self):
        snap = snapshot()
        for invalid_actor, role in ((actor("proposer-a", ("risk_approver",)), "risk_approver"),
                                    (actor("low-limit", ("risk_approver",), "99.99"), "risk_approver"),
                                    (actor("wrong-role", ("proposer",)), "risk_approver")):
            with self.assertRaises(ValueError):
                approve_snapshot(snap, invalid_actor, role=role, now=NOW, expires_at=EXPIRY, active_versions=VERSIONS)
        with self.assertRaises(ValueError):
            approve_snapshot(snap, Actor("eur-a", ("risk_approver",), "EUR", "1000"), role="risk_approver", now=NOW, expires_at=EXPIRY, active_versions=VERSIONS)
        with self.assertRaisesRegex(ValueError, "expired"):
            snap.assert_current(now=EXPIRY, active_versions=VERSIONS)
        with self.assertRaisesRegex(ValueError, "stale"):
            snap.assert_current(now=NOW, active_versions={**VERSIONS, "features": "features-b"})

    def test_one_person_cannot_fill_both_approval_roles(self):
        journal = PaperJournal()
        journal.create("intent-a", snapshot())
        with self.assertRaisesRegex(ValueError, "hold"):
            journal.approve("intent-a", actor("risk-a", ("risk_approver",)), role="risk_approver", now=NOW, expires_at=EXPIRY, active_versions=VERSIONS)
        journal.hold("intent-a", ("hold-a",))
        both = actor("dual-role", ("risk_approver", "treasury_approver"))
        journal.approve("intent-a", both, role="risk_approver", now=NOW, expires_at=EXPIRY, active_versions=VERSIONS)
        with self.assertRaisesRegex(ValueError, "duplicate actor"):
            journal.approve("intent-a", both, role="treasury_approver", now=NOW, expires_at=EXPIRY, active_versions=VERSIONS)
        with self.assertRaises(ValueError):
            journal.submit_paper("intent-a", ("leg-a",), now=NOW, active_versions=VERSIONS)

    def test_price_and_policy_changes_invalidate_approval(self):
        journal = approved_journal()
        with self.assertRaisesRegex(ValueError, "different immutable"):
            journal.create("intent-a", snapshot(economic_inputs={"bid": "2.02"}))
        with self.assertRaisesRegex(ValueError, "stale"):
            journal.submit_paper("intent-a", ("leg-a",), now=LATER, active_versions={**VERSIONS, "policy": "policy-b"})
        with self.assertRaisesRegex(ValueError, "expired"):
            journal.submit_paper("intent-a", ("leg-a",), now=EXPIRY, active_versions=VERSIONS)

    def test_duplicate_submit_returns_original_and_never_mutates_legs(self):
        journal = approved_journal()
        first = journal.submit_paper("intent-a", ("leg-a", "leg-b"), now=LATER, active_versions=VERSIONS)
        self.assertEqual(journal.submit_paper("intent-a", ("leg-a", "leg-b"), now=EXPIRY, active_versions=VERSIONS), first)
        with self.assertRaisesRegex(ValueError, "mutate paper legs"):
            journal.submit_paper("intent-a", ("leg-new",), now=LATER, active_versions=VERSIONS)
        self.assertTrue(journal.to_dict()["paper_only"])
        self.assertFalse(journal.to_dict()["durable"])

    def test_unknown_failure_retains_holds_until_independent_full_reconciliation(self):
        journal = approved_journal()
        journal.submit_paper("intent-a", ("leg-a", "leg-b"), now=LATER, active_versions=VERSIONS)
        journal.mark_unknown("intent-a", "leg-a")
        with self.assertRaisesRegex(ValueError, "uncertain effects"):
            journal.cancel("intent-a", actor_id="proposer-a", reason_id="rollback-attempt")
        reconciler = actor("reconciler-a", ("reconciler",))
        with self.assertRaisesRegex(ValueError, "every paper leg"):
            journal.reconcile("intent-a", {"leg-a": "failed"}, reconciler, evidence_id="audit-a", now=LATER)
        with self.assertRaisesRegex(ValueError, "retain every hold"):
            journal.reconcile("intent-a", {"leg-a": "unknown", "leg-b": "failed"}, reconciler, evidence_id="audit-a", now=LATER, release_hold_ids=("cash-hold-a",))
        with self.assertRaisesRegex(ValueError, "independent"):
            journal.reconcile("intent-a", {"leg-a": "failed", "leg-b": "failed"}, actor("risk-a", ("reconciler",)), evidence_id="audit-a", now=LATER)
        confirmed = journal.reconcile("intent-a", {"leg-a": "matched", "leg-b": "failed"}, reconciler, evidence_id="audit-a", now=LATER)
        self.assertEqual(confirmed.state, "reconciled")
        self.assertEqual(confirmed.hold_ids, ("cash-hold-a", "capacity-hold-a"))
        self.assertEqual(confirmed.reconciler_id, "reconciler-a")

    def test_cancel_before_submission_releases_only_owned_holds(self):
        journal = approved_journal()
        result = journal.cancel("intent-a", actor_id="proposer-a", reason_id="terms-expired")
        self.assertEqual(result.state, "cancelled")
        journal.create("intent-b", snapshot())
        journal.hold("intent-b", ("cash-hold-a",))
        exported = journal.to_dict()
        self.assertEqual(exported["intents"][0]["cancellation_reason_id"], "terms-expired")
        json.dumps(exported, allow_nan=False)

    def test_concurrent_idempotency_and_hold_collision(self):
        journal = PaperJournal()
        with ThreadPoolExecutor(max_workers=8) as pool:
            created = list(pool.map(lambda _: journal.create("same-economic", snapshot()), range(32)))
        self.assertTrue(all(item == created[0] for item in created))
        journal.create("other-economic", snapshot())
        def acquire(key):
            try:
                journal.hold(key, ("same-canonical-resource-hold",))
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(acquire, ("same-economic", "other-economic")))
        self.assertEqual(sum(result), 1)
        self.assertEqual(len(journal.to_dict()["intents"]), 2)


class ForwardReadinessTests(unittest.TestCase):
    def setUp(self):
        self.terms = ForwardTerms("forward-a", "operator-a", "bank-a", "USD", "2024-01-31",
            "2024-07-31", "2024-10-31", "100", "lot-a", ("gpu-a",))
        self.receipt = BankReceipt("receipt-a", "bank-record-a", "2024-01-31", "operator-a", "bank-a", "USD", "100", "100", True)
        cash = evaluate_cash_schedule((), legal_entity_id="operator-a", cash_account_id="bank-a", currency="USD", opening_cash="100", start_date="2024-01-31", end_date="2024-11-10")
        lot = CapacityLot("lot-a", "site-a", "gpu", ("gpu-a",), "2024-07-31T00:00:00Z", "2024-10-31T00:00:00Z")
        reservation = Reservation("reservation-a", "forward-a", "lot-a", ("gpu-a",), lot.start_at, lot.end_at)
        self.evidence = ForwardEvidence(signature_evidence_id="signature-a", receipts=(self.receipt,), funding_evidence_id="verified-funding-a", cash_schedule=cash,
            capacity_evidence_id="capacity-ledger-a", capacity_lots=(lot,), reservations=(reservation,),
            enforceability_evidence_id="legal-opinion-a", delivery_readiness_evidence_id="readiness-a")

    def assess(self, evidence=None, as_of="2024-01-31"):
        return assess_forward_readiness(self.terms, evidence or self.evidence, as_of=as_of)

    def test_signing_lead_and_service_are_distinct_actual_calendar_intervals(self):
        result = self.assess()
        self.assertEqual(result.lead_days, 182)
        self.assertEqual(result.service_days, 92)
        self.assertEqual(result.state, "delivery_ready")
        self.assertFalse(result.execution_eligible)

    def test_signature_is_not_bank_cash_enforceability_or_delivery(self):
        self.assertEqual(self.assess(ForwardEvidence()).state, "draft")
        self.assertEqual(self.assess(ForwardEvidence(signature_evidence_id="signature-a")).state, "signature")
        uncleared = replace(self.receipt, cleared=False)
        self.assertEqual(self.assess(replace(self.evidence, receipts=(uncleared,))).state, "signature")
        self.assertEqual(self.assess(replace(self.evidence, enforceability_evidence_id=None)).state, "capacity_ready")
        self.assertEqual(self.assess(replace(self.evidence, funding_evidence_id=None)).state, "deposit_verified")

    def test_receipts_are_not_reused_and_refunds_reduce_required_coverage(self):
        with self.assertRaisesRegex(ValueError, "duplicate bank"):
            self.assess(replace(self.evidence, receipts=(self.receipt, self.receipt)))
        refunded = replace(self.receipt, net_unreversed_amount="20")
        self.assertEqual(self.assess(replace(self.evidence, receipts=(refunded,))).state, "signature")
        with self.assertRaisesRegex(ValueError, "different entity"):
            self.assess(replace(self.evidence, receipts=(replace(self.receipt, cash_account_id="inaccessible-bank"),)))
        with self.assertRaisesRegex(ValueError, "future bank"):
            self.assess(replace(self.evidence, receipts=(replace(self.receipt, settled_date="2024-02-01"),)))

    def test_capacity_gaps_block_forward_start_and_date_alone_does_not_complete(self):
        short = replace(self.evidence.reservations[0], end_at="2024-09-01T00:00:00Z")
        self.assertEqual(self.assess(replace(self.evidence, reservations=(short,))).state, "funding_ready")
        accepted = replace(self.evidence, delivery_acceptance_evidence_id="accepted-a", delivery_acceptance_date="2024-07-31")
        self.assertEqual(self.assess(accepted, as_of="2024-07-31").state, "active")
        self.assertEqual(self.assess(accepted, as_of="2024-11-01").state, "active")
        self.assertEqual(self.assess(replace(accepted, completion_reconciliation_evidence_id="final-a"), as_of="2024-11-01").state, "completed")
        final_refund = replace(accepted, receipts=(replace(self.receipt, net_unreversed_amount="0"),), completion_reconciliation_evidence_id="final-refund-a")
        self.assertEqual(self.assess(final_refund, as_of="2024-11-01").state, "completed")
        self.assertEqual(self.assess(replace(self.evidence, default_evidence_id="default-a")).state, "defaulted")


if __name__ == "__main__":
    unittest.main()
