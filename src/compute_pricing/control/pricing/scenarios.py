"""Reprice complete explicit scenarios without fabricating shock probabilities."""
from .._numbers import digest
from ..domain import ValidationError
from .engine import evaluate_pricing


def evaluate_pricing_scenarios(payload):
    if not isinstance(payload, dict) or set(payload) != {"baseline", "scenarios"}:
        raise ValidationError("scenarios: complete baseline and explicit alternatives required")
    scenarios = payload["scenarios"]
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 32:
        raise ValidationError("scenarios: bounded nonempty list required")
    baseline = evaluate_pricing(payload["baseline"])
    results, seen = [], set()
    for row in scenarios:
        if not isinstance(row, dict) or set(row) != {"scenario_id", "request"}:
            raise ValidationError("scenario: explicit identity and complete request required")
        identity = row["scenario_id"]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValidationError("scenario: unique identity required")
        seen.add(identity)
        result = evaluate_pricing(row["request"])
        if result["economics"] is None or baseline["economics"] is None or result["economics"]["currency"] != baseline["economics"]["currency"]:
            raise ValidationError("scenario: matching currency and commercial economics required")
        results.append({"scenario_id": identity, "result": result})
    return {"baseline": baseline, "scenarios": results, "input_hash": digest(payload),
            "model": "explicit-pricing-scenarios/1.0.0", "execution_enabled": False,
            "probability_status": "none_supplied_no_expected_tail_distribution",
            "warnings": ["alternatives_are_independent_complete_scenarios_not_additive_cash_or_capacity"]}
