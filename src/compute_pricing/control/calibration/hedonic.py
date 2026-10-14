"""Explicit log-price OLS with temporal, provider and underlying-lot holdouts.

Float arithmetic is confined to statistical research. No fitted coefficient is
published as a financial price, regional premium or approved pricing policy.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any, Mapping

import numpy as np

from compute_pricing.control._numbers import digest, hours
from compute_pricing.control.domain import ValidationError, exact_decimal, parse_market_observation, utc_instant

PHYSICAL_KINDS = {"listing_ask", "firm_supplier_rfq", "confirmed_rental_trade"}
SUPPORT_KEYS = frozenset({"training_rows", "holdout_rows", "training_provider_groups", "holdout_provider_groups",
                        "training_sources", "holdout_sources", "training_timestamps", "holdout_timestamps",
                        "training_source_times", "holdout_source_times"})


def _fail(code: str) -> None:
    raise ValidationError(code)


def _design_contract(numeric_features, categorical_features):
    if not isinstance(numeric_features, dict) or not isinstance(categorical_features, dict):
        _fail("calibration_feature_contract_required")
    if not numeric_features and not categorical_features or set(numeric_features) & set(categorical_features):
        _fail("calibration_nonoverlapping_features_required")
    if len(numeric_features) + len(categorical_features) > 32:
        _fail("calibration_feature_limit")
    columns = ["intercept"]
    for name, definition in sorted(numeric_features.items()):
        if not isinstance(name, str) or not name or not isinstance(definition, dict) or set(definition) != {"unit"} or not isinstance(definition["unit"], str) or not definition["unit"]:
            _fail("calibration_numeric_unit_required")
        columns.append("numeric:" + name)
    for name, definition in sorted(categorical_features.items()):
        if not isinstance(name, str) or not name or not isinstance(definition, dict) or set(definition) != {"reference", "levels", "unit"}:
            _fail("calibration_category_contract_required")
        levels = definition["levels"]
        if (not isinstance(levels, list) or not 2 <= len(levels) <= 64 or any(not isinstance(item, str) or not item for item in levels)
                or len(set(levels)) != len(levels) or definition["reference"] not in levels
                or definition["unit"] is not None and not isinstance(definition["unit"], str)):
            _fail("calibration_category_reference_required")
        columns.extend("category:" + name + "=" + level for level in levels if level != definition["reference"])
    if len(columns) > 64 or len(set(columns)) != len(columns):
        _fail("calibration_design_column_limit")
    return columns


def _cohort_contract(cohort):
    required = {"hardware_model", "currency", "kind", "configuration", "duration_hours", "billing_type"}
    if not isinstance(cohort, dict) or set(cohort) != required or cohort["kind"] not in PHYSICAL_KINDS:
        _fail("calibration_physical_cohort_required")
    if not isinstance(cohort["hardware_model"], str) or not cohort["hardware_model"] or not isinstance(cohort["billing_type"], str) or not cohort["billing_type"]:
        _fail("calibration_cohort_identity_required")
    if not isinstance(cohort["configuration"], dict) or not cohort["configuration"] or any(value is None for value in cohort["configuration"].values()):
        _fail("calibration_configuration_cohort_required")
    if not isinstance(cohort["currency"], str) or not re.fullmatch(r"[A-Z]{3}", cohort["currency"]):
        _fail("calibration_currency_required")
    if exact_decimal(cohort["duration_hours"], nonnegative=True) <= 0:
        _fail("calibration_duration_required")


def _supports(rows):
    return {"rows": len(rows), "provider_groups": len({row["group"] for row in rows}),
            "sources": len({row["source"] for row in rows}),
            "timestamps": len({row["observed"] for row in rows}),
            "source_times": len({(row["source"], row["observed"]) for row in rows})}


def evaluate_calibration_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"rows", "cohort", "numeric_features", "categorical_features", "split_at", "as_of", "minimum_support"}
    if not isinstance(payload, dict) or set(payload) != expected:
        _fail("calibration_explicit_payload_required")
    return fit_hedonic(**payload)


def fit_hedonic(*, rows: list[dict], cohort: dict, numeric_features: dict, categorical_features: dict,
                split_at: str, as_of: str, minimum_support: dict) -> dict[str, Any]:
    _cohort_contract(cohort)
    columns = _design_contract(numeric_features, categorical_features)
    cutoff, clock = utc_instant(split_at), utc_instant(as_of)
    if cutoff >= clock:
        _fail("calibration_holdout_must_follow_training")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        _fail("calibration_bounded_rows_required")
    if not isinstance(minimum_support, dict) or set(minimum_support) != SUPPORT_KEYS:
        _fail("calibration_explicit_support_required")
    if any(type(value) is not int or not 2 <= value <= 10000 for value in minimum_support.values()):
        _fail("calibration_minimum_support_must_be_at_least_two")
    training, holdout, exclusions, identities = [], [], [], set()
    for position, record in enumerate(rows):
        identity = "invalid-observation-" + str(position)
        reasons = []
        try:
            if not isinstance(record, dict) or set(record) != {"observation", "features"}:
                _fail("calibration_row_shape")
            observation = parse_market_observation(record["observation"])
            identity = observation.id
            if identity in identities:
                _fail("calibration_duplicate_observation")
            identities.add(identity)
        except ValidationError:
            exclusions.append({"observation_id": identity, "reasons": ["domain_or_duplicate_validation"]})
            continue
        observed, ingested = utc_instant(observation.observed_at), utc_instant(observation.ingested_at)
        if observed > clock or ingested > clock:
            reasons.append("future_or_unavailable_at_as_of")
        if observed < cutoff and ingested >= cutoff:
            reasons.append("training_data_not_available_at_split")
        rights = observation.rights
        if (observation.status != "verified" or rights is None or rights.status != "allowed"
                or rights.observe != "PASS" or rights.retain != "PASS" or rights.benchmark != "PASS" or rights.verified_by is None
                or rights.expires_at is not None and utc_instant(rights.expires_at) <= clock):
            reasons.append("unverified_or_unadmitted_research_rights")
        if not observation.source_version or not observation.provider_group_id or not observation.lot_id:
            reasons.append("missing_source_or_independent_identity")
        if observation.kind != cohort["kind"] or observation.kind not in PHYSICAL_KINDS:
            reasons.append("incompatible_price_role")
        if observation.price is None or observation.price.unit != "gpu_hour" or observation.price.currency != cohort["currency"]:
            reasons.append("incompatible_price_denominator")
        elif exact_decimal(observation.price.amount, nonnegative=True) <= 0:
            reasons.append("nonpositive_log_price")
        if observation.hardware is None or observation.hardware.model != cohort["hardware_model"]:
            reasons.append("hardware_cohort_mismatch")
        if observation.configuration is None or any(observation.configuration.to_dict().get(key) != value for key, value in cohort["configuration"].items()):
            reasons.append("configuration_cohort_mismatch")
        if observation.extensions.get("billing_type") != cohort["billing_type"]:
            reasons.append("billing_cohort_mismatch")
        if observation.starts_at is None or observation.ends_at is None or hours(observation.starts_at, observation.ends_at) != exact_decimal(cohort["duration_hours"]):
            reasons.append("duration_cohort_mismatch")
        features, values = record["features"], {}
        if not isinstance(features, dict):
            reasons.append("feature_metadata_required")
        else:
            for name, definition in {**numeric_features, **categorical_features}.items():
                feature = features.get(name)
                if not isinstance(feature, dict) or set(feature) != {"value", "unit", "available_at", "status"} or feature.get("status") != "verified":
                    reasons.append("missing_or_unverified_feature")
                    continue
                try:
                    if utc_instant(feature["available_at"]) > observed:
                        reasons.append("feature_unavailable_at_observation")
                    if feature["unit"] != definition["unit"]:
                        reasons.append("feature_unit_mismatch")
                    if name in numeric_features:
                        values[name] = float(exact_decimal(feature["value"]))
                        if not math.isfinite(values[name]):
                            reasons.append("nonfinite_design_value")
                    elif feature["value"] not in definition["levels"]:
                        reasons.append("undeclared_category")
                    else:
                        values[name] = feature["value"]
                except (ValidationError, ValueError, TypeError, OverflowError):
                    reasons.append("invalid_feature_value_or_time")
        if reasons:
            exclusions.append({"observation_id": identity, "reasons": sorted(set(reasons))})
            continue
        item = {"id": identity, "group": observation.provider_group_id, "lot": observation.lot_id,
                "source": observation.source_id, "observed": observed, "features": values,
                "log_price": math.log(float(exact_decimal(observation.price.amount)))}
        (training if observed < cutoff else holdout).append(item)
    for label, population in (("training", training), ("holdout", holdout)):
        support = _supports(population)
        if any(support[key] < minimum_support[label + "_" + key] for key in support):
            _fail("calibration_insufficient_" + label + "_support")
    if len(training) <= len(columns):
        _fail("calibration_insufficient_residual_degrees_of_freedom")
    if {row["group"] for row in training} & {row["group"] for row in holdout}:
        _fail("calibration_provider_group_holdout_leakage")
    if {row["lot"] for row in training} & {row["lot"] for row in holdout}:
        _fail("calibration_underlying_lot_holdout_leakage")
    # One training observation per underlying lot prevents duplicated resellers
    # or time snapshots from manufacturing sample support within the fit.
    if len({row["lot"] for row in training}) != len(training) or len({row["lot"] for row in holdout}) != len(holdout):
        _fail("calibration_repeated_underlying_lot")
    scaling = {}
    for name in sorted(numeric_features):
        population = np.asarray([row["features"][name] for row in training], dtype=float)
        mean, standard = float(population.mean()), float(population.std())
        if not math.isfinite(mean) or not math.isfinite(standard) or standard <= 0:
            _fail("calibration_constant_or_invalid_numeric_design")
        scaling[name] = {"mean": mean, "standard_deviation": standard, "unit": numeric_features[name]["unit"],
                         "training_min": float(population.min()), "training_max": float(population.max())}

    def matrix(population):
        result = []
        for row in population:
            design = [1.0]
            for name in sorted(numeric_features):
                design.append((row["features"][name] - scaling[name]["mean"]) / scaling[name]["standard_deviation"])
            for name, definition in sorted(categorical_features.items()):
                design.extend(float(row["features"][name] == level) for level in definition["levels"] if level != definition["reference"])
            result.append(design)
        return np.asarray(result, dtype=float)
    x_train, x_holdout = matrix(training), matrix(holdout)
    y_train, y_holdout = np.asarray([row["log_price"] for row in training]), np.asarray([row["log_price"] for row in holdout])
    if not all(np.isfinite(array).all() for array in (x_train, x_holdout, y_train, y_holdout)):
        _fail("calibration_nonfinite_matrix")
    try:
        coefficients, _, rank, singular = np.linalg.lstsq(x_train, y_train, rcond=None)
    except np.linalg.LinAlgError:
        _fail("calibration_solver_did_not_converge")
    if int(rank) != len(columns) or not np.isfinite(coefficients).all():
        _fail("calibration_rank_deficient_design")

    def errors(x, y):
        error = x @ coefficients - y
        if not np.isfinite(error).all():
            _fail("calibration_nonfinite_holdout_error")
        magnitude = float(np.abs(error).max())
        scaled = error / magnitude if magnitude > 0 else error
        # Scaling avoids squaring overflow on explicit out-of-range holdouts.
        return {"mae_log": magnitude * float(np.abs(scaled).mean()), "rmse_log": magnitude * float(np.sqrt((scaled ** 2).mean())),
                "observations": int(len(y)), "target": {"transformation": "natural_log", "currency": cohort["currency"], "unit": "gpu_hour"}}
    outside_range = sum(any(row["features"][name] < scaling[name]["training_min"] or row["features"][name] > scaling[name]["training_max"] for name in numeric_features) for row in holdout)
    result = {"status": "research_only", "live_pricing_eligible": False, "execution_enabled": False,
              "approval_status": "independent_empirical_calibration_approval_required",
              "versions": {"model": "research-hedonic-log-ols/1.0.0", "numpy": np.__version__, "domain": "1.0.0"},
              "cohort": dict(cohort), "split": {"split_at": split_at, "as_of": as_of,
                  "criterion": "temporal_provider_and_underlying_lot_disjoint", "feature_scaling": "training_only"},
              "columns": columns, "numeric_scaling": scaling, "categorical_coding": categorical_features,
              "coefficients": {name: float(value) for name, value in zip(columns, coefficients)},
              "design_rank": int(rank), "condition_number": float(singular[0] / singular[-1]),
              "training_metrics": errors(x_train, y_train), "holdout_metrics": errors(x_holdout, y_holdout),
              "support": {"training": _supports(training), "holdout": _supports(holdout)},
              "coverage": {"input_rows": len(rows), "eligible_rows": len(training) + len(holdout),
                  "exclusions": exclusions, "exclusion_counts": dict(Counter(reason for row in exclusions for reason in row["reasons"])),
                  "holdout_outside_numeric_training_range": outside_range,
                  "population": "one_explicit_physical_cohort_with_disjoint_future_provider_groups_not_all_compute"},
              "warnings": ["research_float_log_regression_not_a_financial_price", "observational_associations_not_causal_premiums",
                  "holdout_provider_disjoint_population_can_differ_from_existing_providers", "no_live_policy_activation",
                  "no_exponentiated_price_without_bias_correction_and_independent_validation"]}
    packet = {"rows": rows, "cohort": cohort, "numeric_features": numeric_features, "categorical_features": categorical_features,
              "split_at": split_at, "as_of": as_of, "minimum_support": minimum_support}
    result["input_hash"] = digest(packet)
    result["model_hash"] = digest(result)
    return result
