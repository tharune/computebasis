"""Current-source-bound comparisons of complete selected retained snapshots.

The display index is never an input. This module reads no vendor API, invents
no market bid, and separates publisher aggregates from physical comparisons.
"""
from collections import Counter
from copy import deepcopy
import datetime as dt
from decimal import Decimal, localcontext
import re

from compute_pricing.control._numbers import calculation_precision, canonical_json, digest, hours, number, text_number
from compute_pricing.control.benchmark import evaluate_benchmark
from compute_pricing.control.connectors.adapters import ADAPTERS
from compute_pricing.control.domain import ValidationError, admission_blockers, parse_market_observation, utc_instant
from compute_pricing.control.reporting import SnapshotStoreError
from .market import _collection_packet
from .provenance import PricingProvenance


VERSION = "retained-market-reference/1.0.0"
MAX_ROWS = 10000
_COHORT = {"scope", "hardware_model", "hardware_memory_gib", "currency", "native_unit", "price_side",
           "country_code", "configuration", "starts_at", "ends_at", "gpu_count", "aggregate_terms", "observation_period"}
_CONFIG_NUMERIC = {"cpu_cores", "ram_gib", "storage_gib", "network_gbps"}
_CONFIG = _CONFIG_NUMERIC | {"interconnect", "privacy_class", "tenancy"}
_NON_COMPUTE_ROLES = {"cloud_vm_list_price", "publisher_gpu_vm_reference", "native_cloud_meter_tariff",
    "native_product_price_catalog", "energy_market_reference", "reference_fx", "model_token_price",
    "model_metadata", "model_recipe_metadata", "financial_future_mark", "event_contract_price", "licensed_index", "catalog",
    "carbon_intensity_reference", "grid_carbon_intensity", "grid_carbon_reference"}


def market_reference_contract() -> dict:
    return {"schema_version": VERSION, "request_fields": ["source_scopes", "policy_revision", "cohort"],
        "cohort_fields": sorted(_COHORT), "source_scope_fields": ["source_id", "filters"],
        "template_unknown": {"source_scopes": [], "policy_revision": None,
                             "cohort": {key: None for key in sorted(_COHORT)}},
        "scopes": ["aggregate_reference", "physical_offer"], "native_units": ["gpu_hour", "node_hour"],
        "price_sides": ["ask", "trade"], "configuration_fields": sorted(_CONFIG),
        "maximum_selected_rows": MAX_ROWS, "as_of": "current_server_utc_instant",
        "aggregate_rules": ["country_memory_delivery_quantity_null_configuration_empty",
            "exact_billing_type_reservation_months_and_measurement_period",
            "advertised_commitment_duration_never_becomes_future_start_delivery"],
        "physical_rules": ["explicit_memory_configuration_region_quantity_and_exact_calendar_delivery",
            "node_rates_require_explicit_whole_node_count_and_complete_allocation"],
        "normalization": "node_hour_divided_only_by_retained_explicit_integer_accelerator_count",
        "reference_basis": "saved_policy_weighted_same_side_retained_evidence_not_orderbook_midpoint",
        "policy_binding": "exact_current_saved_policy_revision_and_current_server_source_permissions",
        "physical_price_eligible": False, "firm_price_eligible": False, "execution_enabled": False,
        "market_complete": False, "vendor_fetch_per_request": False}


def _shape(value, fields, name):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(f"{name}: exact explicit fields required")


def _scope_key(scope):
    _shape(scope, {"source_id", "filters"}, "source scope")
    if not isinstance(scope["source_id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", scope["source_id"]):
        raise ValidationError("source_id: canonical server source required")
    if not isinstance(scope["filters"], dict):
        raise ValidationError("filters: explicit object required")
    try:
        encoded = canonical_json({key: value for key, value in scope["filters"].items() if key != "max_pages"})
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValidationError("filters: finite JSON object required") from exc
    if len(encoded.encode()) > 65536:
        raise ValidationError("filters: exceeds supported size")
    return scope["source_id"], encoded


def _known(value, name, reasons):
    if value is None or value == "":
        reasons.append(name + "_unknown")
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValidationError(f"{name}: explicit bounded text required")
    return value


def _age(now, instant):
    delta = now - instant
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1000000


def _cohort(raw):
    _shape(raw, _COHORT, "cohort")
    reasons = []
    scope = raw["scope"]
    if scope not in {"aggregate_reference", "physical_offer"}:
        raise ValidationError("cohort.scope: supported explicit scope required")
    model = _known(raw["hardware_model"], "hardware_model", reasons)
    currency = _known(raw["currency"], "currency", reasons)
    if currency is not None and not re.fullmatch("[A-Z]{3}", currency):
        raise ValidationError("currency: three-letter code required")
    unit = _known(raw["native_unit"], "native_unit", reasons)
    if unit is not None and unit not in {"gpu_hour", "node_hour"}:
        raise ValidationError("native_unit: physical compute rate unit required")
    if raw["price_side"] not in {"ask", "trade"}:
        raise ValidationError("price_side: ask or observed trade required; no invented market bid")
    target = {"scope": scope, "hardware_model": model, "currency": currency,
              "country_code": raw["country_code"], "configuration": {},
              "starts_at": raw["starts_at"], "ends_at": raw["ends_at"]}
    if scope == "aggregate_reference":
        if any(raw[key] is not None for key in ("hardware_memory_gib", "country_code", "starts_at", "ends_at", "gpu_count")) or raw["configuration"] != {}:
            raise ValidationError("aggregate cohort: physical terms must be explicitly not applicable")
        _shape(raw["aggregate_terms"], {"billing_type", "reservation_months"}, "aggregate_terms")
        _known(raw["aggregate_terms"]["billing_type"], "billing_type", reasons)
        months = raw["aggregate_terms"]["reservation_months"]
        if months is not None and (type(months) is not int or not 1 <= months <= 1200):
            raise ValidationError("reservation_months: explicit bounded integer or null required")
        _known(raw["observation_period"], "observation_period", reasons)
        # One GPU-hour defines the kernel's reference unit, not supply quantity
        # or a delivery contract. Aggregate output retains that explicit caveat.
        target.update(gpu_count="1", duration_hours="1", aggregate_terms=deepcopy(raw["aggregate_terms"]))
    else:
        if raw["aggregate_terms"] is not None or raw["observation_period"] is not None:
            raise ValidationError("physical cohort: aggregate terms/period must be explicitly not applicable")
        country = _known(raw["country_code"], "country_code", reasons)
        if country is not None and not re.fullmatch("[A-Z]{2}", country):
            raise ValidationError("country_code: two-letter code required")
        if raw["hardware_memory_gib"] is None:
            reasons.append("hardware_memory_gib_unknown")
        else:
            number(raw["hardware_memory_gib"], "hardware_memory_gib", positive=True)
        config = raw["configuration"]
        if not isinstance(config, dict):
            raise ValidationError("configuration: explicit object required")
        if set(config) != _CONFIG:
            reasons.append("physical_configuration_incomplete_or_unregistered")
        for key in _CONFIG & set(config):
            if config[key] is None:
                reasons.append("configuration_" + key + "_unknown")
            elif key in _CONFIG_NUMERIC:
                number(config[key], key, positive=True)
            else:
                _known(config[key], "configuration_" + key, reasons)
        target["configuration"] = deepcopy(config)
        if raw["gpu_count"] is None:
            reasons.append("gpu_count_unknown")
        else:
            count = number(raw["gpu_count"], "gpu_count", positive=True)
            if count != count.to_integral_value():
                raise ValidationError("gpu_count: whole physical allocation required")
            target["gpu_count"] = text_number(count)
        if raw["starts_at"] is None or raw["ends_at"] is None:
            reasons.append("delivery_interval_unknown")
        else:
            span = hours(raw["starts_at"], raw["ends_at"])
            delta = utc_instant(raw["ends_at"]) - utc_instant(raw["starts_at"])
            micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
            if micros % 9:
                raise ValidationError("delivery: exact decimal hours required")
            target["duration_hours"] = text_number(span)
    return target, reasons


def evaluate_market_reference(payload, *, store, policies, repository, collection_plan, clock=None):
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        return _evaluate(payload, store, policies, repository, collection_plan,
                         clock or (lambda: dt.datetime.now(dt.timezone.utc)))


def _evaluate(payload, store, policies, repository, collection_plan, clock):
    _shape(payload, {"source_scopes", "policy_revision", "cohort"}, "reference request")
    requested = payload["source_scopes"]
    if not isinstance(requested, list) or not 1 <= len(requested) <= 32:
        raise ValidationError("source_scopes: bounded nonempty explicit scope list required")
    keys = [_scope_key(scope) for scope in requested]
    if len(set(keys)) != len(keys):
        raise ValidationError("source_scopes: duplicate economic scopes rejected")
    configured = {_scope_key(scope) for scope in collection_plan}
    target, holds = _cohort(payload["cohort"])
    now = clock()
    if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise ValidationError("clock: aware UTC server instant required")
    as_of = now.isoformat().replace("+00:00", "Z")
    revision = payload["policy_revision"]
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
        raise ValidationError("policy_revision: exact saved policy revision required")
    saved = repository.get(revision)
    policy = None if saved is None else saved["document"]["policy"]
    if policy is None:
        holds.append("saved_policy_revision_not_found")
    else:
        head = repository.head(saved["policy_id"])
        if head is None or head["revision"] != revision:
            holds.append("saved_policy_revision_is_not_current_head")
        if utc_instant(policy["effective_at"]) > now:
            holds.append("saved_policy_not_yet_effective")
        if policy.get("expires_at") is not None and utc_instant(policy["expires_at"]) <= now:
            holds.append("saved_policy_expired")
        if policy.get("critical_feature_ids"):
            holds.append("critical_feature_model_unvalidated")
    rules = {} if policy is None else policy["parameters"]["benchmark"]["source_rules"]
    selected, scopes, rejected, catalog_count = [], [], [], 0
    for scope, key in zip(requested, keys):
        source = scope["source_id"]
        reasons = []
        if key not in configured:
            reasons.append("source_filter_scope_not_configured")
        admitted = policies.get(source)
        if admitted is None:
            reasons.append("source_not_admitted_by_server")
        else:
            for purpose in ("observe", "retain", "benchmark"):
                reasons.extend(admitted.blockers(purpose, now))
        role = ADAPTERS[source].role if source in ADAPTERS else "server_admitted_normalized_observations"
        if role in _NON_COMPUTE_ROLES:
            reasons.append("source_role_not_compute_price_evidence")
        if rules.get(source, {}).get("enabled") is not True:
            reasons.append("source_not_enabled_by_saved_policy")
        summary = {"source_id": source, "filters": deepcopy(scope["filters"]), "snapshot_id": None,
                   "source_role": role, "status": "rejected" if reasons else "requested", "reasons": sorted(set(reasons))}
        scopes.append(summary)
        if reasons:
            holds.append("requested_scope_not_admitted")
        else:
            selected.append(scope)
    scan = store.requested_collection_scan(selected) if selected else None
    by_key = {}
    for snapshot in (() if scan is None else scan.snapshots):
        packet, output, inputs, source = _collection_packet(snapshot)
        if packet["document"].get("kind") != "market_collection" or not isinstance(output.get("coverage", {}), dict):
            raise SnapshotStoreError("snapshot_integrity_failed")
        key = _scope_key({"source_id": source, "filters": inputs.get("filters", {})})
        if key in by_key:
            raise SnapshotStoreError("snapshot_integrity_failed")
        by_key[key] = (packet, output, inputs, source)
    full_row_count = sum(len(item[1].get("observations", [])) for item in by_key.values())
    over_limit = full_row_count > MAX_ROWS
    if over_limit:
        holds.append("selected_population_exceeds_study_limit")
    candidates, not_assessed = [], 0
    for summary, key in zip(scopes, keys):
        if summary["status"] == "rejected":
            continue
        retained = by_key.get(key)
        if retained is None:
            summary.update(status="rejected", reasons=["latest_retained_scope_not_found"])
            holds.append("requested_scope_snapshot_missing")
            continue
        packet, output, _, source = retained
        summary.update(snapshot_id=packet["snapshot_id"], created_at=packet["created_at"],
                       captured_at=output.get("raw_metadata", {}).get("captured_at"),
                       observation_count=len(output.get("observations", [])), catalog_record_count=len(output.get("catalog_records", [])),
                       upstream_coverage=deepcopy(output.get("coverage", {})))
        catalog_count += summary["catalog_record_count"]
        reasons = []
        try:
            age = _age(now, utc_instant(summary["captured_at"]))
            if not 0 <= age < policies[source].max_age_s:
                reasons.append("retained_capture_stale_or_future")
        except (ValueError, TypeError):
            reasons.append("retained_capture_unverified")
        coverage = output.get("coverage", {})
        if (output.get("display_truncated") is True or coverage.get("display_truncated") is True
                or coverage.get("observation_display_truncated") is True):
            reasons.append("retained_display_projection_not_complete")
        if over_limit:
            reasons.append("selected_population_exceeds_study_limit")
        if reasons:
            summary.update(status="rejected", reasons=reasons)
            holds.append("requested_scope_evidence_incomplete_or_stale")
            not_assessed += summary["observation_count"]
            continue
        summary.update(status="retained", reasons=[])
        for position, row in enumerate(output.get("observations", [])):
            origin = {"snapshot_id": packet["snapshot_id"], "source_id": source, "row_index": position,
                      "observation_id": row.get("id")}
            reasons = []
            try:
                observation = parse_market_observation(row)
            except ValidationError:
                rejected.append({**origin, "reasons": ["observation_domain_validation"]})
                continue
            normalized = observation.to_dict()
            reasons.extend(admission_blockers(observation, as_of, purpose="indicative"))
            age = _age(now, utc_instant(observation.observed_at))
            if not 0 <= age < policies[source].max_age_s:
                reasons.append("observation_stale_under_current_server_policy")
            if observation.price is None or observation.price.unit != payload["cohort"]["native_unit"]:
                reasons.append("native_unit_not_requested")
            if observation.price_side != payload["cohort"]["price_side"]:
                reasons.append("price_side_not_requested")
            if observation.extensions.get("price_eligible") is False or observation.extensions.get("gpu_hour_benchmark_eligible") is False or observation.extensions.get("normalization_blockers"):
                reasons.append("retained_normalization_not_price_eligible")
            if target["scope"] == "aggregate_reference":
                if observation.kind != "aggregate_advertised_index":
                    reasons.append("aggregate_role_required")
                if observation.extensions.get("period") != payload["cohort"]["observation_period"]:
                    reasons.append("measurement_period_not_requested")
            else:
                if observation.kind not in {"listing_ask", "firm_supplier_rfq", "confirmed_rental_trade"}:
                    reasons.append("physical_comparable_role_required")
                if observation.hardware is None or observation.hardware.memory_gib is None or (
                        payload["cohort"]["hardware_memory_gib"] is not None and Decimal(observation.hardware.memory_gib) != Decimal(payload["cohort"]["hardware_memory_gib"])):
                    reasons.append("hardware_memory_unknown_or_mismatched")
                config = observation.configuration.to_dict() if observation.configuration else {}
                for field, expected in target["configuration"].items():
                    actual = config.get(field)
                    if actual is None or expected is None:
                        reasons.append("configuration_" + field + "_unknown_or_mismatched")
                    elif field in _CONFIG_NUMERIC:
                        if Decimal(actual) != Decimal(expected):
                            reasons.append("configuration_" + field + "_unknown_or_mismatched")
                    elif actual != expected:
                        reasons.append("configuration_" + field + "_unknown_or_mismatched")
                if observation.starts_at is None or observation.ends_at is None or (
                        target.get("starts_at") is not None and utc_instant(observation.starts_at) != utc_instant(target["starts_at"])) or (
                        target.get("ends_at") is not None and utc_instant(observation.ends_at) != utc_instant(target["ends_at"])):
                    reasons.append("delivery_interval_not_exact_cohort")
                count = observation.hardware.accelerator_count if observation.hardware else None
                if count is None or Decimal(count) <= 0 or Decimal(count) != Decimal(count).to_integral_value():
                    reasons.append("physical_node_allocation_unknown")
                elif target.get("gpu_count") is not None and Decimal(target["gpu_count"]) % Decimal(count):
                    reasons.append("requested_quantity_not_whole_nodes")
            if holds:
                reasons.append("study_scope_or_policy_not_eligible")
            if reasons:
                rejected.append({**origin, "reasons": sorted(set(reasons))})
            else:
                candidates.append({"row": normalized, "origin": origin})
    if holds:
        rejected.extend({**entry["origin"], "reasons": ["study_scope_or_policy_not_eligible"]} for entry in candidates)
        candidates = []
    duplicates = {identity for identity, count in Counter(entry["row"]["id"] for entry in candidates).items() if count > 1}
    if duplicates:
        rejected.extend({**entry["origin"], "reasons": ["duplicate_retained_observation_id_quarantined"]} for entry in candidates if entry["row"]["id"] in duplicates)
        candidates = [entry for entry in candidates if entry["row"]["id"] not in duplicates]
    benchmark, eligible, boundary_reasons = None, [], []
    if policy is not None and not holds:
        bound = {"pricing_provenance": {"mode": "retained_market", "policy_revision": revision},
                 "market": {"policy": policy, "as_of": as_of,
                            "observations": [{**entry["row"], "snapshot_id": entry["origin"]["snapshot_id"]} for entry in candidates]}}
        _, _, boundary_reasons = PricingProvenance(store, policies, repository, clock=lambda: now).blockers(bound)
        kernel_target = {**target, "configuration": {}}
        # Configuration was compared exactly above, with decimal-semantic
        # equality for numeric fields. Keep original retained rows unchanged
        # for provenance rather than rewriting their financial encodings.
        benchmark = evaluate_benchmark([entry["row"] for entry in candidates], kernel_target, policy["parameters"]["benchmark"], as_of)
        benchmark["cohort"] = deepcopy(target)
        holds.extend(boundary_reasons)
        holds.extend(benchmark["hold_reasons"])
        entries = {entry["row"]["id"]: entry for entry in candidates}
        for exclusion in benchmark["exclusions"]:
            entry = entries.get(exclusion["observation_id"])
            if entry is not None:
                rejected.append({**entry["origin"], "reasons": exclusion["reasons"]})
        for contribution in benchmark["contributors"]:
            entry = entries[contribution["observation_id"]]
            eligible.append({**entry["origin"], **contribution, "kind": entry["row"]["kind"],
                             "native_price": deepcopy(entry["row"]["price"]),
                             "measurement_period": entry["row"]["extensions"].get("period"),
                             "source_statistic": entry["row"]["extensions"].get("price_statistic")})
    if not eligible:
        holds.append("no_qualified_retained_reference")
    prices = [Decimal(row["normalized_price"]) for row in eligible]
    price_range = None
    if not holds and prices:
        with localcontext() as context:
            context.prec = calculation_precision([text_number(value) for value in prices])
            price_range = {"minimum": text_number(min(prices)), "maximum": text_number(max(prices)),
                "range": text_number(max(prices) - min(prices)),
                "basis": "dispersion_across_same_side_comparables_not_bid_ask_spread"}
    result = {"schema_version": VERSION, "as_of": as_of, "status": "held" if holds else "indicative_reference",
        "reference": None if holds or benchmark is None else {"amount": benchmark["price"], "currency": target["currency"],
            "unit": "gpu_hour", "basis": "saved_policy_same_side_retained_sample",
            "price_side": payload["cohort"]["price_side"], "estimator": benchmark.get("estimator")},
        "cohort": deepcopy(payload["cohort"]), "policy_revision": revision, "benchmark": benchmark,
        "eligible": eligible, "rejected": rejected, "scopes": scopes, "hold_reasons": sorted(set(holds)),
        "comparable_price_range": price_range,
        "bid": None, "ask": None, "midpoint": None, "spread": None,
        "source_evidence_eligible": not holds, "physical_price_eligible": False, "inventory_verified": False,
        "firm_price_eligible": False, "execution_enabled": False,
        "coverage": {"requested_scopes": len(requested), "retained_scopes": sum(s["status"] == "retained" for s in scopes),
            "selected_observation_count": full_row_count, "eligible_observation_count": len(eligible),
            "rejected_observation_count": len(rejected), "excluded_catalog_record_count": catalog_count,
            "not_assessed_observation_count": not_assessed,
            "non_contributing_observation_count": max(0, full_row_count - len(eligible) - len(rejected) - not_assessed),
            "inputs_from_display_index": False, "display_row_limit_applied": False,
            "selected_retained_population_complete": not holds, "market_complete": False,
            "upstream_complete": all(s.get("upstream_coverage", {}).get("complete") is True for s in scopes),
            "history_verification": "exact_selected_latest_snapshots_only_not_entire_history"},
        "warnings": ["indicative_reference_is_not_a_market_bid_midpoint_or_physical_offer",
            "weights_dispersion_and_source_status_are_not_calibrated_confidence_or_credit_estimates",
            "publisher_aggregates_do_not_prove_country_premium_quantity_or_future_start_delivery",
            "selected_retained_sample_does_not_establish_complete_market_coverage"],
        "versions": {"reference": VERSION, "benchmark": "indicative-benchmark/1.0.0"}}
    if holds and benchmark is not None:
        result["benchmark"] = {**benchmark, "status": "held", "price": None, "hold_reasons": sorted(set(holds))}
    result["input_hash"] = digest(payload)
    result["decision_hash"] = digest(result)
    return result
