"""The quote book: reproducible, internally consistent, and anchored to the mock workbook."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.quote_book import market as market_module, scoring, seed
from compute_pricing.control.quote_book.market import QuoteBook, MAX_CATCH_UP

try:
    import openpyxl
except ImportError:
    openpyxl = None

# The mock workbook is not committed. Point this at the file named in seed.SOURCE to run the workbook oracle.
WORKBOOK = Path(os.environ["QUOTE_BOOK_WORKBOOK"]) if os.environ.get("QUOTE_BOOK_WORKBOOK") else None
SKIP_REASON = "set QUOTE_BOOK_WORKBOOK to the mock workbook named in seed.SOURCE (needs openpyxl)"


def workbook_available():
    if not (openpyxl and WORKBOOK and WORKBOOK.exists()):
        return False
    if hashlib.sha256(WORKBOOK.read_bytes()).hexdigest() != seed.SOURCE_SHA256:
        raise AssertionError("QUOTE_BOOK_WORKBOOK is not the workbook the seed was generated from (SHA-256 differs)")
    return True


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make(seed_value=2026):
    clock = FakeClock()
    return QuoteBook(seed_value=seed_value, clock=clock, tick_seconds=3.0), clock


def run(market, clock, steps):
    for _ in range(steps):
        clock.advance(3.0)
        market.encoded()


class StartingStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market, cls.clock = make()
        cls.snapshot = cls.market.snapshot()

    def test_it_is_labelled_simulated_and_names_its_source(self):
        self.assertIs(self.snapshot["simulated"], True)
        self.assertEqual(self.snapshot["meta"]["source"], seed.SOURCE)
        self.assertEqual(self.snapshot["meta"]["tick"], 0)

    def test_scale_resembles_the_workbook_extended(self):
        kpis = self.snapshot["kpis"]
        self.assertEqual(kpis["providers_total"], 28)
        self.assertTrue(140 <= kpis["live_quotes"] <= 170, kpis["live_quotes"])
        self.assertEqual(len(self.snapshot["quotes"]), kpis["live_quotes"])
        self.assertEqual(len({q["id"] for q in self.snapshot["quotes"]}), kpis["live_quotes"])
        self.assertEqual({m["model"] for m in self.snapshot["models"]}, set(market_module.MODELS))

    def test_every_workbook_quote_is_present_at_its_published_price(self):
        by_id = {q["id"]: q for q in self.snapshot["quotes"]}
        for row in seed.QUOTES:
            self.assertEqual(by_id[row["id"]]["price"], f'{row["price"]:.2f}', row["id"])
            self.assertTrue(by_id[row["id"]]["workbook"])

    def test_history_is_already_on_the_charts(self):
        series = self.snapshot["series"]
        self.assertEqual(series["ticks"], list(range(-90, 1)))
        for key in ("live", "gpus", "eligible_share", "basis"):
            self.assertEqual(len(series[key]), 91, key)
        self.assertEqual(series["live"][-1], self.snapshot["kpis"]["live_quotes"])
        self.assertEqual(series["models"]["B300"]["cheapest"][-1], min(float(q["price"]) for q in self.snapshot["quotes"] if q["gpu"] == "B300"))

    def test_the_cheapest_quote_is_usually_a_weak_seller_and_basis_is_positive(self):
        weak = [m for m in self.snapshot["models"] if m["cheapest"] and m["cheapest"]["grade"] in ("C", "D")]
        self.assertGreaterEqual(len(weak), 4)
        for model in self.snapshot["models"]:
            if model["basis"] is not None:
                self.assertGreater(model["basis"], 0, model["model"])
        gb300 = next(m for m in self.snapshot["models"] if m["model"] == "GB300")
        self.assertIsNone(gb300["best"])  # newest hardware has no vetted seller, as in the workbook
        self.assertIsNone(gb300["basis"])

    def test_the_workbook_rows_carry_the_workbooks_own_numbers(self):
        by_id = {q["id"]: q for q in self.snapshot["quotes"]}
        self.assertAlmostEqual(by_id["Q038"]["risk_adjusted"], 5.69012375, places=3)
        self.assertAlmostEqual(by_id["Q001"]["risk_adjusted"], 5.2790675, places=3)
        self.assertEqual(by_id["Q038"]["grade"], "A")
        self.assertEqual(by_id["Q001"]["grade"], "D")
        self.assertFalse(by_id["Q001"]["eligible"])
        self.assertIn("grade D is below C", by_id["Q001"]["reasons"])

    @unittest.skipUnless(workbook_available(), SKIP_REASON)
    def test_workbook_only_summary_matches_the_workbooks_quote_summary(self):
        sheet = openpyxl.load_workbook(WORKBOOK, data_only=True)["Quote Summary"]
        grades = {p["name"]: scoring.grade_for(scoring.quality_score(p["tiers"]))[0] for p in seed.PROVIDERS}
        import datetime as dt
        as_of = dt.date.fromisoformat(seed.AS_OF)
        for model, quotes, _, reference, cheapest, _, cheapest_grade, cheapest_price, best, _, _, _, risk, *_ in sheet.iter_rows(min_row=3, max_row=8, values_only=True):
            rows = [q for q in seed.QUOTES if q["gpu"] == model]
            self.assertEqual(len(rows), quotes)
            priced = sorted(rows, key=lambda q: (q["price"], q["id"]))
            self.assertEqual((priced[0]["id"], priced[0]["price"], grades[priced[0]["provider"]]), (cheapest, cheapest_price, cheapest_grade))
            economics = [(scoring.quote_economics(q, grade=grades[q["provider"]], reference=scoring.ASSUMPTIONS["reference"].get(model), as_of=as_of), q) for q in rows]
            eligible = sorted(((e["risk_adjusted"], q["id"]) for e, q in economics if e["eligible"]))
            if best == "None eligible":
                self.assertEqual(eligible, [], model)
            else:
                self.assertEqual(eligible[0][1], best, model)
                self.assertAlmostEqual(eligible[0][0], risk, places=6)


class DynamicsTests(unittest.TestCase):
    def test_same_seed_and_same_clock_give_identical_bytes_and_other_seeds_differ(self):
        (a, ca), (b, cb), (c, cc) = make(7), make(7), make(8)
        for market, clock in ((a, ca), (b, cb), (c, cc)):
            run(market, clock, 25)
        self.assertEqual(a.encoded(), b.encoded())
        self.assertNotEqual(a.encoded()[1], c.encoded()[1])

    def test_book_stays_healthy_and_every_reference_resolves_over_a_long_run(self):
        market, clock = make()
        run(market, clock, 160)
        snapshot = market.snapshot()
        self.assertEqual(snapshot["meta"]["tick"], 160)
        providers = {p["id"] for p in snapshot["providers"]}
        self.assertTrue(110 <= snapshot["kpis"]["live_quotes"] <= 200, snapshot["kpis"]["live_quotes"])
        for quote in snapshot["quotes"]:
            self.assertIn(quote["provider_id"], providers)
            self.assertGreater(float(quote["price"]), 0)
            self.assertIn(quote["grade"], scoring.GRADES)
        ticks = snapshot["series"]["ticks"]
        self.assertEqual(ticks, sorted(set(ticks)))
        self.assertLessEqual(len(ticks), market_module.HISTORY_STEPS)
        numbers = [a["n"] for a in snapshot["alerts"]]
        self.assertEqual(numbers, sorted(numbers, reverse=True))
        self.assertTrue(any(a["level"] != "info" for a in snapshot["alerts"]))

    def test_a_quote_rank_matches_its_position_and_eligible_ranks_follow_risk_adjusted_cost(self):
        market, clock = make()
        run(market, clock, 30)
        for model in market_module.MODELS:
            quotes = [q for q in market.snapshot()["quotes"] if q["gpu"] == model]
            self.assertEqual(sorted(q["price_rank"] for q in quotes), list(range(1, len(quotes) + 1)))
            eligible = sorted((q for q in quotes if q["eligible"]), key=lambda q: q["risk_rank"])
            self.assertEqual([q["risk_rank"] for q in eligible], list(range(1, len(eligible) + 1)))
            costs = [q["risk_adjusted"] for q in eligible]
            self.assertEqual(costs, sorted(costs))

    def test_the_etag_moves_with_the_market_and_not_otherwise(self):
        market, clock = make()
        first = market.encoded()[0]
        clock.advance(1.0)
        self.assertEqual(market.encoded()[0], first)
        clock.advance(3.0)
        self.assertNotEqual(market.encoded()[0], first)
        self.assertEqual(market.etag(), market.encoded()[0])

    def test_pausing_freezes_the_market_and_resuming_does_not_replay_the_gap(self):
        market, clock = make()
        run(market, clock, 5)
        market.control("pause")
        frozen = market.encoded()
        clock.advance(600.0)
        self.assertEqual(market.encoded()[1], frozen[1])
        self.assertTrue(market.snapshot()["meta"]["paused"])
        market.control("resume")
        self.assertEqual(market.snapshot()["meta"]["tick"], 5)
        clock.advance(3.0)
        self.assertEqual(market.snapshot()["meta"]["tick"], 6)

    def test_a_long_gap_is_capped_rather_than_replayed(self):
        market, clock = make()
        clock.advance(100000.0)
        self.assertEqual(market.snapshot()["meta"]["tick"], MAX_CATCH_UP)
        clock.advance(3.0)
        self.assertEqual(market.snapshot()["meta"]["tick"], MAX_CATCH_UP + 1)

    def test_reset_returns_to_the_published_starting_state(self):
        market, clock = make()
        fresh = market.snapshot()
        run(market, clock, 40)
        market.control("scenario", "downgrade")
        market.control("reset")
        after = market.snapshot()
        self.assertEqual(after["meta"]["tick"], 0)
        self.assertEqual(after["meta"]["epoch"], 1)
        self.assertEqual(after["quotes"], fresh["quotes"])
        self.assertEqual(after["providers"], fresh["providers"])
        self.assertNotEqual(market.etag(), 'W/"book-0-0-0"')

    def test_payload_is_strict_json(self):
        market, clock = make()
        run(market, clock, 10)
        json.loads(market.encoded()[1], parse_constant=lambda name: self.fail(f"non-finite value {name}"))


class ScenarioTests(unittest.TestCase):
    def prepared(self):
        market, clock = make()
        run(market, clock, 6)
        return market, clock

    def model(self, snapshot, name):
        return next(m for m in snapshot["models"] if m["model"] == name)

    def test_price_war_lowers_the_cheapest_quote_and_widens_the_basis(self):
        market, _ = self.prepared()
        before = self.model(market.snapshot(), "B300")
        market.control("scenario", "price_war")
        after_snapshot = market.snapshot()
        after = self.model(after_snapshot, "B300")
        self.assertLess(float(after["cheapest"]["price"]), float(before["cheapest"]["price"]) * 0.96)
        self.assertGreater(after["basis"], before["basis"] + 0.03)
        self.assertEqual(after_snapshot["alerts"][0]["kind"], "scenario")
        self.assertEqual(after_snapshot["series"]["basis"][-1], after_snapshot["kpis"]["basis"])  # the chart already reflects it

    def test_price_war_cuts_hold_instead_of_drifting_back_to_the_old_level(self):
        market, _ = self.prepared()
        before = {q["id"]: q["price"] for q in market.quotes.values() if q["gpu"] == "B300"}
        market.control("scenario", "price_war")
        cut = [q for q in market.quotes.values() if q["id"] in before and q["price"] < before[q["id"]] * 0.95]
        self.assertGreaterEqual(len(cut), 3)
        for quote in cut:  # later revisions pull a quote toward its target; a pinned cut is its own target
            self.assertAlmostEqual(market._target_price(quote), quote["price"], delta=0.01, msg=quote["id"])

    def test_supply_shock_withdraws_a_large_share_of_the_models_gpus(self):
        market, _ = self.prepared()
        before = self.model(market.snapshot(), "H200")["gpus"]
        market.control("scenario", "supply_shock")
        after = self.model(market.snapshot(), "H200")["gpus"]
        self.assertLess(after, before * 0.6)

    def test_downgrade_drops_a_strong_provider_by_at_least_two_grades(self):
        market, _ = self.prepared()
        before = {p["id"]: p["grade"] for p in market.snapshot()["providers"]}
        market.control("scenario", "downgrade")
        snapshot = market.snapshot()
        moved = [p for p in snapshot["providers"] if p["grade"] != before[p["id"]]]
        self.assertEqual(len(moved), 1)
        self.assertEqual(before[moved[0]["id"]], "A")
        self.assertIn(moved[0]["grade"], ("C", "D"))
        self.assertEqual(moved[0]["changed_tick"], snapshot["meta"]["tick"])
        self.assertIn("downgraded", snapshot["alerts"][0]["text"])

    def test_scenarios_may_be_repeated_without_breaking_the_book(self):
        market, clock = self.prepared()
        for name in market_module.SCENARIOS * 3:
            market.control("scenario", name)
            run(market, clock, 2)
        snapshot = market.snapshot()
        self.assertGreater(snapshot["kpis"]["live_quotes"], 30)
        self.assertEqual(snapshot["meta"]["tick"], 6 + 18)


class ControlValidationTests(unittest.TestCase):
    def test_bad_requests_are_rejected_and_change_nothing(self):
        market, _ = make()
        before = market.encoded()
        for action, scenario in (("explode", None), ("scenario", None), ("scenario", "unknown"), ("pause", "price_war"), ("reset", "downgrade")):
            with self.assertRaises(ValueError, msg=(action, scenario)):
                market.control(action, scenario)
        self.assertEqual(market.encoded(), before)

    def test_tick_seconds_must_be_positive(self):
        with self.assertRaises(ValueError):
            QuoteBook(tick_seconds=0)


if __name__ == "__main__":
    unittest.main()
