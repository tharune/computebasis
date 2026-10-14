"""Provider scorecard and per-quote risk economics, ported from the mock workbook (v1.3).

Every constant and formula here mirrors a cell range in "Senthos Labs - Mock Provider and Quote
Data v1.3.xlsx" (sheets Scoring, Assumptions, Provider Scores, Quote Analysis). The failure
probabilities, cost of capital and reference prices are the workbook's own placeholders; they are
inputs to a demonstration, not calibrated estimates. Tests recompute the workbook's cached results.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Mapping

CATEGORIES = (("certification", 0.15), ("dc_tier", 0.15), ("sla", 0.20),
              ("delivery", 0.15), ("credit", 0.05), ("responsiveness", 0.30))
TIER_SCORE = {1: 3, 2: 2, 3: 1}
MAX_CATEGORY_SCORE = 3
GRADE_BANDS = (("A", 85, 0.00), ("B", 70, 0.02), ("C", 55, 0.05), ("D", 0, 0.10))
GRADES = tuple(band[0] for band in GRADE_BANDS)

ASSUMPTIONS: Mapping[str, Any] = {
    "hours_per_month": 730,
    "cost_of_capital": 0.12,            # per year
    "failure_share_remaining": 0.5,     # average share of the term left when a supplier fails
    "typical_term_months": 12,
    "expiry_warning_days": 14,
    "min_eligible_grade": "C",
    "max_missing_fields": 3,
    "failure_probability": {"A": 0.01, "B": 0.03, "C": 0.07, "D": 0.15},  # annual, by grade
    # On-demand or short-term rental indexes, so the discount to them overstates term-resale margin.
    "reference": {"H100": 2.85, "B200": 5.94, "B300": 6.65, "H200": 3.16},  # GB300, Pro 6000: none
}

# The ten quote fields whose absence the workbook counts, in workbook column order (C D H I J L N O P T).
KEY_FIELDS = ("location", "country", "moq", "interconnect", "cooling", "lead_weeks",
              "months", "down_payment", "payment_days", "expires")


def quality_score(tiers: Mapping[str, int]) -> float:
    """Weighted tier scores over the maximum category score, on a 0-100 scale."""
    return sum(TIER_SCORE[tiers[name]] * weight for name, weight in CATEGORIES) / MAX_CATEGORY_SCORE * 100


def grade_for(score: float) -> tuple[str, float]:
    """Letter grade and the risk premium (a share of price) the Scoring tab attaches to it."""
    for grade, minimum, premium in GRADE_BANDS:
        if score >= minimum:
            return grade, premium
    raise ValueError("score below every grade band")  # unreachable: D starts at 0 (negative scores are invalid)


def _date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])


def missing_fields(quote: Mapping[str, Any]) -> list[str]:
    return [name for name in KEY_FIELDS if quote.get(name) in (None, "")]


def quote_economics(quote: Mapping[str, Any], *, grade: str, reference: float | None, as_of: dt.date,
                    assumptions: Mapping[str, Any] = ASSUMPTIONS) -> dict[str, Any]:
    """Per-quote economics exactly as the workbook's Quote Analysis tab computes them.

    Values the workbook leaves blank (no duration, no reference price) are None here.
    """
    price = float(quote["price"])
    months = quote.get("months")
    down_payment = quote.get("down_payment")
    gpus = int(quote["gpus_per_node"]) * int(quote["nodes"])
    premium = dict((band[0], band[2]) for band in GRADE_BANDS)[grade]
    annual_failure = assumptions["failure_probability"][grade]
    capital = assumptions["cost_of_capital"]

    contract_value = None if months is None else gpus * price * assumptions["hours_per_month"] * months
    deposit = None if contract_value is None or down_payment is None else contract_value * down_payment
    available = _date(quote.get("available"))
    beyond_term = None if months is None else (
        contract_value * (months - assumptions["typical_term_months"]) / months if months > assumptions["typical_term_months"] else 0.0)
    financing = None if months is None else price * capital * (down_payment or 0) * months / 24
    scorecard_charge = price * premium
    failure = None if months is None else 1 - (1 - annual_failure) ** (months / 12)
    exposure = None if failure is None else failure * assumptions["failure_share_remaining"] * (
        price * (down_payment or 0) + (0 if reference is None else max(reference - price, 0)))
    missing = missing_fields(quote)
    min_grade, max_missing = assumptions["min_eligible_grade"], assumptions["max_missing_fields"]
    risk_scorecard = None if financing is None else price + financing + scorecard_charge
    risk_adjusted = None if financing is None or exposure is None else price + financing + exposure

    reasons = []
    if risk_adjusted is None:
        reasons.append("no stated duration")
    if down_payment is None:
        reasons.append("no stated down payment")
    if GRADES.index(grade) > GRADES.index(min_grade):
        reasons.append(f"grade {grade} is below {min_grade}")
    if len(missing) > max_missing:
        reasons.append(f"{len(missing)} of {len(KEY_FIELDS)} key fields missing")

    posted, expires = _date(quote.get("posted")), _date(quote.get("expires"))
    flags = []
    if available and posted and available < posted:
        flags.append("Available date is before the posted date.")
    if expires is None:
        flags.append("No expiry.")
    elif (expires - as_of).days <= assumptions["expiry_warning_days"]:
        flags.append(f"Expires within {assumptions['expiry_warning_days']} days.")
    if months is None:
        flags.append("No duration.")
    if down_payment is None:
        flags.append("No down payment stated.")
    if quote.get("location") in (None, ""):
        flags.append("No location.")

    return {
        "gpus": gpus, "contract_value": contract_value, "down_payment_usd": deposit,
        "months_until_available": None if available is None else max(0.0, (available - as_of).days / 30.4),
        "commitment_beyond_term": beyond_term, "financing_cost": financing, "scorecard_charge": scorecard_charge,
        "failure_probability": failure, "exposure_charge": exposure, "risk_adjusted_scorecard": risk_scorecard,
        "risk_adjusted": risk_adjusted, "reference": reference,
        "discount_to_reference": None if reference is None else 1 - price / reference,
        "missing": missing, "flags": flags, "eligible": not reasons, "ineligible_reasons": reasons,
    }
