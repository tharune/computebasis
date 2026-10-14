"""Independent invented half-hour carbon records; tests never contact a feed."""
from copy import deepcopy
import datetime as dt
from decimal import localcontext
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from compute_pricing.control.connectors import (ConnectorError, ReadOnlyTransport, SourcePolicy,
    collect_source, load_policies, source_status)
from compute_pricing.control.connectors.adapters import ADAPTERS
from compute_pricing.control.connectors.carbon import (carbon_request, collect_carbon,
    parse_carbon, resolved_carbon_filters)
from compute_pricing.control.connectors.transport import RawResponse, ReadRequest, SOURCE_SPECS, UTC

SCOPE = {"start": "2048-04-15T00:00Z", "end": "2048-04-16T00:00Z", "limit": 336}
CAPTURE = "2048-04-16T00:17:00Z"


def policy(**changes):
    values = {"source_id": "gb_carbon_intensity", "enabled": True, "rights_status": "allowed",
        "rights_evidence": "invented context-purpose review", "verified_by": "independent-test-review",
        "permissions": {"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        "max_age_s": 7200, "min_interval_s": 0}
    return SourcePolicy(**{**values, **changes})


def packet(scope=SCOPE):
    current = dt.datetime.fromisoformat(scope["start"].replace("Z", "+00:00"))
    last = dt.datetime.fromisoformat(scope["end"].replace("Z", "+00:00"))
    rows = []
    while current < last:
        end = current + dt.timedelta(minutes=30)
        rows.append({"from": current.isoformat(timespec="minutes").replace("+00:00", "Z"),
            "to": end.isoformat(timespec="minutes").replace("+00:00", "Z"),
            "intensity": {"forecast": 147, "actual": 153, "index": "moderate"}})
        current = end
    return {"data": rows}


def raw(payload=None, *, scope=SCOPE, captured=CAPTURE, **changes):
    value = packet(scope) if payload is None else payload
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return RawResponse(**{"source_id": "gb_carbon_intensity", "captured_at": captured,
        "endpoint_path": "/intensity/" + scope["start"] + "/" + scope["end"],
        "status": 200, "headers": {}, "body": body, **changes})


class GridCarbonSourceTests(unittest.TestCase):
    def test_anonymous_get_has_pinned_host_path_and_explicit_scope(self):
        request = carbon_request(SCOPE)
        self.assertEqual(request.validate().hostname, "api.carbonintensity.org.uk")
        self.assertEqual(request.validate().query, "")
        self.assertEqual(request.spec.method, "GET")
        self.assertIsNone(request.spec.secret_env)
        for url in (request.url + "?token=unapproved", request.url.replace("/intensity/", "/regional/intensity/"),
                request.url.replace("api.carbonintensity.org.uk", "example.org"), request.url.replace(":00Z", "%3A00Z")):
            with self.subTest(url=url), self.assertRaises(ConnectorError):
                ReadRequest(SOURCE_SPECS["gb_carbon_intensity"], url).validate()

    def test_limits_scope_alignment_and_unknown_filters_rejected(self):
        bad = (None, {}, {**SCOPE, "limit": True}, {**SCOPE, "limit": 0}, {**SCOPE, "limit": 337},
            {**SCOPE, "end": "2048-04-23T00:00Z"}, {**SCOPE, "end": SCOPE["start"]},
            {**SCOPE, "start": "2048-04-15T00:01Z"}, {**SCOPE, "start": "2048-04-15T00:00:00Z"},
            {**SCOPE, "start": "2048-02-30T00:00Z"}, {**SCOPE, "rolling_hours": 24},
            {"rolling_hours": True, "limit": 336}, {"rolling_hours": 169, "limit": 336},
            {"rolling_hours": 0, "limit": 336}, {**SCOPE, "postcode": "invented"})
        for scope in bad:
            with self.subTest(scope=scope), self.assertRaises(ConnectorError): carbon_request(scope)

    def test_half_hour_values_are_distinct_native_context_not_compute_prices(self):
        batch = parse_carbon(raw(), policy(), filters=SCOPE)
        self.assertTrue(batch.coverage["complete"])
        self.assertTrue(batch.coverage["forecast_complete"])
        self.assertTrue(batch.coverage["actual_complete"])
        self.assertEqual(batch.coverage["expected_intervals"], 48)
        self.assertEqual(batch.observations, ())
        record = batch.catalog_records[0]
        self.assertEqual(record["native_intensity"], {"forecast": "147", "actual": "153"})
        self.assertEqual(record["native_unit"], "gCO2/kWh")
        self.assertEqual(record["geography"], "GB")
        self.assertEqual(record["starts_at"], "2048-04-15T00:00:00Z")
        self.assertEqual(record["ends_at"], "2048-04-15T00:30:00Z")
        self.assertEqual(record["interval_state"], "completed")
        self.assertEqual(record["actual_basis"], "publisher_estimated_from_metered_generation")
        self.assertIsNone(record["price"])
        self.assertIsNone(record["source_published_at"])
        for field in ("price_eligible", "gpu_hour_benchmark_eligible", "retail_tariff_qualified",
                "site_emissions_qualified", "marginal_emissions_qualified", "carbon_credit_qualified",
                "firm_price_eligible", "execution_enabled", "publisher_revision_known"):
            self.assertFalse(record[field])
        self.assertIn("CC BY 4.0", record["attribution"])
        self.assertFalse(batch.raw_metadata["raw_body_retained"])

    def test_null_missing_zero_forecast_and_actual_never_substitute(self):
        value = packet()
        value["data"][0]["intensity"] = {"forecast": 0, "actual": None, "index": "very low"}
        value["data"][1]["intensity"] = {"actual": 0}
        value["data"][2]["intensity"] = {"forecast": None}
        batch = parse_carbon(raw(value), policy(), filters=SCOPE)
        rows = batch.catalog_records
        self.assertEqual(rows[0]["native_intensity"], {"forecast": "0", "actual": None})
        self.assertEqual(rows[0]["missing_intensity_fields"], [])
        self.assertEqual(rows[1]["native_intensity"], {"forecast": None, "actual": "0"})
        self.assertEqual(rows[1]["missing_intensity_fields"], ["forecast"])
        self.assertEqual(rows[2]["status"], "held")
        self.assertEqual(rows[2]["missing_intensity_fields"], ["actual"])
        self.assertTrue(batch.coverage["complete"])
        self.assertFalse(batch.coverage["forecast_complete"])
        self.assertFalse(batch.coverage["actual_complete"])
        self.assertEqual(batch.coverage["forecast_missing_values"], 2)
        self.assertEqual(batch.coverage["actual_missing_values"], 2)

    def test_missing_intervals_empty_or_selection_limit_remain_partial(self):
        for removed in (1, 48):
            value = packet(); value["data"] = value["data"][removed:]
            batch = parse_carbon(raw(value), policy(), filters=SCOPE)
            self.assertFalse(batch.coverage["complete"])
            self.assertEqual(batch.coverage["missing_intervals"], removed)
            self.assertEqual(len(batch.catalog_records), 48 - removed)
        limited = {**SCOPE, "limit": 3}
        batch = parse_carbon(raw(), policy(), filters=limited)
        self.assertEqual(len(batch.catalog_records), 3)
        self.assertEqual(batch.coverage["records_matched"], 48)
        self.assertEqual(batch.coverage["missing_intervals"], 45)
        self.assertTrue(batch.coverage["selection_truncated"])
        self.assertFalse(batch.coverage["complete"])

    def test_only_touching_boundary_rows_omitted_and_no_outside_context_admitted(self):
        value = packet()
        value["data"].insert(0, {"from": "2048-04-14T23:30Z", "to": SCOPE["start"], "intensity": {"actual": 211}})
        value["data"].append({"from": SCOPE["end"], "to": "2048-04-16T00:30Z", "intensity": {"forecast": 109}})
        batch = parse_carbon(raw(value), policy(), filters=SCOPE)
        self.assertEqual(batch.coverage["boundary_rows_omitted"], 2)
        self.assertEqual(batch.coverage["rows_received"], 50)
        self.assertEqual(len(batch.catalog_records), 48)
        self.assertTrue(batch.coverage["complete"])
        value["data"][0]["from"] = "2048-04-14T23:00Z"
        value["data"][0]["to"] = "2048-04-14T23:30Z"
        with self.assertRaisesRegex(ConnectorError, "outside_scope"):
            parse_carbon(raw(value), policy(), filters=SCOPE)

    def test_future_forecasts_remain_forecasts_without_fabricated_actuals(self):
        value = packet()
        for item in value["data"]: item["intensity"]["actual"] = None
        batch = parse_carbon(raw(value, captured="2048-04-14T23:50:00Z"), policy(), filters=SCOPE)
        self.assertTrue(all(item["interval_state"] == "future" for item in batch.catalog_records))
        self.assertFalse(batch.coverage["actual_complete"])
        self.assertEqual(batch.coverage["actual_missing_values"], 48)
        self.assertTrue(batch.coverage["forecast_complete"])

    def test_wrong_interval_duplicate_scope_record_shape_and_types_fail_closed(self):
        for case in ("interval", "duplicate", "timestamp", "negative", "boolean", "string", "huge",
                "shape", "index", "missing", "record_budget", "error"):
            value = packet(); row = value["data"][0]
            if case == "interval": row["to"] = "2048-04-15T01:00Z"
            elif case == "duplicate": value["data"][1] = deepcopy(row)
            elif case == "timestamp": row["from"] = "2048-04-15T00:00+01:00"
            elif case == "negative": row["intensity"]["forecast"] = -1
            elif case == "boolean": row["intensity"]["actual"] = True
            elif case == "string": row["intensity"]["forecast"] = "147"
            elif case == "huge": row["intensity"]["forecast"] = 1000001
            elif case == "shape": row["intensity"] = []
            elif case == "index": row["intensity"]["index"] = ["moderate"]
            elif case == "missing": row.pop("from")
            elif case == "record_budget": value["data"] = value["data"] * 2
            else: value["error"] = {"message": "invented unretained diagnostic"}
            with self.subTest(case=case), self.assertRaises(ConnectorError): parse_carbon(raw(value), policy(), filters=SCOPE)
        with self.assertRaisesRegex(ConnectorError, "scope_mismatch"):
            parse_carbon(raw(endpoint_path="/intensity"), policy(), filters=SCOPE)
        with self.assertRaisesRegex(ConnectorError, "scope_mismatch"):
            parse_carbon(raw(status=500), policy(), filters=SCOPE)

    def test_precision_duplicate_keys_and_nonfinite_values_are_not_coerced(self):
        body = json.dumps(packet()).replace('"forecast": 147', '"forecast": 147.12345678901234567890123456789').encode()
        with localcontext() as context:
            context.prec = 2
            record = parse_carbon(raw(body), policy(), filters=SCOPE).catalog_records[0]
        self.assertEqual(record["native_intensity"]["forecast"], "147.12345678901234567890123456789")
        for bad in (b'{"data":[],"data":[]}', json.dumps(packet()).replace('"forecast": 147', '"forecast": NaN').encode()):
            with self.assertRaises(ConnectorError): parse_carbon(raw(bad), policy(), filters=SCOPE)
        with patch("compute_pricing.control.connectors.carbon.MAX_BODY_BYTES", 1), self.assertRaises(ConnectorError):
            parse_carbon(raw(), policy(), filters=SCOPE)

    def test_unknown_source_values_not_retained_or_turned_into_quality_scores(self):
        value = packet(); value["new_top"] = "invented ignored top value"
        value["data"][0]["new_column"] = "invented ignored row value"
        value["data"][0]["intensity"]["new_intensity"] = "invented ignored nested value"
        value["data"][0]["intensity"]["index"] = "invented unpublished category"
        batch = parse_carbon(raw(value), policy(), filters=SCOPE)
        row = batch.catalog_records[0]
        self.assertEqual(row["unknown_field_names"], ["new_column"])
        self.assertEqual(row["unknown_intensity_field_names"], ["new_intensity"])
        self.assertEqual(batch.coverage["unknown_top_level_field_names"], ["new_top"])
        self.assertIsNone(row["carbon_index"])
        self.assertEqual(row["index_status"], "unrecognized")
        encoded = json.dumps(batch.to_dict())
        self.assertNotIn("invented ignored", encoded)
        self.assertNotIn("invented unpublished", encoded)

    def test_rolling_scope_uses_completed_utc_intervals_once_across_fetch_boundary(self):
        inputs = {"rolling_hours": 24, "limit": 336}
        begin = dt.datetime(2048, 4, 16, 0, 17, tzinfo=UTC)
        self.assertEqual(resolved_carbon_filters(inputs, begin), SCOPE)
        class CrossingTransport:
            def clock(self): return begin
            def fetch(self, request, admission):
                self.request = request
                return raw(captured="2048-04-16T00:31:00Z")
        client = CrossingTransport()
        batch = collect_carbon(policy(), client, inputs)
        self.assertEqual(batch.coverage["scope"], SCOPE)
        self.assertEqual(batch.coverage["requested_scope"], inputs)
        self.assertTrue(batch.coverage["complete"])
        self.assertTrue(client.request.url.endswith(SCOPE["end"]))
        with self.assertRaises(ConnectorError): resolved_carbon_filters(inputs, begin.replace(tzinfo=None))
        with self.assertRaises(ConnectorError):
            resolved_carbon_filters(inputs, dt.datetime(1, 1, 1, tzinfo=UTC))

    def test_utc_grid_is_not_a_local_day_or_dst_settlement_period_guess(self):
        for day in ("2048-03-29", "2048-10-25"):
            first = dt.date.fromisoformat(day)
            scope = {"start": day + "T00:00Z", "end": (first + dt.timedelta(days=1)).isoformat() + "T00:00Z", "limit": 336}
            batch = parse_carbon(raw(scope=scope), policy(), filters=scope)
            self.assertEqual(batch.coverage["expected_intervals"], 48)
            self.assertTrue(batch.coverage["complete"])

    def test_admission_purposes_are_resolved_before_any_network_read(self):
        calls = []
        def exchange(request, parts, addresses, headers):
            calls.append(headers)
            return 200, {"content-type": "application/json"}, json.dumps(packet()).encode()
        client = ReadOnlyTransport(clock=lambda: dt.datetime(2048, 4, 16, 0, 17, tzinfo=UTC),
            resolver=lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))],
            exchange=exchange)
        for purpose in ("observe", "retain", "benchmark"):
            permissions = dict(policy().permissions); permissions[purpose] = "FAIL"
            refused = policy(permissions=permissions)
            for collect in (lambda: collect_source("gb_carbon_intensity", {"gb_carbon_intensity": refused}, transport=client, filters=SCOPE),
                    lambda: collect_carbon(refused, client, SCOPE)):
                with self.subTest(purpose=purpose), self.assertRaises(ConnectorError): collect()
        self.assertEqual(calls, [])
        batch = collect_source("gb_carbon_intensity", {"gb_carbon_intensity": policy()}, transport=client, filters=SCOPE)
        self.assertTrue(batch.coverage["complete"])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Authorization", calls[0])

    def test_registered_discovery_admission_and_collection_examples(self):
        root = Path(__file__).resolve().parents[1]
        policies = load_policies(root / "examples/source-admission.json")
        source = policies["gb_carbon_intensity"]
        self.assertEqual(source.max_age_s, 7200)
        self.assertEqual(source.min_interval_s, 60)
        self.assertEqual(source.liveness, "not_verified")
        self.assertEqual(source.permissions["execution"], "FAIL")
        self.assertIn("CC BY 4.0", source.rights_evidence)
        adapter = ADAPTERS["gb_carbon_intensity"]
        self.assertEqual(adapter.role, "grid_carbon_reference")
        self.assertEqual(adapter.parse(raw(), policy(), filters=SCOPE).source_id, "gb_carbon_intensity")
        status = next(item for item in source_status(policies) if item["source_id"] == "gb_carbon_intensity")
        self.assertFalse(status["auth_required"])
        self.assertEqual(status["collection_parameters"]["native_unit"], "gCO2/kWh")
        self.assertEqual(status["collection_parameters"]["recommended_refresh_s"], 1800)
        for filename in ("collection-plan.json", "backend-collection-plan.json"):
            plan = json.loads((root / "examples" / filename).read_text())
            self.assertLessEqual(len(plan), 32)
            scopes = [entry["filters"] for entry in plan if entry["source_id"] == "gb_carbon_intensity"]
            self.assertEqual(scopes, [{"rolling_hours": 24, "limit": 336}])
            self.assertTrue(all(entry["source_id"] in policies for entry in plan))
        demo = json.loads((root / "examples/demo-collection-plan.json").read_text())
        self.assertNotIn("gb_carbon_intensity", {entry["source_id"] for entry in demo})

    def test_scheduler_cannot_poll_faster_than_published_half_hour_cadence(self):
        from compute_pricing.control.api.refresh import AutomaticRefresh, CollectionCoordinator, RefreshConfig
        inputs = [{"source_id": "gb_carbon_intensity", "filters": {"rolling_hours": 24, "limit": 336}}]
        for configured, lifetime, expected in ((60, 60, 1800), (900, 7200, 1800), (3600, 7200, 3600)):
            config = RefreshConfig.parse({"enabled": True, "on_startup": False,
                "cadence_s": 60, "source_cadence_s": {"gb_carbon_intensity": configured}})
            refresh = AutomaticRefresh(config, inputs, {"gb_carbon_intensity": policy(max_age_s=lifetime)},
                CollectionCoordinator(lambda *_: None), clock=lambda: 0)
            with self.subTest(configured=configured, lifetime=lifetime):
                self.assertEqual(refresh.cadence("gb_carbon_intensity"), expected)


if __name__ == "__main__": unittest.main()
