"""Independent simulation declarations, with no document or market inputs."""
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from types import MappingProxyType

AS_OF = "2032-06-01"
DEFAULT_SEED = 4271
PROVIDER_COUNT = 32
QUOTE_COUNT = 192
MODELS = ("B300", "GB300", "B200", "H200", "H100", "Pro 6000")
TIER_KEYS = ("certification", "dc_tier", "sla", "delivery", "credit", "responsiveness")

# Wholly invented anchors for this simulation, not quotes, forecasts, historical
# averages, publisher prices, physical benchmarks or bid/ask midpoints.
BASE_PRICE = MappingProxyType({"B300": "8.17", "GB300": "11.43", "B200": "6.29",
    "H200": "4.83", "H100": "3.17", "Pro 6000": "1.79"})

PROVIDER_FIELDS = frozenset({"id", "name", "kind", "region", "sites", "tiers", "changed_tick", "synthetic"})
QUOTE_FIELDS = frozenset({"id", "provider_id", "gpu", "gpus_per_node", "nodes", "price", "currency", "price_unit",
    "months", "down_payment", "payment_days", "location", "country", "interconnect", "cooling", "moq",
    "lead_weeks", "available", "expires", "posted", "updated", "posted_tick", "changed_tick", "synthetic"})


def simulation_inputs(seed_value, as_of):
    if type(seed_value) is not int or not 0 <= seed_value < 2**32:
        raise ValueError("simulation seed must be an integer in [0, 2**32)")
    if not isinstance(as_of, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", as_of):
        raise ValueError("simulation assessment date must use YYYY-MM-DD")
    try:
        instant = date.fromisoformat(as_of)
    except ValueError:
        raise ValueError("simulation assessment date is invalid") from None
    if not date(2000, 1, 1) <= instant <= date(2099, 12, 1):
        raise ValueError("simulation assessment date is outside the supported 2000–2099 window")
    return instant


def _money(value, *, fraction=False, positive=False):
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        raise ValueError("simulation financial values require plain decimal strings")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("simulation financial decimal is invalid") from None
    if positive and amount <= 0 or fraction and not 0 <= amount <= 1:
        raise ValueError("simulation financial value is outside its declared bounds")


def validate_population(providers, quotes, *, as_of=AS_OF):
    """Validate only the independent generator's declared shape, never an import."""
    simulation_inputs(DEFAULT_SEED, as_of)
    if not isinstance(providers, list) or len(providers) != PROVIDER_COUNT or not isinstance(quotes, list) or len(quotes) != QUOTE_COUNT:
        raise ValueError("simulation population requires 32 providers and 192 quotes")
    provider_ids = set()
    for provider in providers:
        if not isinstance(provider, Mapping) or set(provider) != PROVIDER_FIELDS:
            raise ValueError("simulation provider shape mismatch")
        if not isinstance(provider["id"], str) or not re.fullmatch(r"provider-demo-[0-9]{3}", provider["id"]) or provider["id"] in provider_ids:
            raise ValueError("simulation provider identity mismatch")
        provider_ids.add(provider["id"])
        if (not isinstance(provider["name"], str) or not re.fullmatch(r"(?:Demo Supplier|Sample Reseller) [0-9]{2}", provider["name"])
                or provider["kind"] not in {"Owner", "Reseller"} or provider["synthetic"] is not True or provider["changed_tick"] != -1):
            raise ValueError("simulation provider label or provenance mismatch")
        if not isinstance(provider["sites"], list) or not 1 <= len(provider["sites"]) <= 3 or any(not isinstance(site, str) or not site.startswith("Demo Site ") for site in provider["sites"]):
            raise ValueError("simulation site claims mismatch")
        tiers = provider["tiers"]
        if not isinstance(tiers, Mapping) or set(tiers) != set(TIER_KEYS) or any(value is not None and (type(value) is not int or not 0 <= value <= 4) for value in tiers.values()):
            raise ValueError("simulation tiers require 0–4 higher-is-stronger or null")
    quote_ids, totals = set(), {model: 0 for model in MODELS}
    for quote in quotes:
        if not isinstance(quote, Mapping) or set(quote) != QUOTE_FIELDS:
            raise ValueError("simulation quote shape mismatch")
        if (not isinstance(quote["id"], str) or not re.fullmatch(r"quote-demo-[0-9]{4}", quote["id"]) or quote["id"] in quote_ids
                or quote["provider_id"] not in provider_ids or quote["gpu"] not in totals):
            raise ValueError("simulation quote identity mismatch")
        quote_ids.add(quote["id"]); totals[quote["gpu"]] += 1
        if quote["synthetic"] is not True or quote["currency"] != "USD" or quote["price_unit"] != "gpu_hour" or quote["changed_tick"] != -1 or quote["posted_tick"] != 0:
            raise ValueError("simulation quote provenance or rate basis mismatch")
        for key in ("gpus_per_node", "nodes", "months", "moq"):
            if type(quote[key]) is not int or not 1 <= quote[key] <= 128:
                raise ValueError("simulation quantity requires bounded positive whole values")
        if quote["moq"] > quote["nodes"] or quote["gpus_per_node"] * quote["nodes"] > 8192:
            raise ValueError("simulation whole-node allocation mismatch")
        for key in ("payment_days", "lead_weeks"):
            if type(quote[key]) is not int or not 0 <= quote[key] <= 128:
                raise ValueError("simulation timing requires bounded nonnegative integers")
        _money(quote["price"], positive=True)
        if quote["down_payment"] is not None:
            _money(quote["down_payment"], fraction=True)
        for key in ("available", "expires", "posted", "updated"):
            if quote[key] is None and key in {"expires", "updated"}:
                continue
            if not isinstance(quote[key], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", quote[key]):
                raise ValueError("simulation quote dates require explicit calendar strings")
            date.fromisoformat(quote[key])
    if any(count != 32 for count in totals.values()):
        raise ValueError("simulation population must contain 32 quotes per model")
    return {"providers": PROVIDER_COUNT, "quotes": QUOTE_COUNT, "quotes_per_model": totals,
        "fixture_label": "independent simulation fixture", "simulated": True, "execution_enabled": False}


def seed_payload(seed_value=DEFAULT_SEED, *, as_of=AS_OF):
    from .population import build_population
    providers, quotes = build_population(seed_value, as_of=as_of)
    return {"schema_version": "independent-quote-book-fixture/1.0", "fixture_label": "independent simulation fixture",
        "data_origin": "generated_only_without_documents_vendor_data_or_customer_inputs", "seed_value": seed_value,
        "simulation_as_of": as_of, "simulated": True, "execution_enabled": False,
        "market_evidence_admitted": False, "inventory_ownership_verified": False,
        "rating_scale": {"minimum": 0, "maximum": 4, "direction": "higher_is_stronger", "unknown": None},
        "price_basis": {"currency": "USD", "unit": "gpu_hour", "decimal_places": 4,
            "meaning": "invented simulation rate_for_declared_whole_GPU_allocation"},
        "base_price_assumptions": dict(BASE_PRICE), "providers": providers, "quotes": quotes}
