"""Exact finite-ladder feasibility and observed-threshold level brackets.

Inputs are dimensionless quote bounds declared under one common pricing measure.
The module neither constructs that measure nor equates it with real-world odds.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import re
from typing import Any

from .._numbers import calculation_precision, text_number
from ..domain import utc_instant

SCHEMA = "conditional-threshold-ladder/1.0"
MODEL = "finite-monotone-quote-diagnostic/1.0.0"
MAX_QUOTES = 256
MAX_VIOLATIONS = 32
NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
IDENTITY = re.compile(r"[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*")
ALIGNMENT = ("terms_id", "underlying_id", "settlement_id", "issuer_id", "threshold_unit", "comparison")
TERMS = {*ALIGNMENT, "bound_basis", "alignment_evidence_id"}
QUOTE = {"quote_id", *ALIGNMENT, "normalization_evidence_id", "threshold", "bid_bound", "ask_bound", "observed_at", "expires_at"}


class DiagnosticError(ValueError):
    """A safe code, without invalid values, quote text or network diagnostics."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _object(value: Any, fields: set[str]):
    if not isinstance(value, dict) or set(value) != fields:
        raise DiagnosticError("explicit_diagnostic_fields_required")


def _identity(value: Any, *, nullable: bool = False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or len(value) > 128 or not IDENTITY.fullmatch(value):
        raise DiagnosticError("canonical_diagnostic_identity_required")


def _number(value: Any, *, probability: bool = False) -> Decimal:
    if not isinstance(value, str) or len(value) > 128 or not NUMBER.fullmatch(value):
        raise DiagnosticError("exact_diagnostic_decimal_string_required")
    result = Decimal(value)
    if not result.is_finite() or probability and not Decimal(0) <= result <= Decimal(1):
        raise DiagnosticError("diagnostic_probability_out_of_range")
    return result


def _time(value: Any):
    try:
        return utc_instant(value)
    except (ValueError, TypeError):
        raise DiagnosticError("diagnostic_utc_timestamp_required") from None


def _text(value: Decimal) -> str:
    return "0" if value == 0 else text_number(value)


def evaluate_threshold_ladder(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate declared bounds only; no HTTP, curve repair or tail extrapolation.

    The level cut is q = inf{x: S(x) <= level}, where S(x) = Q(X > x).
    An observed lower bound > level proves q > threshold. An observed upper
    bound <= level proves q <= threshold. Equality is intentionally asymmetric.
    """
    _object(payload, {"schema_version", "as_of", "survival_level", "common_terms", "quotes"})
    if payload["schema_version"] != SCHEMA:
        raise DiagnosticError("unsupported_diagnostic_schema")
    as_of = _time(payload["as_of"])
    level = _number(payload["survival_level"], probability=True)
    if not Decimal(0) < level < Decimal(1):
        raise DiagnosticError("interior_survival_level_required")
    common, inputs = payload["common_terms"], payload["quotes"]
    _object(common, TERMS)
    if not isinstance(inputs, list) or len(inputs) > MAX_QUOTES:
        raise DiagnosticError("bounded_diagnostic_quotes_required")
    blockers: list[dict[str, Any]] = []
    for field in sorted(TERMS):
        _identity(common[field], nullable=True)
        if common[field] is None:
            blockers.append({"code": "common_term_missing", "field": field})
    if common["comparison"] is not None and common["comparison"] != "strict_gt":
        blockers.append({"code": "comparison_not_supported"})
    if common["bound_basis"] is not None and common["bound_basis"] != "conditional_common_pricing_measure":
        blockers.append({"code": "common_pricing_measure_not_declared"})
    rows, identifiers, thresholds = [], set(), set()
    for item in inputs:
        _object(item, QUOTE)
        _identity(item["quote_id"])
        identity = item["quote_id"]
        if identity in identifiers:
            raise DiagnosticError("duplicate_diagnostic_quote_identity")
        identifiers.add(identity)
        threshold = _number(item["threshold"])
        if threshold in thresholds:
            raise DiagnosticError("duplicate_diagnostic_threshold")
        thresholds.add(threshold)
        bid = None if item["bid_bound"] is None else _number(item["bid_bound"], probability=True)
        ask = None if item["ask_bound"] is None else _number(item["ask_bound"], probability=True)
        for field in ALIGNMENT:
            _identity(item[field], nullable=True)
            if item[field] is None:
                blockers.append({"code": "quote_alignment_missing", "quote_id": identity, "field": field})
            elif item[field] != common[field]:
                blockers.append({"code": "quote_alignment_mismatch", "quote_id": identity, "field": field})
        _identity(item["normalization_evidence_id"], nullable=True)
        if item["normalization_evidence_id"] is None:
            blockers.append({"code": "normalization_evidence_missing", "quote_id": identity})
        observed, expires = _time(item["observed_at"]), _time(item["expires_at"])
        if expires <= observed:
            raise DiagnosticError("positive_quote_validity_interval_required")
        if observed > as_of:
            blockers.append({"code": "future_quote", "quote_id": identity})
        if expires <= as_of:
            blockers.append({"code": "stale_quote", "quote_id": identity})
        rows.append({"quote_id": identity, "threshold": threshold, "bid": bid, "ask": ask})
    rows.sort(key=lambda row: row["threshold"])
    result = {"schema_version": SCHEMA, "model_version": MODEL, "as_of": payload["as_of"],
        "role": "conditional_quote_diagnostic", "status": "held", "quote_count": len(rows),
        "threshold_unit": common["threshold_unit"], "survival_level": _text(level),
        "bound_basis": common["bound_basis"], "alignment_evidence_id": common["alignment_evidence_id"],
        "conditional_envelope_feasible": None, "envelopes": [], "level_identification": None,
        "dominance": {"checked_pair_count": 0, "violation_count": 0, "violations": [], "violations_truncated": False,
                      "basis": "normalized_gross_quote_inequality_under_declared_aligned_payoffs",
                      "executable_arbitrage_claim": False},
        "blockers": blockers, "warnings": ["caller_alignment_and_normalization_claims_not_verified",
            "quote_bounds_conditional_on_common_pricing_measure_not_real_world_probabilities",
            "finite_ladder_does_not_identify_unknown_tails_or_expected_underlying_value",
            "no_depth_fees_funding_credit_or_executable_arbitrage_assessment",
            "observed_threshold_brackets_no_interpolation_or_curve_repair"],
        "expected_underlying_value": None, "compute_price_eligible": False,
        "no_arbitrage_certificate": False, "execution_eligible": False}
    if not rows:
        blockers.append({"code": "empty_ladder"})
    elif not any(row["bid"] is not None or row["ask"] is not None for row in rows):
        blockers.append({"code": "no_quoted_probability_bounds"})
    if blockers:
        return result
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        return _evaluate(rows, level, result)


def _evaluate(rows, level, result):
    count = len(rows)
    lower, upper = [Decimal(0)] * count, [Decimal(1)] * count
    lower_witness, upper_witness = [None] * count, [None] * count
    for index in range(count - 1, -1, -1):
        if index + 1 < count:
            lower[index], lower_witness[index] = lower[index + 1], lower_witness[index + 1]
        bid = rows[index]["bid"]
        if bid is not None and (bid > lower[index] or bid == lower[index] and lower_witness[index] is None):
            lower[index], lower_witness[index] = bid, rows[index]["quote_id"]
    for index in range(count):
        if index:
            upper[index], upper_witness[index] = upper[index - 1], upper_witness[index - 1]
        ask = rows[index]["ask"]
        if ask is not None and (ask < upper[index] or ask == upper[index] and upper_witness[index] is None):
            upper[index], upper_witness[index] = ask, rows[index]["quote_id"]
    result["envelopes"] = [{"quote_id": row["quote_id"], "threshold": _text(row["threshold"]),
        "bid_bound": None if row["bid"] is None else _text(row["bid"]),
        "ask_bound": None if row["ask"] is None else _text(row["ask"]),
        "lower": _text(lower[index]), "upper": _text(upper[index]),
        "lower_quote_witness": lower_witness[index], "upper_quote_witness": upper_witness[index],
        "universal_lower_only": lower_witness[index] is None, "universal_upper_only": upper_witness[index] is None}
        for index, row in enumerate(rows)]
    dominance = result["dominance"]
    for low in range(count):
        for high in range(low, count):
            ask, bid = rows[low]["ask"], rows[high]["bid"]
            if ask is None or bid is None:
                continue
            dominance["checked_pair_count"] += 1
            if bid <= ask:
                continue
            dominance["violation_count"] += 1
            if len(dominance["violations"]) < MAX_VIOLATIONS:
                dominance["violations"].append({"code": "same_threshold_crossing" if low == high else "nested_claim_quote_crossing",
                    "lower_threshold_quote_id": rows[low]["quote_id"], "higher_threshold_quote_id": rows[high]["quote_id"],
                    "normalized_gross_gap": _text(bid - ask)})
    dominance["violations_truncated"] = dominance["violation_count"] > len(dominance["violations"])
    impossible = [rows[index]["quote_id"] for index in range(count) if lower[index] > upper[index]]
    result["conditional_envelope_feasible"] = not impossible
    if impossible:
        result["blockers"].append({"code": "infeasible_monotone_envelope", "quote_ids": impossible})
        return result
    lower_nodes = [row["threshold"] for index, row in enumerate(rows) if lower[index] > level]
    upper_nodes = [row["threshold"] for index, row in enumerate(rows) if upper[index] <= level]
    lo, hi = max(lower_nodes, default=None), min(upper_nodes, default=None)
    bounded = lo is not None and hi is not None
    result["level_identification"] = {"definition": "inf_x_where_conditional_survival_is_at_most_level",
        "lower": None if lo is None else _text(lo), "upper": None if hi is None else _text(hi),
        "lower_open": True if lo is not None else None, "upper_closed": True if hi is not None else None,
        "lower_tail_unbounded": lo is None, "upper_tail_unbounded": hi is None, "bounded": bounded,
        "width": _text(hi - lo) if bounded else None, "threshold_unit": result["threshold_unit"],
        "point_estimate": None, "real_world_quantile_claim": False}
    result["status"] = "conditional_feasible"
    return result
