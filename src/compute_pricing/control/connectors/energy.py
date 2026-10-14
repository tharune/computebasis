"""Anonymous bounded day-ahead electricity context from Energi Data Service.

Published native energy rates stay outside compute MoneyRate observations. This
module retains selected normalized facts, never a raw vendor response row.
"""
import datetime as dt
from decimal import Decimal
import hashlib
import json
import re
import urllib.parse
from collections.abc import Mapping
from zoneinfo import ZoneInfo

from .transport import ConnectorError, ReadRequest, SOURCE_SPECS, UTC, parse_utc, utc_string

SOURCE_ID = "energinet_day_ahead"
LOCAL_ZONE = ZoneInfo("Europe/Copenhagen")
AREAS = frozenset({"DK1", "DK2", "DE", "NO2", "SE3", "SE4"})
COLUMNS = ("TimeUTC", "TimeDK", "PriceArea", "DayAheadPriceEUR", "DayAheadPriceDKK")
STEP = dt.timedelta(minutes=15)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ConnectorError("energy_scope_calendar_date_required")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ConnectorError("energy_scope_calendar_date_invalid") from None


def energinet_filters(filters):
    if not isinstance(filters, Mapping):
        raise ConnectorError("energy_explicit_scope_required")
    keys = set(filters)
    if keys not in ({"price_area", "limit", "start", "end"}, {"price_area", "limit", "rolling_days"}):
        raise ConnectorError("energy_exact_date_or_rolling_scope_required")
    if not isinstance(filters["price_area"], str) or filters["price_area"] not in AREAS:
        raise ConnectorError("energy_price_area_not_admitted")
    if type(filters["limit"]) is not int or not 1 <= filters["limit"] <= 1000:
        raise ConnectorError("energy_record_limit_invalid")
    if "rolling_days" in keys:
        if type(filters["rolling_days"]) is not int or not 1 <= filters["rolling_days"] <= 7:
            raise ConnectorError("energy_rolling_days_invalid")
    else:
        first, last = _date(filters["start"]), _date(filters["end"])
        if not 1 <= (last - first).days <= 7:
            raise ConnectorError("energy_scope_day_budget_invalid")
    return dict(filters)


def resolved_energinet_filters(filters, now):
    scope = energinet_filters(filters)
    if "rolling_days" not in scope:
        return scope
    if not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ConnectorError("energy_resolution_clock_timezone_required")
    try:
        last = now.astimezone(LOCAL_ZONE).date()
        first = last - dt.timedelta(days=scope.pop("rolling_days"))
    except (ValueError, OverflowError):
        raise ConnectorError("energy_scope_calendar_boundary") from None
    return {**scope, "start": first.isoformat(), "end": last.isoformat()}


def energinet_request(filters, *, now=None):
    scope = resolved_energinet_filters(filters, now or dt.datetime.now(UTC))
    query = {"start": scope["start"], "end": scope["end"], "limit": scope["limit"],
        "filter": json.dumps({"PriceArea": [scope["price_area"]]}, separators=(",", ":")),
        "columns": ",".join(COLUMNS), "sort": "TimeUTC ASC"}
    return ReadRequest(SOURCE_SPECS[SOURCE_ID],
        "https://api.energidataservice.dk/dataset/DayAheadPrices?" + urllib.parse.urlencode(query))


def _boundaries(scope):
    try:
        return tuple(dt.datetime.combine(_date(scope[key]), dt.time(), LOCAL_ZONE).astimezone(UTC)
            for key in ("start", "end"))
    except (ValueError, OverflowError):
        raise ConnectorError("energy_scope_calendar_boundary") from None


def _source_time(value):
    # TimeUTC and TimeDK are documented JSON wall-clock strings without a Z.
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}", value):
        raise ConnectorError("energy_documented_timestamp_format_required")
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        raise ConnectorError("energy_delivery_time_invalid") from None


def _signed_price(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ConnectorError("energy_native_number_required")
    result = Decimal(value)
    if not result.is_finite() or len(result.as_tuple().digits) > 128 or abs(result.as_tuple().exponent) > 128:
        raise ConnectorError("energy_native_number_precision_limit")
    encoded = format(result, "f")
    if len(encoded) > 128:
        raise ConnectorError("energy_native_number_precision_limit")
    return encoded


def parse_energinet(raw, policy, *, filters):
    from .adapters import ConnectorBatch, _permission, json_payload
    if raw.source_id != SOURCE_ID or policy.source_id != SOURCE_ID:
        raise ConnectorError("source_policy_mismatch")
    capture = parse_utc(raw.captured_at)
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, capture)
    requested = energinet_filters(filters)
    scope = resolved_energinet_filters(requested, capture)
    first, last = _boundaries(scope)
    packet = json_payload(raw)
    if not isinstance(packet, dict) or packet.get("dataset") != "DayAheadPrices" or not isinstance(packet.get("records"), list):
        raise ConnectorError("energy_dataset_contract_changed")
    if len(packet["records"]) > scope["limit"]:
        raise ConnectorError("energy_response_record_budget_exceeded")
    records, delivered = [], set()
    for item in packet["records"]:
        if (not isinstance(item, dict) or not set(COLUMNS) <= set(item) or len(item) > 32
                or any(not isinstance(key, str) or len(key) > 128 or any(ord(c) < 32 for c in key) for key in item)):
            raise ConnectorError("energy_native_record_shape_changed")
        delivery = _source_time(item["TimeUTC"]).replace(tzinfo=UTC)
        try:
            local = delivery.astimezone(LOCAL_ZONE).replace(tzinfo=None)
            end = delivery + STEP
        except (ValueError, OverflowError):
            raise ConnectorError("energy_delivery_calendar_boundary") from None
        if _source_time(item["TimeDK"]) != local:
            raise ConnectorError("energy_documented_timezones_disagree")
        if delivery.minute % 15 or delivery.second or delivery < first or end > last:
            raise ConnectorError("energy_delivery_outside_scope_or_interval")
        if item["PriceArea"] != scope["price_area"]:
            raise ConnectorError("energy_response_area_mismatch")
        if delivery in delivered:
            raise ConnectorError("energy_duplicate_delivery_interval")
        delivered.add(delivery)
        prices = {"EUR": _signed_price(item["DayAheadPriceEUR"]), "DKK": _signed_price(item["DayAheadPriceDKK"])}
        identity = "|".join((scope["price_area"], utc_string(delivery)))
        records.append({"id": "energy-" + hashlib.sha256(identity.encode()).hexdigest()[:24],
            "source_id": SOURCE_ID, "source_version": "energinet-day-ahead/1.0", "kind": "energy_market_reference",
            "market": "day_ahead", "price_area": scope["price_area"], "native_prices": prices,
            "native_unit": "MWh", "interval_minutes": 15, "starts_at": utc_string(delivery), "ends_at": utc_string(end),
            "observed_at": raw.captured_at, "ingested_at": raw.captured_at, "source_published_at": None,
            "freshness_basis": "retrieval_time_not_verified_original_publication_time",
            "expires_at": utc_string(capture + dt.timedelta(seconds=policy.max_age_s)), "status": "claimed",
            "price": None, "price_eligible": False, "gpu_hour_benchmark_eligible": False,
            "retail_tariff_qualified": False, "firm_price_eligible": False, "execution_enabled": False,
            "rights": _permission(policy), "attribution": "Source: Energinet (www.energidataservice.dk); normalized field names and explicit UTC intervals; CC-BY 4.0; no endorsement",
            "license_url": "https://www.energidataservice.dk/terms-and-conditions",
            "evidence": {"artifact_sha256": raw.sha256, "accessed_at": raw.captured_at, "locator": raw.endpoint_path},
            "unknown_field_names": sorted(set(item) - set(COLUMNS))})
    records.sort(key=lambda record: record["starts_at"])
    expected = set()
    cursor = first
    while cursor < last:
        expected.add(cursor)
        cursor += STEP
    missing = sorted(expected - delivered)
    warnings = ["wholesale_energy_context_does_not_establish_site_tariff_or_gpu_hour_price",
        "retrieval_freshness_does_not_verify_original_publication_time",
        "native_dkk_publisher_conversion_is_not_an_executable_fx_rate"]
    if missing:
        warnings.append("partial_scoped_delivery_coverage_no_interpolation_or_fallback")
    coverage = {"scope": scope, "requested_scope": requested, "request_count": 1,
        "rows_received": len(packet["records"]), "records_selected": len(records),
        "complete": not missing, "expected_intervals": len(expected), "missing_intervals": len(missing),
        "missing_interval_starts": [utc_string(value) for value in missing],
        "starts_at": utc_string(first), "ends_at": utc_string(last), "native_unit": "MWh",
        "all_market_inventory": False, "gpu_hour_benchmark_eligible": False,
        "completion_basis": "exact_utc_grid_for_requested_danish_calendar_days"}
    return ConnectorBatch(SOURCE_ID, {**raw.metadata(), "raw_body_retained": False}, (),
        tuple(records), tuple(warnings), coverage)


def collect_energinet(policy, transport, filters):
    from dataclasses import replace
    requested = energinet_filters(filters)
    scope = resolved_energinet_filters(requested, transport.clock())
    # Resolve once. Midnight during a network read cannot change the response scope.
    response = transport.fetch(energinet_request(scope), policy)
    batch = parse_energinet(response, policy, filters=scope)
    return replace(batch, coverage={**batch.coverage, "requested_scope": requested})
