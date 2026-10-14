"""Typed scenario economics, dated funding and explicit protection proposals.

This demonstration composes existing arithmetic kernels. Its provider claims,
capital budgets and volatility are declared illustrations, not credit models,
market forecasts, cleared bank balances or executable prices.
"""
from copy import deepcopy
import datetime as dt
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
import re

from compute_pricing.control._numbers import calculation_precision, digest, hours, number, text_number
from compute_pricing.control.api.demo import build_demo_pricing_request, demo_supplier_cash_schedule
from compute_pricing.control.api.provenance import PricingProvenance
from compute_pricing.control.domain import ValidationError, exact_decimal, utc_instant
from compute_pricing.control.power import evaluate_power_payload
from compute_pricing.control.pricing import evaluate_pricing
from compute_pricing.control.quote_book.scoring import grade_for, quality_score, validate_policy
from .escrow import evaluate_escrow
from .scenarios import SCHEMA, demo_scenarios

_ZERO, _ONE = Decimal(0), Decimal(1)
_STRUCTURAL = {"pricing.power.cost_owner": "allocated-power-cost/1.0.0",
    "pricing.risk_cost_owner": "demo:declared-capital-budget",
    "settlement.collateral_owner": "provider_restricted_performance_security"}
_HELP = {"provider.credit_score": "Documentary declared score; not a calibrated default probability or extra price premium.",
    "provider.credit_band": "Declared provider classification; separate from verified credit evidence.",
    "provider.uptime_fraction": "Declared service history; does not automatically replace billed utilization or add a price premium.",
    "provider.sla_fraction": "Contract service assertion; documentary until verified.",
    "provider.response_hours": "Declared response commitment; does not independently charge risk twice.",
    "pricing.risk_allowance_per_gpu_hour": "The single explicit capital-budget channel; no additional grade or location premium.",
    "pricing.power.payer": "Declared economic payer; the additional-power cash model currently supports the broker payer.",
    "pricing.billed_utilization": "The share of full supplier capacity billed to the buyer.",
    "pricing.collection_share": "Expected share of gross billings collected; a separate scenario assumption.",
    "surface.tenor_days": "Comma-separated plain decimal strings for whole tenor days, from 1 through 365; at most 12 values.",
    "surface.shocks": "Comma-separated signed plain decimal strings from -3 through 3; at most 9 declared sensitivity shocks.",
    "surface.collection_shocks": "Comma-separated plain decimal strings from 0 through 1; each is a reduction in the collection share, at most 9 values.",
    "settlement.provider_collateral_usd": "Proposed provider performance security; never usable broker cash or automatic loss recovery."}
_CHOICES = {
    "provider.credit_band": ["strong", "balanced", "weak", "unknown"],
    "capacity.ownership": ["owned", "leased", "mixed", "unknown"],
    "pricing.rate_type": ["fixed", "variable"], "pricing.power.inclusion": ["included", "excluded", "unknown"],
    "pricing.power.cost_owner": ["allocated-power-cost/1.0.0"], "pricing.risk_cost_owner": ["demo:declared-capital-budget"],
    "pricing.power.payer": ["broker", "provider", "buyer", "unknown"],
    "settlement.mode": ["upfront", "milestone", "hourly_escrow"],
    "settlement.collateral_owner": ["provider_restricted_performance_security"],
    "settlement.asset_kind": ["bank_deposit", "stable_asset"], "settlement.liquidity": ["liquid", "illiquid", "unknown"],
    "settlement.depeg_status": ["not_applicable", "normal", "depegged", "unknown"],
    "settlement.yield_access": ["hourly_withdrawable", "accrued_only", "unknown"],
    "settlement.service_basis": ["delivered", "available_sla"],
}
_LABELS = {"capacity.model": "GPU model", "capacity.memory_gib": "GPU memory (GiB)",
    "capacity.gpus_per_node": "GPUs per node", "capacity.node_count": "Number of nodes",
    "provider.credit_score": "Declared credit score (0–100)", "provider.uptime_fraction": "Declared uptime fraction",
    "provider.sla_fraction": "Contract SLA fraction", "provider.response_hours": "Response commitment (hours)",
    "pricing.supplier_rate": "Supplier price / GPU-hour", "pricing.buyer_rate": "Buyer price / GPU-hour",
    "pricing.power.pue": "Facility PUE", "pricing.power.tariff_per_kwh": "Declared tariff / kWh",
    "pricing.risk_allowance_per_gpu_hour": "Declared capital budget / GPU-hour",
    "surface.annual_volatility": "Illustrative annual rate volatility", "surface.shocks": "Declared volatility shocks"}


def _flatten(value, prefix=""):
    for key, item in value.items():
        path = prefix + key
        if isinstance(item, dict):
            yield from _flatten(item, path + ".")
        else:
            yield path, item


def _unknown(value):
    if isinstance(value, dict):
        return {key: _unknown(item) for key, item in value.items()}
    return None


def demo_contract():
    scenarios = demo_scenarios()
    template = _unknown(scenarios[0]["inputs"])
    template.update(schema_version=SCHEMA, classification="synthetic")
    for path, value in _STRUCTURAL.items():
        target = template
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
    fields = []
    for path, value in _flatten(scenarios[0]["inputs"]):
        if "." not in path:
            continue
        name = path.rsplit(".", 1)[-1]
        field_type = ("enum" if path in _CHOICES else "boolean" if type(value) is bool else
                      "integer" if type(value) is int else "decimal_list" if isinstance(value, list) else
                      "utc" if name in {"starts_at", "ends_at"} else "date" if name.endswith("_on") else
                      "decimal" if isinstance(value, str) and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) else "text")
        fields.append({"path": path, "label": _LABELS.get(path, name.replace("_", " ").capitalize()),
            "group": "pricing" if path.startswith("surface.") else path.split(".")[0], "type": field_type,
            "choices": deepcopy(_CHOICES.get(path, [])), "required": True, "editable": path not in _STRUCTURAL,
            "help": _HELP.get(path, "Registered model ownership; structural identifier, not a financial input." if path in _STRUCTURAL else "")})
    return {"schema_version": SCHEMA, "classification": "synthetic", "fields": fields,
        "groups": [{"id": group, "label": label} for group, label in (
            ("provider", "Provider and service evidence"), ("capacity", "Hardware and facility"),
            ("pricing", "Pricing, costs and stresses"), ("settlement", "Settlement and protection"),
            ("treasury", "Dated funding"))], "template": template, "scenarios": scenarios,
        "currency": "USD", "price_unit": "gpu_hour", "firm_price_eligible": False, "execution_enabled": False,
        "notes": ["provider_claims_are_independently_invented_and_unverified",
            "capital_budget_is_one_owned_channel_no_additional_quality_grade_premium",
            "volatility_surface_is_declared_unfitted_stress_not_a_market_forward_curve"]}


def _validate_shape(value, reference, path="input"):
    if not isinstance(value, dict) or set(value) != set(reference):
        raise ValidationError(path + ": all known fields required")
    for key, expected in reference.items():
        if isinstance(expected, dict):
            _validate_shape(value[key], expected, path + "." + key)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValidationError("payment date: explicit ISO calendar date required")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("payment date: valid calendar date required") from exc


def _int(value, name, maximum=1000000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValidationError(name + ": positive bounded integer required")
    return value


def evaluate_demo_pricing(payload, *, market_reference=None):
    reference = demo_scenarios()[0]["inputs"]
    _validate_shape(payload, reference)
    if payload["schema_version"] != SCHEMA or payload["classification"] != "synthetic":
        raise ValidationError("pricing demo: explicit synthetic supported schema required")
    missing = [path for path, value in _flatten(payload) if value is None or value == ""]
    if missing:
        return {"schema_version": SCHEMA, "classification": "synthetic", "simulated": True,
            "status": "held", "missing": missing, "hold_reasons": ["required_declared_input_unknown"],
            "summary": {key: None for key in ("supplier_rate", "purchase_ceiling", "sell_floor", "target_ask", "expected_margin", "expected_profit", "cash_required")},
            "quality": None, "terms": None, "power": None, "cash": None, "escrow": None, "surface": None,
            "source_evidence_eligible": False, "firm_price_eligible": False, "execution_enabled": False}
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        return _evaluate(deepcopy(payload), market_reference)


def _evaluate(p, market_reference):
    provider, c, q, s, treasury = (p[key] for key in ("provider", "capacity", "pricing", "settlement", "treasury"))
    for path, value in _flatten(p):
        if path in _CHOICES and value not in _CHOICES[path]:
            raise ValidationError(path + ": unsupported choice")
        if isinstance(value, str) and len(value) > 512:
            raise ValidationError(path + ": text exceeds limit")
    gpus = _int(c["gpus_per_node"], "gpus_per_node") * _int(c["node_count"], "node_count")
    if gpus > 1000000:
        raise ValidationError("total GPUs exceed bounded allocation")
    start, end = utc_instant(c["starts_at"]), utc_instant(c["ends_at"])
    duration = hours(c["starts_at"], c["ends_at"])
    if (duration != duration.to_integral_value() or not 1 <= duration <= 2160 or
            start.minute or start.second or start.microsecond or end.minute or end.second or end.microsecond):
        raise ValidationError("demonstration: positive whole-hour window up to 2160 hours required")
    if s["mode"] == "hourly_escrow" and duration > 1500:
        raise ValidationError("hourly pricing demonstration: cash event budget permits at most 1500 hours")
    for value in treasury.values():
        if isinstance(value, str) and "-" in value:
            _date(value)
    for name in ("credit_score", "response_hours"):
        number(provider[name], name)
    if Decimal(provider["credit_score"]) > 100:
        raise ValidationError("credit score outside declared 0..100 scale")
    for name in ("uptime_fraction", "sla_fraction"):
        number(provider[name], name, fraction=True)
    for name in ("memory_gib", "cpu_cores", "ram_gib", "network_gbps"):
        number(c[name], name, positive=True)
    if not isinstance(c["country_code"], str) or not re.fullmatch("[A-Z]{2}", c["country_code"]):
        raise ValidationError("country code required")
    rates = {name: number(q[name], name) for name in ("supplier_rate", "variable_low", "variable_high", "fixed_operating_cost", "risk_allowance_per_gpu_hour", "discount_apr")}
    for name in ("required_margin", "target_margin", "billed_utilization", "collection_share", "fee_on_collected", "fee_on_gross"):
        number(q[name], name, fraction=True)
    if Decimal(q["target_margin"]) < Decimal(q["required_margin"]):
        raise ValidationError("target margin must be at least required margin")
    if not rates["variable_low"] <= rates["supplier_rate"] <= rates["variable_high"]:
        raise ValidationError("supplier rate must lie inside declared bounds")
    if q["rate_type"] == "fixed" and len({rates[name] for name in ("supplier_rate", "variable_low", "variable_high")}) != 1:
        raise ValidationError("fixed rate requires identical declared low/current/high")
    deposit = number(s["down_payment_fraction"], "deposit fraction", fraction=True)
    apr = number(s["financing_apr"], "financing APR", fraction=True)
    number(s["provider_collateral_usd"], "provider collateral")
    number(s["prefunded_principal"], "prefunded principal")
    number(s["service_fraction"], "service fraction", fraction=True)
    if s["mode"] == "upfront" and deposit != 1:
        raise ValidationError("upfront mode requires an explicit full prepayment fraction")
    if s["mode"] == "hourly_escrow" and deposit != 0:
        raise ValidationError("hourly escrow cannot also prepay supplier principal")
    score = quality_score(provider["ratings"])
    grade, _ = grade_for(score)
    policy = validate_policy()
    quality = {"score": text_number(score), "grade": grade, "policy": policy,
        "provider_claims_verified": False, "calibration_verified": False,
        "financial_effect": "single_explicit_capital_budget_no_extra_grade_or_geographic_premium"}
    supplied_hours = duration * gpus
    power_input = {"currency": "USD", "gpu_count": str(gpus), "idle_watts_per_gpu": q["power"]["idle_watts_per_gpu"],
        "load_watts_per_gpu": q["power"]["load_watts_per_gpu"], "shared_it_watts": q["power"]["shared_it_watts"],
        "pue": q["power"]["pue"], "sold_gpu_hours": text_number(supplied_hours * Decimal(q["billed_utilization"])),
        "compute_power_inclusion": q["power"]["inclusion"], "intervals": [{"starts_at": c["starts_at"], "ends_at": c["ends_at"],
            "utilization": q["power"]["utilization"], "rate": {"currency": "USD", "amount_per_kwh": q["power"]["tariff_per_kwh"],
                "basis": "declared_tariff_energy", "evidence_ref": "independently-invented-tariff"}}],
        "demand_charges": [], "cost_items": [], "evidence_basis": "independently invented allocated load"}
    power = evaluate_power_payload(power_input)
    holds = list(power["blockers"])
    if c["ownership"] == "unknown" or provider["credit_band"] == "unknown":
        holds.append("ownership_or_credit_class_unknown")
    if q["power"]["payer"] == "unknown" or q["power"]["inclusion"] == "excluded" and q["power"]["payer"] != "broker":
        holds.append("power_cash_payer_unknown_or_not_supported_by_broker_cost_model")
    if grade == "D" and s["mode"] != "hourly_escrow":
        holds.append("illustrative_weak_grade_requires_hourly_restricted_escrow")
    escrow = None
    if s["mode"] == "hourly_escrow":
        native = {"schema_version": "hourly-escrow/1.0", "delivery_start": c["starts_at"], "delivery_end": c["ends_at"],
            "gpu_count": gpus, "service_basis": s["service_basis"], "hourly_service_fractions": [s["service_fraction"]] * int(duration),
            "buyer_rate": text_number(Decimal(q["buyer_rate"]) * Decimal(q["billed_utilization"])), "provider_rate": q["supplier_rate"],
            "prefunded_principal": s["prefunded_principal"], "asset_kind": s["asset_kind"], "asset_unit": s["asset_unit"],
            "asset_price_usd": s["asset_price_usd"], "liquidity": s["liquidity"], "depeg_status": s["depeg_status"],
            "annual_yield_apr": s["yield_apr"], "yield_shares": {party: s["yield_share_" + party] for party in ("provider", "broker", "buyer")},
            "yield_access": s["yield_access"], "release_authorized": s["release_authorized"], "refund_at_end": s["refund_at_end"],
            "entitlement_basis": s["vesting_basis"], "opening_broker_cash": treasury["opening_cash"], "minimum_broker_cash": treasury["minimum_cash"],
            "broker_operating_cost_per_hour": "0", "provider_risk_grade": grade, "buffer_hours": s["buffer_hours"],
            "collateral_fraction": s["collateral_fraction"]}
        escrow = evaluate_escrow(native)
        holds.extend(escrow["broker"]["hold_reasons"])
        if not escrow["prefunding"]["full_prefunding_declared"]:
            holds.append("full_escrow_prefunding_not_declared")
        if Decimal(s["service_fraction"]) != 1 or Decimal(q["collection_share"]) != 1:
            holds.append("pricing_cash_inversion_requires_full_declared_service_and_collection_in_hourly_mode")
        if s["refund_at_end"] is not True:
            holds.append("remaining_customer_principal_refund_not_confirmed")
    if power["incremental_compute_power_cost"] is None or holds:
        return _held(p, quality, power, escrow, holds)
    power_cost = Decimal(power["incremental_compute_power_cost"])
    capital = supplied_hours * rates["risk_allowance_per_gpu_hour"]
    days = duration / 24
    carry = (deposit * apr * days / 365).quantize(Decimal("0.000000000001"), rounding=ROUND_CEILING)
    request = _request(p, power_cost, capital, carry)
    priced = PricingProvenance(None, None, None).apply(request, evaluate_pricing(request))
    target_request = deepcopy(request); target_request["commercial"]["required_margin"] = q["target_margin"]
    target_priced = evaluate_pricing(target_request)
    actual = demo_supplier_cash_schedule(request)
    caps = [Decimal(value) for value in priced["caps"].values()]
    tick = Decimal(q["tick_size"])
    ceiling = None if not caps or min(caps) <= 0 else (min(caps) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    economics = priced["economics"]
    cash_required = max(_ZERO, Decimal(treasury["opening_cash"]) - Decimal(actual["minimum_free_cash"]) + Decimal(treasury["minimum_cash"]))
    summary = {"currency": "USD", "price_unit": "gpu_hour", "supplier_rate": q["supplier_rate"],
        "purchase_ceiling": None if ceiling is None else text_number(ceiling), "sell_floor": priced["ask"].get("zero_economic_profit"),
        "minimum_margin_ask": priced["ask"].get("sell_floor_tick"), "target_ask": target_priced["ask"].get("sell_floor_tick"),
        "expected_margin": economics["economic_margin"], "expected_profit": economics["economic_profit"],
        "operating_contribution": economics["expected_contribution"], "margin_basis": "gross_billings_after_explicit_capital_budget",
        "gross_billings": economics["gross_billings"], "expected_collections": economics["expected_collections"],
        "cash_required": text_number(cash_required), "cash_shortfall": actual["required_extra_cash_for_floor"],
        "cash_feasible": actual["cash_floor_feasible"], "capital_budget": text_number(capital),
        "power_rate": text_number(power_cost / supplied_hours), "financing_carry_fraction": text_number(carry),
        "npv": _npv(actual, treasury["opening_cash"], q["discount_apr"]), "npv_basis": "dated_net_operating_cash_ACT365_declared_discount_rate",
        "irr": None, "irr_basis": "equity_financing_timeline_not_declared", "net_cash_flow": text_number(Decimal(actual["days"][-1]["cash"]) - Decimal(treasury["opening_cash"]))}
    if ceiling is None:
        holds.append("no_positive_economic_and_cash_purchase_ceiling")
    if not actual["cash_floor_feasible"]:
        holds.append("supplied_rate_breaches_declared_cash_floor")
    proposals = _proposals(s["mode"], grade)
    agreement = {"classification": "synthetic", "provider": deepcopy(provider), "capacity": {**deepcopy(c), "total_gpu_count": gpus},
        "pricing": {**deepcopy(q), "currency": "USD", "price_unit": "gpu_hour"}, "settlement": deepcopy(s),
        "treasury": deepcopy(treasury), "summary": deepcopy(summary), "legal_entitlements_verified": False}
    result = {"schema_version": SCHEMA, "classification": "synthetic", "simulated": True,
        "status": "held" if holds else "scenario_estimate", "missing": [], "hold_reasons": sorted(set(holds)), "summary": summary,
        "quality": quality, "terms": {"capacity": agreement["capacity"], "settlement": deepcopy(s), "protection_proposals": proposals},
        "power": power, "cash": actual, "escrow": escrow, "pricing": priced, "agreement_terms": agreement,
        "surface": _surface(p, power_cost / supplied_hours), "live_reference": _reference(market_reference, c["model"]),
        "source_evidence_eligible": False, "physical_price_eligible": False, "firm_price_eligible": False, "execution_enabled": False,
        "warnings": ["provider_quality_and_credit_are_declared_not_calibrated", "one_owned_capital_budget_no_duplicate_grade_premium",
            "provider_collateral_is_a_proposal_not_available_broker_cash", "unearned_customer_principal_and_accrued_yield_are_not_revenue",
            "date_only_cash_uses_declared_event_order_not_bank_settlement_proof", "live_aggregate_reference_is_context_not_physical_purchase_cap"],
        "versions": {"demo": SCHEMA, "power": power["model_version"]}}
    result["input_hash"] = digest(p)
    result["decision_hash"] = digest(result)
    return result


def _request(p, power_cost, capital, carry):
    c, q, s, t = (p[key] for key in ("capacity", "pricing", "settlement", "treasury"))
    gpus = c["gpus_per_node"] * c["node_count"]
    supplied = hours(c["starts_at"], c["ends_at"]) * gpus
    fixed = Decimal(q["fixed_operating_cost"]) + power_cost
    request = build_demo_pricing_request({"gpu_count": str(gpus), "delivery_start": c["starts_at"], "delivery_end": c["ends_at"],
        "billed_utilization": q["billed_utilization"], "supplier_rate": q["supplier_rate"], "buyer_rate": q["buyer_rate"],
        "reference_rate": text_number(max(Decimal(q["supplier_rate"]), Decimal(q["tick_size"]))),
        "collection_share": q["collection_share"], "fee_on_collected": q["fee_on_collected"], "fee_on_gross": q["fee_on_gross"],
        "fixed_operating_cost": text_number(fixed), "opening_cash": t["opening_cash"], "minimum_cash": t["minimum_cash"],
        "required_margin": q["required_margin"], "tick_size": q["tick_size"], "payment_dates": {
            "supplier_payment_on": t["supplier_payment_on"], "buyer_invoice_on": t["buyer_invoice_on"],
            "buyer_receipt_on": t["buyer_receipt_on"], "operating_cost_on": t["operating_cost_on"], "fees_on": t["fees_on"], "writeoff_on": t["writeoff_on"]}})
    commercial = request["commercial"]
    commercial["exclusive_node_gpu_count"] = str(c["gpus_per_node"])
    commercial["cost_owners"] = {"operations": "demo:operations", "power": q["power"]["cost_owner"],
                                "capital": q["risk_cost_owner"], "financing": "demo:simple-deposit-funding"}
    commercial["costs"] = [{"id": channel, "channel": channel, "owner_model": commercial["cost_owners"][channel],
        "amount": text_number(amount), "basis": basis, "kind": kind} for channel, amount, basis, kind in (
            ("operations", Decimal(q["fixed_operating_cost"]), "fixed_contract", "expected_cost"),
            ("power", power_cost, "fixed_contract", "expected_cost"), ("capital", capital, "fixed_contract", "policy_capital"),
            ("financing", carry, "fraction_of_supply_purchase", "expected_cost"))]
    request["target"].update(hardware_model=c["model"], country_code=c["country_code"])
    template, schedule = request["cash_template"], request["cash_template"]["schedule"]
    identity = "demo-pricing:" + digest(p)[:16]
    events, coefficients = [], {}

    def add(name, day, kind, amount, *, coefficient=None, invoice=None, account=None):
        if amount == 0 and coefficient is None:
            return
        event = {"event_id": identity + ":" + name, "obligation_id": identity + ":" + name + ":obligation",
                 "on": day, "kind": kind, "amount": text_number(amount), "currency": "USD"}
        if invoice:
            event["invoice_id"] = invoice
        if account:
            event["advance_account"] = account
        if coefficient is not None and coefficient > 0:
            coefficients[event["event_id"]] = text_number(coefficient)
        events.append(event)

    buyer_events = [deepcopy(row) for row in schedule["events"] if row["kind"] in {"buyer_invoice", "revenue", "buyer_receipt", "receivable_writeoff"}]
    fees = sum(Decimal(row["amount"]) for row in schedule["events"] if row["kind"] == "other_outflow") - fixed
    add("operating-payment", t["operating_cost_on"], "other_outflow", fixed)
    add("operating-expense", t["operating_cost_on"], "expense", fixed)
    add("fees-payment", t["fees_on"], "other_outflow", fees)
    add("fees-expense", t["fees_on"], "expense", fees)
    add("finance-payment", t["supplier_balance_on"], "other_outflow", _ZERO, coefficient=supplied * carry if carry else None)
    add("finance-expense", t["supplier_balance_on"], "expense", _ZERO, coefficient=supplied * carry if carry else None)
    if s["mode"] != "hourly_escrow":
        dp = Decimal(s["down_payment_fraction"])
        supply_invoice, prepay = identity + ":supplier-invoice", identity + ":supplier-prepay"
        if dp:
            add("supplier-prepayment", t["supplier_payment_on"], "supplier_prepayment", _ZERO, coefficient=supplied * dp, account=prepay)
        add("supplier-invoice", t["supplier_balance_on"], "supplier_invoice", _ZERO, coefficient=supplied, invoice=supply_invoice)
        add("supplier-expense", c["ends_at"][:10], "expense", _ZERO, coefficient=supplied)
        if dp:
            add("supplier-prepaid-apply", t["supplier_balance_on"], "prepaid_apply", _ZERO, coefficient=supplied * dp, invoice=supply_invoice, account=prepay)
        if dp < 1:
            add("supplier-payment", t["supplier_balance_on"], "supplier_payment", _ZERO, coefficient=supplied * (1-dp), invoice=supply_invoice)
        events.extend(buyer_events)
    else:
        account = identity + ":customer-restricted-principal"
        add("customer-principal-segregated", c["starts_at"][:10], "buyer_deposit", Decimal(s["prefunded_principal"]), account=account)
        unit_bill = Decimal(q["buyer_rate"]) * Decimal(q["billed_utilization"]) * gpus
        for hour in range(int(hours(c["starts_at"], c["ends_at"]))):
            when = (utc_instant(c["starts_at"]) + dt.timedelta(hours=hour + 1)).date().isoformat()
            buyer_invoice, supply_invoice = identity + ":buyer-" + str(hour), identity + ":supply-" + str(hour)
            add("buyer-invoice-" + str(hour), when, "buyer_invoice", unit_bill, invoice=buyer_invoice)
            add("revenue-" + str(hour), when, "revenue", unit_bill, invoice=buyer_invoice)
            add("release-" + str(hour), when, "deposit_apply", unit_bill, invoice=buyer_invoice, account=account)
            add("supply-invoice-" + str(hour), when, "supplier_invoice", _ZERO, coefficient=Decimal(gpus), invoice=supply_invoice)
            add("supply-payment-" + str(hour), when, "supplier_payment", _ZERO, coefficient=Decimal(gpus), invoice=supply_invoice)
            add("supply-expense-" + str(hour), when, "expense", _ZERO, coefficient=Decimal(gpus))
        refund = Decimal(s["prefunded_principal"]) - unit_bill * hours(c["starts_at"], c["ends_at"])
        if refund > 0:
            add("customer-refund", t["buyer_receipt_on"], "deposit_refund", refund, account=account)
    # Stable date ordering preserves the explicit hourly invoice/earn/release/pay
    # sequence; ordinary dated costs were deliberately added before receipts.
    events.sort(key=lambda row: row["on"])
    first = min(schedule["start_date"], *(row["on"] for row in events))
    last = max(c["ends_at"][:10], t["supplier_balance_on"], *(row["on"] for row in events))
    close = (_date(last) + dt.timedelta(days=1)).isoformat()
    schedule.update(start_date=first, end_date=close, events=events)
    if capital:
        schedule["reserves"] = [{"reserve_id": identity + ":risk-reserve", "coverage_id": identity + ":capital-budget",
            "amount": text_number(capital), "start_date": first, "end_date": close}]
    template.update(purchase_coefficients=coefficients, deal_event_ids=[row["event_id"] for row in events])
    return request


def _npv(cash, opening, apr):
    rate = number(apr, "discount APR")
    first = _date(cash["days"][0]["on"])
    previous = Decimal(opening)
    result = _ZERO
    for day in cash["days"]:
        current = Decimal(day["cash"])
        elapsed = Decimal((_date(day["on"]) - first).days) / 365
        discount = _ONE if not rate else ((_ONE + rate).ln() * elapsed).exp()
        result += (current - previous) / discount
        previous = current
    return text_number(result)


def _proposals(mode, grade):
    return {"mode": mode, "grade": grade, "required": "hourly_restricted_escrow" if grade == "D" else "declared_milestone_controls",
        "vesting": "Verified service only; unearned customer principal remains refundable/restricted",
        "collateral": "Provider performance pledge proposal; custody/perfection/enforcement unresolved",
        "yield": "Explicit party entitlements; accrued amounts excluded from pricing revenue and funding",
        "legal_status": "nonbinding_unsigned_simulation", "real_funding_verified": False}


def _reference(reference, model):
    if not isinstance(reference, dict):
        return {"status": "unavailable", "model": model, "reason": "no_server_bound_same_model_reference", "physical_eligible": False}
    cohort = reference.get("cohort", {})
    price = reference.get("reference", {})
    valid = (reference.get("source_evidence_eligible") is True and reference.get("status") == "indicative_reference"
             and cohort.get("hardware_model") == model and cohort.get("currency") == "USD"
             and isinstance(price, dict) and price.get("currency") == "USD" and price.get("unit") == "gpu_hour")
    return {"status": "context_only" if valid else "held", "model": model,
        "reference": deepcopy(reference.get("reference")) if valid else None,
        "snapshot_binding": "server_supplied_retained_study", "source_evidence_eligible": valid,
        "physical_eligible": False, "used_as_purchase_cap": False}


def _surface(p, power_rate):
    q, c, s, assumptions = p["pricing"], p["capacity"], p["settlement"], p["surface"]
    if (not isinstance(assumptions["tenor_days"], list) or not 1 <= len(assumptions["tenor_days"]) <= 12
            or not isinstance(assumptions["shocks"], list) or not 1 <= len(assumptions["shocks"]) <= 9
            or not isinstance(assumptions["collection_shocks"], list) or not 1 <= len(assumptions["collection_shocks"]) <= 9):
        raise ValidationError("surface: bounded explicit axes required")
    collection_shocks = [number(value, "collection share reduction", fraction=True) for value in assumptions["collection_shocks"]]
    sigma = number(assumptions["annual_volatility"], "annual volatility", fraction=True)
    points, collection_points = [], []
    for tenor in assumptions["tenor_days"]:
        days = number(tenor, "tenor days", positive=True)
        if days != days.to_integral_value() or days > 365:
            raise ValidationError("surface tenor: whole days within one year required")
        t = days / 365
        capacity = days * 24 * c["node_count"] * c["gpus_per_node"]
        carry = Decimal(s["down_payment_fraction"]) * Decimal(s["financing_apr"]) * t
        factor = Decimal(q["collection_share"]) * (1-Decimal(q["fee_on_collected"])) - Decimal(q["fee_on_gross"]) - Decimal(q["required_margin"])
        cap = (Decimal(q["buyer_rate"]) * Decimal(q["billed_utilization"]) * factor - power_rate
               - Decimal(q["risk_allowance_per_gpu_hour"]) - Decimal(q["fixed_operating_cost"]) / capacity) / (1+carry)
        for shock in assumptions["shocks"]:
            z = exact_decimal(shock)
            if abs(z) > 3:
                raise ValidationError("surface shock: within declared -3..3 bound required")
            rate = Decimal(q["supplier_rate"]) * (sigma * t.sqrt() * z - sigma*sigma*t/2).exp()
            points.append({"tenor_days": text_number(days), "shock": text_number(z), "rate": text_number(rate),
                           "economic_cap": text_number(cap), "rate_below_economic_cap": rate <= cap})
        for shock in collection_shocks:
            collection = max(_ZERO, Decimal(q["collection_share"]) - shock)
            factor = collection * (1-Decimal(q["fee_on_collected"])) - Decimal(q["fee_on_gross"]) - Decimal(q["required_margin"])
            cap = (Decimal(q["buyer_rate"]) * Decimal(q["billed_utilization"]) * factor - power_rate
                   - Decimal(q["risk_allowance_per_gpu_hour"]) - Decimal(q["fixed_operating_cost"]) / capacity) / (1+carry)
            collection_points.append({"tenor_days": text_number(days), "collection_share_reduction": text_number(shock),
                "collection_share": text_number(collection), "economic_cap": text_number(cap)})
    return {"label": "Illustrative declared lognormal rate sensitivity — no fitted volatility or market forward curve",
        "axes": {"x": "tenor_days", "y": "declared_standardized_shock", "z": "USD_per_gpu_hour"},
        "annual_volatility": assumptions["annual_volatility"], "points": points, "calibrated": False,
        "model": "R0*exp(sigma*sqrt(days/365)*z-0.5*sigma^2*days/365)",
        "drift": "zero_declared_arithmetic_drift_not_risk_neutral_or_forecast",
        "cash_feasibility_recomputed_for_surface": False, "collection_shocks": deepcopy(assumptions["collection_shocks"]),
        "collection_sensitivity_points": collection_points}


def _held(p, quality, power, escrow, holds):
    return {"schema_version": SCHEMA, "classification": "synthetic", "simulated": True, "status": "held", "missing": [],
        "hold_reasons": sorted(set(holds)), "summary": {key: None for key in ("supplier_rate", "purchase_ceiling", "sell_floor", "target_ask", "expected_margin", "expected_profit", "cash_required")},
        "quality": quality, "terms": {"capacity": deepcopy(p["capacity"]), "protection_proposals": _proposals(p["settlement"]["mode"], quality["grade"])},
        "power": power, "cash": None, "escrow": escrow, "surface": None,
        "source_evidence_eligible": False, "firm_price_eligible": False, "execution_enabled": False}


evaluate_pricing_demo = evaluate_demo_pricing
