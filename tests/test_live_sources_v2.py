"""Offline native-unit cloud/FX contracts; no external requests in tests."""
import datetime as dt
import json
from pathlib import Path
import socket
import ssl
import sys
import unittest
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.connectors import ConnectorError, ReadOnlyTransport, SourcePolicy, collect_source, load_policies
from compute_pricing.control.connectors.adapters import azure_request, parse_azure, parse_ecb
from compute_pricing.control.connectors.transport import RawResponse, _PinnedHTTPSConnection
from compute_pricing.control.domain import parse_market_observation

NOW = dt.datetime(2026, 10, 14, 12, tzinfo=dt.timezone.utc)
XML = b'''<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube><Cube time="2026-10-13"><Cube currency="USD" rate="1.12345678901234567890123456789"/><Cube currency="ZZZ" rate="2.30"/></Cube></Cube></gesmes:Envelope>'''


def policy(name):
    return SourcePolicy(name, enabled=True, rights_status="allowed", rights_evidence="synthetic-admission", verified_by="synthetic-reviewer",
        permissions={"observe":"PASS", "retain":"PASS", "benchmark":"PASS", "execution":"FAIL"}, max_age_s=7 * 86400, min_interval_s=1)


def meter(identity="synthetic-meter", **changes):
    return {"currencyCode":"USD", "tierMinimumUnits":"0", "retailPrice":"12.345678901234567890123456789",
        "unitPrice":"12.345678901234567890123456789", "armRegionName":"eastus", "location":"US East",
        "effectiveStartDate":"2020-01-01T00:00:00Z", "meterId":identity, "skuId":"synthetic-sku",
        "meterName":"N Future Compute", "productName":"Virtual Machines N Future Series", "skuName":"N Future",
        "serviceName":"Virtual Machines", "unitOfMeasure":"1 Hour", "type":"Consumption", "isPrimaryMeterRegion":True,
        "armSkuName":"Standard_NFuture", "new_field":{"value":"unknown-preserved"}, **changes}


def azure_raw(items, next_page=None):
    body = json.dumps({"Items":items, "NextPageLink":next_page}).encode()
    return RawResponse("azure", "2026-10-14T12:00:00Z", "/api/retail/prices", 200, {"content-type":"application/json"}, body)


class LiveSourceV2Tests(unittest.TestCase):
    def test_admission_keeps_pending_feeds_disabled(self):
        config = load_policies(Path(__file__).resolve().parents[1] / "examples/source-admission.json")
        self.assertEqual({name for name, p in config.items() if p.enabled}, {"azure", "ecb", "getdeploying", "huggingface", "aws_public_pricing", "openrouter", "huggingface_catalog", "energinet_day_ahead", "gpuhunt_catalog", "gb_carbon_intensity"})
        for name in ("azure", "ecb", "getdeploying", "huggingface", "aws_public_pricing", "openrouter", "huggingface_catalog"):
            self.assertEqual(config[name].permissions["execution"], "FAIL")
        self.assertFalse(config["oracle"].enabled)
        self.assertFalse(config["scaleway"].enabled)

    def test_tls_ca_supplement_keeps_certificate_and_hostname_verification(self):
        connection = _PinnedHTTPSConnection("prices.azure.com","93.184.216.34",15)
        self.assertEqual(connection._context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(connection._context.check_hostname)
        self.assertGreater(connection._context.cert_store_stats()["x509_ca"],0)
        connection.close()

    def test_azure_native_vm_price_has_no_inferred_hardware_or_inventory(self):
        batch = parse_azure(azure_raw([meter()]), policy("azure"))
        item = batch.to_dict()["observations"][0]
        self.assertEqual(item["price"], {"amount":"12.345678901234567890123456789", "currency":"USD", "unit":"node_hour"})
        self.assertEqual(item["hardware"], {"model":None, "accelerator_count":None})
        self.assertIsNone(item["quantity"])
        self.assertIsNone(item["lot_id"])
        self.assertIsNone(item["region"])
        self.assertEqual(item["observed_at"], "2026-10-14T12:00:00Z")
        self.assertEqual(item["extensions"]["effective_start_date"], "2020-01-01T00:00:00Z")
        self.assertEqual(item["extensions"]["source_row"]["new_field"], {"value":"unknown-preserved"})
        parse_market_observation(item)

    def test_numeric_json_lexemes_are_exact_in_shared_domain_extensions(self):
        body = b'{"Items":[{"currencyCode":"USD","tierMinimumUnits":0.0,"retailPrice":12.12345678901234567890123456789,"unitPrice":12.12345678901234567890123456789,"armRegionName":"eastus","meterId":"synthetic","skuId":"synthetic","meterName":"N Future","productName":"N Future","skuName":"N Future","serviceName":"Virtual Machines","unitOfMeasure":"1 Hour","type":"Consumption","isPrimaryMeterRegion":true,"armSkuName":"Standard_NFuture"}],"NextPageLink":null}'
        raw = RawResponse("azure","2026-10-14T12:00:00Z","/synthetic",200,{},body)
        item=parse_azure(raw,policy("azure")).observations[0]
        self.assertEqual(item["price"]["amount"],"12.12345678901234567890123456789")
        self.assertEqual(item["extensions"]["source_row"]["retailPrice"],"12.12345678901234567890123456789")
        parse_market_observation(item)

    def test_ambiguous_source_json_duplicate_price_keys_are_rejected(self):
        raw = RawResponse("azure", "2026-10-14T12:00:00Z", "/synthetic", 200, {},
                          b'{"Items":[],"Items":[{"retailPrice":0,"retailPrice":999}],"NextPageLink":null}')
        with self.assertRaisesRegex(ConnectorError, "duplicate_json_response_key"):
            parse_azure(raw, policy("azure"))

    def test_reservation_hour_label_is_not_divided_into_hourly_price(self):
        batch = parse_azure(azure_raw([meter(type="Reservation", retailPrice="99999", reservationTerm="1 Year"),
                                      meter(type="DevTestConsumption"), meter(currencyCode="EUR"),
                                      meter(unitOfMeasure="1 Month"), meter(tierMinimumUnits="100"), meter(isPrimaryMeterRegion=False)]), policy("azure"))
        self.assertEqual(batch.observations, ())
        self.assertEqual(len(batch.coverage["exclusions"]), 6)

    def test_spot_and_low_priority_remain_distinct_billing_variants(self):
        for label, expected in (("N Future Spot", "SPOT"), ("N Future Low Priority", "LOW_PRIORITY")):
            batch = parse_azure(azure_raw([meter(meterName=label)]), policy("azure"))
            self.assertEqual(batch.observations[0]["extensions"]["billing_type"], expected)

    def test_future_effective_and_cpu_meter_are_not_current_gpu_catalog(self):
        batch = parse_azure(azure_raw([meter(effectiveStartDate="2026-10-15T00:00:00Z"), meter(armSkuName="Standard_DFuture")]), policy("azure"))
        self.assertEqual(batch.observations, ())
        self.assertEqual(len(batch.coverage["exclusions"]), 2)
        for price in ("NaN", "-1"):
            with self.subTest(price=price), self.assertRaises(ConnectorError):
                parse_azure(azure_raw([meter(retailPrice=price)]), policy("azure"))

    def test_azure_requires_explicit_safe_region_and_paging_budget(self):
        for options in ({}, {"region":"eastus' or true"}, {"region":"eastus", "sku":"Standard_D1"}, {"region":"eastus", "max_pages":6}, {"region":"eastus", "$filter":"anything"}):
            with self.subTest(options=options), self.assertRaises(ConnectorError):
                azure_request(options)
        request = azure_request({"region":"eastus", "sku":"Standard_NFuture"})
        request.validate()
        self.assertIn("armSkuName eq 'Standard_NFuture'", urllib.parse.parse_qs(urllib.parse.urlsplit(request.url).query)["$filter"][0])

    def transport(self, responses):
        monotonic = [100.0]
        calls = []
        def exchange(*args):
            calls.append(args)
            return responses[len(calls)-1]
        def sleep(seconds):
            monotonic[0] += seconds
        resolver = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34",443))]
        self.calls = calls
        return ReadOnlyTransport(clock=lambda:NOW, monotonic=lambda:monotonic[0], sleep=sleep, resolver=resolver, exchange=exchange)

    def next_url(self, **changes):
        original = azure_request({"region":"eastus"})
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(original.url).query))
        return "https://prices.azure.com:443/api/retail/prices?" + urllib.parse.urlencode({**query, "$skip":"1000", **changes})

    def response(self, items, next_page=None):
        return 200, {"content-type":"application/json"}, json.dumps({"Items":items, "NextPageLink":next_page}).encode()

    def test_complete_azure_pagination_paces_and_records_scope_hashes(self):
        client = self.transport([self.response([meter()], self.next_url()), self.response([meter("second")])])
        batch = collect_source("azure", {"azure":policy("azure")}, transport=client, filters={"region":"eastus"})
        self.assertTrue(batch.coverage["complete"])
        self.assertFalse(batch.coverage["pagination_truncated"])
        self.assertEqual(batch.coverage["request_count"], 2)
        self.assertEqual(len(batch.raw_metadata["pages"]), 2)
        self.assertEqual(batch.coverage["rows_received"], 2)
        self.assertEqual(len(batch.observations), 2)
        self.assertFalse(batch.coverage["all_market_inventory"])

    def test_budget_exhaustion_returns_explicit_partial_scope(self):
        client = self.transport([self.response([meter()], self.next_url())])
        batch = collect_source("azure", {"azure":policy("azure")}, transport=client, filters={"region":"eastus", "max_pages":1})
        self.assertFalse(batch.coverage["complete"])
        self.assertTrue(batch.coverage["pagination_truncated"])
        self.assertIn("pagination_budget_reached_partial_scoped_catalog", batch.warnings)

    def test_next_page_scope_host_port_credentials_and_cursor_are_guarded(self):
        unsafe = [self.next_url(**{"$filter":"serviceName eq 'All Services'"}), self.next_url(**{"$skip":"0"}),
                  self.next_url(**{"currencyCode":"'EUR'"}), self.next_url().replace("prices.azure.com:443","evil.example"),
                  self.next_url().replace("prices.azure.com:443","prices.azure.com:444"), self.next_url().replace("prices.azure.com:443","@prices.azure.com:443")]
        for url in unsafe:
            client = self.transport([self.response([meter()], url)])
            with self.subTest(url=url), self.assertRaises(ConnectorError):
                collect_source("azure", {"azure":policy("azure")}, transport=client, filters={"region":"eastus"})
            self.assertEqual(len(self.calls),1)

    def test_http_redirect_cannot_change_admitted_query_scope(self):
        request = azure_request({"region": "eastus"})
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.url).query))
        broader = "https://prices.azure.com/api/retail/prices?" + urllib.parse.urlencode({**query, "$filter": "serviceName eq 'All Services'"})
        client = self.transport([(302, {"location": broader}, b"")])
        with self.assertRaisesRegex(ConnectorError, "redirect_scope_changed"):
            client.fetch(request, policy("azure"))
        self.assertEqual(len(self.calls), 1)

    def test_wrong_response_region_and_duplicate_page_meters_fail_closed(self):
        for responses in ([self.response([meter(armRegionName="westus")])],
                          [self.response([meter()],self.next_url()), self.response([meter()])]):
            client = self.transport(responses)
            with self.subTest(responses=responses), self.assertRaises(ConnectorError):
                collect_source("azure", {"azure":policy("azure")}, transport=client, filters={"region":"eastus"})

    def test_ecb_dynamic_currencies_and_exact_reference_units(self):
        raw = RawResponse("ecb", "2026-10-14T12:00:00Z", "/stats/eurofxref/eurofxref-daily.xml",200,{},XML)
        batch = parse_ecb(raw,policy("ecb"))
        self.assertEqual(batch.observations, ())
        record = batch.catalog_records[0]
        self.assertEqual(record["quote_per_base"],"1.12345678901234567890123456789")
        self.assertEqual(record["unit"],"USD_per_EUR")
        self.assertFalse(record["transaction_quote"])
        self.assertIsNone(record["observed_time"])
        self.assertEqual(batch.catalog_records[1]["quote_currency"],"ZZZ")
        self.assertTrue(batch.coverage["complete"])

    def test_ecb_stale_future_duplicate_entities_and_invalid_rate(self):
        for body in (XML.replace(b"2026-10-13",b"2026-10-15"), XML.replace(b"ZZZ",b"USD"),
                     XML.replace(b"2.30",b"NaN"), b'<!DOCTYPE x [<!ENTITY secret "x">]>' + XML):
            raw = RawResponse("ecb","2026-10-14T12:00:00Z","/synthetic",200,{},body)
            with self.subTest(body=body[:50]), self.assertRaises(ConnectorError):
                parse_ecb(raw,policy("ecb"))
        raw = RawResponse("ecb","2026-11-14T12:00:00Z","/synthetic",200,{},XML)
        self.assertEqual(parse_ecb(raw,policy("ecb")).catalog_records[0]["status"],"stale")

    def test_pending_scaleway_and_oracle_never_contact_network(self):
        policies=load_policies(Path(__file__).resolve().parents[1]/"examples/source-admission.json")
        client=self.transport([])
        for name in ("scaleway","oracle"):
            with self.subTest(name=name),self.assertRaisesRegex(ConnectorError,"admission_blocked"):
                collect_source(name,policies,transport=client)
        self.assertEqual(self.calls,[])

    def test_model_metadata_response_cannot_escape_explicit_author_or_budget(self):
        filters = {"author": "synthetic-author", "pipeline_tag": "text-generation", "limit": 1, "full": True}
        good = {"id": "synthetic-author/new-model", "author": "synthetic-author", "pipeline_tag": "text-generation", "private": False}
        for payload in ([{**good, "id": "another-author/model"}], [{**good, "author": "another-author"}],
                        [{**good, "pipeline_tag": "image-generation"}], [good, {**good, "id": "synthetic-author/second-model"}]):
            client = self.transport([(200, {"content-type": "application/json"}, json.dumps(payload).encode())])
            with self.subTest(payload=payload), self.assertRaises(ConnectorError):
                collect_source("huggingface", {"huggingface": policy("huggingface")}, transport=client, filters=filters)
        client = self.transport([(200, {"content-type": "application/json"}, json.dumps([good]).encode())])
        batch = collect_source("huggingface", {"huggingface": policy("huggingface")}, transport=client, filters=filters)
        self.assertEqual(batch.observations, ())
        self.assertEqual(batch.coverage["request_scope"]["author"], "synthetic-author")
        self.assertEqual(batch.coverage["maximum_records"], 1)
        self.assertFalse(batch.coverage["complete"])
        client = self.transport([(200, {"content-type": "application/json"}, json.dumps([{**good, "pipeline_tag": None}]).encode())])
        batch = collect_source("huggingface", {"huggingface": policy("huggingface")}, transport=client, filters=filters)
        self.assertEqual(batch.coverage["missing_pipeline_tags"], 1)
        self.assertIn("missing_pipeline_tag_remains_unqualified_metadata", batch.warnings)


if __name__ == "__main__":
    unittest.main()
