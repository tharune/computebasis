"""Invented API-shaped records verify bounds, signed rates, timezones and rights."""
from copy import deepcopy
import datetime as dt
import json
import socket
import unittest
from urllib.parse import parse_qs, urlsplit

from compute_pricing.control.connectors import ConnectorError, ReadOnlyTransport, SourcePolicy, collect_source, source_status
from compute_pricing.control.connectors.adapters import ADAPTERS
from compute_pricing.control.connectors.energy import (LOCAL_ZONE, collect_energinet, energinet_request,
    parse_energinet, resolved_energinet_filters)
from compute_pricing.control.connectors.transport import RawResponse, ReadRequest, SOURCE_SPECS, UTC


def scope(day="2054-06-11", limit=1000):
    first = dt.date.fromisoformat(day)
    return {"price_area": "DK2", "start": day, "end": (first + dt.timedelta(days=1)).isoformat(), "limit": limit}


def admission(**overrides):
    values = {"source_id": "energinet_day_ahead", "enabled": True, "rights_status": "allowed",
        "rights_evidence": "invented test review", "permissions": {"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        "max_age_s": 172800, "verified_by": "independent-test-review", "min_interval_s": 0}
    return SourcePolicy(**{**values, **overrides})


def grid(options):
    begin = dt.datetime.combine(dt.date.fromisoformat(options["start"]), dt.time(), LOCAL_ZONE).astimezone(UTC)
    end = dt.datetime.combine(dt.date.fromisoformat(options["end"]), dt.time(), LOCAL_ZONE).astimezone(UTC)
    rows = []
    while begin < end:
        rows.append({"TimeUTC": begin.replace(tzinfo=None).isoformat(),
            "TimeDK": begin.astimezone(LOCAL_ZONE).replace(tzinfo=None).isoformat(), "PriceArea": options["price_area"],
            "DayAheadPriceEUR": -23.5, "DayAheadPriceDKK": -175.25})
        begin += dt.timedelta(minutes=15)
    return {"dataset": "DayAheadPrices", "total": len(rows), "records": rows}


def response(packet, captured="2054-06-12T12:00:00Z"):
    body = packet if isinstance(packet, bytes) else json.dumps(packet).encode()
    return RawResponse("energinet_day_ahead", captured, "/dataset/DayAheadPrices", 200, {}, body)


class AnonymousEnergyTests(unittest.TestCase):
    def test_fixed_anonymous_get_contract_and_explicit_budgets(self):
        request = energinet_request(scope())
        query = parse_qs(urlsplit(request.url).query)
        self.assertEqual(request.validate().hostname, "api.energidataservice.dk")
        self.assertEqual(request.spec.method, "GET")
        self.assertIsNone(request.spec.secret_env)
        self.assertEqual(query["sort"], ["TimeUTC ASC"])
        self.assertEqual(json.loads(query["filter"][0]), {"PriceArea": ["DK2"]})
        self.assertEqual(set(query["columns"][0].split(",")), {"TimeUTC", "TimeDK", "PriceArea", "DayAheadPriceEUR", "DayAheadPriceDKK"})
        for changed in (None, {}, {**scope(), "limit": 0}, {**scope(), "limit": True}, {**scope(), "limit": 1001},
                {**scope(), "end": "2054-06-19"}, {**scope(), "price_area": "FI"}, {**scope(), "rolling_days": 1},
                {"price_area": "DK1", "limit": 500, "rolling_days": 8}, {**scope(), "offset": 10}):
            with self.subTest(changed=changed), self.assertRaises(ConnectorError): energinet_request(changed)
        for url in ("https://api.energidataservice.dk/dataset/Elspotprices", request.url + "&token=unapproved"):
            with self.assertRaises(ConnectorError): ReadRequest(SOURCE_SPECS["energinet_day_ahead"], url).validate()

    def test_complete_grid_preserves_signed_native_values_without_price_qualification(self):
        batch = parse_energinet(response(grid(scope())), admission(), filters=scope())
        self.assertTrue(batch.coverage["complete"])
        self.assertEqual(batch.coverage["expected_intervals"], 96)
        self.assertEqual(batch.observations, ())
        row = batch.catalog_records[0]
        self.assertEqual(row["native_prices"], {"EUR": "-23.5", "DKK": "-175.25"})
        self.assertEqual(row["native_unit"], "MWh")
        self.assertEqual(row["starts_at"], "2054-06-10T22:00:00Z")
        self.assertEqual(row["ends_at"], "2054-06-10T22:15:00Z")
        self.assertIsNone(row["source_published_at"])
        for field in ("price_eligible", "gpu_hour_benchmark_eligible", "retail_tariff_qualified", "firm_price_eligible", "execution_enabled"):
            self.assertFalse(row[field])
        self.assertIn("Energinet", row["attribution"])
        self.assertFalse(batch.raw_metadata["raw_body_retained"])

    def test_dst_grids_count_actual_utc_intervals_and_repeat_local_hour_safely(self):
        for day, length in (("2054-03-29", 92), ("2054-10-25", 100)):
            options = scope(day)
            packet = grid(options)
            batch = parse_energinet(response(packet), admission(), filters=options)
            self.assertEqual(len(batch.catalog_records), length)
            self.assertEqual(batch.coverage["expected_intervals"], length)
            self.assertTrue(batch.coverage["complete"])
            self.assertEqual(len({row["starts_at"] for row in batch.catalog_records}), length)

    def test_missing_or_empty_intervals_remain_partial_without_filling(self):
        for remove in (1, 96):
            packet = grid(scope()); packet["records"] = packet["records"][remove:]
            batch = parse_energinet(response(packet), admission(), filters=scope())
            self.assertFalse(batch.coverage["complete"])
            self.assertEqual(batch.coverage["missing_intervals"], remove)
            self.assertEqual(len(batch.catalog_records), 96 - remove)
            self.assertTrue(any("no_interpolation" in warning for warning in batch.warnings))

    def test_unknown_response_values_are_not_retained(self):
        packet = grid(scope()); packet["records"][0]["FutureColumn"] = "invented unretained value"
        batch = parse_energinet(response(packet), admission(), filters=scope())
        self.assertIn("FutureColumn", batch.catalog_records[0]["unknown_field_names"])
        self.assertNotIn("invented unretained value", json.dumps(batch.to_dict()))
        self.assertNotIn("source_row", json.dumps(batch.to_dict()))

    def test_wrong_scope_duplicates_timestamps_and_native_types_fail(self):
        for case in ("area", "duplicate", "localtime", "timestamp", "alignment", "number", "boolean", "missing", "dataset", "limit"):
            packet = grid(scope())
            row = packet["records"][0]
            if case == "area": row["PriceArea"] = "DE"
            elif case == "duplicate": packet["records"][1] = deepcopy(row)
            elif case == "localtime": row["TimeDK"] = "2054-06-11T00:01:00"
            elif case == "timestamp": row["TimeUTC"] += "Z"
            elif case == "alignment":
                row["TimeUTC"] = "2054-06-10T22:01:00"; row["TimeDK"] = "2054-06-11T00:01:00"
            elif case == "number": row["DayAheadPriceEUR"] = "-23.5"
            elif case == "boolean": row["DayAheadPriceEUR"] = False
            elif case == "missing": row.pop("DayAheadPriceDKK")
            elif case == "dataset": packet["dataset"] = "different dataset"
            else: packet["records"] = packet["records"] * 11
            with self.subTest(case=case), self.assertRaises(ConnectorError):
                parse_energinet(response(packet), admission(), filters=scope())

    def test_json_decimal_precision_duplicate_keys_and_nonfinite_are_not_coerced(self):
        packet = grid(scope()); packet["records"] = packet["records"][:1]
        raw = json.dumps(packet).replace("-23.5", "-0.123456789012345678901234567890123456789").encode()
        batch = parse_energinet(response(raw), admission(), filters=scope())
        self.assertEqual(batch.catalog_records[0]["native_prices"]["EUR"], "-0.123456789012345678901234567890123456789")
        for bad in (b'{"dataset":"DayAheadPrices","dataset":"DayAheadPrices","records":[]}',
                    json.dumps(packet).replace("-23.5", "NaN").encode()):
            with self.assertRaises(ConnectorError): parse_energinet(response(bad), admission(), filters=scope())

    def test_rolling_completed_days_resolve_once_using_danish_calendar(self):
        options = {"price_area": "DK1", "limit": 1000, "rolling_days": 2}
        instant = dt.datetime(2054, 6, 13, 23, tzinfo=UTC)  # Danish June14.
        resolved = resolved_energinet_filters(options, instant)
        self.assertEqual(resolved, {"price_area": "DK1", "limit": 1000, "start": "2054-06-12", "end": "2054-06-14"})
        class MidnightTransport:
            request = None
            def clock(self): return instant
            def fetch(self, request, policy):
                self.request = request
                return response(grid(resolved), "2054-06-14T22:00:00Z")
        transport = MidnightTransport()
        batch = collect_energinet(admission(), transport, options)
        self.assertEqual(batch.coverage["scope"], resolved)
        self.assertEqual(batch.coverage["requested_scope"], options)
        self.assertTrue(batch.coverage["complete"])
        self.assertEqual(parse_qs(urlsplit(transport.request.url).query)["end"], ["2054-06-14"])

    def test_every_purpose_gate_precedes_transport_and_anonymous_collection_has_no_auth_header(self):
        calls = []
        def exchange(request, parts, addresses, headers):
            calls.append(headers)
            return 200, {"content-type": "application/json"}, json.dumps(grid(scope())).encode()
        transport = ReadOnlyTransport(clock=lambda: dt.datetime(2054, 6, 12, 12, tzinfo=UTC),
            resolver=lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))],
            exchange=exchange)
        for purpose in ("observe", "retain", "benchmark"):
            permission = dict(admission().permissions); permission[purpose] = "FAIL"
            with self.assertRaises(ConnectorError):
                collect_source("energinet_day_ahead", {"energinet_day_ahead": admission(permissions=permission)}, transport=transport, filters=scope())
        self.assertEqual(calls, [])
        batch = collect_source("energinet_day_ahead", {"energinet_day_ahead": admission()}, transport=transport, filters=scope())
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Authorization", calls[0])
        self.assertTrue(batch.coverage["complete"])

    def test_registered_parser_and_discovery_contract_remain_non_executable(self):
        adapter = ADAPTERS["energinet_day_ahead"]
        self.assertEqual(adapter.role, "energy_market_reference")
        batch = adapter.parse(response(grid(scope())), admission(), filters=scope())
        self.assertEqual(batch.source_id, "energinet_day_ahead")
        result = next(item for item in source_status({"energinet_day_ahead": admission()}) if item["source_id"] == "energinet_day_ahead")
        self.assertFalse(result["auth_required"])
        self.assertEqual(result["collection_parameters"]["max_days"], 7)
        self.assertFalse(result["execution_enabled"])


if __name__ == "__main__": unittest.main()
