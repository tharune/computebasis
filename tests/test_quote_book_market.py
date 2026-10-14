"""Independent synthetic state/control regressions; no vendor or file IO."""
from copy import deepcopy
from decimal import Decimal, localcontext
import json
import math
import unittest

from compute_pricing.control.quote_book import QuoteBook
from compute_pricing.control.quote_book.population import MODELS
from compute_pricing.control.quote_book.scoring import quote_economics, validate_policy


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value


class QuoteBookMarketTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.book = QuoteBook(clock=self.clock)

    def test_baseline_has_all_families_and_only_simulation_eligibility(self):
        snapshot = self.book.snapshot()
        self.assertEqual(len(snapshot["providers"]), 32)
        self.assertEqual(len(snapshot["quotes"]), 192)
        self.assertEqual({row["gpu"] for row in snapshot["models"]}, set(MODELS))
        for row in snapshot["models"]:
            self.assertGreater(row["eligible"], 0)
            self.assertIsNotNone(row["best"])
            self.assertTrue(row["best"]["eligible"])
            self.assertIsInstance(row["best"]["missing"], int)
            self.assertIsInstance(row["best"]["missing_fields"], list)
            self.assertEqual(row["price_unit"], "gpu_hour")
        held = [row for row in snapshot["quotes"] if not row["eligible"]]
        self.assertTrue(held)
        self.assertTrue(any("grade" in row["missing_fields"] for row in held))
        self.assertTrue(any("simulated_quote_expired" in row["ineligible_reasons"] for row in held))
        for scope in (snapshot, snapshot["meta"], *snapshot["quotes"], *snapshot["providers"]):
            self.assertTrue(scope["simulated"])
            self.assertFalse(scope["source_evidence_eligible"])
            self.assertFalse(scope["firm_price_eligible"])
            self.assertFalse(scope["execution_enabled"])
        encoded = self.book.encoded()[1]
        self.assertNotIn("workbook", encoded.lower())
        self.assertNotIn("source_hash", encoded)
        self.assertIn("independently_invented", encoded)

    def test_financial_serialization_and_compatibility_collections(self):
        snapshot = self.book.snapshot()
        self.assertIsInstance(snapshot["kpis"]["contract_value"], str)
        self.assertIsInstance(snapshot["kpis"]["basis"], str)
        self.assertIsInstance(snapshot["kpis"]["gpus"], int)
        for quote in snapshot["quotes"]:
            for key in ("price", "risk_adjusted", "risk_adjusted_scorecard", "contract_value",
                        "down_payment_usd", "financing_cost", "failure_probability", "reference"):
                self.assertTrue(quote[key] is None or isinstance(quote[key], str), key)
        self.assertIsInstance(snapshot["grade_mix"]["A"], dict)
        self.assertIsInstance(snapshot["supply"][MODELS[0]], dict)
        self.assertIsInstance(snapshot["expiry"], list)
        self.assertEqual(sum(row["quotes"] for row in snapshot["expiry"]), 192)
        self.assertEqual(sum(row["quotes"] for row in snapshot["completeness"]), 192)
        for model in snapshot["series"]["models"].values():
            self.assertEqual({len(values) for values in model.values()}, {1})
        for provider in snapshot["providers"]:
            self.assertIn("price_index", provider)
            self.assertIn("missing_average", provider)
        tag, body = self.book.encoded()
        self.assertTrue(tag.startswith('W/"') and tag.endswith('"'))
        self.assertEqual(json.loads(body), snapshot)

    def test_basis_compares_best_cost_to_lowest_offer_and_totals_expose_unknowns(self):
        snapshot = self.book.snapshot()
        for model in snapshot["models"]:
            with localcontext() as context:
                context.prec = 200
                expected = Decimal(model["best"]["risk_adjusted"]) / Decimal(model["cheapest"]["price"]) - 1
                self.assertLess(abs(Decimal(model["basis"]) - expected), Decimal("1e-60"))
            self.assertEqual(model["basis_unit"], "fraction_above_lowest_displayed_native_offer")
        known, unknown = snapshot["kpis"]["contract_value_known_components"], snapshot["kpis"]["contract_value_unknown_components"]
        self.assertEqual(known + unknown, snapshot["kpis"]["live_quotes"])
        target = next(row for row in self.book._quotes if row["id"] == snapshot["models"][0]["best"]["id"])
        target["available"] = None
        self.book._record(replace_current=True)
        updated = self.book.snapshot()
        self.assertEqual(updated["kpis"]["contract_value_unknown_components"], unknown + 1)
        self.assertFalse(updated["kpis"]["contract_value_complete"])
        changed = next(row for row in updated["quotes"] if row["id"] == target["id"])
        self.assertIsNone(changed["contract_value"])
        self.assertIn("available", changed["missing_fields"])

    def test_aggregate_basis_uses_gpu_weights_and_exposes_unsupported_capacity(self):
        snapshot = self.book.snapshot()
        with localcontext() as context:
            context.prec = 300
            numerator = sum((Decimal(row["basis"]) * row["gpus"] for row in snapshot["models"]), Decimal(0))
            denominator = sum(row["gpus"] for row in snapshot["models"])
            self.assertLess(abs(Decimal(snapshot["kpis"]["basis"]) - numerator / denominator), Decimal("1e-60"))
        self.assertEqual(snapshot["kpis"]["basis_supported_gpus"], denominator)
        self.assertEqual(Decimal(snapshot["kpis"]["basis_weight_coverage"]), Decimal(1))
        excluded_model = snapshot["models"][0]
        for quote in self.book._quotes:
            if quote["gpu"] == excluded_model["gpu"]:
                quote["down_payment"] = None
        self.book._record(replace_current=True)
        unsupported = self.book.snapshot()
        self.assertEqual(unsupported["kpis"]["basis_unsupported_gpus"], excluded_model["gpus"])
        self.assertEqual(unsupported["kpis"]["models_with_basis"], 5)
        self.assertEqual(unsupported["kpis"]["basis_supported_gpus"] + unsupported["kpis"]["basis_unsupported_gpus"],
                         unsupported["kpis"]["basis_total_quoted_gpus"])
        self.assertFalse(unsupported["assumptions"]["basis_is_market_benchmark"])
        self.assertIsNone(unsupported["models"][0]["basis"])

    def test_ui_metadata_aliases_and_alerts_remain_explicit_simulation(self):
        initial = self.book.snapshot()
        self.assertEqual(initial["assumptions"]["weights"], initial["assumptions"]["scorecard_policy"]["weights"])
        self.assertEqual(initial["meta"]["epoch"], 0)
        self.assertEqual(initial["meta"]["source"], "Independent simulation fixture")
        self.assertEqual(initial["meta"]["step_minutes"], 1)
        self.book.control("scenario", "supply_shock")
        first = self.book.snapshot()["alerts"][-1]
        self.assertEqual(first["time"], self.book.snapshot()["meta"]["time"])
        self.assertEqual(first["level"], "warn")
        self.assertTrue(first["text"] and first["simulated"])
        self.assertIsInstance(first["n"], int)
        self.assertEqual(self.book.control("reset")["epoch"], 1)
        self.book.control("scenario", "price_war")
        second = self.book.snapshot()["alerts"][-1]
        self.assertGreater(second["n"], first["n"])
        self.assertEqual(second["level"], "info")
        self.assertEqual(self.book.control("reset")["epoch"], 2)

    def test_quote_aliases_preserve_rate_units_unknowns_and_exact_ranking(self):
        snapshot = self.book.snapshot()
        financed = next(row for row in snapshot["quotes"] if row["financing_cost"] is not None and Decimal(row["financing_cost"]) > 0)
        self.assertEqual(financed["financing"], financed["financing_cost_per_gpu_hour"])
        self.assertNotEqual(financed["financing"], financed["financing_cost"])
        self.assertEqual(financed["exposure"], financed["exposure_charge"])
        self.assertEqual(financed["units"]["financing"], "USD_per_gpu_hour")
        for quote in snapshot["quotes"]:
            self.assertIsInstance(quote["missing"], list)
            self.assertEqual(quote["missing_count"], len(quote["missing"]))
            self.assertEqual(quote["reasons"], quote["ineligible_reasons"])
            if not quote["eligible"]:
                self.assertIsNone(quote["risk_rank"])
            if quote["expires"] is None:
                self.assertIsNone(quote["days_to_expiry"])
        for model in snapshot["models"]:
            best = next(row for row in snapshot["quotes"] if row["id"] == model["best"]["id"])
            cheapest = next(row for row in snapshot["quotes"] if row["id"] == model["cheapest"]["id"])
            self.assertEqual(best["risk_rank"], 1)
            self.assertEqual(cheapest["price_rank"], 1)
            self.assertIsInstance(model["cheapest"]["missing"], int)
        for provider in snapshot["providers"]:
            if provider["grade"] is None:
                self.assertIsNone(provider["score"])
                self.assertIsNone(provider["score_exact"])
            else:
                self.assertIsInstance(provider["score"], (int, float))
                self.assertIsInstance(provider["score_exact"], str)

    def test_same_seed_reproduces_ticks_and_snapshots_are_detached(self):
        second = QuoteBook(clock=self.clock)
        baseline = self.book.snapshot()
        baseline["quotes"][0]["price"] = "999999999999"
        baseline["providers"][0]["tiers"].clear()
        baseline["assumptions"]["scorecard_policy"]["weights"].clear()
        self.assertEqual(self.book.snapshot(), second.snapshot())
        self.clock.value = 12
        self.assertEqual(self.book.snapshot(), second.snapshot())
        self.assertEqual(self.book.snapshot()["meta"]["tick"], 4)
        self.assertNotEqual(self.book.snapshot()["quotes"][0]["price"], "999999999999")

    def test_pause_resume_drops_parked_time_and_controls_are_idempotent(self):
        self.assertTrue(self.book.control("pause")["changed"])
        paused = self.book.snapshot()
        tag = self.book.etag()
        self.clock.value = 1_000_000
        self.assertEqual(self.book.snapshot(), paused)
        self.assertEqual(self.book.etag(), tag)
        self.assertFalse(self.book.control("pause")["changed"])
        self.assertTrue(self.book.control("resume")["changed"])
        self.clock.value += 2
        self.assertFalse(self.book.control("resume")["changed"])
        self.clock.value += 1
        self.assertEqual(self.book.snapshot()["meta"]["tick"], 1)

    def test_large_and_backward_clock_moves_are_bounded(self):
        self.clock.value = 10_000
        first = self.book.snapshot()
        self.assertEqual(first["meta"]["tick"], 8)
        self.assertTrue(first["meta"]["catchup_clamped"])
        self.assertEqual(self.book.snapshot()["meta"]["tick"], 8)
        self.clock.value = -20
        self.assertEqual(self.book.snapshot()["meta"]["tick"], 8)
        self.clock.value = -17
        self.assertEqual(self.book.snapshot()["meta"]["tick"], 9)
        self.clock.value = 1e308
        self.assertEqual(self.book.snapshot()["meta"]["tick"], 17)
        self.assertTrue(math.isfinite(self.book._last_clock))

    def test_history_arrays_are_bounded_and_aligned(self):
        for _ in range(17):
            self.clock.value += 24
            self.book.snapshot()
        snapshot = self.book.snapshot()
        series = snapshot["series"]
        self.assertEqual(len(series["ticks"]), 128)
        self.assertEqual(series["ticks"][-1], snapshot["meta"]["tick"])
        for key in ("times", "live", "gpus", "eligible_share", "basis"):
            self.assertEqual(len(series[key]), 128)
        for model in series["models"].values():
            self.assertEqual({len(values) for values in model.values()}, {128})

    def test_price_war_recomputes_costs_persists_and_same_selection_is_noop(self):
        original = self.book.snapshot()
        result = self.book.control("scenario", "price_war")
        self.assertTrue(result["posted"] and result["changed"])
        stressed = self.book.snapshot()
        for before, after in zip(original["quotes"], stressed["quotes"]):
            self.assertEqual(Decimal(after["price"]), Decimal(before["price"]) * Decimal("0.96"))
        selected = next(row for row in stressed["quotes"] if row["eligible"])
        raw = next(row for row in self.book._quotes if row["id"] == selected["id"])
        expected = quote_economics(raw, grade=(selected["grade"], Decimal(selected["grade_premium"])),
                                   reference=selected["reference"], as_of=stressed["meta"]["as_of"])
        self.assertEqual(Decimal(selected["risk_adjusted"]), expected["risk_adjusted"])
        tag = self.book.etag()
        self.assertFalse(self.book.control("scenario", "price_war")["changed"])
        self.assertEqual(self.book.etag(), tag)
        self.clock.value = 3
        moved = self.book.snapshot()
        self.assertTrue(all(Decimal(after["price"]) < Decimal(before["price"])
                            for before, after in zip(original["quotes"], moved["quotes"])))
        self.assertEqual(moved["meta"]["scenario"], "price_war")

    def test_supply_shock_removes_whole_nodes_and_preserves_delivery_dates(self):
        original = self.book.snapshot()
        self.book.control("scenario", "supply_shock")
        shocked = self.book.snapshot()
        for before, after in zip(original["quotes"], shocked["quotes"]):
            self.assertEqual(after["nodes"], before["nodes"] * 3 // 4)
            self.assertEqual(after["available"], before["available"])
            if not after["nodes"]:
                self.assertFalse(after["eligible"])
                self.assertIn("no_available_capacity", after["ineligible_reasons"])
        self.assertLess(shocked["kpis"]["gpus"], original["kpis"]["gpus"])
        self.assertEqual(len(shocked["quotes"]), 192)

    def test_downgrade_rescores_known_ratings_without_filling_unknowns(self):
        original = self.book.snapshot()
        self.book.control("scenario", "downgrade")
        downgraded = self.book.snapshot()
        for before, after in zip(original["providers"], downgraded["providers"]):
            for key, value in before["tiers"].items():
                self.assertEqual(after["tiers"][key], None if value is None else 0)
            self.assertEqual(after["grade"], None if before["grade"] is None else "D")
        self.assertEqual(downgraded["grade_mix"]["A"]["providers"], 0)
        self.assertEqual(downgraded["grade_mix"]["unknown"]["providers"],
                         original["grade_mix"]["unknown"]["providers"])

    def test_reset_restores_population_policy_series_and_rng(self):
        initial = self.book.snapshot()
        self.clock.value = 9
        self.book.snapshot()
        self.book.control("scenario", "downgrade")
        self.book.control("pause")
        self.book.control("reset")
        initial["meta"]["epoch"] = 1
        self.assertEqual(self.book.snapshot(), initial)
        fresh = QuoteBook(clock=self.clock)
        self.clock.value += 6
        same_rates = fresh.snapshot()
        same_rates["meta"]["epoch"] = 1
        self.assertEqual(self.book.snapshot(), same_rates)

    def test_simulation_midnight_uses_same_assessment_for_eligibility_and_buckets(self):
        # Place the deterministic state just before its calendar boundary;
        # testing 1,440 random-price steps would obscure this date regression.
        self.book._tick = 1439
        self.book._quotes[0]["expires"] = "2032-06-02"
        self.book._record()
        before = self.book.snapshot()
        self.assertEqual(before["meta"]["time"], "2032-06-01T23:59:00Z")
        self.assertEqual(before["meta"]["as_of"], "2032-06-01")
        self.clock.value = 3
        after = self.book.snapshot()
        self.assertEqual(after["meta"]["time"], "2032-06-02T00:00:00Z")
        self.assertEqual(after["meta"]["as_of"], "2032-06-02")
        self.assertTrue(all(row["as_of"] == "2032-06-02" for row in after["quotes"]))
        self.assertIn("simulated_quote_expired", after["quotes"][0]["ineligible_reasons"])
        self.assertEqual(after["series"]["times"][-1], after["meta"]["time"])

    def test_policy_is_effective_detached_and_context_independent(self):
        policy = validate_policy()
        policy["grade_premiums"]["A"] = "0.023"
        book = QuoteBook(clock=self.clock, policy=policy)
        policy["grade_premiums"]["A"] = "0.9"
        self.assertEqual(book.snapshot()["assumptions"]["scorecard_policy"]["grade_premiums"]["A"], "0.023")
        self.assertTrue(any(row["grade_premium"] == "0.023" for row in book.snapshot()["quotes"]))
        with localcontext() as context:
            context.prec = 6
            same = QuoteBook(clock=self.clock, policy=deepcopy(book._policy))
        self.assertEqual(book.snapshot(), same.snapshot())

    def test_invalid_controls_and_clock_do_not_mutate_the_book(self):
        before = self.book.snapshot()
        for action, scenario in (({}, None), ("publish", None), ("scenario", "other"),
                                 ("pause", "price_war"), ("scenario", {})):
            with self.assertRaises(ValueError):
                self.book.control(action, scenario)
        self.assertEqual(before, self.book.snapshot())
        self.clock.value = float("nan")
        with self.assertRaises(ValueError):
            self.book.snapshot()
        self.clock.value = 0
        self.assertEqual(before, self.book.snapshot())
        for seed in (True, -1, 2**32):
            with self.assertRaises(ValueError):
                QuoteBook(seed_value=seed)
        for duration in (0, float("inf"), float("nan"), True):
            with self.assertRaises(ValueError):
                QuoteBook(tick_seconds=duration)


if __name__ == "__main__":
    unittest.main()
