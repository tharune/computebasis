"""Deterministic synthetic suppliers and offers, built solely from invented rules."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import random

from .seed import AS_OF, BASE_PRICE, DEFAULT_SEED, MODELS, TIER_KEYS, simulation_inputs

REGION_CLAIMS = (("North America", ("US", "CA")), ("Europe", ("DE", "NL")),
    ("Asia Pacific", ("JP", "SG")), ("Latin America", ("BR", "CL")))


def _ratings(index):
    group, member = divmod(index, 8)
    if group == 0:
        values = [4] * 6
    elif group == 1:
        values = [3] * 6; values[member % 6] = 4
    elif group == 2:
        values = [2 + (category + member) % 2 for category in range(6)]
    elif member == 0:
        values = [0] * 6
    elif member == 1:
        values = [1] * 6
    else:
        values = [(category + member) % 2 for category in range(6)]
    if index == 30:
        values[4] = None
    if index == 31:
        values[5] = None
    return dict(zip(TIER_KEYS, values))


def build_population(seed_value=DEFAULT_SEED, *, as_of=AS_OF):
    """Return fresh provider/quote lists for an explicitly declared simulation date.

    Inputs are bounded, there is no I/O, and all provider/site/rating/price/term
    claims are invented. Null terms are deliberate unknowns, not implied zero.
    """
    day = simulation_inputs(seed_value, as_of)
    rng = random.Random(seed_value)
    providers, quotes = [], []
    for index in range(32):
        ordinal = index + 1
        region, countries = REGION_CLAIMS[index % len(REGION_CLAIMS)]
        site_count = 1 + rng.randrange(3)
        sites = ["Demo Site " + f"{ordinal:02d}" + "-" + chr(65 + site) + " (" + countries[site % 2] + ")"
            for site in range(site_count)]
        kind = "Reseller" if index % 3 == 2 else "Owner"
        provider_id = f"provider-demo-{ordinal:03d}"
        providers.append({"id": provider_id, "name": ("Sample Reseller " if kind == "Reseller" else "Demo Supplier ") + f"{ordinal:02d}",
            "kind": kind, "region": region, "sites": sites, "tiers": _ratings(index),
            "changed_tick": -1, "synthetic": True})
        for model_index, model in enumerate(MODELS):
            pattern = index % 8
            offset = (-14, -5, -1, 14, -10, -30, 84, -3)[pattern]
            available = day + timedelta(days=offset)
            lead = (offset + 6) // 7 + rng.randrange(1, 5) if offset > 0 else rng.randrange(0, 7)
            posted = available - timedelta(days=7 * lead)
            expiry = None if pattern == 2 else day + timedelta(days=-3 if pattern == 1 else 18 + rng.randrange(55))
            updated = None if pattern == 5 else max(posted, day - timedelta(days=rng.randrange(4)))
            location_index = (index + model_index) % site_count
            gpus = 72 if model == "GB300" else rng.choice((4, 8)) if model in {"B300", "B200", "H200", "H100"} else rng.choice((1, 2, 4))
            nodes = 4 + rng.randrange(37)
            with localcontext() as arithmetic:
                arithmetic.prec = 48
                price = Decimal(BASE_PRICE[model]) * Decimal(8200 + rng.randrange(4401)) / Decimal(10000)
                encoded_price = format(price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN), "f")
            deposit_percent = rng.choice((0, 7, 18, 28, 43, 57, 71))
            deposit = None if pattern == 2 else "0" if deposit_percent == 0 else "0." + f"{deposit_percent:02d}"
            quotes.append({"id": f"quote-demo-{len(quotes) + 1:04d}", "provider_id": provider_id, "gpu": model,
                "gpus_per_node": gpus, "nodes": nodes, "price": encoded_price, "currency": "USD", "price_unit": "gpu_hour",
                "months": rng.choice((1, 2, 3, 5, 7, 9, 12, 18)), "down_payment": deposit,
                "payment_days": rng.choice((0, 14, 21, 35, 49, 63)), "location": sites[location_index],
                "country": countries[location_index % 2],
                "interconnect": None if pattern == 2 and model_index % 2 == 0 else "Simulated fabric" if gpus > 4 else "Simulated PCIe",
                "cooling": None if pattern == 2 and model_index % 2 == 1 else "Simulated liquid" if model_index < 3 else "Simulated air",
                "moq": 1 + rng.randrange(min(nodes, 5)), "lead_weeks": lead,
                "available": available.isoformat(), "expires": None if expiry is None else expiry.isoformat(),
                "posted": posted.isoformat(), "updated": None if updated is None else updated.isoformat(),
                "posted_tick": 0, "changed_tick": -1, "synthetic": True})
    return providers, quotes


__all__ = ["AS_OF", "BASE_PRICE", "MODELS", "build_population"]
