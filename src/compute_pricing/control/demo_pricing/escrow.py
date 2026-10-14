"""Bounded hypothetical hourly service vesting with segregated asset principal.

No balance is a bank balance, source observation, verified entitlement or payment.
Native asset units and USD service obligations remain separate throughout.
"""
from datetime import timedelta
from decimal import Decimal, localcontext
import re

from compute_pricing.control._numbers import calculation_precision, number, text_number
from compute_pricing.control.domain import ValidationError, utc_instant

SCHEMA = "hourly-escrow/1.0"
MAX_HOURS = 2160
MAX_CHART_ROWS = 24
PARTIES = ("provider", "broker", "buyer")
FIELDS = (
    "schema_version", "delivery_start", "delivery_end", "gpu_count", "service_basis",
    "hourly_service_fractions", "buyer_rate", "provider_rate", "prefunded_principal",
    "asset_kind", "asset_unit", "asset_price_usd", "liquidity", "depeg_status",
    "annual_yield_apr", "yield_shares", "yield_access", "release_authorized",
    "refund_at_end", "entitlement_basis", "opening_broker_cash", "minimum_broker_cash",
    "broker_operating_cost_per_hour", "provider_risk_grade", "buffer_hours", "collateral_fraction",
)


def escrow_contract():
    """An unknown input template, not an automatically executable example."""
    return {
        "schema_version": SCHEMA, "required_fields": list(FIELDS),
        "template_unknown": {name: None for name in FIELDS},
        "decimal_encoding": "finite_plain_decimal_strings", "currency": "USD",
        "rate_unit": "USD_per_gpu_hour", "maximum_hours": MAX_HOURS,
        "maximum_chart_rows": MAX_CHART_ROWS, "yield_day_count": "ACT/365F",
        "yield_basis": "opening_restricted_principal_native_asset_units_noncompounding",
        "asset_kinds": ["bank_deposit", "stable_asset"],
        "service_bases": ["delivered", "available_sla"],
        "yield_parties": list(PARTIES), "unknown_values_defaulted": False,
        "simulation_only": True, "source_evidence_eligible": False,
        "legal_entitlements_verified": False, "execution_enabled": False,
    }


def _choice(value, allowed, label):
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError(f"{label}: explicit supported choice required")
    return value


def _boolean(value, label):
    if value is not None and type(value) is not bool:
        raise ValidationError(f"{label}: explicit true, false or null required")
    return value


def _integer(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{label}: bounded whole integer required")
    return value


def _validate(payload):
    if not isinstance(payload, dict) or set(payload) != set(FIELDS):
        raise ValidationError("escrow: complete known input fields required")
    if payload["schema_version"] != SCHEMA:
        raise ValidationError("escrow: unsupported schema")
    start, end = utc_instant(payload["delivery_start"]), utc_instant(payload["delivery_end"])
    seconds = (end - start).total_seconds()
    if seconds <= 0 or seconds % 3600 or seconds > MAX_HOURS * 3600:
        raise ValidationError("escrow: positive whole-hour horizon at most 2160 hours required")
    hours = int(seconds // 3600)
    gpu_count = _integer(payload["gpu_count"], "gpu_count", 1, 1000000)
    fractions = payload["hourly_service_fractions"]
    if not isinstance(fractions, list) or len(fractions) != hours:
        raise ValidationError("hourly_service_fractions: one explicit fraction per hour required")
    service = [number(value, "hourly service", fraction=True) for value in fractions]
    kind = _choice(payload["asset_kind"], {"bank_deposit", "stable_asset"}, "asset_kind")
    unit = payload["asset_unit"]
    if not isinstance(unit, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", unit):
        raise ValidationError("asset_unit: bounded explicit native asset unit required")
    mark = None if payload["asset_price_usd"] is None else number(payload["asset_price_usd"], "asset price", positive=True)
    depeg = _choice(payload["depeg_status"], {"not_applicable", "normal", "depegged", "unknown"}, "depeg_status")
    if kind == "bank_deposit" and (unit != "USD" or mark not in (None, Decimal(1)) or depeg != "not_applicable"):
        raise ValidationError("bank_deposit: explicit USD unit, USD mark and not-applicable depeg required")
    if kind == "stable_asset" and depeg == "not_applicable":
        raise ValidationError("stable_asset: depeg status must be declared")
    shares = payload["yield_shares"]
    if not isinstance(shares, dict) or set(shares) != set(PARTIES):
        raise ValidationError("yield_shares: all three party fractions required")
    shares = {party: number(value, "yield share", fraction=True) for party, value in shares.items()}
    if sum(shares.values(), Decimal(0)) != 1:
        raise ValidationError("yield_shares: exact sum of one required")
    basis = payload["entitlement_basis"]
    if basis is not None and (not isinstance(basis, str) or basis != basis.strip() or not basis or len(basis) > 512):
        raise ValidationError("entitlement_basis: explicit bounded assertion or null required")
    grade = payload["provider_risk_grade"]
    if grade is not None:
        _choice(grade, {"A", "B", "C", "D"}, "provider_risk_grade")
    amounts = {name: number(payload[name], name) for name in
               ("buyer_rate", "provider_rate", "prefunded_principal", "opening_broker_cash",
                "minimum_broker_cash", "broker_operating_cost_per_hour")}
    return {
        **amounts, "start": start, "hours": hours, "gpu_count": gpu_count, "service": service,
        "service_basis": _choice(payload["service_basis"], {"delivered", "available_sla"}, "service_basis"),
        "asset_kind": kind, "asset_unit": unit, "mark": mark, "depeg_status": depeg,
        "liquidity": _choice(payload["liquidity"], {"liquid", "illiquid", "unknown"}, "liquidity"),
        "annual_yield_apr": number(payload["annual_yield_apr"], "yield APR", fraction=True), "shares": shares,
        "yield_access": _choice(payload["yield_access"], {"hourly_withdrawable", "accrued_only", "unknown"}, "yield_access"),
        "release_authorized": _boolean(payload["release_authorized"], "release_authorized"),
        "refund_at_end": _boolean(payload["refund_at_end"], "refund_at_end"), "entitlement_basis": basis,
        "provider_risk_grade": grade, "buffer_hours": _integer(payload["buffer_hours"], "buffer_hours", 0, hours),
        "collateral_fraction": number(payload["collateral_fraction"], "collateral fraction", fraction=True),
    }


def _time(value):
    return value.isoformat().replace("+00:00", "Z")


def _text(value):
    return None if value is None else text_number(value)


def evaluate_escrow(payload):
    """Evaluate explicit simulated obligations; return sampled rows and full totals."""
    with localcontext() as context:
        context.prec = calculation_precision(payload) + 32
        return _evaluate(_validate(payload))


def _evaluate(p):
    zero = Decimal(0)
    mark, hours, gpu = p["mark"], p["hours"], p["gpu_count"]
    principal = p["prefunded_principal"]
    buyer_maximum = p["buyer_rate"] * gpu * hours
    opening_value = None if mark is None else principal * mark
    prefund_gap = None if mark is None else max(zero, buyer_maximum - opening_value)
    holds = []
    if mark is None:
        holds.append("asset_price_unknown")
    if p["liquidity"] != "liquid":
        holds.append("asset_" + p["liquidity"])
    if p["depeg_status"] in {"depegged", "unknown"}:
        holds.append("depeg_" + p["depeg_status"])
    if p["release_authorized"] is not True:
        holds.append("principal_release_unconfirmed" if p["release_authorized"] is None else "principal_release_denied")
    release_allowed = not holds
    yield_holds = list(holds)
    if p["yield_access"] != "hourly_withdrawable":
        yield_holds.append("yield_" + p["yield_access"])
    if p["entitlement_basis"] is None:
        yield_holds.append("yield_entitlement_unknown")
    yield_available = not yield_holds
    unearned, earned = principal, zero
    yield_accrued = {party: zero for party in PARTIES}
    yield_paid = {party: zero for party in PARTIES}
    broker_cash = unconstrained_cash = p["opening_broker_cash"]
    minimum_actual = minimum_unconstrained = broker_cash
    buyer_earned = provider_earned = operating_earned = zero
    provider_paid = operating_paid = principal_released = funded_earnings = zero
    provider_owed = operating_owed = zero
    service_gpu_hours = zero
    samples = set(range(hours)) if hours <= MAX_CHART_ROWS else {
        index * (hours - 1) // (MAX_CHART_ROWS - 1) for index in range(MAX_CHART_ROWS)}
    rows = []
    for hour, fraction in enumerate(p["service"]):
        opening_locked = unearned + earned
        hourly_yield = opening_locked * p["annual_yield_apr"] / Decimal(365 * 24)
        for party in PARTIES:
            yield_accrued[party] += hourly_yield * p["shares"][party]
        service = gpu * fraction
        service_gpu_hours += service
        buyer_amount = service * p["buyer_rate"]
        provider_amount = service * p["provider_rate"]
        buyer_earned += buyer_amount
        provider_earned += provider_amount
        operating_earned += p["broker_operating_cost_per_hour"]
        if mark is not None:
            allocation = min(unearned, buyer_amount / mark)
            unearned -= allocation
            earned += allocation
            funded_earnings += allocation * mark
        released_assets = earned if release_allowed else zero
        if release_allowed:
            earned = zero
        principal_released += released_assets
        released_usd = released_assets * mark if release_allowed else zero
        broker_yield_cash = zero
        if yield_available:
            for party in PARTIES:
                payable = yield_accrued[party] - yield_paid[party]
                yield_paid[party] += payable
                if party == "broker":
                    broker_yield_cash += payable * mark
        broker_cash += released_usd + broker_yield_cash
        provider_owed += provider_amount
        provider_payment = min(provider_owed, broker_cash)
        provider_owed -= provider_payment
        provider_paid += provider_payment
        broker_cash -= provider_payment
        operating_owed += p["broker_operating_cost_per_hour"]
        operating_payment = min(operating_owed, broker_cash)
        operating_owed -= operating_payment
        operating_paid += operating_payment
        broker_cash -= operating_payment
        unconstrained_cash += released_usd + broker_yield_cash - provider_amount - p["broker_operating_cost_per_hour"]
        minimum_actual = min(minimum_actual, broker_cash)
        minimum_unconstrained = min(minimum_unconstrained, unconstrained_cash)
        if hour in samples:
            rows.append({"hour": hour + 1, "starts_at": _time(p["start"] + timedelta(hours=hour)),
                "ends_at": _time(p["start"] + timedelta(hours=hour + 1)), "service_fraction": _text(fraction),
                "opening_restricted_principal_asset_units": _text(opening_locked),
                "yield_accrued_asset_units": _text(hourly_yield),
                "buyer_service_earned_usd": _text(buyer_amount), "provider_service_earned_usd": _text(provider_amount),
                "principal_released_asset_units": _text(released_assets),
                "closing_restricted_principal_asset_units": _text(unearned + earned),
                "unearned_refundable_principal_asset_units": _text(unearned if mark is not None else None),
                "provider_service_paid_usd": _text(provider_payment), "provider_service_owed_usd": _text(provider_owed),
                "cumulative_provider_service_paid_usd": _text(provider_paid),
                "cumulative_buyer_service_earned_usd": _text(buyer_earned),
                "cumulative_broker_yield_cash_usd": _text(None if mark is None else yield_paid["broker"] * mark),
                "broker_cash_usd": _text(broker_cash), "unconstrained_broker_cash_usd": _text(unconstrained_cash)})
    refundable = unearned if mark is not None else None
    refund = unearned if release_allowed and p["refund_at_end"] is True else zero
    if refund:
        unearned -= refund
    unpaid_yield = {party: yield_accrued[party] - yield_paid[party] for party in PARTIES}
    tail_unknown = mark is None or (p["refund_at_end"] is None and refundable != zero)
    tail_resolved = None if tail_unknown else unearned + earned == 0 and sum(unpaid_yield.values(), zero) == 0
    broker_yield_income = None if mark is None else yield_accrued["broker"] * mark
    economic_margin = buyer_earned - provider_earned - operating_earned
    extra_cash = max(zero, p["minimum_broker_cash"] - minimum_unconstrained)
    unknown_funding = mark is None or p["liquidity"] == "unknown" or p["depeg_status"] == "unknown" or p["release_authorized"] is None
    cash_feasible = None if unknown_funding else not holds and prefund_gap == 0 and extra_cash == 0 and provider_owed == 0 and operating_owed == 0
    maximum_provider = p["provider_rate"] * gpu * hours
    return {
        "schema_version": SCHEMA, "classification": "hypothetical_hourly_escrow", "simulated": True,
        "source_evidence_eligible": False, "legal_entitlements_verified": False,
        "inventory_verified": False, "firm_price_eligible": False, "execution_enabled": False,
        "asset": {"kind": p["asset_kind"], "unit": p["asset_unit"], "declared_price_usd": _text(mark),
            "price_basis": "caller_declared_scenario_mark_not_verified", "liquidity": p["liquidity"],
            "depeg_status": p["depeg_status"], "stable_parity_verified": False, "deposit_insurance_verified": False},
        "service": {"basis": p["service_basis"], "hours": hours, "gpu_count": gpu,
            "maximum_gpu_hours": str(gpu * hours), "recognized_gpu_hours": _text(service_gpu_hours),
            "buyer_rate_usd_per_gpu_hour": _text(p["buyer_rate"]), "provider_rate_usd_per_gpu_hour": _text(p["provider_rate"])},
        "prefunding": {"principal_asset_units": _text(principal), "declared_value_usd": _text(opening_value),
            "maximum_buyer_billings_usd": _text(buyer_maximum), "shortfall_usd": _text(prefund_gap),
            "full_prefunding_declared": None if prefund_gap is None else prefund_gap == 0,
            "available_broker_funding_from_unearned_principal_usd": "0"},
        "settlement": {"buyer_service_earned_usd": _text(buyer_earned),
            "provider_service_earned_usd": _text(provider_earned), "provider_service_paid_usd": _text(provider_paid),
            "provider_service_owed_usd": _text(provider_owed), "broker_operating_cost_earned_usd": _text(operating_earned),
            "broker_operating_cost_paid_usd": _text(operating_paid), "broker_operating_cost_owed_usd": _text(operating_owed),
            "broker_service_economic_margin_usd": _text(economic_margin),
            "principal_released_asset_units": _text(principal_released),
            "earned_unreleased_principal_asset_units": _text(earned if mark is not None else None),
            "refundable_principal_before_terminal_refund_asset_units": _text(refundable),
            "terminal_buyer_refund_asset_units": _text(refund),
            "terminal_buyer_refund_usd": _text(None if mark is None else refund * mark),
            "unearned_liability_remaining_asset_units": _text(unearned if mark is not None else None),
            "unearned_liability_remaining_usd": _text(None if mark is None else unearned * mark),
            "restricted_principal_remaining_asset_units": _text(unearned + earned),
            "buyer_service_receivable_usd": _text(None if mark is None else max(zero, buyer_earned - funded_earnings)),
            "liability_tail_resolved": tail_resolved,
            "refund_at_end": p["refund_at_end"], "release_authorized": p["release_authorized"]},
        "yield": {"hypothetical": True, "annual_nominal_apr": _text(p["annual_yield_apr"]),
            "day_count": "ACT/365F", "compounding": False, "access": p["yield_access"],
            "basis": "opening_hourly_restricted_principal_excludes_released_principal_and_accrued_yield",
            "entitlement_basis": p["entitlement_basis"], "entitlements_verified": False,
            "shares": {party: _text(p["shares"][party]) for party in PARTIES},
            "total_accrued_asset_units": _text(sum(yield_accrued.values(), zero)),
            "accrued_asset_units_by_party": {party: _text(yield_accrued[party]) for party in PARTIES},
            "paid_asset_units_by_party": {party: _text(yield_paid[party]) for party in PARTIES},
            "unpaid_entitlement_asset_units_by_party": {party: _text(unpaid_yield[party]) for party in PARTIES},
            "broker_economic_entitlement_usd": _text(broker_yield_income),
            "broker_cash_received_usd": _text(None if mark is None else yield_paid["broker"] * mark),
            "cash_access_held": bool(yield_holds), "hold_reasons": yield_holds},
        "broker": {"opening_cash_usd": _text(p["opening_broker_cash"]), "minimum_required_cash_usd": _text(p["minimum_broker_cash"]),
            "ending_available_cash_usd": _text(broker_cash), "minimum_actual_cash_usd": _text(minimum_actual),
            "minimum_cash_if_all_obligations_paid_usd": _text(minimum_unconstrained),
            "required_extra_cash_for_all_obligations_and_floor_usd": _text(extra_cash),
            "economic_margin_with_yield_usd": _text(None if broker_yield_income is None else economic_margin + broker_yield_income),
            "scenario_cash_floor_feasible": cash_feasible, "real_funding_verified": False, "hold_reasons": holds},
        "risk_proposal": {"classification": "caller_declared_uncalibrated_buffer_and_collateral",
            "provider_grade": p["provider_risk_grade"], "buffer_hours": p["buffer_hours"],
            "buffer_usd": _text(p["provider_rate"] * gpu * p["buffer_hours"]),
            "collateral_fraction": _text(p["collateral_fraction"]),
            "collateral_usd": _text(maximum_provider * p["collateral_fraction"]),
            "collateral_posted_verified": False, "buffer_added_to_available_cash": False},
        "chart": {"rows": rows, "total_hours_evaluated": hours, "rows_returned": len(rows),
            "sampled": hours > len(rows), "selection": "evenly_spaced_hour_endpoints_including_first_and_last",
            "terminal_refund_is_after_last_hour": True, "aggregates_use_every_hour": True},
    }
