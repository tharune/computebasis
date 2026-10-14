"""Pinned local policy previews and immutable simulation configuration revisions."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from fastapi.testclient import TestClient

from compute_pricing.control.api import create_app
from compute_pricing.control.api.book_policy import (
    BookPolicyCapacity, BookPolicyConflict, BookPolicyNotFound, book_policy_contract,
    evaluate_book_policy, read_book_policy, update_book_policy,
)
from compute_pricing.control.quote_book import QuoteBook


class BookPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.book = QuoteBook(clock=lambda: self.now)

    def candidate(self, *, version="1.1.0"):
        document = read_book_policy(self.book)["record"]["document"]
        document["version"] = version
        return {"expected_revision": self.book.read_policy()["current_revision"], "document": document}

    def test_resolved_contract_and_reads_are_detached_without_tick(self):
        original = self.book.snapshot()
        contract = book_policy_contract()
        self.assertFalse(contract["unknown_values_defaulted"])
        self.assertEqual(contract["storage"], "process_memory_only")
        self.now = 500
        state = read_book_policy(self.book)
        self.assertEqual(state["record"]["tick"], 0)
        self.assertEqual(state["current_revision"], 0)
        state["record"]["document"]["economics"]["deposit_apr"] = "0.99"
        self.assertEqual(read_book_policy(self.book)["record"]["document"]["economics"]["deposit_apr"], "0.085")
        self.now = 0
        self.assertEqual(self.book.snapshot(), original)
        with self.assertRaises(BookPolicyNotFound):
            read_book_policy(self.book, 99)

    def test_preview_changes_financing_without_mutating_prices_clock_rng_or_policy(self):
        payload = self.candidate(version="1.0.0")
        payload["document"]["economics"]["deposit_apr"] = "0.17"
        original = self.book.snapshot()
        tag = self.book.etag()
        self.now = 90
        preview = evaluate_book_policy(self.book, payload)
        self.assertEqual(preview["context"]["tick"], 0)
        self.assertGreater(preview["changed_quotes"], 0)
        financed = next(row for row in preview["quote_changes"] if row["before"]["financing"]
                        is not None and Decimal(row["before"]["financing"]) > 0)
        with localcontext() as context:
            context.prec = 200
            self.assertLess(abs(Decimal(financed["after"]["financing"]) -
                                2 * Decimal(financed["before"]["financing"])), Decimal("1e-40"))
        self.assertFalse(preview["book_changed"])
        self.assertFalse(preview["cost_models_combined"])
        self.now = 0
        self.assertEqual(self.book.etag(), tag)
        self.assertEqual(self.book.snapshot(), original)
        fresh = QuoteBook(clock=lambda: self.now)
        self.now = 3
        self.assertEqual(self.book.snapshot(), fresh.snapshot())

    def test_grade_premium_changes_only_the_alternative_scorecard_cost(self):
        payload = self.candidate()
        payload["document"]["scorecard"]["grade_premiums"]["A"] = "0.025"
        preview = evaluate_book_policy(self.book, payload)
        changed = next(row for row in preview["quote_changes"] if row["before"]["grade"] == "A"
                       and row["before"]["risk_adjusted_scorecard"] is not None)
        self.assertNotEqual(changed["before"]["risk_adjusted_scorecard"], changed["after"]["risk_adjusted_scorecard"])
        self.assertEqual(changed["before"]["risk_adjusted"], changed["after"]["risk_adjusted"])
        self.assertEqual(changed["delta"]["risk_adjusted"], "0")

    def test_failure_and_recovery_assumptions_reach_exposure_model(self):
        payload = self.candidate()
        payload["document"]["economics"]["annual_failure_probability"]["A"] = "0.031"
        payload["document"]["economics"]["recovery_fraction"] = "0.7"
        updated = update_book_policy(self.book, payload)
        self.assertTrue(updated["changed"])
        quote = next(row for row in self.book.snapshot()["quotes"] if row["grade"] == "A" and row["eligible"])
        self.assertEqual(quote["annual_failure_probability"], "0.031")
        self.assertEqual(quote["assumptions"]["recovery_fraction"], "0.7")
        self.assertFalse(quote["source_evidence_eligible"])

    def test_commit_exact_retry_cas_and_immutable_history(self):
        baseline = read_book_policy(self.book)["record"]
        payload = self.candidate()
        payload["document"]["economics"]["deposit_apr"] = "0.12"
        first = update_book_policy(self.book, payload)
        self.assertEqual(first["current_revision"], 1)
        self.assertEqual(first["record"]["predecessor_revision"], 0)
        payload["document"]["economics"]["deposit_apr"] = "0.99"
        self.assertEqual(read_book_policy(self.book, 0)["record"], baseline)
        retry = {"expected_revision": 0, "document": first["record"]["document"]}
        tag = self.book.etag()
        self.assertFalse(update_book_policy(self.book, retry)["changed"])
        self.assertEqual(self.book.etag(), tag)
        stale = self.candidate(version="1.2.0")
        stale["expected_revision"] = 0
        with self.assertRaises(BookPolicyConflict):
            update_book_policy(self.book, stale)
        self.assertEqual(len(read_book_policy(self.book)["history"]), 2)

    def test_policy_change_updates_etag_and_appends_same_time_revision_point(self):
        before = self.book.snapshot()
        tag = self.book.etag()
        payload = self.candidate()
        payload["document"]["economics"]["deposit_apr"] = "0.11"
        update_book_policy(self.book, payload)
        after = self.book.snapshot()
        self.assertNotEqual(tag, self.book.etag())
        self.assertEqual(after["meta"]["policy_revision"], 1)
        self.assertEqual(after["series"]["policy_revisions"], [0, 1])
        self.assertEqual(after["series"]["ticks"], [0, 0])
        self.assertEqual(after["series"]["times"][0], after["series"]["times"][1])
        self.assertEqual([row["price"] for row in before["quotes"]], [row["price"] for row in after["quotes"]])

    def test_reset_preserves_effective_policy_and_earlier_revisions(self):
        payload = self.candidate()
        payload["document"]["economics"]["deposit_apr"] = "0.13"
        update_book_policy(self.book, payload)
        self.now = 6
        self.book.snapshot()
        self.book.control("reset")
        after = self.book.snapshot()
        self.assertEqual(after["meta"]["tick"], 0)
        self.assertEqual(after["meta"]["policy_revision"], 1)
        self.assertEqual(after["series"]["policy_revisions"], [1])
        self.assertEqual(after["assumptions"]["quote_model_assumptions"]["deposit_apr"], "0.13")
        self.assertEqual(read_book_policy(self.book, 0)["record"]["document"]["version"], "1.0.0")

    def test_racing_same_predecessor_has_one_committed_revision(self):
        left, right = self.candidate(), self.candidate()
        left["document"]["economics"]["deposit_apr"] = "0.14"
        right["document"]["economics"]["deposit_apr"] = "0.16"
        def attempt(payload):
            try:
                return update_book_policy(self.book, payload)["changed"]
            except BookPolicyConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, (left, right)))
        self.assertCountEqual(outcomes, [True, "conflict"])
        self.assertEqual(len(read_book_policy(self.book)["history"]), 2)

    def test_bad_complete_documents_refuse_without_silent_defaults(self):
        valid = self.candidate()
        mutations = [
            lambda doc: doc.update(extra=True),
            lambda doc: doc.update(scorecard=None),
            lambda doc: doc.update(economics=None),
            lambda doc: doc["scorecard"]["weights"].pop("credit"),
            lambda doc: doc["scorecard"]["weights"].update(credit=None),
            lambda doc: doc["scorecard"]["weights"].update(credit="-0.2"),
            lambda doc: doc["scorecard"]["weights"].update(credit="NaN"),
            lambda doc: doc["scorecard"]["weights"].update(credit=0.2),
            lambda doc: doc["scorecard"]["grade_bands"].update(A="75"),
            lambda doc: doc["economics"].update(deposit_apr="1.01"),
            lambda doc: doc["economics"].update(recovery_fraction="-0.1"),
            lambda doc: doc["economics"]["annual_failure_probability"].update(D=None),
            lambda doc: doc.update(version="1.01.0"),
        ]
        original = self.book.snapshot()
        for mutate in mutations:
            invalid = deepcopy(valid)
            mutate(invalid["document"])
            with self.assertRaises(ValueError):
                update_book_policy(self.book, invalid)
        self.assertEqual(self.book.snapshot(), original)
        same_version = self.candidate(version="1.0.0")
        same_version["document"]["economics"]["deposit_apr"] = "0.12"
        with self.assertRaises(ValueError):
            update_book_policy(self.book, same_version)

    def test_unknown_ratings_stay_unknown_and_history_capacity_drops_nothing(self):
        before = [row["id"] for row in self.book.snapshot()["providers"] if row["grade"] is None]
        payload = self.candidate()
        payload["document"]["scorecard"]["weights"] = {key: "1" if key == "sla" else "0"
                                                       for key in payload["document"]["scorecard"]["weights"]}
        with patch("compute_pricing.control.api.book_policy.MAX_REVISIONS", 2):
            update_book_policy(self.book, payload)
            successor = self.candidate(version="1.2.0")
            with self.assertRaises(BookPolicyCapacity):
                update_book_policy(self.book, successor)
        after = [row["id"] for row in self.book.snapshot()["providers"] if row["grade"] is None]
        self.assertEqual(before, after)
        self.assertEqual(len(read_book_policy(self.book)["history"]), 2)
        self.assertEqual(read_book_policy(self.book, 0)["record"]["revision"], 0)

    def test_http_policy_reads_preview_commit_and_conflict_are_authenticated(self):
        with tempfile.TemporaryDirectory() as folder:
            key = "invented-policy-client-credential-000006"
            headers = {"Authorization": "Bearer " + key}
            app = create_app(api_key=key, store_path=Path(folder) / "paper.sqlite")
            app.state.quote_book = self.book
            with TestClient(app) as client:
                self.assertEqual(client.get("/v1/book/policy").status_code, 401)
                self.assertEqual(client.get("/v1/book/policy/contract", headers=headers).status_code, 200)
                payload = self.candidate()
                payload["document"]["economics"]["deposit_apr"] = "0.19"
                preview = client.post("/v1/book/policy/evaluate", json=payload, headers=headers)
                self.assertEqual(preview.status_code, 200, preview.text)
                self.assertFalse(preview.json()["book_changed"])
                self.assertEqual(client.get("/v1/book/policy", headers=headers).json()["current_revision"], 0)
                commit = client.put("/v1/book/policy", json=payload, headers=headers)
                self.assertEqual(commit.status_code, 200, commit.text)
                self.assertEqual(commit.json()["current_revision"], 1)
                self.assertFalse(client.put("/v1/book/policy", json=payload, headers=headers).json()["changed"])
                payload["document"]["version"] = "1.2.0"
                self.assertEqual(client.put("/v1/book/policy", json=payload, headers=headers).status_code, 409)
                original = client.get("/v1/book/policy/revisions/0", headers=headers)
                self.assertEqual(original.json()["record"]["document"]["economics"]["deposit_apr"], "0.085")
                self.assertEqual(client.get("/v1/book/policy/revisions/99", headers=headers).status_code, 404)
                self.assertEqual(client.put("/v1/book/policy", json={}, headers=headers).status_code, 422)
                self.assertIsNone(app.state.store.latest_refresh())
                self.assertFalse(commit.json()["execution_enabled"])


if __name__ == "__main__":
    unittest.main()
