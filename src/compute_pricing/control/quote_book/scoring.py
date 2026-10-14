"""Independent illustrative supply-cost scenarios, not calibrated underwriting.

The grade premium and expected-loss calculation are alternative comparisons.
They are never added together. Missing deposits, references or evidence remain
unknown. Every default below is an explicitly invented simulation policy.
"""
from calendar import monthrange
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
import re

from compute_pricing.control._numbers import calculation_precision, number, text_number
from compute_pricing.control.domain import ValidationError, utc_instant


_WEIGHTS = {"certification": "0.20", "dc_tier": "0.10", "sla": "0.25", "delivery": "0.15",
            "credit": "0.20", "responsiveness": "0.10"}
CATEGORIES = {name: {"label": label, "weight": _WEIGHTS[name]} for name, label in (
    ("certification", "Controls attestation"), ("dc_tier", "Facility continuity"),
    ("sla", "Service reliability"), ("delivery", "Provisioning readiness"),
    ("credit", "Payment resilience"), ("responsiveness", "Incident response"),
)}
GRADES = ("A", "B", "C", "D")
GRADE_BANDS = {"A": "90", "B": "75", "C": "60", "D": "0"}
_PREMIUMS = {"A": "0.005", "B": "0.017", "C": "0.041", "D": "0.083"}
KEY_FIELDS = ("gpu", "gpus_per_node", "nodes", "price", "currency", "price_unit", "months",
              "down_payment", "available", "expires", "payment_days", "moq", "lead_weeks",
              "location", "country", "interconnect", "cooling")
ASSUMPTIONS = {
    "label": "Independently invented, uncalibrated public simulation assumptions",
    "deposit_apr": "0.085",
    "annual_failure_probability": {"A": "0.008", "B": "0.024", "C": "0.061", "D": "0.173"},
    "recovery_fraction": "0.35",
}
_POLICY_KEYS = {"label", "weights", "grade_bands", "grade_premiums", "rating_scale"}
_QUOTE_KEYS = set(KEY_FIELDS) | {"id", "provider_id", "posted", "updated", "posted_tick", "changed_tick", "synthetic", "active"}
_ZERO, _ONE = Decimal(0), Decimal(1)


def _shape(value, keys, label):
    if not isinstance(value, dict) or set(value) != keys:
        raise ValidationError(f"{label}: complete explicit contract with known fields required")


def _amount(value, label, *, fraction=False, positive=False):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValidationError(f"{label}: finite plain decimal required")
        value = text_number(value)
    return number(value, label, fraction=fraction, positive=positive)


def _integer(value, label, *, minimum=0, maximum=1000000):
    if type(value) is int:
        result = value
    elif isinstance(value, str) and len(value) <= 32 and re.fullmatch(r"(?:0|[1-9][0-9]*)", value):
        result = int(value)
    else:
        raise ValidationError(f"{label}: explicit bounded whole integer required")
    if not minimum <= result <= maximum:
        raise ValidationError(f"{label}: outside allowed integer bounds")
    return result


def _label(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValidationError(f"{name}: explicit bounded text required")
    return value


def _precision_inputs(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _precision_inputs(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_precision_inputs(item) for item in value]
    return value


def validate_policy(policy=None) -> dict:
    """Return a detached, validated policy; overrides cannot silently fill gaps."""
    if policy is None:
        policy = {"label": "Independently invented public simulation scorecard",
            "weights": deepcopy(_WEIGHTS), "grade_bands": deepcopy(GRADE_BANDS), "grade_premiums": deepcopy(_PREMIUMS),
            "rating_scale": {"minimum": 0, "maximum": 4, "higher_is_stronger": True}}
    _shape(policy, _POLICY_KEYS, "scorecard policy")
    _label(policy["label"], "policy label")
    _shape(policy["weights"], set(CATEGORIES), "weights")
    _shape(policy["grade_bands"], set(GRADES), "grade_bands")
    _shape(policy["grade_premiums"], set(GRADES), "grade_premiums")
    _shape(policy["rating_scale"], {"minimum", "maximum", "higher_is_stronger"}, "rating_scale")
    scale = policy["rating_scale"]
    if type(scale["minimum"]) is not int or type(scale["maximum"]) is not int or scale != {
            "minimum": 0, "maximum": 4, "higher_is_stronger": True} or scale["higher_is_stronger"] is not True:
        raise ValidationError("rating_scale: explicit 0..4 higher-is-stronger convention required")
    with localcontext() as context:
        context.prec = calculation_precision(_precision_inputs(policy))
        weights = {key: _amount(value, "weight", fraction=True) for key, value in policy["weights"].items()}
        if sum(weights.values(), _ZERO) != 1:
            raise ValidationError("weights: exact sum of one required")
        bands = {key: _amount(value, "grade band") for key, value in policy["grade_bands"].items()}
        if not 100 >= bands["A"] > bands["B"] > bands["C"] > bands["D"] == 0:
            raise ValidationError("grade_bands: strictly ordered thresholds in [0,100], D=0 required")
        premiums = {key: _amount(value, "grade premium", fraction=True) for key, value in policy["grade_premiums"].items()}
    return {"label": policy["label"], "weights": {key: text_number(value) for key, value in weights.items()},
            "grade_bands": {key: text_number(value) for key, value in bands.items()},
            "grade_premiums": {key: text_number(value) for key, value in premiums.items()},
            "rating_scale": deepcopy(scale)}


def quality_score(tiers, policy=None) -> Decimal:
    """Explicit ratings 0..4 map linearly to 0..100; unknowns cannot get a grade."""
    selected = validate_policy(policy)
    _shape(tiers, set(CATEGORIES), "ratings")
    ratings = {key: _integer(value, "rating", maximum=4) for key, value in tiers.items()}
    with localcontext() as context:
        context.prec = calculation_precision(selected)
        return sum((Decimal(ratings[key]) * Decimal(selected["weights"][key]) for key in CATEGORIES), _ZERO) * 25


def grade_for(score, policy=None) -> tuple[str, Decimal]:
    selected = validate_policy(policy)
    if type(score) is int:
        score = Decimal(score)
    score = _amount(score, "quality score")
    if score > 100:
        raise ValidationError("quality score: outside [0,100]")
    for grade in GRADES:
        if score >= Decimal(selected["grade_bands"][grade]):
            return grade, Decimal(selected["grade_premiums"][grade])
    raise AssertionError("validated grade bands cover the score domain")


def _assumptions(values):
    selected = deepcopy(ASSUMPTIONS) if values is None else values
    _shape(selected, set(ASSUMPTIONS), "economics assumptions")
    _label(selected["label"], "assumptions label")
    _shape(selected["annual_failure_probability"], set(GRADES), "annual_failure_probability")
    rates = {grade: _amount(value, "annual failure probability", fraction=True)
             for grade, value in selected["annual_failure_probability"].items()}
    return {"label": selected["label"], "deposit_apr": _amount(selected["deposit_apr"], "deposit APR"),
            "annual_failure_probability": rates,
            "recovery_fraction": _amount(selected["recovery_fraction"], "recovery fraction", fraction=True)}


def _date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValidationError(f"{label}: explicit ISO calendar date required")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{label}: valid calendar date required") from exc


def _month_end(start, months):
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    if year > 9999:
        raise ValidationError("term: resulting calendar end outside supported years")
    return start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))


def quote_economics(quote, *, grade, reference=None, as_of, assumptions=None) -> dict:
    """Cost the displayed nodes for the full calendar contract as a scenario.

    Financing is simple deposit interest for the entire term. The loss scenario
    assumes an unrecovered deposit plus replacement at the declared reference
    for the entire term; it does not estimate the actual time of a failure.
    """
    if not isinstance(quote, dict):
        raise ValidationError("quote: explicit object required")
    with localcontext() as context:
        context.prec = calculation_precision(_precision_inputs({"quote": quote, "reference": reference,
            "grade": grade, "assumptions": ASSUMPTIONS if assumptions is None else assumptions}))
        return _economics(quote, grade, reference, as_of, _assumptions(assumptions))


def _economics(quote, grade, reference, as_of, assumptions):
    when = _date(as_of, "as_of") if isinstance(as_of, str) and len(as_of) == 10 else utc_instant(as_of).date()
    missing = {name for name in KEY_FIELDS if quote.get(name) is None or quote.get(name) == ""}
    flags = ["illustrative_uncalibrated_simulation", "financing_assumes_deposit_held_for_full_contract_term",
             "loss_assumes_unrecovered_deposit_plus_full_term_replacement_premium",
             "scorecard_and_exposure_models_are_alternatives_not_cumulative",
             "payment_days_and_operating_features_are_preserved_not_additional_cost_models"]
    reasons = set()
    unknown = set(quote) - _QUOTE_KEYS
    if unknown:
        reasons.add("unregistered_quote_fields")
        flags.append("unpriced_fields:" + ",".join(sorted(unknown)))
    for name in ("gpu", "currency", "price_unit", "location", "country", "interconnect", "cooling"):
        if name not in missing:
            _label(quote[name], name)
    if "currency" not in missing and quote["currency"] != "USD":
        reasons.add("unsupported_currency_no_implicit_fx")
    if "price_unit" not in missing and quote["price_unit"] != "gpu_hour":
        reasons.add("unsupported_price_unit_no_implicit_conversion")
    money_supported = quote.get("currency") == "USD" and quote.get("price_unit") == "gpu_hour"
    if quote.get("synthetic") is not True:
        reasons.add("simulation_classification_not_explicit")
    if "active" in quote:
        if type(quote["active"]) is not bool:
            raise ValidationError("active: explicit boolean required")
        if not quote["active"]:
            reasons.add("inactive_simulated_quote")
    nodes = None if "nodes" in missing else _integer(quote["nodes"], "nodes")
    per_node = None if "gpus_per_node" in missing else _integer(quote["gpus_per_node"], "gpus_per_node", minimum=1)
    gpus = None if nodes is None or per_node is None else nodes * per_node
    if nodes == 0:
        reasons.add("no_available_capacity")
    moq = None if "moq" in missing else _integer(quote["moq"], "moq", minimum=1)
    if nodes is not None and moq is not None and nodes < moq:
        reasons.add("available_nodes_below_minimum_order")
    for name in ("lead_weeks", "payment_days"):
        if name not in missing:
            _integer(quote[name], name)
    start = None if "available" in missing else _date(quote["available"], "available")
    months = None if "months" in missing else _integer(quote["months"], "months", minimum=1, maximum=1200)
    end = None if start is None or months is None else _month_end(start, months)
    days = None if end is None else (end - start).days
    term_hours = None if days is None else Decimal(days) * 24
    gpu_hours = None if gpus is None or term_hours is None else Decimal(gpus) * term_hours
    if start is not None and start < when:
        reasons.add("contract_start_precedes_as_of")
    if end is not None and end <= when:
        reasons.add("contract_term_expired")
    if "expires" not in missing and _date(quote["expires"], "expires") <= when:
        reasons.add("simulated_quote_expired")
    price = None if "price" in missing else _amount(quote["price"], "price")
    dp = None if "down_payment" in missing else _amount(quote["down_payment"], "down_payment", fraction=True)
    premium = None
    if grade is None:
        grade_label = None
        missing.add("grade")
    elif isinstance(grade, tuple) and len(grade) == 2:
        grade_label, premium = grade
        if not isinstance(grade_label, str) or grade_label not in GRADES:
            raise ValidationError("grade: known simulated grade required")
        premium = _amount(premium, "declared grade premium", fraction=True)
    elif isinstance(grade, str) and grade in GRADES:
        grade_label, premium = grade, Decimal(_PREMIUMS[grade])
    else:
        raise ValidationError("grade: known label/premium tuple or explicit unknown required")
    ref = None if reference is None else _amount(reference, "reference")
    if ref is None:
        missing.add("reference")
    elif ref == 0:
        flags.append("zero_reference_discount_undefined")
        reasons.add("positive_reference_required_for_relative_comparison")
    value = None if not money_supported or price is None or gpu_hours is None else price * gpu_hours
    deposit = None if value is None or dp is None else value * dp
    finance = None if deposit is None or days is None else deposit * assumptions["deposit_apr"] * Decimal(days) / 365
    finance_rate = None if finance is None or not gpu_hours else finance / gpu_hours
    scorecard = None if not money_supported or price is None or premium is None else price * premium
    annual = None if grade_label is None else assumptions["annual_failure_probability"][grade_label]
    probability = None
    if annual is not None and days is not None:
        if annual == 0:
            probability = _ZERO
        elif annual == 1:
            probability = _ONE
        elif days % 365 == 0:
            probability = _ONE - (_ONE - annual) ** (days // 365)
        else:
            probability = _ONE - ((_ONE - annual).ln() * Decimal(days) / 365).exp()
    recovered_deposit = None if deposit is None else deposit * assumptions["recovery_fraction"]
    replacement_premium = None if not money_supported or ref is None or price is None or gpu_hours is None else max(_ZERO, ref - price) * gpu_hours
    loss_exposure = None if deposit is None or replacement_premium is None else deposit - recovered_deposit + replacement_premium
    expected_loss = None if loss_exposure is None or probability is None else probability * loss_exposure
    exposure_rate = None if expected_loss is None or not gpu_hours else expected_loss / gpu_hours
    scorecard_cost = None if price is None or finance_rate is None or scorecard is None else price + finance_rate + scorecard
    exposure_cost = None if price is None or finance_rate is None or exposure_rate is None else price + finance_rate + exposure_rate
    discount = None if not money_supported or price is None or not ref else (ref - price) / ref
    reasons.update("missing_" + name for name in missing)
    eligible = not reasons and exposure_cost is not None and scorecard_cost is not None
    return {"gpus": gpus, "currency": quote.get("currency"), "unit": quote.get("price_unit"),
            "price": price, "contract_start": None if start is None else start.isoformat(),
            "term_end": None if end is None else end.isoformat(), "term_days": days, "term_hours": term_hours,
            "contract_gpu_hours": gpu_hours, "contract_value": value, "down_payment_usd": deposit,
            "financing_cost": finance, "financing_cost_per_gpu_hour": finance_rate,
            "grade": grade_label, "grade_premium": premium, "scorecard_charge": scorecard,
            "annual_failure_probability": annual, "failure_probability": probability,
            "recovered_deposit_usd": recovered_deposit, "replacement_premium_usd": replacement_premium,
            "loss_exposure_usd": loss_exposure, "expected_loss_usd": expected_loss, "exposure_charge": exposure_rate,
            "risk_adjusted_scorecard": scorecard_cost, "risk_adjusted": exposure_cost,
            "reference": ref, "reference_basis": "independently_declared_simulation_reference_not_market_evidence",
            "discount_to_reference": discount, "missing": sorted(missing), "flags": flags,
            "eligible": eligible, "ineligible_reasons": sorted(reasons), "simulated": True,
            "source_evidence_eligible": False, "firm_price_eligible": False, "execution_enabled": False,
            "eligibility_basis": "complete_simulated_scenario_inputs_not_trade_authority",
            "cost_basis": "all_displayed_nodes_full_calendar_term",
            "units": {"contract_value": "USD", "down_payment_usd": "USD", "financing_cost": "USD",
                      "scorecard_charge": "USD_per_gpu_hour", "exposure_charge": "USD_per_gpu_hour",
                      "risk_adjusted": "USD_per_gpu_hour", "risk_adjusted_scorecard": "USD_per_gpu_hour"},
            "assumptions": deepcopy(assumptions), "as_of": when.isoformat()}
