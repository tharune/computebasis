"""Fresh invented offline scenarios for bounded, nonexecuting local persistence."""
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.execution import Actor, DecisionSnapshot, DurablePaperRepository, PaperRepositoryError, actor_payload
from compute_pricing.control.execution import repository as module

INSTANT = "2038-04-06T09:00:00Z"
SUBMITTED = "2038-04-06T09:05:00Z"
EXPIRY = "2038-04-06T10:00:00Z"
VERSIONS = {"schema": "demo-schema-7", "policy": "demo-policy-7", "model": "demo-model-7", "data": "demo-input-7"}


def decision():
    return DecisionSnapshot.create(proposer_id="actor:originator", as_of=INSTANT,
        expires_at=EXPIRY, amount="84.875", currency="EUR", versions=VERSIONS,
        economic_inputs={"case": "invented-public-paper-fixture", "opening_cash": "200.125",
                         "units": ["unit:alpha", "unit:beta"], "cash_capacity_review": "assertion:invented"}).to_dict()


def approver(identity, role, *, limit="90", currency="EUR"):
    return actor_payload(Actor(identity, (role,), currency, limit))


class DurablePaperV7Tests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "paper.sqlite"
        self.store = DurablePaperRepository(self.path)
        self.counter = 0

    def tearDown(self):
        self.directory.cleanup()

    def apply(self, operation, payload, *, intent="intent:alpha", revision=None, command=None, store=None):
        repository = store or self.store
        self.counter += 1
        if revision is None:
            revision = 0 if operation == "create" else repository.get(intent)["revision"]
        return repository.apply(command_id=command or "command:" + str(self.counter), intent_id=intent,
                                operation=operation, payload=payload, expected_revision=revision)

    def approved(self, *, intent="intent:alpha", holds=None):
        self.apply("create", {"snapshot": decision()}, intent=intent)
        self.apply("hold", {"hold_ids": holds or ["hold:cash", "hold:capacity"]}, intent=intent)
        for actor, role in (("actor:credit", "risk_approver"), ("actor:funding", "treasury_approver")):
            self.apply("approve", {"actor": approver(actor, role), "role": role, "now": INSTANT,
                "expires_at": EXPIRY, "active_versions": VERSIONS}, intent=intent)

    def submitted(self):
        self.approved()
        return self.apply("submit_paper", {"leg_ids": ["leg:resource", "leg:collection"],
                          "now": SUBMITTED, "active_versions": VERSIONS})

    def reconciliation(self, outcomes, *, release=None, actor="actor:audit", limit="90", currency="EUR"):
        return {"outcomes": outcomes, "actor": approver(actor, "reconciler", limit=limit, currency=currency),
                "evidence_id": "evidence:invented-audit", "now": SUBMITTED, "release_hold_ids": release or []}

    def test_restart_returns_original_acknowledgement_without_reapplying_old_command(self):
        request = {"snapshot": decision()}
        first = self.apply("create", request, command="command:first")
        self.apply("hold", {"hold_ids": ["hold:cash"]})
        restarted = DurablePaperRepository(self.path)
        repeated = self.apply("create", request, command="command:first", revision=0, store=restarted)
        self.assertEqual(repeated, first)
        self.assertEqual(repeated["revision"], 1)
        self.assertEqual(restarted.get("intent:alpha")["revision"], 2)
        self.assertEqual(restarted.audit()["command_count"], 2)
        self.assertFalse(repeated["execution_enabled"])
        amended = copy.deepcopy(request); amended["snapshot"]["amount"] = "84.876"
        with self.assertRaisesRegex(PaperRepositoryError, "idempotency_conflict"):
            self.apply("create", amended, command="command:first", revision=0, store=restarted)

    def test_separate_instances_cannot_acquire_the_same_canonical_resource(self):
        self.apply("create", {"snapshot": decision()}, intent="intent:alpha")
        self.apply("create", {"snapshot": decision()}, intent="intent:beta")
        other = DurablePaperRepository(self.path)
        def acquire(identity):
            try:
                (self.store if identity == "alpha" else other).apply(command_id="race:" + identity,
                    intent_id="intent:" + identity, operation="hold", payload={"hold_ids": ["hold:one-unit"]}, expected_revision=1)
                return True
            except PaperRepositoryError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            winners = list(executor.map(acquire, ("alpha", "beta")))
        self.assertEqual(sum(winners), 1)
        self.assertEqual(self.store.audit()["command_count"], 3)

    def test_stale_revision_independent_authority_and_expiry_cannot_make_outbox_items(self):
        self.apply("create", {"snapshot": decision()})
        with self.assertRaisesRegex(PaperRepositoryError, "revision_conflict"):
            self.apply("hold", {"hold_ids": ["hold:cash"]}, revision=0)
        self.apply("hold", {"hold_ids": ["hold:cash"]})
        for actor in (approver("actor:originator", "risk_approver"), approver("actor:low", "risk_approver", limit="84.874"),
                      approver("actor:wrong-currency", "risk_approver", currency="USD")):
            with self.assertRaises(PaperRepositoryError):
                self.apply("approve", {"actor": actor, "role": "risk_approver", "now": INSTANT,
                    "expires_at": EXPIRY, "active_versions": VERSIONS})
        self.assertEqual(self.store.audit()["command_count"], 2)
        for actor, role in (("actor:credit", "risk_approver"), ("actor:funding", "treasury_approver")):
            self.apply("approve", {"actor": approver(actor, role), "role": role, "now": INSTANT,
                "expires_at": EXPIRY, "active_versions": VERSIONS})
        for now, versions in ((EXPIRY, VERSIONS), (SUBMITTED, {**VERSIONS, "policy": "demo-policy-successor"})):
            with self.assertRaises(PaperRepositoryError):
                self.apply("submit_paper", {"leg_ids": ["leg:one"], "now": now, "active_versions": versions})
        self.assertEqual(self.store.audit()["command_count"], 4)
        self.assertEqual(self.store.pending_outbox()["items"], [])

    def test_submission_is_atomic_deterministic_and_bounded_without_dispatch(self):
        submitted = self.submitted()
        current = DurablePaperRepository(self.path).pending_outbox(limit=1)
        self.assertEqual(len(current["items"]), 1)
        self.assertEqual(current["total_pending_or_unknown"], 2)
        self.assertTrue(current["truncated"])
        self.assertFalse(current["dispatch_supported"])
        self.assertFalse(current["execution_enabled"])
        self.assertEqual(current["items"][0]["snapshot_hash"], submitted["intent"]["snapshot_hash"])
        self.assertTrue(current["items"][0]["paper_only"])
        for limit in (0, 101, True, "1"):
            with self.assertRaisesRegex(PaperRepositoryError, "limit_invalid"):
                self.store.pending_outbox(limit=limit)

    def test_unknown_survives_restart_and_reconciliation_releases_only_known_owned_holds(self):
        self.submitted()
        self.apply("mark_unknown", {"leg_id": "leg:resource"})
        self.store = DurablePaperRepository(self.path)
        self.assertEqual(self.store.get("intent:alpha")["intent"]["hold_ids"], ["hold:cash", "hold:capacity"])
        with self.assertRaises(PaperRepositoryError):
            self.apply("cancel", {"actor_id": "actor:originator", "reason_id": "reason:retry"})
        with self.assertRaises(PaperRepositoryError):
            self.apply("reconcile", self.reconciliation({"leg:resource": "unknown", "leg:collection": "failed"}, release=["hold:cash"]))
        with self.assertRaises(PaperRepositoryError):
            self.apply("reconcile", self.reconciliation({"leg:resource": "failed"}))
        with self.assertRaises(PaperRepositoryError):
            self.apply("reconcile", self.reconciliation({"leg:resource": "failed", "leg:collection": "failed"}, release=["hold:not-owned"]))
        reconciled = self.apply("reconcile", self.reconciliation({"leg:resource": "matched", "leg:collection": "failed"}, release=["hold:cash"]))
        self.assertEqual(reconciled["intent"]["hold_ids"], ["hold:capacity"])
        self.assertEqual(reconciled["intent"]["state"], "reconciled")
        self.assertEqual(self.store.pending_outbox()["items"], [])
        self.apply("create", {"snapshot": decision()}, intent="intent:beta")
        self.apply("hold", {"hold_ids": ["hold:cash"]}, intent="intent:beta")

    def test_independent_reconciler_must_have_currency_amount_and_known_outcomes_cannot_change(self):
        self.submitted()
        outcomes = {"leg:resource": "matched", "leg:collection": "unknown"}
        for actor, limit, currency in (("actor:credit", "90", "EUR"), ("actor:audit", "84", "EUR"), ("actor:audit", "90", "USD")):
            with self.assertRaises(PaperRepositoryError):
                self.apply("reconcile", self.reconciliation(outcomes, actor=actor, limit=limit, currency=currency))
        self.apply("reconcile", self.reconciliation(outcomes))
        with self.assertRaisesRegex(PaperRepositoryError, "known_outcome"):
            self.apply("reconcile", self.reconciliation({"leg:resource": "failed", "leg:collection": "failed"}))
        final = self.apply("reconcile", self.reconciliation({"leg:resource": "matched", "leg:collection": "failed"}))
        self.assertEqual(final["intent"]["state"], "reconciled")

    def test_exception_after_command_insertion_rolls_back_simulated_state_and_outbox(self):
        self.approved()
        original = module._outbox
        calls = []
        def fault(journal):
            calls.append(True)
            if len(calls) == 2:
                raise ValueError("invented persistence fault")
            return original(journal)
        with patch.object(module, "_outbox", side_effect=fault), self.assertRaises(PaperRepositoryError):
            self.apply("submit_paper", {"leg_ids": ["leg:resource"], "now": SUBMITTED, "active_versions": VERSIONS})
        restarted = DurablePaperRepository(self.path)
        self.assertEqual(restarted.audit()["command_count"], 4)
        self.assertEqual(restarted.get("intent:alpha")["intent"]["state"], "approved")
        self.assertEqual(restarted.pending_outbox()["items"], [])

    def test_append_only_triggers_and_outbox_drift_fail_recovery(self):
        self.submitted()
        with sqlite3.connect(self.path) as connection:
            for statement in ("UPDATE paper_commands SET receipt='{}'", "DELETE FROM paper_commands"):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "append_only"):
                    connection.execute(statement)
            connection.execute("UPDATE paper_outbox SET state='failed'")
        with self.assertRaisesRegex(PaperRepositoryError, "integrity_failed"):
            DurablePaperRepository(self.path)

    def test_path_permissions_exact_json_and_unknown_identity_fail_safely(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        with self.assertRaisesRegex(PaperRepositoryError, "unknown_intent"):
            self.store.get("intent:missing")
        with self.assertRaises(PaperRepositoryError):
            DurablePaperRepository(Path("relative.sqlite"))
        link = Path(self.directory.name) / "linked.sqlite"; link.symlink_to(self.path)
        with self.assertRaises(PaperRepositoryError):
            DurablePaperRepository(link)
        checkout = Path(self.directory.name) / "checkout"; (checkout / ".git").mkdir(parents=True)
        with self.assertRaises(PaperRepositoryError):
            DurablePaperRepository(checkout / "paper.sqlite")
        bad = decision(); bad["economic_inputs"]["price"] = 0.25
        with self.assertRaisesRegex(PaperRepositoryError, "exact_json"):
            self.apply("create", {"snapshot": bad})
        nested = {}; value = nested
        for _ in range(30):
            value["next"] = {}; value = value["next"]
        with self.assertRaisesRegex(PaperRepositoryError, "structure_limit"):
            self.apply("create", {"snapshot": nested})
        self.assertEqual(self.store.audit()["command_count"], 0)

    def test_pre_submission_cancellation_releases_only_its_resource_owner(self):
        self.approved()
        cancelled = self.apply("cancel", {"actor_id": "actor:originator", "reason_id": "reason:revised-input"})
        self.assertEqual(cancelled["intent"]["state"], "cancelled")
        self.assertEqual(cancelled["intent"]["hold_ids"], [])
        self.apply("create", {"snapshot": decision()}, intent="intent:beta")
        held = self.apply("hold", {"hold_ids": ["hold:cash", "hold:capacity"]}, intent="intent:beta")
        self.assertEqual(held["intent"]["state"], "held")


if __name__ == "__main__":
    unittest.main()
