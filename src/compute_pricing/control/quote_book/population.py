"""Provider and quote populations for the quote book: the workbook's rows plus invented ones in the same shape.

The extensions follow the correlations visible in the workbook: brokers quote the most and the
cheapest and leave the most fields blank, strong providers quote completely, and newer hardware has
fewer vetted suppliers. Every name and figure is fictional.
"""
from __future__ import annotations

import datetime as dt
import random
from typing import Any

from . import scoring, seed

MODELS = ("B300", "GB300", "B200", "H200", "H100", "Pro 6000")
# Mid-market price per GPU-hour by model: the median of the workbook's quotes for that model.
BASE_PRICE = {"B300": 5.53, "GB300": 6.17, "B200": 3.71, "H200": 2.39, "H100": 1.67, "Pro 6000": 1.27}
# Where a quote tends to sit against its model's mid-market, by provider grade (cheapest from D-grade sellers).
GRADE_PRICE_OFFSET = {"A": 0.04, "B": 0.01, "C": -0.03, "D": -0.09}
MODEL_WEIGHT = {"B300": 38, "H200": 18, "Pro 6000": 16, "H100": 12, "B200": 10, "GB300": 6}
NODE_CHOICES = ((4, 6), (8, 12), (16, 28), (32, 28), (64, 14), (128, 12))

REGIONS = {
    "US": (("Dallas TX", "USA"), ("Ashburn VA", "USA"), ("Chicago IL", "USA"), ("Phoenix AZ", "USA"), ("Atlanta GA", "USA")),
    "EU": (("Frankfurt", "Germany"), ("Amsterdam", "Netherlands"), ("Paris", "France"), ("Madrid", "Spain")),
    "UK": (("London", "UK"), ("Manchester", "UK")),
    "Canada": (("Toronto", "Canada"), ("Montreal", "Canada")),
    "APAC": (("Singapore", "Singapore"), ("Tokyo", "Japan"), ("Johor", "Malaysia"), ("Sydney", "Australia")),
    "India": (("Mumbai", "India"), ("Chennai", "India")),
    "Middle East": (("Dubai", "UAE"),),
    "Nordics": (("Reykjavik", "Iceland"), ("Oslo", "Norway")),
}

CITY_COUNTRY = {city: country for cities in REGIONS.values() for city, country in cities}
CITY_COUNTRY.update({"Austin TX": "USA", "Reno NV": "USA", "Las Vegas": "USA"})  # cities only the workbook uses

# (name, kind, region, target grade). Names are invented; brokers hold no facility of their own.
EXTRA_PROVIDERS = (
    ("Tidewater Compute", "Owner", "US", "A"), ("Fathom GPU", "Owner", "EU", "A"),
    ("Juniper Datacenters", "Owner", "Canada", "A"), ("Redwood AI Cloud", "Owner", "US", "A"),
    ("Stonefield Compute", "Owner", "Nordics", "B"), ("Cairn Systems", "Owner", "UK", "B"),
    ("Lumen Racks", "Owner", "APAC", "B"), ("Granite Peak Compute", "Owner", "US", "B"),
    ("Wren Datacenters", "Owner", "EU", "B"), ("Bramble Cloud", "Owner", "India", "C"),
    ("Cobalt Fabric", "Owner", "Middle East", "C"), ("Ironbridge GPU", "Owner", "UK", "C"),
    ("Sable Systems", "Owner", "APAC", "C"), ("Pinnacle Metal", "Owner", "US", "D"),
    ("Gantry Capacity (Broker)", "Reseller", "US", "D"), ("Vellum Compute (Broker)", "Reseller", "EU", "D"),
)
_TIER_ODDS = {"A": (0.70, 0.25, 0.05), "B": (0.35, 0.45, 0.20), "C": (0.15, 0.50, 0.35), "D": (0.05, 0.25, 0.70)}
_MISSING_RATE = {1: 0.03, 2: 0.12, 3: 0.38}  # per key field, by the provider's responsiveness tier


def grade_of(provider: dict[str, Any]) -> str:
    return scoring.grade_for(scoring.quality_score(provider["tiers"]))[0]


def build_providers(rng: random.Random) -> dict[str, dict[str, Any]]:
    providers: dict[str, dict[str, Any]] = {}
    for row in seed.PROVIDERS:
        providers[row["id"]] = {
            "id": row["id"], "name": row["name"], "kind": row["kind"], "region": row["regions"],
            "jurisdiction": row["jurisdiction"], "sites": row["dc_locations"], "tiers": dict(row["tiers"]),
            "weight": 1.0, "seed": True,
        }
    for index, (name, kind, region, target) in enumerate(EXTRA_PROVIDERS, start=len(seed.PROVIDERS) + 1):
        tiers = {}
        for _ in range(400):  # rejection-sample a tier pattern that lands on the target grade
            tiers = {category: rng.choices((1, 2, 3), weights=_TIER_ODDS[target])[0] for category, _ in scoring.CATEGORIES}
            if kind == "Reseller":
                tiers["dc_tier"] = 3
            if grade_of({"tiers": tiers}) == target:
                break
        sites = rng.sample(REGIONS[region], k=min(2, len(REGIONS[region])))
        providers[f"P{index:03d}"] = {
            "id": f"P{index:03d}", "name": name, "kind": kind, "region": region,
            "jurisdiction": sites[0][1], "sites": "Not stated" if kind == "Reseller" else ", ".join(site[0] for site in sites),
            "tiers": tiers, "weight": 2.5 if kind == "Reseller" else rng.choice((0.7, 1.0, 1.3, 1.8)), "seed": False,
            "_sites": sites,
        }
    for provider in providers.values():  # brokers quote the most, as in the workbook
        if provider["kind"] == "Reseller":
            provider["weight"] = max(provider["weight"], 2.5)
    return providers


def seed_quotes(providers: dict[str, dict[str, Any]], as_of: dt.date) -> dict[str, dict[str, Any]]:
    by_name = {provider["name"]: provider["id"] for provider in providers.values()}
    quotes = {}
    for row in seed.QUOTES:
        quote = dict(row, provider_id=by_name[row["provider"]], seed=True)
        del quote["provider"]
        quote["posted_tick"] = quote["changed_tick"] = 0
        quote["skew"] = 1.0  # set by the market once grades are known
        quotes[quote["id"]] = quote
    return quotes


def new_quote(rng: random.Random, number: int, providers: dict[str, dict[str, Any]], now: dt.datetime, tick: int,
              *, provider_id: str | None = None, gpu: str | None = None, backdate: bool = False, factors: dict[str, float] | None = None) -> dict[str, Any]:
    """One invented quote. Eligibility of the seller to quote a model follows its grade (new hardware is thinly vetted)."""
    pool = list(providers.values())
    if gpu is None:
        gpu = rng.choices(MODELS, weights=[MODEL_WEIGHT[m] for m in MODELS])[0]
    if provider_id is None:
        allowed = [p for p in pool if gpu != "GB300" or grade_of(p) in ("C", "D")]
        provider = rng.choices(allowed, weights=[p["weight"] for p in allowed])[0]
    else:
        provider = providers[provider_id]
    grade = grade_of(provider)
    miss = _MISSING_RATE[provider["tiers"]["responsiveness"]]

    def stated(value: Any, scale: float = 1.0) -> Any:
        return None if rng.random() < miss * scale else value

    sites = provider.get("_sites") or [(city.strip(), CITY_COUNTRY.get(city.strip())) for city in str(provider["sites"]).split(",")]
    site = rng.choice(sites)
    hidden_site = site[0] == "Not stated" or (provider["kind"] == "Reseller" and rng.random() < 0.8)
    lead = rng.choice((2, 4, 6, 8, 10, 12))
    months = rng.choices((12, 24, 36, 60), weights=(20, 25, 35, 20))[0]
    age_days = rng.uniform(0, 20) if backdate else 0.0
    posted = (now - dt.timedelta(days=age_days)).date()
    skew = rng.gauss(1, 0.03)  # this quote's lasting position against its grade's usual level
    price = BASE_PRICE[gpu] * (factors or {}).get(gpu, 1.0) * (1 + GRADE_PRICE_OFFSET[grade]) * skew
    return {
        "id": f"Q{number:03d}", "provider_id": provider["id"], "gpu": gpu, "seed": False,
        "location": None if hidden_site else stated(site[0], 0.5), "country": None if hidden_site else stated(site[1], 0.5),
        "gpus_per_node": 8, "nodes": rng.choices([n for n, _ in NODE_CHOICES], weights=[w for _, w in NODE_CHOICES])[0],
        "moq": stated(rng.choice((2, 4, 8))),
        "interconnect": stated("RoCE" if gpu == "Pro 6000" else rng.choice(("Infiniband", "RoCE"))),
        "cooling": stated("Liquid" if gpu in ("B300", "GB300") and rng.random() < 0.35 else "Air"),
        "available": (now + dt.timedelta(weeks=lead)).date().isoformat(), "lead_weeks": stated(lead),
        "price": round(price, 2), "months": stated(months, 0.5), "down_payment": stated(rng.choice((0.1, 0.2, 0.25, 0.3, 0.35))),
        "payment_days": stated(rng.choice((15, 30, 45))), "status": "Live",
        "posted": posted.isoformat(), "updated": posted.isoformat(),
        "expires": None if rng.random() < miss * 1.2 else (now + dt.timedelta(days=rng.uniform(3, 75))).date().isoformat(),
        "posted_tick": tick, "changed_tick": tick, "skew": skew,
    }
