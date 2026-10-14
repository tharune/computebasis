"""Bounded anonymous GB grid-carbon context, separate from monetary pricing.

The publisher's forecast and estimated actual intensity are distinct facts.
No site-level emissions, marginal emissions, tariff or compute price is inferred.
"""
from collections.abc import Mapping
from dataclasses import replace
import datetime as dt
from decimal import Decimal
import hashlib
import re

from .transport import ConnectorError, ReadRequest, SOURCE_SPECS, UTC, parse_utc, utc_string

SOURCE_ID = "gb_carbon_intensity"
STEP = dt.timedelta(minutes=30)
MAX_HOURS = 168
MAX_RECORDS = 336
MAX_BODY_BYTES = 512 * 1024
INDEX_LABELS = frozenset({"very low", "low", "moderate", "high", "very high"})
DOCUMENTATION = "https://carbon-intensity.github.io/api-definitions/"
TERMS = "https://github.com/carbon-intensity/terms"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = ("Source: Carbon Intensity API, National Energy System Operator "
    "(https://carbonintensity.org.uk), CC BY 4.0; normalized field names and UTC intervals; "
    "no endorsement")


def _half_hour(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}Z", value):
        raise ConnectorError("carbon_half_hour_utc_timestamp_required")
    try:
        instant = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ConnectorError("carbon_timestamp_invalid") from None
    if instant.minute not in (0, 30):
        raise ConnectorError("carbon_half_hour_alignment_required")
    return instant


def _path_time(instant):
    return instant.isoformat(timespec="minutes").replace("+00:00", "Z")


def carbon_filters(filters):
    if not isinstance(filters, Mapping):
        raise ConnectorError("carbon_explicit_scope_required")
    if set(filters) not in ({"start", "end", "limit"}, {"rolling_hours", "limit"}):
        raise ConnectorError("carbon_exact_date_or_rolling_scope_required")
    if type(filters["limit"]) is not int or not 1 <= filters["limit"] <= MAX_RECORDS:
        raise ConnectorError("carbon_record_limit_invalid")
    if "rolling_hours" in filters:
        if type(filters["rolling_hours"]) is not int or not 1 <= filters["rolling_hours"] <= MAX_HOURS:
            raise ConnectorError("carbon_rolling_hours_invalid")
    else:
        first, last = _half_hour(filters["start"]), _half_hour(filters["end"])
        if not STEP <= last - first <= dt.timedelta(hours=MAX_HOURS):
            raise ConnectorError("carbon_interval_scope_budget_invalid")
    return dict(filters)


def resolved_carbon_filters(filters, now):
    scope = carbon_filters(filters)
    if "rolling_hours" not in scope:
        return scope
    if not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ConnectorError("carbon_resolution_clock_timezone_required")
    try:
        current = now.astimezone(UTC)
        last = current.replace(minute=(current.minute // 30) * 30, second=0, microsecond=0)
        first = last - dt.timedelta(hours=scope.pop("rolling_hours"))
    except (ValueError, OverflowError):
        raise ConnectorError("carbon_scope_calendar_boundary") from None
    return {**scope, "start": _path_time(first), "end": _path_time(last)}


def carbon_request(filters, *, now=None):
    scope = resolved_carbon_filters(filters, now or dt.datetime.now(UTC))
    return ReadRequest(SOURCE_SPECS[SOURCE_ID], "https://api.carbonintensity.org.uk/intensity/"
        + scope["start"] + "/" + scope["end"])


def _field_names(value):
    if (not isinstance(value, dict) or len(value) > 24
            or any(not isinstance(key, str) or len(key) > 80
                or any(ord(char) < 32 for char in key) for key in value)):
        raise ConnectorError("carbon_record_shape_changed")
    return set(value)


def _intensity(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ConnectorError("carbon_native_number_required")
    number = Decimal(value)
    if (not number.is_finite() or number < 0 or number > 1000000
            or len(number.as_tuple().digits) > 128 or abs(number.as_tuple().exponent) > 128):
        raise ConnectorError("carbon_native_number_budget_invalid")
    result = format(number, "f")
    if len(result) > 128:
        raise ConnectorError("carbon_native_number_budget_invalid")
    return result


def parse_carbon(raw, policy, *, filters):
    from .adapters import ConnectorBatch, _permission, json_payload
    if raw.source_id != SOURCE_ID or policy.source_id != SOURCE_ID:
        raise ConnectorError("source_policy_mismatch")
    capture = parse_utc(raw.captured_at)
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, capture)
    requested = carbon_filters(filters)
    scope = resolved_carbon_filters(requested, capture)
    first, last = _half_hour(scope["start"]), _half_hour(scope["end"])
    expected_path = "/intensity/" + scope["start"] + "/" + scope["end"]
    if raw.endpoint_path != expected_path or raw.status != 200:
        raise ConnectorError("carbon_response_request_scope_mismatch")
    expected_count = int((last - first) / STEP)
    if len(raw.body) > MAX_BODY_BYTES:
        raise ConnectorError("carbon_response_byte_budget_exceeded")
    packet = json_payload(raw)
    packet_keys = _field_names(packet)
    if "error" in packet_keys or not isinstance(packet.get("data"), list):
        raise ConnectorError("carbon_data_contract_changed")
    # A publisher may return a touching endpoint interval. At most one at each
    # boundary is inspected and omitted; no outside interval enters the catalog.
    if len(packet["data"]) > expected_count + 2:
        raise ConnectorError("carbon_response_record_budget_exceeded")
    try:
        expiry = utc_string(capture + dt.timedelta(seconds=policy.max_age_s))
    except (ValueError, OverflowError):
        raise ConnectorError("carbon_capture_calendar_boundary") from None
    records, seen, boundary_rows = [], set(), 0
    for item in packet["data"]:
        keys = _field_names(item)
        if not {"from", "to", "intensity"} <= keys:
            raise ConnectorError("carbon_interval_fields_required")
        start, end = _half_hour(item["from"]), _half_hour(item["to"])
        if end - start != STEP:
            raise ConnectorError("carbon_delivery_interval_invalid")
        if start in seen:
            raise ConnectorError("carbon_duplicate_delivery_interval")
        seen.add(start)
        intensity = item["intensity"]
        intensity_keys = _field_names(intensity)
        forecast, actual = _intensity(intensity.get("forecast")), _intensity(intensity.get("actual"))
        label = intensity.get("index")
        if label is not None and not isinstance(label, str):
            raise ConnectorError("carbon_index_type_invalid")
        label_known = isinstance(label, str) and label in INDEX_LABELS
        if end == first or start == last:
            boundary_rows += 1
            continue
        if start < first or end > last:
            raise ConnectorError("carbon_interval_outside_scope")
        identity = "GB|national|" + utc_string(start)
        records.append({"id": "grid-carbon-" + hashlib.sha256(identity.encode()).hexdigest()[:24],
            "source_id": SOURCE_ID, "source_version": "gb-grid-carbon/1.0", "kind": "grid_carbon_reference",
            "geography": "GB", "geography_scope": "national_great_britain_not_all_uk",
            "native_intensity": {"forecast": forecast, "actual": actual}, "native_unit": "gCO2/kWh",
            "actual_basis": "publisher_estimated_from_metered_generation", "forecast_basis": "publisher_model_forecast",
            "carbon_index": label if label_known else None,
            "index_status": "published" if label_known else "missing" if label is None else "unrecognized",
            "missing_intensity_fields": sorted({"forecast", "actual"} - intensity_keys),
            "interval_minutes": 30, "starts_at": utc_string(start), "ends_at": utc_string(end),
            "interval_state": "completed" if end <= capture else "future" if start >= capture else "current",
            "observed_at": raw.captured_at, "ingested_at": raw.captured_at,
            "source_published_at": None, "publisher_revision_known": False,
            "freshness_basis": "retrieval_time_not_verified_original_publication_or_revision_time",
            "expires_at": expiry, "status": "held" if forecast is None and actual is None else "claimed",
            "price": None, "price_eligible": False, "gpu_hour_benchmark_eligible": False,
            "retail_tariff_qualified": False, "site_emissions_qualified": False,
            "marginal_emissions_qualified": False, "carbon_credit_qualified": False,
            "firm_price_eligible": False, "execution_enabled": False,
            "rights": _permission(policy), "attribution": ATTRIBUTION, "license_url": LICENSE,
            "terms_url": TERMS, "docs_url": DOCUMENTATION,
            "evidence": {"artifact_sha256": raw.sha256, "accessed_at": raw.captured_at, "locator": raw.endpoint_path},
            "unknown_field_names": sorted(keys - {"from", "to", "intensity"}),
            "unknown_intensity_field_names": sorted(intensity_keys - {"forecast", "actual", "index"})})
    records.sort(key=lambda record: record["starts_at"])
    matched = len(records)
    records = records[:scope["limit"]]
    included = {parse_utc(record["starts_at"]) for record in records}
    expected = {first + index * STEP for index in range(expected_count)}
    missing = sorted(expected - included)
    unknown_forecast = sum(record["native_intensity"]["forecast"] is None for record in records)
    unknown_actual = sum(record["native_intensity"]["actual"] is None for record in records)
    warnings = ["national_grid_carbon_context_does_not_establish_site_or_marginal_emissions",
        "forecast_and_estimated_actual_are_separate_no_substitution",
        "carbon_intensity_is_not_a_tariff_compute_price_or_carbon_credit_price",
        "retrieval_freshness_does_not_verify_original_publication_or_revision_time"]
    if missing:
        warnings.append("partial_scoped_interval_coverage_no_interpolation_or_fallback")
    if unknown_forecast or unknown_actual:
        warnings.append("missing_intensity_values_preserved_no_forecast_actual_fill")
    if matched > scope["limit"]:
        warnings.append("local_record_selection_truncated")
    coverage = {"scope": scope, "requested_scope": requested, "request_count": 1,
        "geography": "GB", "native_unit": "gCO2/kWh", "rows_received": len(packet["data"]),
        "boundary_rows_omitted": boundary_rows, "records_matched": matched, "records_selected": len(records),
        "selection_truncated": matched > scope["limit"], "complete": not missing,
        "expected_intervals": expected_count, "missing_intervals": len(missing),
        "missing_interval_starts": [utc_string(value) for value in missing],
        "forecast_missing_values": unknown_forecast, "actual_missing_values": unknown_actual,
        "forecast_complete": not missing and not unknown_forecast,
        "actual_complete": not missing and not unknown_actual,
        "starts_at": utc_string(first), "ends_at": utc_string(last),
        "completion_basis": "fully_contained_half_hour_intervals_for_exact_utc_scope",
        "gpu_hour_benchmark_eligible": False, "site_emissions_qualified": False,
        "all_market_inventory": False, "unknown_top_level_field_names": sorted(packet_keys - {"data"})}
    return ConnectorBatch(SOURCE_ID, {**raw.metadata(), "raw_body_retained": False}, (),
        tuple(records), tuple(warnings), coverage)


def collect_carbon(policy, transport, filters):
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, transport.clock())
    requested = carbon_filters(filters)
    scope = resolved_carbon_filters(requested, transport.clock())
    response = transport.fetch(carbon_request(scope), policy)
    batch = parse_carbon(response, policy, filters=scope)
    return replace(batch, coverage={**batch.coverage, "requested_scope": requested})
