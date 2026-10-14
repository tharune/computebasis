"""Compute electricity from an allocated load profile, not a hardware premium.

The result is scenario arithmetic. Input evidence labels do not authenticate a
tariff, measured power, or a provider's inclusion terms.
"""
from collections.abc import Mapping
from decimal import Decimal, localcontext
import re

from .._numbers import calculation_precision, number, text_number
from ..domain import ValidationError, exact_decimal, utc_instant

MODEL = "allocated-power-cost/1.0.0"
ROOT_FIELDS = frozenset("currency gpu_count load_watts_per_gpu idle_watts_per_gpu shared_it_watts pue sold_gpu_hours compute_power_inclusion intervals demand_charges cost_items evidence_basis".split())
INTERVAL_FIELDS = frozenset("starts_at ends_at utilization rate".split())
RATE_FIELDS = frozenset("amount_per_kwh currency basis evidence_ref".split())
DEMAND_FIELDS = frozenset("billing_period_id starts_at ends_at allocated_peak_kw amount_per_kw currency".split())
COST_FIELDS = frozenset("id amount currency scope".split())
RATE_BASES = frozenset({"declared_tariff_energy", "wholesale_reference", "retail_all_in_reference"})


def _object(value, fields, context):
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValidationError(context + ": supply every registered field and no others")
    return value


def _entries(value, maximum, context):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValidationError(context + ": bounded list required")
    return value


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160 or any(ord(c) < 32 for c in value):
        raise ValidationError("nonempty bounded evidence or charge label required")
    return value


def _money_currency(value, currency=None):
    if not isinstance(value, str) or not re.fullmatch("[A-Z]{3}", value) or currency is not None and value != currency:
        raise ValidationError("currency: explicit conversion required before evaluation")
    return value


def _period(row):
    first, last = utc_instant(row["starts_at"]), utc_instant(row["ends_at"])
    if first >= last or first.microsecond or last.microsecond:
        raise ValidationError("period requires positive whole-second UTC coverage")
    return first, last


def _costs(items, currency):
    labels, result = set(), Decimal(0)
    for item in _entries(items, 120, "cost_items"):
        _object(item, COST_FIELDS, "cost item")
        identity = _name(item["id"])
        if identity in labels:
            raise ValidationError("duplicate allocated cost identity")
        labels.add(identity)
        _money_currency(item["currency"], currency)
        if not isinstance(item["scope"], str) or item["scope"] not in {"network", "tax", "fixed", "other_power"}:
            raise ValidationError("unregistered electricity charge scope")
        result += number(item["amount"], "allocated charge")
    return result


def _demand(items, currency, profile):
    periods, names, total = [], set(), Decimal(0)
    for item in _entries(items, 120, "demand_charges"):
        _object(item, DEMAND_FIELDS, "demand charge")
        name = _name(item["billing_period_id"])
        if name in names:
            raise ValidationError("demand billing period identity must be unique")
        names.add(name)
        first, last = _period(item)
        if first < profile[0][0] or last > profile[-1][1]:
            raise ValidationError("profile must cover the full demand billing period")
        if any(first < finish and begin < last for begin, finish in periods):
            raise ValidationError("demand billing periods cannot overlap")
        periods.append((first, last))
        measured = number(item["allocated_peak_kw"], "allocated demand peak")
        modeled = max(kw for begin, finish, kw in profile if first < finish and begin < last)
        if measured < modeled:
            raise ValidationError("demand peak below facility load within its billing period")
        _money_currency(item["currency"], currency)
        total += measured * number(item["amount_per_kw"], "demand rate")
    return total


def evaluate_power_payload(payload):
    """Evaluate a caller-declared, contiguous allocation with exact input decimals."""
    _object(payload, ROOT_FIELDS, "power scenario")
    with localcontext() as arithmetic:
        arithmetic.prec = calculation_precision(payload)
        currency = _money_currency(payload["currency"])
        GPUs = number(payload["gpu_count"], "gpu_count", positive=True)
        if GPUs > 1000000 or GPUs != GPUs.to_integral_value():
            raise ValidationError("gpu_count: whole count between one and one million required")
        idle = number(payload["idle_watts_per_gpu"], "idle_watts_per_gpu")
        loaded = number(payload["load_watts_per_gpu"], "load_watts_per_gpu")
        shared = number(payload["shared_it_watts"], "shared_it_watts")
        if idle > loaded:
            raise ValidationError("idle consumption exceeds loaded consumption")
        pue = number(payload["pue"], "pue")
        if pue < 1:
            raise ValidationError("pue cannot be less than one")
        inclusion = payload["compute_power_inclusion"]
        if not isinstance(inclusion, str) or inclusion not in {"included", "excluded", "unknown"}:
            raise ValidationError("declare compute power inclusion explicitly")
        _name(payload["evidence_basis"])
        inputs = _entries(payload["intervals"], 10000, "intervals")
        if not inputs:
            raise ValidationError("at least one electricity interval required")
        output, profile, bases = [], [], set()
        duration_sum = consumed = electricity = Decimal(0)
        for item in inputs:
            _object(item, INTERVAL_FIELDS, "power interval")
            begin, finish = _period(item)
            if profile and profile[-1][1] != begin:
                raise ValidationError("profile intervals must be ordered and contiguous")
            elapsed = finish - begin
            duration = Decimal(elapsed.days * 86400 + elapsed.seconds) / Decimal(3600)
            utilization = number(item["utilization"], "utilization", fraction=True)
            rate = _object(item["rate"], RATE_FIELDS, "electricity rate")
            _money_currency(rate["currency"], currency)
            basis = rate["basis"]
            if not isinstance(basis, str) or basis not in RATE_BASES:
                raise ValidationError("unregistered electricity price basis")
            _name(rate["evidence_ref"])
            amount = exact_decimal(rate["amount_per_kwh"])
            if abs(amount) > Decimal("1e24"):
                raise ValidationError("electricity price exceeds arithmetic range")
            gpu_watts = GPUs * (idle * (1 - utilization) + loaded * utilization)
            it_kw = (gpu_watts + shared) / Decimal(1000)
            site_kw = pue * it_kw
            kwh = duration * site_kw
            native_cost = kwh * amount
            output.append({"starts_at": item["starts_at"], "ends_at": item["ends_at"],
                "hours": text_number(duration), "utilization": text_number(utilization),
                "it_kw": text_number(it_kw), "facility_kw": text_number(site_kw),
                "kwh": text_number(kwh), "energy_cost": text_number(native_cost), "rate_basis": basis})
            profile.append((begin, finish, site_kw))
            bases.add(basis)
            duration_sum += duration
            consumed += kwh
            electricity += native_cost
        if len(bases) != 1:
            raise ValidationError("evaluate different rate bases separately")
        basis = bases.pop()
        capacity = duration_sum * GPUs
        sold = number(payload["sold_gpu_hours"], "sold_gpu_hours")
        if sold > capacity:
            raise ValidationError("sold GPU hours exceed powered GPU hours")
        demand = _demand(payload["demand_charges"], currency, profile)
        other = _costs(payload["cost_items"], currency)
        if basis == "retail_all_in_reference" and (payload["demand_charges"] or payload["cost_items"]):
            raise ValidationError("all-in reference cannot be augmented by already included charges")
        holds = []
        if inclusion == "unknown":
            holds.append("compute_quote_power_inclusion_unknown")
        if basis != "declared_tariff_energy":
            holds.append("reference_price_is_not_verified_site_tariff")
        if electricity < 0:
            holds.append("negative_energy_cost_requires_contract_credit_terms")
        total = electricity + demand + other
        incremental = {"included": Decimal(0), "excluded": total, "unknown": None}[inclusion]
        return {"model_version": MODEL, "status": "held" if holds else "indicative",
            "currency": currency, "cost_basis": basis, "power_evidence_status": "caller_declared_unverified",
            "blockers": holds, "powered_hours": text_number(duration_sum),
            "capacity_gpu_hours": text_number(capacity), "sold_gpu_hours": text_number(sold),
            "unsold_gpu_hours": text_number(capacity - sold), "energy_kwh": text_number(consumed),
            "energy_cost": text_number(electricity), "demand_cost": text_number(demand),
            "other_power_cost": text_number(other), "facility_power_cost": text_number(total),
            "compute_power_inclusion": inclusion,
            "incremental_compute_power_cost": None if incremental is None else text_number(incremental),
            "facility_cost_per_capacity_gpu_hour": text_number(total / capacity),
            "facility_cost_per_sold_gpu_hour": text_number(total / sold) if sold else None,
            "intervals": output, "execution_enabled": False,
            "warnings": ["idle_capacity_consumes_energy_even_when_unsold",
                "shared_it_power_is_total_allocated_host_network_storage_power",
                "pue_already_accounts_for_facility_overhead",
                "full_nonoverlapping_demand_periods_required_no_automatic_proration",
                "empty_charges_are_a_declaration_not_tariff_verification",
                "scenario_cost_does_not_modify_compute_prices_or_authorize_orders"]}


def power_contract():
    return {"model_version": MODEL, "fields": sorted(ROOT_FIELDS), "interval_fields": sorted(INTERVAL_FIELDS),
        "rate_fields": sorted(RATE_FIELDS), "demand_fields": sorted(DEMAND_FIELDS),
        "cost_fields": sorted(COST_FIELDS), "rate_bases": sorted(RATE_BASES),
        "decimal_encoding": "plain_decimal_strings", "missing_is_zero": False,
        "timestamps": "UTC_whole_seconds_contiguous_end_exclusive", "energy_unit": "kWh",
        "execution_enabled": False}
