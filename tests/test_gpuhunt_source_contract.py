"""Invented publisher archives verify scope, numbers, ownership and ZIP bounds."""
from copy import deepcopy
import csv
import datetime as dt
import io
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
import zipfile

from compute_pricing.control.connectors import ReadOnlyTransport, collect_source, source_status
from compute_pricing.control.connectors.adapters import ADAPTERS
from compute_pricing.control.connectors.gpuhunt import FIELDS, gpuhunt_request, parse_gpuhunt
from compute_pricing.control.connectors.transport import ConnectorError, RawResponse, ReadRequest, SOURCE_SPECS, SourcePolicy, load_policies

VERSION = "20660703-17"
NOW = dt.datetime(2066, 7, 3, 11, tzinfo=dt.timezone.utc)
SCOPE = {"provider": "aws", "location": "invented-region-a", "limit": 10}


def policy(**changes):
    inputs = {"source_id": "gpuhunt_catalog", "enabled": True, "rights_status": "allowed",
        "rights_evidence": "invented local catalog-use review", "verified_by": "invented-review",
        "permissions": {"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        "max_age_s": 172800, "min_interval_s": 0, "attribution": "GPUHunt; invented payload"}
    return SourcePolicy(**{**inputs, **changes})


def offer(**changes):
    values = {"instance_name": "invented.gpu-two", "location": "invented-region-a", "price": "6.30",
        "cpu": "16", "memory": "64", "gpu_count": "2", "gpu_name": "NovelGPU-Alpha",
        "gpu_memory": "48", "spot": "False", "disk_size": "", "gpu_vendor": "nvidia",
        "flags": "", "cpu_arch": "x86", "provider_data": "{}"}
    return {**values, **changes}


def archive(rows=None, *, provider="aws", version=VERSION, extra=None, compression=zipfile.ZIP_DEFLATED):
    csv_body = io.StringIO(newline="")
    fields = list(sorted(FIELDS))
    writer = csv.DictWriter(csv_body, fieldnames=fields)
    writer.writeheader(); writer.writerows(rows if rows is not None else [offer()])
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w", compression=compression) as zipped:
        zipped.writestr(provider + ".csv", csv_body.getvalue())
        zipped.writestr("version", version + "\n")
        if extra:
            zipped.writestr(extra, "invented unretained archive member")
    return body.getvalue()


def raw(body=None, *, version=VERSION, provider="aws", capture="2066-07-03T11:00:00Z"):
    return RawResponse("gpuhunt_catalog", capture, "/v3/" + provider + "/" + version + "/catalog.zip", 200, {},
        archive(provider=provider, version=version) if body is None else body)


class GPUHuntCatalogTests(unittest.TestCase):
    def test_fixed_anonymous_provider_manifest_and_pinned_archive_contract(self):
        first = gpuhunt_request(SCOPE)
        self.assertIsNone(first.spec.secret_env)
        self.assertEqual(first.validate().path, "/v3/aws/version")
        self.assertEqual(gpuhunt_request(SCOPE, version=VERSION).validate().path, "/v3/aws/" + VERSION + "/catalog.zip")
        for filters in (None, {}, {**SCOPE, "provider": "vastai"}, {**SCOPE, "limit": True}, {**SCOPE, "limit": 1001},
                {**SCOPE, "location_prefix": "invented"}, {"provider": "aws", "limit": 5}, {**SCOPE, "spot": "false"},
                {**SCOPE, "version": "../../other"}, {**SCOPE, "region": "invented"}):
            with self.subTest(filters=filters), self.assertRaises(ConnectorError): gpuhunt_request(filters)
        with self.assertRaises(ConnectorError):
            ReadRequest(SOURCE_SPECS["gpuhunt_catalog"], "https://dstack-gpu-pricing.s3.eu-west-1.amazonaws.com/v3/aws/latest/catalog.zip").validate()

    def test_native_instance_price_and_per_count_diagnostic_are_distinct(self):
        batch = parse_gpuhunt(raw(), policy(), filters=SCOPE, version=VERSION)
        self.assertEqual(batch.observations, ())
        row = batch.catalog_records[0]
        self.assertEqual(row["native_price"], {"amount": "6.30", "currency": "USD", "unit": "instance_hour"})
        self.assertEqual(row["normalized_price_diagnostic"]["amount"], "3.15")
        self.assertEqual(row["gpu_count"], "2")
        self.assertEqual(row["gpu_memory_gb"], "48")
        self.assertIsNone(row["disk_size_gb"])
        self.assertIsNone(row["quantity_available"])
        self.assertFalse(row["whole_device_allocation_verified"])
        self.assertFalse(row["gpu_hour_benchmark_eligible"])
        self.assertFalse(row["firm_price_eligible"])
        self.assertFalse(row["execution_enabled"])
        self.assertEqual(row["price_side"], "publisher_reference_not_midpoint")
        self.assertFalse(batch.raw_metadata["raw_body_retained"])

    def test_exact_published_float_string_precision_and_zero_are_preserved(self):
        for price in ("0", "0.123456789012345678901234567890123456789"):
            row = parse_gpuhunt(raw(archive([offer(price=price, gpu_count="1")])), policy(), filters=SCOPE, version=VERSION).catalog_records[0]
            self.assertEqual(row["native_price"]["amount"], price)
        with self.assertRaises(ConnectorError):
            parse_gpuhunt(raw(archive([offer(price="NaN")])), policy(), filters=SCOPE, version=VERSION)

    def test_cpu_tpu_unknown_vendor_and_other_scope_are_not_gpu_supply(self):
        rows = [offer(), offer(instance_name="invented.cpu", gpu_count="0", gpu_vendor="", gpu_name=""),
            offer(instance_name="invented.tpu", gpu_vendor="google", gpu_name="tpu-invented"),
            offer(instance_name="invented.unknown", gpu_vendor=""), offer(location="another-region")]
        batch = parse_gpuhunt(raw(archive(rows)), policy(), filters=SCOPE, version=VERSION)
        self.assertEqual(len(batch.catalog_records), 1)
        self.assertEqual(batch.coverage["counts"]["non_gpu_or_unknown_gpu_vendor"], 3)
        self.assertEqual(batch.coverage["counts"]["outside_location"], 1)

    def test_spot_scope_and_prefix_remain_explicit(self):
        rows = [offer(location="invented-region-a-zone1"), offer(location="invented-region-a-zone2", spot="True")]
        filters = {"provider": "aws", "location_prefix": "invented-region-a-", "spot": True, "limit": 10}
        row = parse_gpuhunt(raw(archive(rows)), policy(), filters=filters, version=VERSION).catalog_records[0]
        self.assertTrue(row["spot_claim"])
        self.assertEqual(row["billing_mode"], "spot_reference")
        self.assertFalse(row["location_is_verified_physical_site"])

    def test_unknown_flags_or_gcp_calendar_mode_never_become_ondemand_prices(self):
        for changes in ({"flags": "future-billing"}, {"provider_data": '{"is_dws_calendar_mode":true}'},
                {"provider_data": '{"is_dws_calendar_mode":0}'}, {"provider_data": '{"unknown_condition":"invented unretained value"}'}):
            batch = parse_gpuhunt(raw(archive([offer(**changes)])), policy(), filters=SCOPE, version=VERSION)
            row = batch.catalog_records[0]
            self.assertEqual(row["billing_mode"], "conditional_or_unknown")
            self.assertIsNone(row["native_price"])
            self.assertIsNone(row["normalized_price_diagnostic"])
            self.assertFalse(row["comparison_eligible"])
            self.assertEqual(row["reported_price"]["amount"], "6.30")
            self.assertNotIn("invented unretained value", json.dumps(batch.to_dict()))
        row = parse_gpuhunt(raw(archive([offer(provider_data='{"is_dws_calendar_mode":false}')])), policy(), filters=SCOPE, version=VERSION).catalog_records[0]
        self.assertTrue(row["comparison_eligible"])

    def test_missing_price_is_held_technical_fact_not_sample_fallback(self):
        row = parse_gpuhunt(raw(archive([offer(price="")])), policy(), filters=SCOPE, version=VERSION).catalog_records[0]
        self.assertIsNone(row["native_price"])
        self.assertIn("publisher_price_missing", row["record_hold_reasons"])
        self.assertFalse(row["comparison_eligible"])

    def test_gcp_attached_gpu_and_calendar_variants_do_not_false_conflict(self):
        rows = [offer(gpu_name="NovelGPU-Alpha", gpu_count="1"),
            offer(gpu_name="NovelGPU-Beta", gpu_count="2", gpu_memory="96", price="9.80"),
            offer(gpu_name="NovelGPU-Alpha", gpu_count="4", price="15.70"),
            offer(gpu_name="NovelGPU-Alpha", gpu_count="1", provider_data='{"is_dws_calendar_mode":true}', price="5.40")]
        filters = {**SCOPE, "provider": "gcp"}
        batch = parse_gpuhunt(raw(archive(rows, provider="gcp"), provider="gcp"), policy(), filters=filters, version=VERSION)
        self.assertEqual(len(batch.catalog_records), 4)
        self.assertEqual(len({row["id"] for row in batch.catalog_records}), 4)
        self.assertEqual(batch.coverage["counts"]["held_matching_rows"], 1)
        self.assertIsNone(batch.catalog_records[-1]["native_price"])
        self.assertEqual(batch.catalog_records[-1]["billing_mode"], "conditional_or_unknown")
        self.assertEqual(batch.catalog_records[0]["native_price"]["amount"], "6.30")
        self.assertTrue(all(row["catalog_observed_at"] == "2066-07-03T11:00:00Z" for row in batch.catalog_records))

    def test_catalog_age_stays_old_when_downloaded_again(self):
        batch = parse_gpuhunt(raw(capture="2066-07-10T11:00:00Z"), policy(), filters=SCOPE, version=VERSION)
        row = batch.catalog_records[0]
        self.assertEqual(row["publisher_catalog_date"], "2066-07-03")
        self.assertEqual(row["expires_at"], "2066-07-05T00:00:00Z")
        self.assertIsNone(row["vendor_quote_observed_at"])
        self.assertFalse(row["vendor_price_age_known"])
        self.assertEqual(row["raw_capture_at"], "2066-07-10T11:00:00Z")
        future = "20660704-18"
        with self.assertRaises(ConnectorError): parse_gpuhunt(raw(version=future), policy(), filters=SCOPE, version=future)

    def test_archive_entry_name_count_version_compression_and_size_guards(self):
        for body in (archive(extra="../unexpected.csv"), archive(extra="other.csv"), archive(version="20660702-16"),
                archive(compression=zipfile.ZIP_LZMA), b"not an archive"):
            with self.subTest(bytes=len(body)), self.assertRaises(ConnectorError): parse_gpuhunt(raw(body), policy(), filters=SCOPE, version=VERSION)
        with patch("compute_pricing.control.connectors.gpuhunt.MAX_ARCHIVE_BYTES", 10), self.assertRaises(ConnectorError):
            parse_gpuhunt(raw(), policy(), filters=SCOPE, version=VERSION)
        with patch("compute_pricing.control.connectors.gpuhunt.MAX_CSV_BYTES", 10), self.assertRaises(ConnectorError):
            parse_gpuhunt(raw(), policy(), filters=SCOPE, version=VERSION)

    def test_conflicting_bundle_and_partial_selection_cannot_fake_independence(self):
        with self.assertRaises(ConnectorError):
            parse_gpuhunt(raw(archive([offer(), offer(price="6.31")])), policy(), filters=SCOPE, version=VERSION)
        filters = {**SCOPE, "limit": 1}
        rows = [offer(), deepcopy(offer()), offer(instance_name="invented.gpu-four", gpu_count="4", price="12.60")]
        batch = parse_gpuhunt(raw(archive(rows)), policy(), filters=filters, version=VERSION)
        self.assertEqual(len(batch.catalog_records), 1)
        self.assertEqual(batch.coverage["counts"]["duplicate_rows"], 1)
        self.assertEqual(batch.coverage["counts"]["matching_gpu_rows"], 2)
        self.assertTrue(batch.coverage["selection_truncated"])
        self.assertFalse(batch.coverage["complete"])
        with patch("compute_pricing.control.connectors.gpuhunt.MAX_ROWS", 1), self.assertRaises(ConnectorError):
            parse_gpuhunt(raw(archive(rows)), policy(), filters=SCOPE, version=VERSION)

    def test_symlink_and_compression_bomb_are_refused_without_extraction(self):
        for mode in ("symlink", "expansion"):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
                member = zipfile.ZipInfo("aws.csv")
                if mode == "symlink":
                    member.create_system = 3
                    member.external_attr = 0o120777 << 16
                    zipped.writestr(member, "invented link target")
                else:
                    zipped.writestr("aws.csv", b"x" * 1048576)
            with self.subTest(mode=mode), self.assertRaises(ConnectorError):
                parse_gpuhunt(raw(data.getvalue()), policy(), filters=SCOPE, version=VERSION)

    def test_wrong_provider_path_fractional_count_and_metadata_duplicates_fail(self):
        for body in (archive([offer(gpu_count="0.5")]), archive([offer(spot="maybe")]),
                archive([offer(provider_data='{"condition":true,"condition":false}')])):
            with self.assertRaises(ConnectorError): parse_gpuhunt(raw(body), policy(), filters=SCOPE, version=VERSION)
        with self.assertRaises(ConnectorError):
            parse_gpuhunt(raw(provider="gcp"), policy(), filters=SCOPE, version=VERSION)

    def test_rights_block_before_any_fetch_and_collector_performs_two_anonymous_reads(self):
        calls = []
        def exchange(request, parts, addresses, headers):
            calls.append((parts.path, headers))
            return (200, {"content-type": "text/plain"}, (VERSION + "\n").encode()) if parts.path.endswith("/version") else (200, {"content-type": "application/zip"}, archive())
        client = ReadOnlyTransport(clock=lambda: NOW, exchange=exchange,
            resolver=lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))])
        for purpose in ("observe", "retain", "benchmark"):
            rights = dict(policy().permissions); rights[purpose] = "FAIL"
            with self.assertRaises(ConnectorError):
                collect_source("gpuhunt_catalog", {"gpuhunt_catalog": policy(permissions=rights)}, transport=client, filters=SCOPE)
        self.assertEqual(calls, [])
        batch = collect_source("gpuhunt_catalog", {"gpuhunt_catalog": policy()}, transport=client, filters=SCOPE)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("Authorization" not in headers for _, headers in calls))
        self.assertEqual(batch.coverage["request_count"], 2)
        self.assertEqual(batch.coverage["provider_catalog_version"], VERSION)
        pinned = {**SCOPE, "version": VERSION}
        self.assertEqual(ADAPTERS["gpuhunt_catalog"].parse(raw(), policy(), filters=pinned).source_id, "gpuhunt_catalog")

    def test_current_configuration_and_source_coverage_are_honest(self):
        policies = load_policies(Path(__file__).resolve().parents[1] / "examples/source-admission.json")
        entries = {row["source_id"]: row for row in source_status(policies, NOW)}
        row = entries["gpuhunt_catalog"]
        self.assertTrue(row["enabled"])
        self.assertFalse(row["auth_required"])
        self.assertFalse(row["collection_parameters"]["direct_vendor_quotes"])
        self.assertEqual(row["collection_parameters"]["providers"], ["aws", "azure", "gcp"])
        self.assertFalse(row["execution_enabled"])
        self.assertTrue(entries["gcp_cloud_billing"]["auth_required"])
        self.assertFalse(entries["gcp_cloud_billing"]["can_attempt_read"])
        self.assertIn("catalog_data_license_unresolved", entries["skypilot_catalog"]["blockers"])


if __name__ == "__main__": unittest.main()
