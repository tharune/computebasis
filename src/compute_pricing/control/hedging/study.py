"""Paper scalar futures analysis using explicit weighted financial scenarios."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
import re

from compute_pricing.control._numbers import calculation_precision
from compute_pricing.control.domain import ValidationError, utc_instant

SCHEMA = "hedge-study/1.0"
VERSION = "scalar-linear-futures-scenario-study/1.0.0"
D0, D1 = Decimal(0), Decimal(1)
NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


def _shape(obj, keys, label):
    if not isinstance(obj, dict) or obj.keys() != keys:
        raise ValidationError(label + " has missing or unregistered fields")


def _decimal(value, label, negative=False):
    if not isinstance(value, str) or len(value) > 100 or NUMBER.fullmatch(value) is None:
        raise ValidationError(label + " needs a finite plain Decimal string")
    parsed = Decimal(value)
    if not parsed.is_finite() or (not negative and parsed < 0):
        raise ValidationError(label + " is outside its signed range")
    return parsed


def _key(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValidationError(label + " needs a bounded identifier")
    return value


def _day(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValidationError("ISO calendar date required")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError("invalid calendar date") from error
    return value


def _position(value):
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 10**12:
        raise ValidationError("position bound needs a signed integer within the input budget")
    return value


def _string(value):
    if value == D0:
        return "0"
    encoded = format(value, "f")
    return encoded.rstrip("0").rstrip(".") if "." in encoded else encoded


@dataclass(frozen=True)
class _Case:
    identity: str
    weight: Decimal
    loss: Decimal
    long_payoff: Decimal
    margin: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class _Terms:
    minimum: int
    maximum: int
    fee: Decimal
    collateral: Decimal
    posting: str
    release: str


@dataclass(frozen=True)
class _Book:
    initial_cash: Decimal
    required_cash: Decimal
    start: str
    end: str
    changes: tuple[tuple[str, str, Decimal], ...]


def _read(payload):
    _shape(payload, {"schema_version", "request_id", "as_of", "currency", "loss_unit", "payoff_unit",
                     "confidence", "contract", "cash", "scenarios"}, "study")
    if payload["schema_version"] != SCHEMA:
        raise ValidationError("unsupported study schema")
    _key(payload["request_id"], "request_id")
    try:
        utc_instant(payload["as_of"])
    except (TypeError, ValueError) as error:
        raise ValidationError("as_of needs a UTC instant") from error
    if payload["currency"] != "USD" or payload["loss_unit"] != "USD" or payload["payoff_unit"] != "USD_per_long_contract":
        raise ValidationError("this scalar study requires explicit USD losses and USD payoffs for one long contract")
    alpha = _decimal(payload["confidence"], "confidence")
    if alpha <= D0 or alpha >= D1:
        raise ValidationError("confidence must be strictly inside (0, 1)")
    t = payload["contract"]
    _shape(t, {"payoff_kind", "settlement_currency", "minimum_position", "maximum_position",
               "fee_per_contract", "initial_collateral_per_contract", "collateral_post_on", "collateral_release_on"}, "contract")
    if t["payoff_kind"] != "linear_futures" or t["settlement_currency"] != "USD":
        raise ValidationError("only scalar linear futures with USD settlement are supported")
    terms = _Terms(_position(t["minimum_position"]), _position(t["maximum_position"]),
                   _decimal(t["fee_per_contract"], "fee"), _decimal(t["initial_collateral_per_contract"], "initial collateral"),
                   _day(t["collateral_post_on"]), _day(t["collateral_release_on"]))
    if terms.minimum > terms.maximum or terms.posting > terms.release:
        raise ValidationError("reversed contract bounds or collateral dates")
    c = payload["cash"]
    _shape(c, {"opening_cash", "minimum_free_cash", "start_date", "end_date", "baseline_events"}, "cash")
    start, end = _day(c["start_date"]), _day(c["end_date"])
    if not start <= terms.posting <= terms.release <= end:
        raise ValidationError("cash dates must cover posting and release")
    if not isinstance(c["baseline_events"], list) or len(c["baseline_events"]) > 512:
        raise ValidationError("baseline event input budget exceeded")
    baseline, event_keys = [], set()
    for item in c["baseline_events"]:
        _shape(item, {"event_id", "on", "cash_change"}, "baseline change")
        identity = _key(item["event_id"], "event_id")
        when = _day(item["on"])
        if identity in event_keys or identity.startswith("hedge:") or not start <= when <= end:
            raise ValidationError("baseline identity collision or omitted date")
        event_keys.add(identity)
        baseline.append((identity, when, _decimal(item["cash_change"], "baseline cash change", True)))
    book = _Book(_decimal(c["opening_cash"], "opening cash"), _decimal(c["minimum_free_cash"], "cash floor"),
                 start, end, tuple(baseline))
    if not isinstance(payload["scenarios"], list) or not 3 <= len(payload["scenarios"]) <= 256:
        raise ValidationError("three to 256 explicit scenarios are required")
    cases, keys, total = [], set(), len(baseline) * len(payload["scenarios"])
    for item in payload["scenarios"]:
        _shape(item, {"scenario_id", "probability", "unhedged_loss", "long_contract_payoff", "variation_margin"}, "scenario")
        identity = _key(item["scenario_id"], "scenario_id")
        probability = _decimal(item["probability"], "probability")
        if identity in keys or not D0 < probability <= D1:
            raise ValidationError("scenario identity and positive probability must be explicit")
        keys.add(identity)
        points = item["variation_margin"]
        if not isinstance(points, list) or len(points) > 512:
            raise ValidationError("margin point budget exceeded")
        margin, dates = [], set()
        for point in points:
            _shape(point, {"on", "cash_per_long_contract"}, "margin point")
            when = _day(point["on"])
            if when in dates or not terms.posting <= when <= terms.release:
                raise ValidationError("daily margin dates must be unique and covered by collateral")
            dates.add(when)
            margin.append((when, _decimal(point["cash_per_long_contract"], "long-contract cash", True)))
        total += len(margin) + 2
        cases.append(_Case(identity, probability, _decimal(item["unhedged_loss"], "loss", True),
                           _decimal(item["long_contract_payoff"], "long payoff", True), tuple(sorted(margin))))
    if total > 8192:
        raise ValidationError("combined cash trace input budget exceeded")
    return alpha, terms, book, tuple(cases)


def _weighted_moments(cases):
    """Pairwise identities avoid subtracting large nearly equal raw moments."""
    mean_l = sum((case.weight * case.loss for case in cases), D0)
    mean_h = sum((case.weight * case.long_payoff for case in cases), D0)
    variance, covariance = D0, D0
    for i, left in enumerate(cases):
        for right in cases[i + 1:]:
            weight = left.weight * right.weight
            dh = left.long_payoff - right.long_payoff
            variance += weight * dh * dh
            covariance += weight * dh * (left.loss - right.loss)
    return mean_l, mean_h, variance, covariance


def _loss_statistics(points, alpha):
    masses = {}
    for value, weight in points:
        masses[value] = masses.get(value, D0) + weight
    ordered = sorted(masses.items())
    mean = sum((value * weight for value, weight in ordered), D0)
    variance = D0
    for index, (left, p) in enumerate(ordered):
        for right, q in ordered[index + 1:]:
            variance += p * q * (left - right) ** 2
    cdf, quantile = D0, ordered[-1][0]
    for value, weight in ordered:
        cdf += weight
        if cdf >= alpha:
            quantile = value
            break
    needed, integral = D1 - alpha, D0
    for value, weight in reversed(ordered):
        mass = min(needed, weight)
        integral += mass * value
        needed -= mass
        if needed == D0:
            break
    return {"expected_loss": _string(mean), "variance": _string(variance), "value_at_risk": _string(quantile),
            "expected_shortfall": _string(integral / (D1 - alpha)), "worst_loss": _string(ordered[-1][0])}


def _cash_trace(size, case, terms, book):
    funds = {}
    def flow(when, identity, kind, cash, posted=D0):
        funds.setdefault(when, []).append((identity, kind, cash, posted))
    for identity, when, change in book.changes:
        flow(when, identity, "baseline", change)
    deposit, fees = abs(size) * terms.collateral, abs(size) * terms.fee
    flow(terms.posting, "hedge:collateral-post", "initial_collateral", -deposit, deposit)
    flow(terms.posting, "hedge:fees", "fees", -fees)
    for when, unit_cash in case.margin:
        flow(when, "hedge:vm:" + when, "variation_margin", size * unit_cash)
    flow(terms.release, "hedge:collateral-release", "collateral_release", deposit, -deposit)
    cash, collateral, lowest = book.initial_cash, D0, book.initial_cash
    evidence = {"on": book.start, "basis": "opening_cash"}
    path = []
    for when in sorted(set(funds) | {book.start, book.end}):
        entries = funds.get(when, ())
        debits = sum((entry[2] for entry in entries if entry[2] < D0), D0)
        trough = cash + debits
        if trough < lowest:
            lowest = trough
            evidence = {"on": when, "basis": "all_same_day_outflows_before_inflows",
                        "outflow_event_ids": sorted(entry[0] for entry in entries if entry[2] < D0)}
        cash += sum((entry[2] for entry in entries), D0)
        collateral += sum((entry[3] for entry in entries), D0)
        path.append({"on": when, "unrestricted_cash": _string(cash), "posted_collateral": _string(collateral),
                     "conservative_same_day_minimum": _string(trough),
                     "events": [{"event_id": identity, "kind": kind, "cash_change": _string(change), "collateral_change": _string(posted)}
                                for identity, kind, change, posted in sorted(entries)]})
    shortage = max(D0, book.required_cash - lowest)
    return {"scenario_id": case.identity, "probability": _string(case.weight), "ending_unrestricted_cash": _string(cash),
            "ending_posted_collateral": _string(collateral), "minimum_free_cash": _string(lowest), "minimum_free_cash_witness": evidence,
            "required_extra_cash": _string(shortage), "passes_declared_funding": shortage == D0,
            "variation_margin_total": _string(size * case.long_payoff), "initial_collateral": _string(deposit),
            "fees": _string(fees), "terminal_payoff_added_separately": False, "dates": path}, shortage


def evaluate_hedge_payload(payload):
    """Compare declared integer candidates; no broker or execution side effects."""
    alpha, terms, book, cases = _read(payload)
    with localcontext() as ctx:
        ctx.prec = calculation_precision(payload)
        if sum((case.weight for case in cases), D0) != D1:
            raise ValidationError("probabilities must total exactly one without normalization")
        if any(sum((value for _, value in case.margin), D0) != case.long_payoff for case in cases):
            raise ValidationError("daily margin must sum exactly to the complete long-contract payoff")
        mean_l, mean_h, variance, covariance = _weighted_moments(cases)
        fit = covariance / variance if variance else None
        bounded = min(Decimal(terms.maximum), max(Decimal(terms.minimum), fit)) if fit is not None else None
        positions = {0}
        if bounded is not None:
            positions |= {int(bounded.to_integral_value(rounding=ROUND_FLOOR)), int(bounded.to_integral_value(rounding=ROUND_CEILING))}
        reports = []
        for size in sorted(positions):
            fee = abs(size) * terms.fee
            residual = [(case.loss - size * case.long_payoff + fee, case.weight) for case in cases]
            traces, liquidity = [], []
            for case in cases:
                trace, deficit = _cash_trace(size, case, terms, book)
                traces.append(trace)
                liquidity.append((deficit, case.weight))
            reports.append({"position": size, "reference_unhedged": size == 0,
                "within_declared_position_bounds": terms.minimum <= size <= terms.maximum,
                "economic_loss": _loss_statistics(residual, alpha), "fees": _string(fee),
                "margin_liquidity": {"basis": "dated_declared_baseline_plus_collateral_fees_and_variation_margin",
                    "same_day_basis": "conservative_outflows_before_inflows_not_actual_settlement_order",
                    "all_scenarios_pass_declared_funding": all(row["passes_declared_funding"] for row in traces),
                    "funding_shortfall_tail": _loss_statistics(liquidity, alpha), "scenarios": traces}})
        eligible = [row for row in reports if row["within_declared_position_bounds"] and row["margin_liquidity"]["all_scenarios_pass_declared_funding"]]
        reasons = ["hedge_payoff_variance_zero"] if fit is None else []
        if not eligible:
            reasons.append("no_compared_position_passes_declared_bounds_and_funding")
        preferred = None if fit is None or not eligible else min(eligible, key=lambda row: (
            Decimal(row["economic_loss"]["variance"]), Decimal(row["economic_loss"]["expected_loss"]), abs(row["position"]), row["position"]))["position"]
        square_sum = sum((case.weight ** 2 for case in cases), D0)
        return {"schema_version": SCHEMA, "model_version": VERSION, "request_id": payload["request_id"], "as_of": payload["as_of"],
            "status": "held" if reasons else "scenario_only", "currency": "USD", "confidence": _string(alpha),
            "loss_unit": "USD", "payoff_unit": "USD_per_long_contract", "fit": {
                "basis": "weighted_declared_population_moments_in_sample_not_calibrated", "scenario_count": len(cases),
                "effective_scenario_count": _string(D1 / square_sum), "effective_count_basis": "inverse_probability_square_sum_not_independent_observations",
                "unhedged_loss_mean": _string(mean_l), "long_contract_payoff_mean": _string(mean_h),
                "long_contract_payoff_variance": _string(variance), "loss_payoff_covariance": _string(covariance),
                "minimum_variance_signed_contracts": None if fit is None else _string(fit),
                "bound_projected_signed_contracts": None if bounded is None else _string(bounded),
                "minimum_position": terms.minimum, "maximum_position": terms.maximum, "division_basis": "finite_precision_decimal_signed_contracts"},
            "candidates": reports, "preferred_compared_scenario_position": preferred, "blockers": reasons,
            "selection_basis": "lowest_in_sample_variance_then_expected_loss_among_compared_funded_integer_positions",
            "tail_basis": "discrete_weighted_quantile_and_top_tail_mean_including_boundary_probability_mass",
            "sample_probabilities_verified": False, "calibration_verified": False, "actual_settlement_verified": False,
            "source_rights_verified": False, "firm_price_eligible": False, "execution_enabled": False, "paper_only": True,
            "warnings": ["declared_weights_do_not_establish_predictive_or_independent_sample_evidence",
                "loss_and_margin_baseline_ownership_and_settlement_are_unverified",
                "economic_loss_is_separate_from_cash_shortfall_and_is_not_an_extra_cash_debit",
                "initial_collateral_returns_as_an_asset_and_variation_margin_already_includes_terminal_payoff",
                "dated_cash_uses_same_day_debits_before_credits_without_verified_intraday_times",
                "compared_positions_are_zero_and_adjacent_integers_of_the_bound_projected_scalar_fit",
                "funding_feasible_positions_elsewhere_in_the_declared_interval_are_not_searched",
                "margin_hikes_intraday_calls_clearing_lags_haircuts_spreads_and_real_commissions_are_not_modelled",
                "multi_instrument_covariance_options_fx_nonlinear_positions_and_execution_are_unsupported"]}


def hedge_contract():
    return {"schema_version": SCHEMA, "request_id": None, "as_of": None, "currency": "USD", "loss_unit": "USD",
            "payoff_unit": "USD_per_long_contract", "confidence": None, "scenarios": [],
            "contract": {"payoff_kind": "linear_futures", "settlement_currency": "USD", "minimum_position": None,
                         "maximum_position": None, "fee_per_contract": None, "initial_collateral_per_contract": None,
                         "collateral_post_on": None, "collateral_release_on": None},
            "cash": {"opening_cash": None, "minimum_free_cash": None, "start_date": None, "end_date": None, "baseline_events": []}}


def evaluate_hedge_study(payload):
    return evaluate_hedge_payload(payload)


def hedge_study_template():
    return hedge_contract()
