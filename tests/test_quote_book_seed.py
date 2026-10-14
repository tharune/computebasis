"""Independent population coverage, exact values and non-imported provenance."""
from collections import Counter
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

from compute_pricing.control.quote_book.population import build_population
from compute_pricing.control.quote_book.seed import AS_OF, BASE_PRICE, MODELS, QUOTE_FIELDS, TIER_KEYS, seed_payload, validate_population


class IndependentBookSeedTests(unittest.TestCase):
    def test_exact_requested_cardinality_model_and_identity_coverage(self):
        providers, quotes = build_population()
        self.assertEqual(len(providers), 32)
        self.assertEqual(len(quotes), 192)
        self.assertEqual(Counter(row["gpu"] for row in quotes), Counter({gpu: 32 for gpu in MODELS}))
        self.assertEqual(Counter(row["provider_id"] for row in quotes), Counter({row["id"]: 6 for row in providers}))
        self.assertEqual({row["id"] for row in providers}, {f"provider-demo-{i:03d}" for i in range(1, 33)})
        self.assertEqual({row["id"] for row in quotes}, {f"quote-demo-{i:04d}" for i in range(1, 193)})
        self.assertEqual(validate_population(providers, quotes)["quotes"], 192)

    def test_same_seed_is_deterministic_new_seed_varies_and_returns_are_detached(self):
        first = build_population(4271)
        self.assertEqual(first, build_population(4271))
        self.assertNotEqual(first, build_population(4272))
        first[0][0]["tiers"]["credit"] = None
        first[1][0]["price"] = "999"
        fresh = build_population(4271)
        self.assertEqual(fresh[0][0]["tiers"]["credit"], 4)
        self.assertNotEqual(fresh[1][0]["price"], "999")

    def test_provider_labels_and_site_claims_are_obviously_simulated(self):
        providers, quotes = build_population()
        self.assertEqual({row["kind"] for row in providers}, {"Owner", "Reseller"})
        self.assertEqual(len({row["region"] for row in providers}), 4)
        known = {row["id"]: row for row in providers}
        self.assertGreater(len({row["country"] for row in quotes}), 4)
        self.assertTrue(any(len(row["sites"]) > 1 for row in providers))
        for provider in providers:
            self.assertRegex(provider["name"], r"^(Demo Supplier|Sample Reseller) [0-9]{2}$")
            self.assertTrue(all(site.startswith("Demo Site ") for site in provider["sites"]))
            self.assertIs(provider["synthetic"], True)
            self.assertEqual(provider["changed_tick"], -1)
        for quote in quotes:
            self.assertIn(quote["location"], known[quote["provider_id"]]["sites"])
            self.assertTrue(quote["location"].endswith("(" + quote["country"] + ")"))

    def test_rating_patterns_cover_strong_middle_weak_and_unknown_without_inversion(self):
        providers, _ = build_population()
        values = [set(row["tiers"].values()) for row in providers]
        self.assertIn({4}, values)
        self.assertIn({3, 4}, values)
        self.assertIn({2, 3}, values)
        self.assertIn({0}, values)
        self.assertIn({1}, values)
        self.assertIn({0, 1}, values)
        self.assertTrue(any(None in row for row in values))
        self.assertTrue(all(set(row["tiers"]) == set(TIER_KEYS) for row in providers))
        self.assertTrue(all(value is None or type(value) is int and 0 <= value <= 4
            for row in providers for value in row["tiers"].values()))
        self.assertEqual(seed_payload()["rating_scale"]["direction"], "higher_is_stronger")

    def test_money_is_plain_exact_strings_and_whole_device_allocations_positive(self):
        _, quotes = build_population()
        self.assertTrue(any(row["gpus_per_node"] > 8 for row in quotes))
        for quote in quotes:
            self.assertEqual(set(quote), QUOTE_FIELDS)
            self.assertRegex(quote["price"], r"^[0-9]+\.[0-9]{4}$")
            self.assertGreater(Decimal(quote["price"]), 0)
            self.assertEqual(quote["currency"], "USD")
            self.assertEqual(quote["price_unit"], "gpu_hour")
            for field in ("gpus_per_node", "nodes", "months", "moq"):
                self.assertIs(type(quote[field]), int)
                self.assertGreater(quote[field], 0)
            self.assertLessEqual(quote["moq"], quote["nodes"])
            self.assertLessEqual(quote["gpus_per_node"] * quote["nodes"], 8192)
            if quote["down_payment"] is not None:
                self.assertIsInstance(quote["down_payment"], str)
                self.assertTrue(0 <= Decimal(quote["down_payment"]) <= 1)

    def test_missing_terms_zero_expired_and_future_delivery_are_distinct(self):
        _, quotes = build_population()
        day = date.fromisoformat(AS_OF)
        self.assertTrue(any(row["down_payment"] is None for row in quotes))
        self.assertTrue(any(row["down_payment"] == "0" for row in quotes))
        self.assertTrue(any(row["expires"] is None for row in quotes))
        self.assertTrue(any(row["updated"] is None for row in quotes))
        self.assertTrue(any(row["interconnect"] is None for row in quotes))
        self.assertTrue(any(row["cooling"] is None for row in quotes))
        self.assertTrue(any(row["expires"] is not None and date.fromisoformat(row["expires"]) < day for row in quotes))
        self.assertTrue(any(date.fromisoformat(row["available"]) > day for row in quotes))
        self.assertTrue(all(date.fromisoformat(row["posted"]) <= day for row in quotes))
        self.assertTrue(all(row["updated"] is None or date.fromisoformat(row["posted"]) <= date.fromisoformat(row["updated"]) <= day for row in quotes))

    def test_each_model_has_several_complete_strong_current_comparisons(self):
        providers, quotes = build_population()
        providers = {row["id"]: row for row in providers}
        day = date.fromisoformat(AS_OF)
        for gpu in MODELS:
            clear = [row for row in quotes if row["gpu"] == gpu and set(providers[row["provider_id"]]["tiers"].values()) == {4}
                and row["down_payment"] is not None and row["expires"] is not None
                and date.fromisoformat(row["expires"]) >= day and date.fromisoformat(row["available"]) <= day
                and row["interconnect"] is not None and row["cooling"] is not None]
            self.assertGreaterEqual(len(clear), 4, gpu)

    def test_declared_date_moves_terms_without_using_real_time(self):
        _, baseline = build_population()
        _, shifted = build_population(as_of="2041-01-07")
        delta = date(2041, 1, 7) - date.fromisoformat(AS_OF)
        for left, right in zip(baseline, shifted):
            self.assertEqual(left["price"], right["price"])
            for field in ("posted", "available", "expires", "updated"):
                if left[field] is None:
                    self.assertIsNone(right[field])
                else:
                    self.assertEqual(date.fromisoformat(right[field]) - date.fromisoformat(left[field]), delta)

    def test_bounds_and_invalid_calendar_inputs_fail_without_partial_population(self):
        for seed in (True, False, -1, 2**32, 1.5, "4271", None):
            with self.subTest(seed=seed), self.assertRaises(ValueError): build_population(seed)
        for instant in (None, "2032-6-1", "2032-02-30", "2032-06-01T00:00:00Z", "1999-12-31", "2100-01-01"):
            with self.subTest(instant=instant), self.assertRaises(ValueError): build_population(as_of=instant)
        validate_population(*build_population(2**32 - 1, as_of="2099-12-01"), as_of="2099-12-01")

    def test_generator_has_no_external_input_and_no_source_fingerprint_fields(self):
        with patch("builtins.open", side_effect=AssertionError("generator must not read documents")), \
                patch("socket.socket.connect", side_effect=AssertionError("generator must not call a source")):
            payload = seed_payload()
        self.assertEqual(payload["fixture_label"], "independent simulation fixture")
        self.assertFalse(payload["market_evidence_admitted"])
        self.assertFalse(payload["inventory_ownership_verified"])
        self.assertFalse(payload["execution_enabled"])
        text = json.dumps(payload, sort_keys=True)
        self.assertIsNone(re.search(r"\b[a-f0-9]{64}\b", text))
        self.assertNotIn("artifact_sha256", text)
        self.assertNotIn("source_file", text)
        self.assertEqual(set(BASE_PRICE), set(MODELS))

    def test_financial_generation_is_independent_of_ambient_decimal_precision(self):
        ordinary = build_population()
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(build_population(), ordinary)

    def test_validation_rejects_floats_bad_tiers_and_unit_or_identity_drift(self):
        for case in ("float", "tier", "unit", "duplicate", "quantity"):
            providers, quotes = deepcopy(build_population())
            if case == "float": quotes[0]["price"] = 1.5
            elif case == "tier": providers[0]["tiers"]["credit"] = True
            elif case == "unit": quotes[0]["price_unit"] = "node_hour"
            elif case == "duplicate": quotes[1]["id"] = quotes[0]["id"]
            else: quotes[0]["moq"] = quotes[0]["nodes"] + 1
            with self.subTest(case=case), self.assertRaises(ValueError): validate_population(providers, quotes)

    def test_cli_check_and_json_emit_only_the_generated_fixture(self):
        script = Path(__file__).resolve().parents[1] / "scripts/gen_quote_book_seed.py"
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        checked = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, timeout=10, env=environment)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        report = json.loads(checked.stdout)
        self.assertTrue(report["checked"])
        self.assertEqual(report["quotes"], 192)
        exported = subprocess.run([sys.executable, str(script), "--seed", "99", "--json"], capture_output=True, text=True, timeout=10, env=environment)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        payload = json.loads(exported.stdout)
        self.assertEqual(payload["seed_value"], 99)
        self.assertEqual(payload["simulation_as_of"], AS_OF)
        self.assertEqual(len(payload["providers"]), 32)
        self.assertTrue(all(row["synthetic"] for row in payload["quotes"]))


if __name__ == "__main__": unittest.main()
