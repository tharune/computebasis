"""The desk ledger (`GET /v1/book/desk`): invented positions and brokered bids over the simulated quote book.

`validate_desk_ledger` is the structural contract (docs/desk-ledger-contract.md) as code. It checks the real
backend output and the frontend fixture `tests/fixtures/desk-ledger.json`, so drift between the two fails here.

Regenerate the fixture from the real starting book (seed 4271, tick 0) with:
    python tests/test_desk_ledger.py --write-fixture
"""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from compute_pricing.control.api import create_app
from compute_pricing.control.quote_book import QuoteBook
from compute_pricing.control.quote_book.desk import build_desk_ledger, encode_desk_ledger
from compute_pricing.control.quote_book.desk_placement import (
    COUNTRY_METROS, US_METROS, US_OVERFLOW_METROS, DeskLedgerError, UnknownCountryError, assign_placements,
)
from compute_pricing.control.quote_book.population import REGION_CLAIMS, build_population

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "desk-ledger.json"

TOP_KEYS = ["schema_version", "simulated", "synthetic", "source_evidence_eligible", "inventory_verified",
            "firm_price_eligible", "execution_enabled", "meta", "summary", "sites", "positions", "bids"]
FLAGS = {"simulated": True, "synthetic": True, "source_evidence_eligible": False, "inventory_verified": False,
         "firm_price_eligible": False, "execution_enabled": False}
META_KEYS = ["as_of", "time", "tick", "epoch", "seed", "book_schema_version", "ledger_basis", "placement_basis"]
SUMMARY_KEYS = ["positions", "position_gpus", "position_notional_usd", "unrealized_usd", "unrealized_basis", "bids", "bids_open",
                "bids_filled", "bids_declined", "bids_expired", "bid_gpus", "filled_gpus", "open_gpus", "fill_rate", "sites",
                "us_sites", "us_supply_gpus", "supply_gpus", "us_supply_share"]
SITE_KEYS = ["id", "name", "provider_id", "provider", "provider_grade", "country", "placement", "capacity", "position_gpus", "open_bid_gpus"]
PLACEMENT_KEYS = ["label", "state", "lat", "lon"]
CAPACITY_KEYS = ["gpus", "quotes", "eligible_quotes", "eligible_gpus", "models"]
POSITION_KEYS = ["id", "site_id", "provider_id", "model", "gpus", "months", "start", "end", "status", "price", "mark", "mark_basis",
                 "unrealized_usd", "remaining_hours", "notional_usd"]
BID_KEYS = ["id", "quote_id", "site_id", "provider_id", "model", "gpus", "months", "ask", "bid", "status", "placed", "decided", "position_id"]
PRICE, CENT, RATE = re.compile(r"-?\d+\.\d{4}"), re.compile(r"-?\d+\.\d{2}"), re.compile(r"[01]\.\d{4}")
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
PLACEHOLDERS = {"nan", "infinity", "-infinity", "inf", "n/a", "na", "null", "none", "undefined"}

# Rough state outlines (south, north, west, east): a typo in a US metro's coordinates or state fails the placement test.
STATE_BOXES = {
    "VA": (36.5, 39.5, -83.7, -75.2), "TX": (25.8, 36.5, -106.7, -93.5), "AZ": (31.3, 37.0, -114.9, -109.0),
    "IL": (37.0, 42.5, -91.6, -87.0), "GA": (30.3, 35.0, -85.7, -80.8), "OH": (38.4, 42.0, -84.9, -80.5),
    "OR": (42.0, 46.3, -124.6, -116.4), "WA": (45.5, 49.0, -124.8, -116.9), "UT": (37.0, 42.0, -114.1, -109.0),
    "CO": (37.0, 41.0, -109.1, -102.0), "NV": (35.0, 42.0, -120.0, -114.0), "CA": (32.5, 42.0, -124.5, -114.1),
    "NE": (40.0, 43.0, -104.1, -95.3), "MO": (36.0, 40.6, -95.8, -89.1), "MN": (43.5, 49.4, -97.3, -89.5),
    "NC": (33.8, 36.6, -84.4, -75.4), "FL": (24.5, 31.0, -87.7, -80.0), "NJ": (38.9, 41.4, -75.6, -73.9),
    "MA": (41.2, 42.9, -73.5, -69.9), "TN": (34.9, 36.7, -90.4, -81.6), "NM": (31.3, 37.0, -109.1, -103.0),
    "WY": (41.0, 45.0, -111.1, -104.0), "IA": (40.4, 43.5, -96.7, -90.1), "OK": (33.6, 37.0, -103.0, -94.4),
    "PA": (39.7, 42.3, -80.6, -74.7), "MI": (41.7, 48.3, -90.4, -82.1), "ID": (42.0, 49.0, -117.2, -111.0),
}


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value


def start_book(seed=4271):
    clock = Clock()
    return QuoteBook(seed_value=seed, clock=clock), clock


def tick(book, clock, count=1):
    """Advance the simulated book by `count` ticks (at most the catch-up limit per read)."""
    clock.value += book._period * count
    return book.snapshot()


def money(value, step):
    return format(value.quantize(Decimal(step), rounding=ROUND_HALF_EVEN), "f")


def validate_desk_ledger(doc, book=None):
    """Raise AssertionError unless `doc` meets the desk ledger contract.

    `book` is a `QuoteBook.snapshot()`; when given, every join, capacity sum and mark is checked against it too.
    Without it only the ledger's internal consistency is checked.
    """
    def need(condition, message):
        if not condition:
            raise AssertionError("desk ledger: " + message)

    def keys(value, expected, label):
        need(isinstance(value, dict) and list(value) == expected, f"{label} keys/order {list(value) if isinstance(value, dict) else value!r}")

    def count(value, label, minimum=0):
        need(type(value) is int and value >= minimum, f"{label} must be a whole number >= {minimum}, got {value!r}")

    def text(value, label, pattern=None):
        need(isinstance(value, str) and value != "" and value.lower() not in PLACEHOLDERS, f"{label} must be a real string, got {value!r}")
        need(pattern is None or pattern.fullmatch(value) is not None, f"{label} has the wrong shape: {value!r}")

    def walk(value, path):
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, float):
            need(path[-2:] in (("placement", "lat"), ("placement", "lon")) and math.isfinite(value), f"float outside lat/lon at {path}")
        elif isinstance(value, str):
            need(value != "" and value.lower() not in PLACEHOLDERS, f"empty or placeholder string at {path}")
        elif isinstance(value, dict):
            for name, item in value.items():
                walk(item, path + (name,))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, path + (index,))
        else:
            need(type(value) is int, f"unexpected {type(value).__name__} at {path}")

    keys(doc, TOP_KEYS, "top-level")
    walk(doc, ())
    need(doc["schema_version"] == "synthetic-desk-ledger/1.0", "schema_version")
    for name, expected in FLAGS.items():
        need(doc[name] is expected, f"{name} must be {expected}")
    meta, summary = doc["meta"], doc["summary"]
    keys(meta, META_KEYS, "meta")
    need(meta["ledger_basis"] == "deterministic_invented_desk_positions_and_bids_not_trades", "ledger_basis")
    need(meta["placement_basis"] == "illustrative_metro_assignment_not_vendor_location", "placement_basis")
    text(meta["time"], "meta.time", TIME)
    as_of = date.fromisoformat(meta["as_of"])
    need(meta["time"].startswith(meta["as_of"]), "meta.time is on meta.as_of")
    for name in ("tick", "epoch", "seed"):
        count(meta[name], "meta." + name)
    keys(summary, SUMMARY_KEYS, "summary")
    need(summary["unrealized_basis"] == "mark_is_current_best_eligible_all_in_cost_per_model", "unrealized_basis")
    sites, positions, bids = doc["sites"], doc["positions"], doc["bids"]
    for label, rows in (("sites", sites), ("positions", positions), ("bids", bids)):
        need(isinstance(rows, list), label + " is a list")
        need(len({row["id"] for row in rows}) == len(rows), label + " ids are unique")
    need(len({site["name"] for site in sites}) == len(sites), "site names are unique")
    by_site = {site["id"]: site for site in sites}
    by_position = {position["id"]: position for position in positions}

    for site in sites:
        keys(site, SITE_KEYS, "site")
        text(site["id"], "site.id")
        text(site["name"], "site.name")
        text(site["provider_id"], "site.provider_id")
        text(site["provider"], "site.provider")
        need(site["provider_grade"] in ("A", "B", "C", "D", None), "provider_grade is A..D or null")
        text(site["country"], "site.country", re.compile(r"[A-Z]{2}"))
        place, capacity = site["placement"], site["capacity"]
        keys(place, PLACEMENT_KEYS, "placement")
        text(place["label"], "placement.label")
        need(type(place["lat"]) is float and type(place["lon"]) is float, "placement lat/lon are always present")
        need(-90 <= place["lat"] <= 90 and -180 <= place["lon"] <= 180, "placement is on the globe")
        if site["country"] == "US":
            need(re.fullmatch(r"[A-Z]{2}", place["state"] or "") is not None, "a US site has a state")
        else:
            need(place["state"] is None, "a non-US site has no state")
        keys(capacity, CAPACITY_KEYS, "capacity")
        for name in CAPACITY_KEYS[:-1]:
            count(capacity[name], "capacity." + name)
        need(isinstance(capacity["models"], dict), "capacity.models is a mapping")
        need(all(type(gpus) is int and gpus > 0 for gpus in capacity["models"].values()), "models with no GPUs are omitted")
        need(sum(capacity["models"].values()) == capacity["gpus"], "capacity.models sums to capacity.gpus")
        need(capacity["eligible_quotes"] <= capacity["quotes"] and capacity["eligible_gpus"] <= capacity["gpus"], "eligible is within live")
        need(capacity["quotes"] > 0 or capacity["gpus"] == 0, "a site with no live quotes has no capacity")
        count(site["position_gpus"], "site.position_gpus")
        count(site["open_bid_gpus"], "site.open_bid_gpus")
        need(site["position_gpus"] == sum(p["gpus"] for p in positions if p["site_id"] == site["id"]), "site.position_gpus sums its positions")
        need(site["open_bid_gpus"] == sum(b["gpus"] for b in bids if b["status"] == "open" and b["site_id"] == site["id"]), "site.open_bid_gpus sums its open bids")

    for position in positions:
        keys(position, POSITION_KEYS, "position")
        site = by_site.get(position["site_id"])
        need(site is not None, "position.site_id joins a site")
        need(position["provider_id"] == site["provider_id"], "position.provider_id is its site's provider")
        text(position["model"], "position.model")
        count(position["gpus"], "position.gpus", 1)
        count(position["months"], "position.months", 1)
        start, end = date.fromisoformat(position["start"]), date.fromisoformat(position["end"])
        need(end > start, "position ends after it starts")
        need(position["status"] in ("active", "upcoming"), "position status")
        need(position["status"] == ("active" if start <= as_of else "upcoming"), "position status follows as_of")
        text(position["price"], "position.price", PRICE)
        need(Decimal(position["price"]) > 0, "position.price is positive")
        need(position["mark_basis"] == "model_best_eligible_all_in", "mark_basis")
        hours = (end - start).days * 24
        remaining = max(0, (end - max(start, as_of)).days) * 24
        need(position["remaining_hours"] == remaining, f"remaining_hours is the days left to the end, times 24 ({position['remaining_hours']} != {remaining})")
        need(position["notional_usd"] == money(Decimal(position["price"]) * position["gpus"] * hours, "0.01"), "notional is price x GPUs x contract hours")
        text(position["notional_usd"], "position.notional_usd", CENT)
        if position["mark"] is None:
            need(position["unrealized_usd"] is None, "no mark means no unrealized figure (null, not 0)")
        else:
            text(position["mark"], "position.mark", PRICE)
            need(position["unrealized_usd"] == money((Decimal(position["mark"]) - Decimal(position["price"])) * position["gpus"] * remaining, "0.01"),
                 "unrealized is (mark - price) x GPUs x remaining hours")
            text(position["unrealized_usd"], "position.unrealized_usd", CENT)

    time = datetime.fromisoformat(meta["time"].replace("Z", "+00:00"))
    for bid in bids:
        keys(bid, BID_KEYS, "bid")
        site = by_site.get(bid["site_id"])
        need(site is not None, "bid.site_id joins a site")
        need(bid["provider_id"] == site["provider_id"], "bid.provider_id is its site's provider")
        text(bid["quote_id"], "bid.quote_id")
        text(bid["model"], "bid.model")
        count(bid["gpus"], "bid.gpus", 1)
        count(bid["months"], "bid.months", 1)
        text(bid["ask"], "bid.ask", PRICE)
        text(bid["bid"], "bid.bid", PRICE)
        need(0 < Decimal(bid["bid"]) < Decimal(bid["ask"]), "a bid is under its ask")
        need(bid["status"] in ("open", "filled", "declined", "expired"), "bid status")
        text(bid["placed"], "bid.placed", TIME)
        need(datetime.fromisoformat(bid["placed"].replace("Z", "+00:00")) < time, "a bid is placed before as_of")
        if bid["status"] == "open":
            need(bid["decided"] is None, "an open bid has decided: null")
        else:
            text(bid["decided"], "bid.decided", TIME)
            decided = datetime.fromisoformat(bid["decided"].replace("Z", "+00:00"))
            need(datetime.fromisoformat(bid["placed"].replace("Z", "+00:00")) < decided <= time, "a bid is decided after it was placed and not after as_of")
        if bid["position_id"] is None:
            need(bid["status"] != "filled", "this backend turns every filled bid into a position")
        else:
            position = by_position.get(bid["position_id"])
            need(position is not None and bid["status"] == "filled", "bid.position_id joins a position and the bid is filled")
            need((position["site_id"], position["model"], position["gpus"], position["months"], position["price"])
                 == (bid["site_id"], bid["model"], bid["gpus"], bid["months"], bid["bid"]), "a position is its filled bid, held at the bid price")
    need(sorted(bid["position_id"] for bid in bids if bid["position_id"]) == sorted(by_position), "every position is one filled bid")

    status = {name: sum(bid["status"] == name for bid in bids) for name in ("open", "filled", "declined", "expired")}
    decided_total = status["filled"] + status["declined"] + status["expired"]
    supply = sum(site["capacity"]["gpus"] for site in sites)
    us_supply = sum(site["capacity"]["gpus"] for site in sites if site["country"] == "US")
    marks_known = all(position["unrealized_usd"] is not None for position in positions)
    expected = {
        "positions": len(positions), "position_gpus": sum(p["gpus"] for p in positions),
        "position_notional_usd": money(sum((Decimal(p["notional_usd"]) for p in positions), Decimal(0)), "0.01"),
        "unrealized_usd": money(sum((Decimal(p["unrealized_usd"]) for p in positions), Decimal(0)), "0.01") if marks_known else None,
        "unrealized_basis": "mark_is_current_best_eligible_all_in_cost_per_model",
        "bids": len(bids), "bids_open": status["open"], "bids_filled": status["filled"], "bids_declined": status["declined"],
        "bids_expired": status["expired"], "bid_gpus": sum(b["gpus"] for b in bids),
        "filled_gpus": sum(b["gpus"] for b in bids if b["status"] == "filled"),
        "open_gpus": sum(b["gpus"] for b in bids if b["status"] == "open"),
        "fill_rate": money(Decimal(status["filled"]) / decided_total, "0.0001") if decided_total else None,
        "sites": len(sites), "us_sites": sum(site["country"] == "US" for site in sites),
        "us_supply_gpus": us_supply, "supply_gpus": supply,
        "us_supply_share": money(Decimal(us_supply) / supply, "0.0001") if supply else None,
    }
    need(summary == expected, "summary counts equal the lists: " + json.dumps({k: [summary[k], v] for k, v in expected.items() if summary[k] != v}))
    if summary["fill_rate"] is not None:
        text(summary["fill_rate"], "summary.fill_rate", RATE)

    if book is None:
        return
    bm, quotes = book["meta"], {row["id"]: row for row in book["quotes"]}
    need((meta["as_of"], meta["time"], meta["tick"], meta["epoch"], meta["seed"], meta["book_schema_version"])
         == (bm["as_of"], bm["time"], bm["tick"], bm["epoch"], bm["seed"], bm["schema_version"]), "meta follows the book's")
    providers = {row["id"]: row for row in book["providers"]}

    def live(row):  # the book's own rule, restated: active, at least one node, an expiry after as_of
        return row.get("active", True) and row["nodes"] > 0 and row["expires"] is not None and row["expires"] > bm["as_of"]

    need({site["name"] for site in sites} == {row["location"] for row in book["quotes"]}, "one site per distinct quote location")
    for site in sites:
        provider = providers.get(site["provider_id"])
        need(provider is not None, "site.provider_id is a book provider")
        need((site["provider"], site["provider_grade"]) == (provider["name"], provider["grade"]), "site carries its provider's name and grade")
        rows = [row for row in book["quotes"] if row["location"] == site["name"]]
        need({row["provider_id"] for row in rows} == {site["provider_id"]} and {row["country"] for row in rows} == {site["country"]}, "a location has one provider and country")
        current = [row for row in rows if live(row)]
        eligible = [row for row in current if row.get("eligible") is True]
        models = {}
        for row in current:
            models[row["gpu"]] = models.get(row["gpu"], 0) + row["gpus"]
        need(site["capacity"] == {"gpus": sum(row["gpus"] for row in current), "quotes": len(current), "eligible_quotes": len(eligible),
                                  "eligible_gpus": sum(row["gpus"] for row in eligible), "models": models}, f"capacity of {site['name']} equals its live quotes")
    kpis = book["kpis"]
    need(supply == summary["supply_gpus"] == kpis["gpus"], "supply_gpus equals kpis.gpus")
    need(sum(site["capacity"]["quotes"] for site in sites) == kpis["live_quotes"], "live quotes sum to kpis.live_quotes")
    need(sum(site["capacity"]["eligible_quotes"] for site in sites) == kpis["eligible_quotes"], "eligible quotes sum to kpis.eligible_quotes")
    for bid in bids:
        quote = quotes.get(bid["quote_id"])
        need(quote is not None, f"{bid['id']} joins a book quote")
        need((bid["provider_id"], bid["model"], by_site[bid["site_id"]]["name"]) == (quote["provider_id"], quote["gpu"], quote["location"]), "a bid agrees with its quote")
    best = {row["gpu"]: row["best"]["risk_adjusted"] if row["best"] else None for row in book["models"]}
    for position in positions:
        mark = best.get(position["model"])
        need(position["mark"] == (None if mark is None else money(Decimal(mark), "0.0001")), "mark is the model's best eligible all-in cost")


def reject_constant(name):
    raise AssertionError("JSON contains " + name)


class DeskLedgerCase(unittest.TestCase):
    def setUp(self):
        self.book, self.clock = start_book()

    def snapshot(self):
        return self.book.snapshot()

    def ledger(self):
        snapshot = self.snapshot()
        document = build_desk_ledger(snapshot)
        validate_desk_ledger(document, snapshot)
        return document

    def marks(self, document):
        return {position["id"]: position["mark"] for position in document["positions"]}


class ContractGuaranteeTests(DeskLedgerCase):
    def test_starting_book_meets_every_guarantee(self):
        snapshot = self.snapshot()
        document = build_desk_ledger(snapshot)
        validate_desk_ledger(document, snapshot)
        self.assertEqual(len(document["sites"]), 72)
        self.assertEqual(document["summary"]["us_sites"], 10)
        self.assertEqual(document["summary"]["supply_gpus"], snapshot["kpis"]["gpus"])
        self.assertEqual(document["summary"]["positions"], len(document["positions"]))
        self.assertEqual((document["meta"]["tick"], document["meta"]["epoch"], document["meta"]["seed"]), (0, 0, 4271))
        summary = document["summary"]
        self.assertTrue(summary["positions"] and summary["bids_open"] and summary["bids_declined"] and summary["bids_expired"])
        self.assertIsNotNone(summary["unrealized_usd"])
        self.assertTrue(any(site["country"] == "US" and site["position_gpus"] for site in document["sites"]), "the US map has desk positions")
        self.assertTrue(any(position["status"] == "active" for position in document["positions"]))
        self.assertTrue(any(position["status"] == "upcoming" for position in document["positions"]))

    def test_ids_follow_the_contract_example_and_stay_stable(self):
        document = self.ledger()
        by_name = {site["name"]: site["id"] for site in document["sites"]}
        self.assertEqual(by_name["Demo Site 01-A (US)"], "site-demo-01-a")
        self.assertEqual(by_name["Demo Site 02-B (NL)"], "site-demo-02-b")
        self.assertEqual([site["id"] for site in document["sites"]], sorted(by_name.values()))
        self.assertEqual([bid["id"] for bid in document["bids"]][:2], ["bid-0001", "bid-0002"])
        self.assertEqual([position["id"] for position in document["positions"]][:2], ["pos-0001", "pos-0002"])

    def test_the_json_is_strict_and_money_is_never_a_float(self):
        snapshot = self.snapshot()
        etag, body = encode_desk_ledger(snapshot)
        document = json.loads(body, parse_constant=reject_constant)
        validate_desk_ledger(document, snapshot)
        self.assertEqual(document, build_desk_ledger(snapshot))
        self.assertNotRegex(body, r"NaN|Infinity")
        self.assertRegex(etag, r'^"[0-9a-f]{64}"$')
        for position in document["positions"]:
            for name in ("price", "mark", "unrealized_usd", "notional_usd"):
                self.assertIsInstance(position[name], str)
        for bid in document["bids"]:
            self.assertIsInstance(bid["ask"], str)
            self.assertIsInstance(bid["bid"], str)

    def test_builder_does_not_touch_the_snapshot_or_use_clocks_or_global_randomness(self):
        snapshot = self.snapshot()
        before = deepcopy(snapshot)
        banned = AssertionError("global time or randomness used")
        with patch("time.time", side_effect=banned), patch("time.monotonic", side_effect=banned), \
                patch("random.random", side_effect=banned), patch("random.randrange", side_effect=banned), \
                patch("random.shuffle", side_effect=banned), patch("random.choice", side_effect=banned):
            build_desk_ledger(snapshot)
        self.assertEqual(snapshot, before)

    def test_unknown_marks_are_null_never_zero(self):
        snapshot = self.snapshot()
        document = build_desk_ledger(snapshot)
        model = document["positions"][0]["model"]
        for row in snapshot["models"]:
            if row["gpu"] == model:
                row["best"] = None
        gap = build_desk_ledger(snapshot)
        validate_desk_ledger(gap, snapshot)
        affected = [position for position in gap["positions"] if position["model"] == model]
        self.assertTrue(affected)
        for position in affected:
            self.assertIsNone(position["mark"])
            self.assertIsNone(position["unrealized_usd"])
        self.assertIsNone(gap["summary"]["unrealized_usd"])
        self.assertEqual([p["price"] for p in gap["positions"]], [p["price"] for p in document["positions"]])

    def test_nothing_to_report_is_null_not_zero(self):
        snapshot = self.snapshot()
        snapshot["quotes"] = []  # no quotes: no sites, no capacity, nothing the desk could have bid on
        document = build_desk_ledger(snapshot)
        validate_desk_ledger(document)
        summary = document["summary"]
        self.assertEqual((summary["bids"], summary["positions"], summary["sites"], summary["supply_gpus"]), (0, 0, 0, 0))
        self.assertIsNone(summary["fill_rate"])
        self.assertIsNone(summary["us_supply_share"])


class DeterminismTests(DeskLedgerCase):
    def test_same_book_same_bytes(self):
        snapshot = self.snapshot()
        self.assertEqual(encode_desk_ledger(snapshot), encode_desk_ledger(deepcopy(snapshot)))
        other, _ = start_book()
        self.assertEqual(encode_desk_ledger(snapshot), encode_desk_ledger(other.snapshot()))

    def test_a_different_seed_is_a_different_but_valid_ledger(self):
        first = self.ledger()
        other_book, _ = start_book(seed=7)
        snapshot = other_book.snapshot()
        second = build_desk_ledger(snapshot)
        validate_desk_ledger(second, snapshot)
        self.assertEqual(second["meta"]["seed"], 7)
        self.assertNotEqual(first["bids"], second["bids"])
        self.assertNotEqual(first["positions"], second["positions"])
        self.assertNotEqual(encode_desk_ledger(snapshot)[0], encode_desk_ledger(self.snapshot())[0])

    def test_many_seeds_are_valid_and_well_formed(self):
        for seed in (0, 1, 2, 3, 99999, 2**32 - 1):
            book, _ = start_book(seed=seed)
            snapshot = book.snapshot()
            document = build_desk_ledger(snapshot)
            validate_desk_ledger(document, snapshot)
            self.assertEqual(len(document["bids"]), 14, seed)
            self.assertEqual(len(document["positions"]), 6, seed)
            self.assertGreaterEqual(document["summary"]["bids_open"], 1, seed)
            self.assertTrue(document["summary"]["us_sites"] > 0, seed)

    def test_positions_are_stable_across_ticks_while_marks_move(self):
        first = self.ledger()
        statics = lambda doc: [{k: v for k, v in p.items() if k not in ("mark", "unrealized_usd", "remaining_hours")} for p in doc["positions"]]
        for _ in range(3):
            tick(self.book, self.clock, 8)
        later = self.ledger()
        self.assertEqual(later["meta"]["tick"], 24)
        self.assertEqual(statics(first), statics(later))
        self.assertEqual(first["bids"], later["bids"])
        self.assertEqual([s["placement"] for s in first["sites"]], [s["placement"] for s in later["sites"]])
        self.assertNotEqual(self.marks(first), self.marks(later), "marks follow the book's prices")
        self.assertNotEqual(first["summary"]["unrealized_usd"], later["summary"]["unrealized_usd"])

    def test_open_bids_lapse_as_the_simulated_day_advances_and_the_rest_stays_put(self):
        snapshot = self.snapshot()
        first = build_desk_ledger(snapshot)
        later = deepcopy(snapshot)
        later["meta"].update(as_of="2032-06-04", time="2032-06-04T00:00:00Z", tick=3 * 1440)
        document = build_desk_ledger(later)
        validate_desk_ledger(document)
        self.assertEqual([b["id"] for b in first["bids"]], [b["id"] for b in document["bids"]])
        self.assertLess(document["summary"]["bids_open"], first["summary"]["bids_open"])
        self.assertEqual(document["summary"]["bids_open"], 0)
        lapsed = [b for b in document["bids"] if b["status"] == "expired"]
        self.assertGreater(len(lapsed), first["summary"]["bids_expired"])
        self.assertTrue(all(b["decided"] is not None for b in lapsed))
        for old, new in zip(first["bids"], document["bids"]):
            if old["status"] != "open":
                self.assertEqual(old, new)
            self.assertEqual((old["quote_id"], old["placed"], old["gpus"], old["ask"], old["bid"]), (new["quote_id"], new["placed"], new["gpus"], new["ask"], new["bid"]))
        for old, new in zip(first["positions"], document["positions"]):
            self.assertEqual((old["id"], old["price"], old["start"], old["end"]), (new["id"], new["price"], new["start"], new["end"]))
            if old["status"] == "active":
                self.assertEqual(new["remaining_hours"], old["remaining_hours"] - 3 * 24)


class ScenarioTests(DeskLedgerCase):
    def test_price_war_lowers_every_mark_and_the_unrealized_total(self):
        before = self.ledger()
        self.book.control("scenario", "price_war")
        after = self.ledger()
        for old, new in zip(before["positions"], after["positions"]):
            self.assertLess(Decimal(new["mark"]), Decimal(old["mark"]), old["id"])
            self.assertEqual(old["price"], new["price"])
        self.assertLess(Decimal(after["summary"]["unrealized_usd"]), Decimal(before["summary"]["unrealized_usd"]))
        self.assertEqual(after["summary"]["supply_gpus"], before["summary"]["supply_gpus"])
        self.assertEqual(before["bids"], after["bids"])

    def test_supply_shock_removes_capacity_in_the_same_snapshot_as_kpis(self):
        before = self.ledger()
        self.book.control("scenario", "supply_shock")
        snapshot = self.snapshot()
        after = build_desk_ledger(snapshot)
        validate_desk_ledger(after, snapshot)
        self.assertLess(after["summary"]["supply_gpus"], before["summary"]["supply_gpus"])
        self.assertEqual(after["summary"]["supply_gpus"], snapshot["kpis"]["gpus"])
        self.assertLess(after["summary"]["us_supply_gpus"], before["summary"]["us_supply_gpus"])
        for old, new in zip(before["sites"], after["sites"]):
            self.assertLessEqual(new["capacity"]["gpus"], old["capacity"]["gpus"])
            self.assertEqual(old["placement"], new["placement"])
        self.assertEqual([p["id"] for p in before["positions"]], [p["id"] for p in after["positions"]])
        self.assertEqual(before["bids"], after["bids"])

    def test_downgrade_raises_marks_and_regrades_the_sites(self):
        before = self.ledger()
        self.book.control("scenario", "downgrade")
        after = self.ledger()
        for old, new in zip(before["positions"], after["positions"]):
            # A model whose best quote is already from a weakest-grade seller does not move; the others do.
            self.assertGreaterEqual(Decimal(new["mark"]), Decimal(old["mark"]), old["id"])
        self.assertGreater(sum(a["mark"] != b["mark"] for a, b in zip(before["positions"], after["positions"])), 0)
        self.assertGreater(Decimal(after["summary"]["unrealized_usd"]), Decimal(before["summary"]["unrealized_usd"]))
        for old, new in zip(before["sites"], after["sites"]):
            self.assertEqual(new["provider_grade"], None if old["provider_grade"] is None else "D")
        self.assertEqual(after["summary"]["supply_gpus"], before["summary"]["supply_gpus"])

    def test_repeated_shocks_keep_the_live_quote_rule(self):
        for _ in range(4):
            self.book.control("scenario", "supply_shock")
            self.book.control("scenario", "price_war")
        snapshot = self.snapshot()
        self.assertLess(snapshot["kpis"]["live_quotes"], 144, "some quotes ran out of nodes and left the live set")
        document = build_desk_ledger(snapshot)
        validate_desk_ledger(document, snapshot)
        self.assertEqual(document["summary"]["supply_gpus"], snapshot["kpis"]["gpus"])

    def test_reset_restores_the_starting_ledger_in_a_new_epoch(self):
        start = self.ledger()
        tick(self.book, self.clock, 8)
        self.book.control("scenario", "supply_shock")
        self.assertNotEqual(self.ledger()["summary"], start["summary"])
        self.book.control("reset")
        restored = self.ledger()
        self.assertEqual(restored["meta"]["epoch"], start["meta"]["epoch"] + 1)
        self.assertEqual(restored["meta"]["tick"], 0)
        self.assertEqual({**restored, "meta": {**restored["meta"], "epoch": 0}}, start)


class PlacementTests(unittest.TestCase):
    def test_tables(self):
        self.assertGreaterEqual(len(US_METROS), 20)
        self.assertEqual(len({m.state for m in US_METROS}), len(US_METROS), "primary metros are in distinct states")
        self.assertEqual(len({m.label for m in (*US_METROS, *US_OVERFLOW_METROS)}), len(US_METROS) + len(US_OVERFLOW_METROS))
        for metro in (*US_METROS, *US_OVERFLOW_METROS):
            south, north, west, east = STATE_BOXES[metro.state]
            self.assertTrue(south <= metro.lat <= north and west <= metro.lon <= east, f"{metro.label} is inside {metro.state}")
            self.assertTrue(24 < metro.lat < 50 and -125 < metro.lon < -66, f"{metro.label} is in the contiguous US")
            self.assertTrue(metro.label.endswith(", " + metro.state))
        for code, (label, lat, lon) in COUNTRY_METROS.items():
            self.assertRegex(code, r"^[A-Z]{2}$")
            self.assertNotEqual(code, "US")
            self.assertTrue(label and -90 < lat < 90 and -180 < lon < 180, code)
        self.assertTrue({"JP", "DE", "NL", "BR", "CL", "CA", "SG"} <= set(COUNTRY_METROS))

    def test_placement_covers_every_country_the_population_can_produce(self):
        codes = {code for _, countries in REGION_CLAIMS for code in countries}
        for seed in (*range(40), 4271, 99999, 2**32 - 1):
            providers, quotes = build_population(seed, as_of="2032-06-01")
            codes |= {quote["country"] for quote in quotes}
            codes |= {re.search(r"\(([A-Z]{2})\)$", site).group(1) for provider in providers for site in provider["sites"]}
        self.assertTrue({"US", "CA", "DE", "NL", "JP", "SG", "BR", "CL"} <= codes)
        placements = assign_placements({"site-" + code.lower(): code for code in sorted(codes)})
        self.assertEqual(len(placements), len(codes))
        for place in placements.values():
            self.assertTrue(place["label"] and isinstance(place["lat"], float) and isinstance(place["lon"], float))
        with self.assertRaises(UnknownCountryError):
            assign_placements({"site-x": "ZZ"})

    def test_us_sites_spread_across_distinct_states_and_never_move(self):
        for seed in (*range(30), 4271):
            providers, quotes = build_population(seed, as_of="2032-06-01")
            sites = {"site-" + quote["location"]: "US" for quote in quotes if quote["country"] == "US"}
            placed = assign_placements(sites)
            states = [place["state"] for place in placed.values()]
            self.assertEqual(len(states), len(set(states)), f"seed {seed}: {len(states)} US sites in {len(set(states))} states")
            self.assertEqual(placed, assign_placements(dict(reversed(list(sites.items())))), "input order does not matter")
        every_metro = len(US_METROS) + len(US_OVERFLOW_METROS)
        crowded = assign_placements({f"site-{n}": "US" for n in range(every_metro)})
        self.assertEqual(len({place["label"] for place in crowded.values()}), every_metro, "no metro is reused while one is free")
        self.assertEqual(len(assign_placements({f"site-{n}": "US" for n in range(every_metro + 3)})), every_metro + 3)

    def test_non_us_sites_sit_at_their_country_metro_without_a_state(self):
        document = build_desk_ledger(start_book()[0].snapshot())
        for site in document["sites"]:
            if site["country"] != "US":
                label, lat, lon = COUNTRY_METROS[site["country"]]
                self.assertEqual(site["placement"], {"label": label, "state": None, "lat": lat, "lon": lon})
        names = {site["country"]: site["placement"]["label"] for site in document["sites"]}
        self.assertEqual({code: names[code] for code in ("JP", "DE", "NL", "BR", "CL", "CA", "SG")},
                         {"JP": "Tokyo", "DE": "Frankfurt", "NL": "Amsterdam", "BR": "São Paulo", "CL": "Santiago", "CA": "Toronto", "SG": "Singapore"})


class FixtureTests(unittest.TestCase):
    def test_frontend_fixture_meets_the_contract_and_is_the_real_starting_ledger(self):
        snapshot = start_book()[0].snapshot()
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"), parse_constant=reject_constant)
        validate_desk_ledger(fixture, snapshot)
        self.assertEqual(fixture, build_desk_ledger(snapshot), "fixture drifted from the backend: python tests/test_desk_ledger.py --write-fixture")

    def test_validator_rejects_the_ways_a_ledger_goes_wrong(self):
        snapshot = start_book()[0].snapshot()
        good = build_desk_ledger(snapshot)

        def broken(mutate):
            document = deepcopy(good)
            mutate(document)
            with self.assertRaises(AssertionError):
                validate_desk_ledger(document, snapshot)

        broken(lambda d: d.update(execution_enabled=True))
        broken(lambda d: d.update(inventory_verified=True))
        broken(lambda d: d["meta"].update(ledger_basis="trades"))
        broken(lambda d: d["positions"][0].update(mark="NaN"))
        broken(lambda d: d["positions"][0].update(mark=7.1008))
        broken(lambda d: d["positions"][0].update(unrealized_usd="n/a"))
        broken(lambda d: d["positions"][0].update(mark=None))
        broken(lambda d: d["positions"][0].update(site_id="site-nowhere"))
        broken(lambda d: d["bids"][0].update(quote_id="quote-demo-9999"))
        broken(lambda d: d["bids"][0].update(position_id="pos-9999"))
        broken(lambda d: d["sites"][0]["capacity"].update(gpus=d["sites"][0]["capacity"]["gpus"] + 1))
        broken(lambda d: d["summary"].update(supply_gpus=d["summary"]["supply_gpus"] + 1))
        broken(lambda d: d["summary"].update(bids_open=99))
        broken(lambda d: d["summary"].update(fill_rate="0.0000"))
        broken(lambda d: d["sites"][0]["placement"].update(lat=None))
        broken(lambda d: d["sites"][0]["placement"].update(lat=float("nan")))
        broken(lambda d: d["sites"][1]["placement"].update(state="VA") if d["sites"][1]["country"] != "US" else d.update(simulated=False))
        broken(lambda d: next(b for b in d["bids"] if b["status"] == "open").update(decided="2032-05-31T00:00:00Z"))
        broken(lambda d: d["bids"].reverse() or d["bids"][0].update(placed="2032-06-02T00:00:00Z"))
        broken(lambda d: d.pop("bids"))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.key = "invented-desk-ledger-credential-00004"
        self.auth = {"Authorization": "Bearer " + self.key}
        self.app = create_app(api_key=self.key, store_path=Path(self.folder.name) / "paper.sqlite")
        self.book, self.clock = start_book()
        self.app.state.quote_book = self.book
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def desk(self, **headers):
        return self.client.get("/v1/book/desk", headers={**self.auth, **headers})

    def test_reads_the_ledger_with_the_books_headers(self):
        response = self.desk()
        book = self.client.get("/v1/book", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["vary"], book.headers["vary"])
        self.assertRegex(response.headers["etag"], r'^"[0-9a-f]{64}"$')
        document = json.loads(response.text, parse_constant=reject_constant)
        validate_desk_ledger(document, book.json())
        self.assertEqual(document["meta"]["tick"], book.json()["meta"]["tick"])
        self.assertEqual(response.content, self.desk().content)

    def test_conditional_reads_answer_304_and_still_authenticate(self):
        etag = self.desk().headers["etag"]
        not_modified = self.desk(**{"If-None-Match": etag})
        self.assertEqual((not_modified.status_code, not_modified.content), (304, b""))
        self.assertEqual((not_modified.headers["etag"], not_modified.headers["cache-control"]), (etag, "no-store"))
        self.assertEqual(self.desk(**{"If-None-Match": '"other", ' + etag}).status_code, 304)
        self.assertEqual(self.desk(**{"If-None-Match": "W/" + etag}).status_code, 304)
        self.assertEqual(self.desk(**{"If-None-Match": "*"}).status_code, 304)
        self.assertEqual(self.desk(**{"If-None-Match": '"other"'}).status_code, 200)
        self.assertEqual(self.client.get("/v1/book/desk", headers={"If-None-Match": etag}).status_code, 401)

    def test_the_etag_changes_when_the_book_does(self):
        etag = self.desk().headers["etag"]
        self.assertEqual(self.desk().headers["etag"], etag)
        tick(self.book, self.clock, 4)
        moved = self.desk(**{"If-None-Match": etag})
        self.assertEqual(moved.status_code, 200)
        self.assertNotEqual(moved.headers["etag"], etag)

    def test_auth_failures_are_the_books_failures(self):
        for headers in ({}, {"Authorization": "Bearer wrong-credential-000000000000000000"}, {"Authorization": "Basic abc"},
                        {"Authorization": "Bearer a", "Cookie": "compute_workbench_session=" + "0" * 64}):
            book, desk = self.client.get("/v1/book", headers=headers), self.client.get("/v1/book/desk", headers=headers)
            self.assertEqual((desk.status_code, desk.json(), desk.headers.get("www-authenticate")),
                             (book.status_code, book.json(), book.headers.get("www-authenticate")), headers)
            self.assertEqual(desk.status_code, 401)
        self.assertEqual(self.client.post("/v1/book/desk", headers=self.auth).status_code,
                         self.client.post("/v1/book", headers=self.auth).status_code)

    def test_browser_sessions_follow_the_same_cookie_and_origin_rules(self):
        origin = "http://127.0.0.1:8877"
        fetch = {"Origin": origin, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
        app = create_app(workbench_origin=origin, store_path=Path(self.folder.name) / "browser.sqlite")
        app.state.quote_book = QuoteBook(clock=lambda: 0)
        with TestClient(app, base_url=origin) as browser:
            def both(headers):
                book, desk = browser.get("/v1/book", headers=headers), browser.get("/v1/book/desk", headers=headers)
                self.assertEqual(desk.status_code, book.status_code, headers)
                if desk.status_code != 200:
                    self.assertEqual(desk.json(), book.json(), headers)
                return desk

            self.assertEqual(both(fetch).status_code, 401)
            boot = browser.post("/v1/session/bootstrap", json={}, headers=fetch)
            self.assertEqual(boot.status_code, 200)
            ok = both(fetch)
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(browser.get("/v1/book/desk", headers={**fetch, "If-None-Match": ok.headers["etag"]}).status_code, 304)
            self.assertEqual(both({**fetch, "Origin": "http://127.0.0.1:8878"}).status_code, 403)
            self.assertEqual(both({k: v for k, v in fetch.items() if k != "Sec-Fetch-Site"}).status_code, 403)
            self.assertEqual(both({**fetch, "Host": "127.0.0.1:9"}).status_code, 403)
            # A read needs no CSRF header; the control POST that moves the book does.
            self.assertEqual(browser.post("/v1/book/control", json={"action": "reset"}, headers=fetch).status_code, 403)
            csrf = {**fetch, "X-Compute-CSRF": boot.json()["csrf_token"]}
            self.assertEqual(browser.post("/v1/book/control", json={"action": "scenario", "scenario": "price_war"}, headers=csrf).status_code, 200)
            after = both(fetch)
            self.assertNotEqual(after.headers["etag"], ok.headers["etag"])
            self.assertLess(Decimal(after.json()["summary"]["unrealized_usd"]), Decimal(ok.json()["summary"]["unrealized_usd"]))

    def test_scenarios_and_reset_through_the_control_route(self):
        start = self.desk().json()
        marks = lambda doc: {p["id"]: p["mark"] for p in doc["positions"]}
        for scenario in ("price_war", "supply_shock", "downgrade"):
            posted = self.client.post("/v1/book/control", json={"action": "scenario", "scenario": scenario}, headers=self.auth)
            self.assertEqual(posted.status_code, 200)
            document = self.desk().json()
            validate_desk_ledger(document, self.client.get("/v1/book", headers=self.auth).json())
            self.assertNotEqual(document["summary"], start["summary"], scenario)
            if scenario == "supply_shock":
                self.assertLess(document["summary"]["supply_gpus"], start["summary"]["supply_gpus"])
            else:
                self.assertNotEqual(marks(document), marks(start), scenario)
        self.client.post("/v1/book/control", json={"action": "reset"}, headers=self.auth)
        restored = self.desk().json()
        book = self.client.get("/v1/book", headers=self.auth).json()
        validate_desk_ledger(restored, book)
        self.assertEqual((restored["meta"]["epoch"], restored["meta"]["tick"]), (book["meta"]["epoch"], book["meta"]["tick"]))
        self.assertEqual({**restored, "meta": {**restored["meta"], "epoch": 0}}, start)

    def test_a_country_without_a_placement_is_a_server_error_not_a_made_up_point(self):
        with patch.dict(COUNTRY_METROS):
            del COUNTRY_METROS["JP"]
            response = self.desk()
        self.assertEqual((response.status_code, response.json()), (500, {"detail": "desk_ledger_unavailable"}))
        with self.assertRaises(DeskLedgerError):
            with patch.dict(COUNTRY_METROS):
                del COUNTRY_METROS["JP"]
                build_desk_ledger(self.book.snapshot())


if __name__ == "__main__":
    if "--write-fixture" in sys.argv:
        FIXTURE.write_text(json.dumps(build_desk_ledger(start_book()[0].snapshot()), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", FIXTURE)
    else:
        unittest.main()
