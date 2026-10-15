"""Invented desk positions and brokered bids, laid over the simulated quote book (`GET /v1/book/desk`).

Everything here is derived from the book's own snapshot and the starting population its seed builds, with no
clock, no global state and no randomness outside one seeded generator, so the same book gives the same bytes:

* Sites are one per distinct quote `location` (placement: `desk_placement`). Capacity counts follow the book's
  own live-quote rule, so `summary.supply_gpus` equals the snapshot's `kpis.gpus`.
* Bids are invented against quotes of the *starting* population (so they join to the book and never move);
  their timestamps hang off the epoch's starting day. Only the open-to-expired lapse and a position's
  active/upcoming status read the snapshot's `as_of`.
* Positions are the filled bids, held at the bid price. They are stable while the epoch lasts; `mark` and
  `unrealized_usd` move with the book (`models[].best.risk_adjusted`, the best eligible all-in cost per model).

None of it is a trade, inventory, a firm price or executable. See docs/desk-ledger-contract.md.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json
import random
import re

from .desk_placement import DeskLedgerError, assign_placements
from .seed import MODELS

SCHEMA_VERSION = "synthetic-desk-ledger/1.0"
LEDGER_BASIS = "deterministic_invented_desk_positions_and_bids_not_trades"
PLACEMENT_BASIS = "illustrative_metro_assignment_not_vendor_location"
UNREALIZED_BASIS = "mark_is_current_best_eligible_all_in_cost_per_model"
MARK_BASIS = "model_best_eligible_all_in"

BID_COUNT = 14
OPEN_BIDS = 4
US_BIDS = 5                  # bids placed on US sites, so the US map has desk activity when the book has US sites
MIN_US_FILLED = 2
MIN_MONTHS = 5               # positions run at least five months, so they outlast a long demo
MAX_BID_GPUS = 128           # no bid, and no minimum order the desk would accept, above this many GPUs
DISCOUNT_PERMILLE = (20, 91)  # a bid is 2% to 9% under the ask
CHEAPEST_SHARE = 3           # bids go to the cheapest third of each model's usable asks
BID_VALID = timedelta(hours=72)
TERM_FIELDS = ("down_payment", "expires", "interconnect", "cooling")

_PRICE, _CENT, _RATE = Decimal("0.0001"), Decimal("0.01"), Decimal("0.0001")


def _text(value, step):
    rounded = value.quantize(step, rounding=ROUND_HALF_EVEN)
    return format(rounded.copy_abs() if rounded == 0 else rounded, "f")


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_months(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return day.replace(year=year, month=month, day=min(day.day, monthrange(year, month)[1]))


def _site_ids(names):
    """Stable ids from the book's site names: "Demo Site 01-A (US)" becomes "site-demo-01-a"."""
    ids = {}
    for name in names:
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"\s*\([A-Z]{2}\)\s*$", "", name).lower()).strip("-")
        ids[name] = "site-demo-" + slug[len("demo-site-"):] if slug.startswith("demo-site-") else "site-" + slug
    taken = {}
    for name, site_id in ids.items():
        taken.setdefault(site_id, []).append(name)
    for site_id, group in taken.items():
        if len(group) > 1:
            for name in group:
                ids[name] = site_id + "-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:6]
    return ids


def _live(row, when):
    """The book's own rule (the quotes counted in kpis.live_quotes): active, with nodes, expiring after as_of."""
    expires = row.get("expires")
    return bool(row.get("active", True)) and row["nodes"] > 0 and expires is not None and date.fromisoformat(expires) > when


def _sites(snapshot, when):
    providers = {row["id"]: row for row in snapshot["providers"]}
    by_location = {}
    for row in sorted(snapshot["quotes"], key=lambda row: row["id"]):
        by_location.setdefault(row["location"], []).append(row)
    ids = _site_ids(by_location)
    placements = assign_placements({ids[name]: rows[0]["country"] for name, rows in by_location.items()})
    sites = []
    for name, rows in by_location.items():
        live = [row for row in rows if _live(row, when)]
        eligible = [row for row in live if row.get("eligible") is True]
        models = {}
        for row in live:
            models[row["gpu"]] = models.get(row["gpu"], 0) + row["gpus"]
        provider = providers[rows[0]["provider_id"]]
        sites.append({"id": ids[name], "name": name, "provider_id": provider["id"], "provider": provider["name"],
            "provider_grade": provider.get("grade"), "country": rows[0]["country"], "placement": placements[ids[name]],
            "capacity": {"gpus": sum(row["gpus"] for row in live), "quotes": len(live),
                "eligible_quotes": len(eligible), "eligible_gpus": sum(row["gpus"] for row in eligible),
                "models": dict(sorted(models.items()))},
            "position_gpus": 0, "open_bid_gpus": 0})
    return sorted(sites, key=lambda site: site["id"])


def _starting_pool(snapshot, seed, day0):
    """Starting-population quotes a desk might plausibly have bid on: complete terms, rated seller, long enough, cheapest third."""
    from .population import build_population
    providers, quotes = build_population(seed, as_of=day0.isoformat())
    rated = {row["id"] for row in providers if all(value is not None for value in row["tiers"].values())}
    rows = {row["id"]: row for row in snapshot["quotes"]}
    pool = []
    for quote in quotes:
        row = rows.get(quote["id"])
        if (row is None or (row["provider_id"], row["gpu"], row["location"]) != (quote["provider_id"], quote["gpu"], quote["location"])
                or quote["provider_id"] not in rated or quote["months"] < MIN_MONTHS or quote["price"] is None
                or quote["moq"] * quote["gpus_per_node"] > MAX_BID_GPUS
                or any(quote[name] is None for name in TERM_FIELDS) or date.fromisoformat(quote["expires"]) <= day0):
            continue
        pool.append(quote)
    prices = {}
    for quote in pool:
        prices.setdefault(quote["gpu"], []).append(Decimal(quote["price"]))
    ceiling = {model: sorted(values)[(len(values) - 1) // CHEAPEST_SHARE] for model, values in prices.items()}
    return sorted((quote for quote in pool if Decimal(quote["price"]) <= ceiling[quote["gpu"]]), key=lambda quote: quote["id"])


def _choose(rng, pool):
    """BID_COUNT distinct quotes at distinct sites, US first, rotating through the models."""
    pool = list(pool)
    rng.shuffle(pool)
    chosen, used, sites = [], set(), set()

    def take(source, limit, distinct_sites):
        for _ in range(limit):
            wanted = MODELS[len(chosen) % len(MODELS)]
            fits = [quote for quote in source if quote["id"] not in used and (not distinct_sites or quote["location"] not in sites)]
            pick = next((quote for quote in fits if quote["gpu"] == wanted), fits[0] if fits else None)
            if pick is None:
                return
            chosen.append(pick)
            used.add(pick["id"])
            sites.add(pick["location"])

    take([quote for quote in pool if quote["country"] == "US"], US_BIDS, True)
    take([quote for quote in pool if quote["country"] != "US"], BID_COUNT - len(chosen), True)
    take(pool, BID_COUNT - len(chosen), False)
    rng.shuffle(chosen)
    return chosen


def _spread(rng, count, newest, oldest):
    """`count` strictly increasing placement moments, as minutes before the epoch's first midnight (oldest first)."""
    if not count:
        return []
    width = (oldest - newest) // count
    return [oldest - index * width - rng.randrange(width) for index in range(count)]


def _plan(snapshot, day0, when, midnight0, now, seed):
    rng = random.Random(int.from_bytes(hashlib.sha256(f"computebasis-desk-ledger/1.0:{seed}".encode("ascii")).digest()[:8], "big"))
    chosen = _choose(rng, _starting_pool(snapshot, seed, day0))
    open_count = min(OPEN_BIDS, len(chosen) // 3)
    decided_count = len(chosen) - open_count
    drawn = []
    for quote in chosen:
        top = min(quote["nodes"], max(quote["moq"], MAX_BID_GPUS // quote["gpus_per_node"]))
        drawn.append({"nodes": rng.randrange(quote["moq"], top + 1), "discount": rng.randrange(*DISCOUNT_PERMILLE),
                      "fill": rng.randrange(120, 40 * 60), "decline": rng.randrange(180, 46 * 60), "lead": rng.randrange(1, 8)})
    ago = _spread(rng, decided_count, 76 * 60, 330 * 60) + _spread(rng, open_count, 3 * 60, 70 * 60)
    filled = (decided_count * 3 + 2) // 5
    expired = 1 if decided_count >= 5 else 0
    outcomes = ["filled"] * filled + ["declined"] * (decided_count - filled - expired) + ["expired"] * expired
    rng.shuffle(outcomes)
    local = [quote["country"] == "US" for quote in chosen[:decided_count]]
    swaps = min(MIN_US_FILLED, sum(local)) - sum(1 for index, flag in enumerate(local) if flag and outcomes[index] == "filled")
    for index, flag in enumerate(local):
        if swaps <= 0:
            break
        other = next((i for i, state in enumerate(outcomes) if state == "filled" and not local[i]), None)
        if flag and outcomes[index] != "filled" and other is not None:
            outcomes[index], outcomes[other] = outcomes[other], outcomes[index]
            swaps -= 1
    plans = []
    for index, (quote, values) in enumerate(zip(chosen, drawn)):
        placed = midnight0 - timedelta(minutes=ago[index])
        ask = Decimal(quote["price"])
        bid = ask * (1000 - values["discount"]) / 1000
        status = outcomes[index] if index < decided_count else "open"
        decided = None
        if status == "filled":
            decided = placed + timedelta(minutes=values["fill"])
        elif status == "declined":
            decided = placed + timedelta(minutes=values["decline"])
        elif status == "expired" or now >= placed + BID_VALID:
            # An unanswered bid lapses after its validity window; as_of is what moves an open bid there.
            status, decided = "expired", placed + BID_VALID
        plans.append({"quote": quote, "nodes": values["nodes"], "lead": values["lead"], "ask": ask, "bid": bid,
                      "status": status, "placed": placed, "decided": decided})
    return plans


def build_desk_ledger(snapshot):
    """The desk ledger for one book snapshot (`QuoteBook.snapshot()`), as plain JSON-ready data."""
    meta = snapshot["meta"]
    with localcontext() as context:
        context.prec = 60
        when = date.fromisoformat(meta["as_of"])
        clock = datetime.fromisoformat(meta["time"].replace("Z", "+00:00"))
        day0 = (clock - timedelta(minutes=meta["tick"] * meta.get("step_minutes", 1))).date()
        midnight0 = datetime(day0.year, day0.month, day0.day, tzinfo=timezone.utc)
        now = datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
        sites = _sites(snapshot, when)
        by_name = {site["name"]: site for site in sites}
        marks = {row["gpu"]: None if row["best"] is None or row["best"]["risk_adjusted"] is None
                 else Decimal(row["best"]["risk_adjusted"]).quantize(_PRICE, rounding=ROUND_HALF_EVEN) for row in snapshot["models"]}

        bids, positions = [], []
        for number, plan in enumerate(_plan(snapshot, day0, when, midnight0, now, meta["seed"]), 1):
            quote, site = plan["quote"], by_name[plan["quote"]["location"]]
            gpus = plan["nodes"] * quote["gpus_per_node"]
            bid_price = plan["bid"].quantize(_PRICE, rounding=ROUND_HALF_EVEN)
            bid = {"id": f"bid-{number:04d}", "quote_id": quote["id"], "site_id": site["id"], "provider_id": quote["provider_id"],
                   "model": quote["gpu"], "gpus": gpus, "months": quote["months"], "ask": _text(plan["ask"], _PRICE),
                   "bid": _text(bid_price, _PRICE), "status": plan["status"], "placed": _stamp(plan["placed"]),
                   "decided": None if plan["decided"] is None else _stamp(plan["decided"]), "position_id": None}
            bids.append(bid)
            if plan["status"] == "open":
                site["open_bid_gpus"] += gpus
            if plan["status"] != "filled":
                continue
            start = max(date.fromisoformat(quote["available"]), plan["decided"].date() + timedelta(days=plan["lead"]))
            end = _add_months(start, quote["months"])
            remaining = max(0, (end - max(start, when)).days) * 24
            mark = marks.get(quote["gpu"])
            bid["position_id"] = f"pos-{len(positions) + 1:04d}"
            site["position_gpus"] += gpus
            positions.append({"id": bid["position_id"], "site_id": site["id"], "provider_id": quote["provider_id"],
                "model": quote["gpu"], "gpus": gpus, "months": quote["months"], "start": start.isoformat(),
                "end": end.isoformat(), "status": "active" if start <= when else "upcoming", "price": _text(bid_price, _PRICE),
                "mark": None if mark is None else _text(mark, _PRICE), "mark_basis": MARK_BASIS,
                "unrealized_usd": None if mark is None else _text((mark - bid_price) * gpus * remaining, _CENT),
                "remaining_hours": remaining, "notional_usd": _text(bid_price * gpus * (end - start).days * 24, _CENT)})

        counts = {status: sum(bid["status"] == status for bid in bids) for status in ("open", "filled", "declined", "expired")}
        decided = counts["filled"] + counts["declined"] + counts["expired"]
        supply = sum(site["capacity"]["gpus"] for site in sites)
        us_supply = sum(site["capacity"]["gpus"] for site in sites if site["country"] == "US")
        unrealized = [position["unrealized_usd"] for position in positions]
        summary = {"positions": len(positions), "position_gpus": sum(position["gpus"] for position in positions),
            "position_notional_usd": _text(sum((Decimal(position["notional_usd"]) for position in positions), Decimal(0)), _CENT),
            "unrealized_usd": None if None in unrealized else _text(sum(map(Decimal, unrealized), Decimal(0)), _CENT),
            "unrealized_basis": UNREALIZED_BASIS, "bids": len(bids), "bids_open": counts["open"], "bids_filled": counts["filled"],
            "bids_declined": counts["declined"], "bids_expired": counts["expired"],
            "bid_gpus": sum(bid["gpus"] for bid in bids),
            "filled_gpus": sum(bid["gpus"] for bid in bids if bid["status"] == "filled"),
            "open_gpus": sum(bid["gpus"] for bid in bids if bid["status"] == "open"),
            "fill_rate": None if not decided else _text(Decimal(counts["filled"]) / decided, _RATE),
            "sites": len(sites), "us_sites": sum(site["country"] == "US" for site in sites),
            "us_supply_gpus": us_supply, "supply_gpus": supply,
            "us_supply_share": None if not supply else _text(Decimal(us_supply) / supply, _RATE)}
    return {"schema_version": SCHEMA_VERSION, "simulated": True, "synthetic": True, "source_evidence_eligible": False,
        "inventory_verified": False, "firm_price_eligible": False, "execution_enabled": False,
        "meta": {"as_of": meta["as_of"], "time": meta["time"], "tick": meta["tick"], "epoch": meta["epoch"], "seed": meta["seed"],
            "book_schema_version": meta["schema_version"], "ledger_basis": LEDGER_BASIS, "placement_basis": PLACEMENT_BASIS},
        "summary": summary, "sites": sites, "positions": positions, "bids": bids}


def encode_desk_ledger(snapshot):
    """`(etag, body)`: compact JSON in the contract's key order and a strong ETag over exactly those bytes."""
    body = json.dumps(build_desk_ledger(snapshot), separators=(",", ":"), allow_nan=False)
    return '"' + hashlib.sha256(body.encode("utf-8")).hexdigest() + '"', body


__all__ = ["DeskLedgerError", "build_desk_ledger", "encode_desk_ledger"]
