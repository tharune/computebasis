"""Fresh bounded reader for publisher-derived GPUHunt instance references.

Only public, versioned AWS/Azure/GCP catalog archives are read. No GPUHunt
package, provider credential, online provider query or deployment is invoked.
"""
from collections import Counter
from collections.abc import Mapping
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
import re
import stat
import zipfile

from .transport import ConnectorError, ReadRequest, SOURCE_SPECS, parse_utc, utc_string

SOURCE_ID = "gpuhunt_catalog"
HOST = "dstack-gpu-pricing.s3.eu-west-1.amazonaws.com"
PROVIDERS = frozenset({"aws", "azure", "gcp"})
FIELDS = frozenset({"instance_name", "location", "price", "cpu", "memory", "gpu_count",
    "gpu_name", "gpu_memory", "spot", "disk_size", "gpu_vendor", "flags", "cpu_arch", "provider_data"})
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_CSV_BYTES = 16 * 1024 * 1024
MAX_ROWS = 100000


def _label(value, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ConnectorError("gpuhunt_bounded_label_required")
    return value


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}-[0-9]{1,12}", value):
        raise ConnectorError("gpuhunt_catalog_version_invalid")
    try:
        date = dt.datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        raise ConnectorError("gpuhunt_catalog_date_invalid") from None
    return date


def gpuhunt_filters(filters):
    if not isinstance(filters, Mapping):
        raise ConnectorError("gpuhunt_explicit_provider_scope_required")
    keys = set(filters)
    if not {"provider", "limit"} <= keys or keys - {"provider", "limit", "location", "location_prefix", "gpu_name", "spot", "version"}:
        raise ConnectorError("gpuhunt_collection_field_not_allowed")
    if not isinstance(filters["provider"], str) or filters["provider"] not in PROVIDERS:
        raise ConnectorError("gpuhunt_provider_not_admitted")
    if ("location" in keys) == ("location_prefix" in keys):
        raise ConnectorError("gpuhunt_exactly_one_location_scope_required")
    for key in ("location", "location_prefix", "gpu_name"):
        if key in keys:
            _label(filters[key], 128)
    if type(filters["limit"]) is not int or not 1 <= filters["limit"] <= 1000:
        raise ConnectorError("gpuhunt_result_limit_invalid")
    if "spot" in keys and type(filters["spot"]) is not bool:
        raise ConnectorError("gpuhunt_explicit_boolean_spot_required")
    if "version" in keys:
        _version(filters["version"])
    return dict(filters)


def gpuhunt_request(filters, *, version=None):
    options = gpuhunt_filters(filters)
    selected = version if version is not None else options.get("version")
    tail = "version" if selected is None else selected + "/catalog.zip"
    if selected is not None:
        _version(selected)
    return ReadRequest(SOURCE_SPECS[SOURCE_ID], "https://" + HOST + "/v3/" + options["provider"] + "/" + tail)


def _decimal(value, *, optional=False, whole=False, maximum=Decimal("1e24")):
    if value == "" and optional:
        return None
    if not isinstance(value, str) or len(value) > 128:
        raise ConnectorError("gpuhunt_numeric_contract_invalid")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ConnectorError("gpuhunt_numeric_contract_invalid") from None
    if (not result.is_finite() or result < 0 or result > maximum
            or len(result.as_tuple().digits) > 128 or abs(result.as_tuple().exponent) > 128
            or whole and result != result.to_integral_value()):
        raise ConnectorError("gpuhunt_numeric_contract_invalid")
    if len(format(result, "f")) > 128:
        raise ConnectorError("gpuhunt_numeric_contract_invalid")
    return result


def _metadata(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ConnectorError("gpuhunt_provider_metadata_budget")
    def unique(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ConnectorError("gpuhunt_duplicate_provider_metadata_key")
            result[key] = item
        return result
    try:
        result = json.loads(value or "{}", object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ConnectorError:
        raise
    except (ValueError, RecursionError):
        raise ConnectorError("gpuhunt_provider_metadata_invalid") from None
    if not isinstance(result, dict) or len(result) > 32 or any(not isinstance(k, str) or len(k) > 64 for k in result):
        raise ConnectorError("gpuhunt_provider_metadata_invalid")
    # Only this explicitly false known condition is compatible with a normal
    # reference. Other provider conditions must receive their own future model.
    unconditional = not result or set(result) == {"is_dws_calendar_mode"} and result["is_dws_calendar_mode"] is False
    condition_id = None if unconditional else hashlib.sha256(value.encode()).hexdigest()
    return unconditional, sorted(result), condition_id


def _bounded_lines(handle):
    while True:
        line = handle.readline(128 * 1024 + 1)
        if not line:
            return
        if len(line) > 128 * 1024:
            raise ConnectorError("gpuhunt_csv_line_budget")
        yield line


def _archive(body, provider, version):
    if len(body) > MAX_ARCHIVE_BYTES:
        raise ConnectorError("gpuhunt_archive_byte_budget")
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
        members = archive.infolist()
        names = [item.filename for item in members]
        expected = provider + ".csv"
        if (len(members) not in {1, 2} or len(set(names)) != len(names)
                or expected not in names or set(names) - {expected, "version"}):
            raise ConnectorError("gpuhunt_archive_entry_contract_invalid")
        for member in members:
            if (member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16)
                    or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or member.file_size > MAX_CSV_BYTES
                    or member.file_size > max(32768, member.compress_size * 200)):
                raise ConnectorError("gpuhunt_archive_expansion_or_compression_budget")
        if sum(item.file_size for item in members) > MAX_CSV_BYTES + 64:
            raise ConnectorError("gpuhunt_archive_expansion_or_compression_budget")
        if "version" in names:
            if archive.getinfo("version").file_size > 64:
                raise ConnectorError("gpuhunt_archive_version_mismatch")
            inside = archive.read("version").decode("ascii").strip()
            if inside != version:
                raise ConnectorError("gpuhunt_archive_version_mismatch")
        return archive, expected
    except ConnectorError:
        raise
    except (zipfile.BadZipFile, UnicodeError, ValueError, OSError):
        raise ConnectorError("gpuhunt_archive_invalid") from None


def parse_gpuhunt(raw, policy, *, filters, version):
    from .adapters import ConnectorBatch, _permission
    if raw.source_id != SOURCE_ID or policy.source_id != SOURCE_ID:
        raise ConnectorError("source_policy_mismatch")
    captured = parse_utc(raw.captured_at)
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, captured)
    options = gpuhunt_filters(filters)
    date = _version(version)
    if date > captured.date():
        raise ConnectorError("gpuhunt_future_catalog_date")
    if options.get("version", version) != version or raw.endpoint_path != "/v3/" + options["provider"] + "/" + version + "/catalog.zip":
        raise ConnectorError("gpuhunt_pinned_archive_scope_mismatch")
    catalog_day = dt.datetime.combine(date, dt.time(), dt.timezone.utc)
    archive, filename = _archive(raw.body, options["provider"], version)
    records, identities, counts = [], {}, Counter()
    try:
        with archive, archive.open(filename) as member, io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as text:
            reader = csv.DictReader(_bounded_lines(text), strict=True)
            header = reader.fieldnames
            if (not header or len(header) > 24 or len(set(header)) != len(header) or not FIELDS <= set(header)
                    or any(not key or len(key) > 128 or any(ord(c) < 32 for c in key) for key in header)):
                raise ConnectorError("gpuhunt_csv_schema_changed")
            for row in reader:
                counts["rows_scanned"] += 1
                if counts["rows_scanned"] > MAX_ROWS:
                    raise ConnectorError("gpuhunt_csv_row_budget")
                if None in row or any(value is None or len(value) > 8192 for value in row.values()):
                    raise ConnectorError("gpuhunt_csv_row_shape_invalid")
                location = _label(row["location"])
                if ("location" in options and location != options["location"]
                        or "location_prefix" in options and not location.startswith(options["location_prefix"])):
                    counts["outside_location"] += 1
                    continue
                count = _decimal(row["gpu_count"], whole=True, maximum=Decimal(8192))
                vendor, model = row["gpu_vendor"], row["gpu_name"]
                if not count or vendor not in {"nvidia", "amd"} or not model or model.lower().startswith("tpu"):
                    counts["non_gpu_or_unknown_gpu_vendor"] += 1
                    continue
                if "gpu_name" in options and model != options["gpu_name"]:
                    counts["outside_gpu_name"] += 1
                    continue
                if row["spot"].lower() not in {"true", "false"}:
                    raise ConnectorError("gpuhunt_spot_contract_invalid")
                spot = row["spot"].lower() == "true"
                if "spot" in options and spot is not options["spot"]:
                    counts["outside_spot_scope"] += 1
                    continue
                instance, model = _label(row["instance_name"]), _label(model)
                architecture = _label(row["cpu_arch"], 32) if row["cpu_arch"] else None
                price = _decimal(row["price"], optional=True)
                cpu = _decimal(row["cpu"], whole=True, maximum=Decimal(65536))
                memory = _decimal(row["memory"], maximum=Decimal("1e9"))
                gpu_memory = _decimal(row["gpu_memory"], optional=True, maximum=Decimal("1e6"))
                disk = _decimal(row["disk_size"], optional=True, maximum=Decimal("1e12"))
                flags = row["flags"].split()
                if len(flags) > 32 or any(len(flag) > 64 for flag in flags):
                    raise ConnectorError("gpuhunt_conditional_flag_budget")
                ordinary, metadata_keys, condition_id = _metadata(row["provider_data"])
                holds = []
                if price is None:
                    holds.append("publisher_price_missing")
                if flags or not ordinary:
                    holds.append("conditional_billing_or_provider_terms_unmodeled")
                # An attached GPU configuration may reuse the same CPU VM name
                # and zone. Its complete published hardware and condition scope
                # are separate references, not contradictory prices for one VM.
                identity = (instance, location, spot, vendor, model, count, gpu_memory,
                    cpu, memory, disk, architecture, tuple(sorted(flags)), condition_id)
                signature = price
                if identity in identities:
                    if identities[identity] != signature:
                        raise ConnectorError("gpuhunt_conflicting_instance_reference")
                    counts["duplicate_rows"] += 1
                    continue
                identities[identity] = signature
                counts["matching_gpu_rows"] += 1
                if holds:
                    counts["held_matching_rows"] += 1
                if len(records) >= options["limit"]:
                    continue
                published_price = None if price is None else {"amount": format(price, "f"), "currency": "USD", "unit": "instance_hour"}
                normalized = None
                if not holds:
                    with localcontext() as context:
                        context.prec = 160
                        normalized = {"amount": format(price / count, "f"), "currency": "USD",
                            "unit": "per_published_accelerator_hour", "basis": "whole_instance_price_divided_by_publisher_count",
                            "division_precision_digits": 160, "benchmark_eligible": False}
                records.append({"id": "gpuhunt-" + hashlib.sha256("|".join(map(str, identity)).encode()).hexdigest()[:24],
                    "source_id": SOURCE_ID, "source_version": "gpuhunt-published/v3", "kind": "gpu_vm_reference",
                    "provider": options["provider"], "instance_name": instance, "provider_location": location,
                    "location_is_verified_physical_site": False, "gpu_name": model, "gpu_count": format(count, "f"),
                    "gpu_vendor": vendor, "gpu_memory_gb": None if gpu_memory is None else format(gpu_memory, "f"),
                    "cpu_count": format(cpu, "f"), "host_memory_gb": format(memory, "f"),
                    "memory_unit_basis": "GB_as_documented_by_publisher_not_reinterpreted_as_GiB",
                    "disk_size_gb": None if disk is None else format(disk, "f"), "cpu_arch": architecture,
                    "spot_claim": spot, "billing_mode": "conditional_or_unknown" if flags or not ordinary else "spot_reference" if spot else "publisher_on_demand_reference",
                    "native_price": None if holds else published_price, "reported_price": published_price,
                    "normalized_price_diagnostic": normalized, "record_hold_reasons": holds,
                    "conditional_flags": flags, "provider_metadata_field_names": metadata_keys,
                    "publisher_catalog_version": version, "publisher_catalog_date": date.isoformat(),
                    "source_published_at": None, "vendor_quote_observed_at": None, "vendor_price_age_known": False,
                    "catalog_observed_at": raw.captured_at, "raw_capture_at": raw.captured_at,
                    "observed_at": raw.captured_at, "ingested_at": raw.captured_at,
                    "expires_at": utc_string(catalog_day + dt.timedelta(seconds=policy.max_age_s)),
                    "freshness_basis": "publisher_catalog_date_at_utc_midnight_conservative_not_vendor_quote_time",
                    "status": "held" if holds else "claimed", "comparison_eligible": not holds,
                    "price_eligible": False, "gpu_hour_benchmark_eligible": False, "physical_inventory_verified": False,
                    "whole_device_allocation_verified": False, "firm_price_eligible": False, "execution_enabled": False,
                    "quantity_available": None, "price_side": "publisher_reference_not_midpoint",
                    "rights": _permission(policy), "attribution": policy.attribution,
                    "evidence": {"artifact_sha256": raw.sha256, "accessed_at": raw.captured_at, "locator": raw.endpoint_path},
                    "unknown_field_names": sorted(set(header) - FIELDS), "raw_provider_payload_retained": False})
    except ConnectorError:
        raise
    except (zipfile.BadZipFile, UnicodeError, csv.Error, ValueError, OSError, RuntimeError):
        raise ConnectorError("gpuhunt_archive_or_csv_invalid") from None
    partial = counts["matching_gpu_rows"] > len(records)
    coverage = {"scope": options, "provider_catalog_version": version,
        "publisher_catalog_date": date.isoformat(), "counts": dict(counts), "records_selected": len(records),
        "selection_truncated": partial, "complete": not partial and counts["held_matching_rows"] == 0,
        "completion_basis": "fully_scanned_single_provider_catalog_with_explicit_local_filter",
        "all_market_inventory": False, "direct_vendor_quote": False, "vendor_price_age_known": False}
    return ConnectorBatch(SOURCE_ID, {**raw.metadata(), "raw_body_retained": False}, (), tuple(records),
        ("publisher_derived_instance_references_not_direct_vendor_quotes_or_available_capacity",
         "publisher_catalog_date_does_not_verify_vendor_quote_age",
         "gpu_hour_division_is_diagnostic_not_verified_whole_device_comparability",
         "local_normalized_comparison_only_no_raw_catalog_redistribution_or_execution"), coverage)


def collect_gpuhunt(policy, transport, filters):
    from dataclasses import replace
    options = gpuhunt_filters(filters)
    version, pages = options.get("version"), []
    if version is None:
        manifest = transport.fetch(gpuhunt_request(options), policy)
        if len(manifest.body) > 64:
            raise ConnectorError("gpuhunt_version_manifest_budget")
        try:
            version = manifest.body.decode("ascii").strip()
        except UnicodeError:
            raise ConnectorError("gpuhunt_catalog_version_invalid") from None
        _version(version)
        pages.append(manifest.metadata())
        transport.wait_for_source(SOURCE_ID, max_wait_s=transport.max_wait_s)
    raw = transport.fetch(gpuhunt_request(options, version=version), policy)
    batch = parse_gpuhunt(raw, policy, filters=options, version=version)
    return replace(batch, raw_metadata={**batch.raw_metadata, "requests": pages + [raw.metadata()], "raw_body_retained": False},
        coverage={**batch.coverage, "request_count": len(pages) + 1})
