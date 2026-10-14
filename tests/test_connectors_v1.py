"""Offline contracts and adversarial transport tests. All payloads are synthetic."""
import dataclasses
import datetime as dt
import json
import os
from pathlib import Path
import socket
import sys
import threading
import unittest
from decimal import localcontext
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.connectors import ADAPTERS, ConnectorError, ReadOnlyTransport, SourcePolicy, collect_source, load_policies, source_status
from compute_pricing.control.connectors.adapters import parse_getdeploying, parse_openrouter, parse_vast
from compute_pricing.control.connectors.transport import RawResponse, ReadRequest, SOURCE_SPECS, SourceSpec, resolve_public

NOW = dt.datetime(2026, 10, 14, 12, tzinfo=dt.timezone.utc)
CSV = ("gpu_slug,date,billing_type,reservation_months,min_price,max_price,median_price,provider_median_price,provider_count,offering_count,extra\n"
       "synthetic-new-accelerator,2026-10-12,ON_DEMAND,,1.25,4.50,2.30,2.20,2,3,future-field\n")


def policy(name="getdeploying", **changes):
    defaults = dict(source_id=name, enabled=True, rights_status="allowed", rights_evidence="synthetic_approval",
                    permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
                    max_age_s=14 * 86400, verified_by="synthetic-reviewer", attribution="synthetic_license")
    return SourcePolicy(**{**defaults, **changes})


def raw(name="getdeploying", body=CSV, captured_at="2026-10-14T12:00:00Z"):
    if not isinstance(body, bytes):
        body = body.encode()
    return RawResponse(name, captured_at, "/synthetic", 200, {"content-type": "text/csv"}, body)


def public_resolver(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]


class AdmissionTests(unittest.TestCase):
    def test_example_only_dataset_enabled(self):
        policies = load_policies(Path(__file__).resolve().parents[1] / "examples/source-admission.json")
        self.assertEqual([key for key, p in policies.items() if p.enabled], ["getdeploying"])
        self.assertEqual(policies["getdeploying"].permissions["execution"], "FAIL")
        statuses = {item["source_id"]: item for item in source_status(policies, NOW)}
        self.assertTrue(statuses["getdeploying"]["can_attempt_read"])
        self.assertEqual(statuses["getdeploying"]["liveness"], "not_verified")
        self.assertFalse(statuses["cme"]["execution_enabled"])
        self.assertEqual(statuses["getdeploying"]["implementation_state"], "implemented")
        self.assertEqual(statuses["runpod"]["implementation_state"], "schema_unverified")
        self.assertEqual(statuses["cme"]["implementation_state"], "candidate_only")

    def test_allowed_status_does_not_grant_scope(self):
        with self.assertRaisesRegex(ConnectorError, "observe_permission_missing"):
            policy(permissions={}).require("observe", NOW)

    def test_observe_does_not_grant_benchmark(self):
        candidate = policy(permissions={"observe": "PASS"})
        candidate.require("observe", NOW)
        with self.assertRaisesRegex(ConnectorError, "benchmark_permission_missing"):
            parse_getdeploying(raw(), candidate)

    def test_expired_and_unreviewed_block(self):
        for changes in ({"expires_at": "2026-10-14T12:00:00Z"}, {"verified_by": None}, {"enabled": False}, {"rights_evidence": ""}):
            with self.subTest(changes=changes), self.assertRaises(ConnectorError):
                policy(**changes).require("observe", NOW)

    def test_invalid_policy_freshness(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ConnectorError):
                policy(max_age_s=value)

    def test_scope_map_is_immutable_and_dates_are_strict(self):
        scopes = {"observe": "PASS"}
        candidate = policy(permissions=scopes)
        scopes["observe"] = "FAIL"
        self.assertEqual(candidate.permissions["observe"], "PASS")
        with self.assertRaises(TypeError):
            candidate.permissions["execution"] = "PASS"
        for value in ("2026-10-14Z", "2026-10-14T12:00:00+00:00", "2026-02-30T12:00:00Z"):
            with self.subTest(value=value), self.assertRaises(ConnectorError):
                policy(expires_at=value)


class ParserTests(unittest.TestCase):
    def test_new_gpu_and_extra_fields_remain_dynamic(self):
        batch = parse_getdeploying(raw(), policy())
        item = batch.to_dict()["observations"][0]
        self.assertEqual(item["hardware"]["model"], "synthetic-new-accelerator")
        self.assertIsNone(item["hardware"]["accelerator_count"])
        self.assertEqual(item["kind"], "aggregate_advertised_index")
        self.assertEqual(item["price"], {"amount": "2.20", "currency": "USD", "unit": "gpu_hour"})
        self.assertEqual(item["extensions"]["source_row"]["extra"], "future-field")
        self.assertFalse(item["extensions"]["executable"])
        self.assertEqual(item["observed_at"], "2026-10-12T00:00:00Z")
        self.assertEqual(item["expires_at"], "2026-10-26T00:00:00Z")
        self.assertEqual(batch.raw_metadata["sha256"], raw().sha256)

    def test_stale_week_not_rejuvenated_by_fetch(self):
        item = parse_getdeploying(raw(captured_at="2026-11-14T12:00:00Z"), policy()).observations[0]
        self.assertEqual(item["status"], "stale")
        self.assertEqual(item["observed_at"], "2026-10-12T00:00:00Z")

    def test_missing_and_duplicate_header_fail(self):
        for body in (CSV.replace("median_price,", "other_price,", 1), CSV.replace("extra\n", "gpu_slug\n", 1)):
            with self.subTest(body=body), self.assertRaisesRegex(ConnectorError, "dataset_header_changed"):
                parse_getdeploying(raw(body=body), policy())

    def test_invalid_prices_and_counts_fail_without_fallback(self):
        for body in (CSV.replace("2.20,2,3", "NaN,2,3"), CSV.replace("2.20,2,3", "-1,2,3"),
                     CSV.replace("2.20,2,3", "2.20,4,3"), CSV.replace("2.20,2,3", "2.20,2.1,3"),
                     CSV.replace("2.30,", "9.30,"), CSV.replace("2.20,", "9.20,")):
            with self.subTest(body=body), self.assertRaises(ConnectorError):
                parse_getdeploying(raw(body=body), policy())

    def test_bad_row_dates_duplicate_row_and_empty_fail(self):
        for body in (CSV.replace("2026-10-12", "2026-10-13"), CSV.replace("2026-10-12", "2026-10-19"),
                     CSV + CSV.splitlines()[1] + "\n", CSV.splitlines()[0] + "\n", CSV + "bad,row\n"):
            with self.subTest(body=body), self.assertRaises(ConnectorError):
                parse_getdeploying(raw(body=body), policy())

    def test_vast_preserves_bundle_scope(self):
        payload = json.dumps({"offers": [{"id": "synthetic-offer", "gpu_name": "synthetic-gpu",
            "num_gpus": 4, "dph_total": "5.432100", "storage_cost": "0.01", "future_metric": {"value": "9"}}]})
        item = parse_vast(raw("vast", payload), policy("vast")).to_dict()["observations"][0]
        self.assertEqual(item["price"], {"amount": "5.432100", "currency": "USD", "unit": "node_hour"})
        self.assertEqual(item["hardware"]["accelerator_count"], "4")
        self.assertEqual(item["extensions"]["source_row"]["future_metric"], {"value": "9"})
        self.assertIsNone(item["provider_group_id"])

    def test_vast_missing_price_rejects(self):
        with self.assertRaisesRegex(ConnectorError, "invalid_price"):
            parse_vast(raw("vast", json.dumps({"offers": [{"id": "a", "gpu_name": "x", "num_gpus": 1}]})), policy("vast"))

    def test_inference_discovery_no_static_model_ids(self):
        body = json.dumps({"data": [{"id": "synthetic/new-model", "pricing": {"prompt": "0.0000023", "completion": "0"},
            "context_length": 17000, "new_modality": "future"}, {"id": "synthetic/unpriced", "pricing": {}}]})
        batch = parse_openrouter(raw("openrouter", body), policy("openrouter"))
        prices = batch.to_dict()["observations"]
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices[0]["price"]["amount"], "2.3")
        self.assertEqual(prices[0]["price"]["unit"], "input_million_tokens")
        self.assertEqual(prices[1]["price"]["amount"], "0")
        self.assertEqual(len(batch.catalog_records), 2)
        json.dumps(batch.to_dict(), allow_nan=False)

    def test_json_nan_and_catalog_duplicate_fail(self):
        for body in ('{"data":[{"id":"x","pricing":{"prompt":NaN}}]}',
                     '{"data":[{"id":"x","pricing":{}},{"id":"x","pricing":{}}]}'):
            with self.subTest(body=body), self.assertRaises(ConnectorError):
                parse_openrouter(raw("openrouter", body), policy("openrouter"))

    def test_large_exponents_fail_and_high_precision_conversion_is_exact(self):
        for value in ("1e1000000000", "1e-1000000000"):
            body = json.dumps({"data": [{"id": "synthetic/model", "pricing": {"prompt": value}}]})
            with self.subTest(value=value), self.assertRaisesRegex(ConnectorError, "numeric_precision_limit"):
                parse_openrouter(raw("openrouter", body), policy("openrouter"))
        body = json.dumps({"data": [{"id": "synthetic/model", "pricing": {"prompt": "0.1234567890123456789012345678901234"}}]})
        with localcontext() as context:
            context.prec = 3
            item = parse_openrouter(raw("openrouter", body), policy("openrouter")).observations[0]
        self.assertEqual(item["price"]["amount"], "123456.7890123456789012345678901234")

    def test_cross_source_policy_cannot_be_reused_by_direct_parsers(self):
        for parser in (parse_vast, parse_openrouter):
            with self.subTest(parser=parser.__name__), self.assertRaisesRegex(ConnectorError, "source_policy_mismatch"):
                parser(raw(), policy())

    def test_adapter_observations_parse_shared_contract(self):
        from compute_pricing.control.domain.contracts import parse_market_observation
        batches = [parse_getdeploying(raw(), policy()),
                   parse_vast(raw("vast", '{"offers":[{"id":123,"gpu_name":"synthetic-gpu","num_gpus":4,"dph_total":"2.21"}]}'), policy("vast")),
                   parse_openrouter(raw("openrouter", '{"data":[{"id":"synthetic/model","pricing":{"prompt":"0.00001"}}]}'), policy("openrouter"))]
        for batch in batches:
            for item in batch.to_dict()["observations"]:
                with self.subTest(source=batch.source_id):
                    parsed = parse_market_observation(item)
                    self.assertEqual(parsed.price.currency, "USD")


class TransportTests(unittest.TestCase):
    def transport(self, responses, **kwargs):
        calls = []
        def exchange(request, parts, addresses, headers):
            calls.append((request, parts, addresses, headers))
            return responses[len(calls) - 1]
        self.calls = calls
        return ReadOnlyTransport(clock=lambda: NOW, resolver=public_resolver, exchange=exchange, **kwargs)

    def test_success_retains_safe_metadata_only(self):
        transport = self.transport([(200, {"Content-Type": "text/csv; charset=utf-8", "Set-Cookie": "secret"}, CSV.encode())])
        response = transport.fetch(ADAPTERS["getdeploying"].request(), policy())
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn(CSV, repr(response))
        self.assertEqual(self.calls[0][2], ["93.184.216.34"])

    def test_no_read_for_disabled_source(self):
        transport = self.transport([])
        with self.assertRaisesRegex(ConnectorError, "source_disabled"):
            transport.fetch(ADAPTERS["getdeploying"].request(), policy(enabled=False))
        self.assertEqual(self.calls, [])

    def test_redirect_credentials_port_host_query_fragment_forbidden(self):
        targets = ["https://other.example/dataset/gpu-prices/weekly.csv", "https://@getdeploying.com/dataset/gpu-prices/weekly.csv",
                   "https://getdeploying.com:444/dataset/gpu-prices/weekly.csv", "http://getdeploying.com/dataset/gpu-prices/weekly.csv",
                   "https://getdeploying.com/dataset/gpu-prices/weekly.csv?key=secret", "/dataset/gpu-prices/weekly.csv#secret"]
        for location in targets:
            with self.subTest(location=location):
                transport = self.transport([(302, {"location": location}, b"")])
                with self.assertRaises(ConnectorError):
                    transport.fetch(ADAPTERS["getdeploying"].request(), policy())
                self.assertEqual(len(self.calls), 1)

    def test_safe_redirect_and_loop_bound(self):
        transport = self.transport([(302, {"location": "/dataset/gpu-prices/weekly.csv"}, b""), (200, {"content-type": "text/csv"}, CSV.encode())])
        transport.fetch(ADAPTERS["getdeploying"].request(), policy())
        self.assertEqual(len(self.calls), 2)
        transport = self.transport([(302, {"location": "/dataset/gpu-prices/weekly.csv"}, b"")] * 3)
        with self.assertRaisesRegex(ConnectorError, "redirect_forbidden"):
            transport.fetch(ADAPTERS["getdeploying"].request(), policy())

    def test_search_post_only_and_auth_redacted(self):
        transport = self.transport([(200, {"content-type": "application/json"}, b'{"offers":[]}')])
        with patch.dict(os.environ, {"COMPUTEBASIS_VAST_READ_API_KEY": "synthetic-secret"}):
            response = transport.fetch(ADAPTERS["vast"].request(filters={"num_gpus": {"gte": 2}}), policy("vast"))
        self.assertNotIn("synthetic-secret", repr(response))
        self.assertEqual(self.calls[0][0].spec.method, "POST")
        with self.assertRaises(ConnectorError):
            ReadRequest(dataclasses.replace(SOURCE_SPECS["vast"], method="PUT"), "https://console.vast.ai/api/v0/bundles").validate()
        with self.assertRaises(ConnectorError):
            ReadRequest(SourceSpec("custom", "custom.example", r"/write", method="POST", post_contract="vast_offer_search_v1"), "https://custom.example/write", {"limit":1,"type":"on-demand"}).validate()

    def test_post_redirect_never_followed(self):
        transport = self.transport([(307, {"location": "/api/v0/bundles"}, b"")])
        with patch.dict(os.environ, {"COMPUTEBASIS_VAST_READ_API_KEY": "synthetic"}), self.assertRaisesRegex(ConnectorError, "redirect_forbidden"):
            transport.fetch(ADAPTERS["vast"].request(), policy("vast"))
        self.assertEqual(len(self.calls), 1)

    def test_missing_auth_before_network(self):
        transport = self.transport([])
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ConnectorError, "authentication_missing"):
            transport.fetch(ADAPTERS["runpod"].request(), policy("runpod"))
        self.assertEqual(self.calls, [])

    def test_ssrf_and_dns_rebinding_guard(self):
        for ip in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fe80::1", "::ffff:127.0.0.1"):
            resolver = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]
            with self.subTest(ip=ip), self.assertRaisesRegex(ConnectorError, "nonpublic_dns_address"):
                resolve_public("getdeploying.com", resolver)
        with self.assertRaises(ConnectorError):
            resolve_public("getdeploying.com", lambda *a, **k: [])

    def test_dns_timeout_is_bounded(self):
        gate = threading.Event()
        def delayed(*args, **kwargs):
            gate.wait(1)
            return public_resolver()
        try:
            with self.assertRaisesRegex(ConnectorError, "dns_resolution_timeout"):
                resolve_public("getdeploying.com", delayed, timeout_s=0.01)
        finally:
            gate.set()

    def test_retry_after_over_cap_sets_same_host_cooldown(self):
        for status in (429, 503):
            transport = self.transport([(status, {"retry-after": "120"}, b"untrusted-secret")], monotonic=lambda: 100)
            with self.subTest(status=status), self.assertRaisesRegex(ConnectorError, "retry_after_exceeds_budget"):
                transport.fetch(ADAPTERS["getdeploying"].request(), policy())
            with self.assertRaisesRegex(ConnectorError, "source_cooldown_active"):
                transport.fetch(ADAPTERS["getdeploying"].request(), policy())
            self.assertEqual(len(self.calls), 1)

    def test_retry_after_http_date_and_budgeted_retry(self):
        slept = []
        transport = self.transport([(429, {"retry-after": "Wed, 14 Oct 2026 12:00:02 GMT"}, b""), (200, {"content-type": "text/csv"}, CSV.encode())], sleep=slept.append)
        result = transport.fetch(ADAPTERS["getdeploying"].request(), policy())
        self.assertEqual(slept, [2])
        self.assertEqual(result.attempts, 2)

    def test_minimum_source_interval_is_enforced(self):
        transport = self.transport([(200, {"content-type": "text/csv"}, CSV.encode())], monotonic=lambda: 100)
        transport.fetch(ADAPTERS["getdeploying"].request(), policy(min_interval_s=60))
        with self.assertRaisesRegex(ConnectorError, "source_cooldown_active"):
            transport.fetch(ADAPTERS["getdeploying"].request(), policy(min_interval_s=60))
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_reads_do_not_bypass_host_interval(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def exchange(*args):
            calls.append(args)
            entered.set()
            release.wait(2)
            return 200, {"content-type": "text/csv"}, CSV.encode()
        transport = ReadOnlyTransport(clock=lambda: NOW, resolver=public_resolver, exchange=exchange)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(transport.fetch, ADAPTERS["getdeploying"].request(), policy())
            self.assertTrue(entered.wait(1))
            try:
                with self.assertRaisesRegex(ConnectorError, "source_collection_in_progress"):
                    transport.fetch(ADAPTERS["getdeploying"].request(), policy())
            finally:
                release.set()
            first.result(timeout=2)
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(ConnectorError, "source_cooldown_active"):
            transport.fetch(ADAPTERS["getdeploying"].request(), policy())

    def test_response_size_html_compression_and_network_messages(self):
        for response in ((200, {"content-type": "text/csv"}, b"a" * 11), (200, {"content-type": "text/html"}, b"x"),
                         (200, {"content-type": "text/csv", "content-encoding": "gzip"}, b"x")):
            transport = self.transport([response], max_bytes=10)
            with self.subTest(response=response), self.assertRaises(ConnectorError):
                transport.fetch(ADAPTERS["getdeploying"].request(), policy())
        def broken(*args):
            raise OSError("sensitive URL secret")
        transport = ReadOnlyTransport(clock=lambda: NOW, resolver=public_resolver, exchange=broken)
        with self.assertRaisesRegex(ConnectorError, "^network_request_failed$"):
            transport.fetch(ADAPTERS["getdeploying"].request(), policy())

    def test_collect_uses_supplied_live_response_no_static_fallback(self):
        transport = self.transport([(200, {"content-type": "text/csv"}, CSV.replace("2.20,", "3.20,").encode())])
        batch = collect_source("getdeploying", {"getdeploying": policy()}, transport=transport)
        self.assertEqual(batch.observations[0]["price"]["amount"], "3.20")
        with self.assertRaises(ConnectorError):
            collect_source("arbitrary", {}, transport=transport)


if __name__ == "__main__":
    unittest.main()
