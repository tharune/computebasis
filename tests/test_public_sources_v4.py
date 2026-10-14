"""Independent native-tariff/CPU-scope cases; no real feed snapshots or requests."""
import datetime as dt
import json
from pathlib import Path
import socket
import sys
import unittest
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.connectors import ConnectorError, ReadOnlyTransport, SourcePolicy, collect_source, load_policies, source_status
from compute_pricing.control.connectors.adapters import azure_request, parse_azure, parse_openrouter
from compute_pricing.control.connectors.aws import aws_request, parse_aws
from compute_pricing.control.connectors.openrouter import openrouter_request
from compute_pricing.control.connectors.transport import RawResponse

NOW = dt.datetime(2026, 10, 14, 12, tzinfo=dt.timezone.utc)
FILTERS = {"service": "AmazonLightsail", "region": "us-east-1"}


def policy(name="aws_public_pricing", **changes):
    values = dict(source_id=name, enabled=True, rights_status="allowed", rights_evidence="invented-native-cost-review",
        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        verified_by="invented-reviewer", max_age_s=86400, min_interval_s=1)
    values.update(changes)
    return SourcePolicy(**values)


def payload(*, service="AmazonLightsail", region="us-east-1", unit="Hrs", amount="0.123456789012345678901234567890", term_type="OnDemand"):
    return {"formatVersion": "v1.0", "offerCode": service, "version": "20261013120000", "publicationDate": "2026-10-13T12:00:00Z",
        "disclaimer": "Invented tariff is not a firm quote", "products": {"NEWSKU": {"sku": "NEWSKU", "productFamily": "Compute Instance",
            "attributes": {"servicecode": service, "regionCode": region, "vcpu": "4", "memory": "8 GB", "new_attribute": "unpriced"}}},
        "terms": {term_type: {"NEWSKU": {"NEWSKU.TERM": {"sku": "NEWSKU", "offerTermCode": "TERM", "effectiveDate": "2020-01-01T00:00:00Z",
            "termAttributes": {"invented_commitment": "not normalized"}, "priceDimensions": {"NEWSKU.TERM.RATE": {
                "rateCode": "NEWSKU.TERM.RATE", "description": "Invented native rate", "unit": unit,
                "beginRange": "0", "endRange": "Inf", "pricePerUnit": {"USD": amount}, "future_field": "retained"}}}}}}}


def raw(data):
    return RawResponse("aws_public_pricing", "2026-10-14T12:00:00Z", "/invented-price-file", 200, {}, json.dumps(data).encode())


class PublicSourcesV4Tests(unittest.TestCase):
    def test_aws_requires_explicit_reviewed_service_region_and_safe_sku(self):
        for filters in ({}, {"service": "AmazonEC2", "region": "us-east-1"}, {**FILTERS, "region": "../all"},
                        {**FILTERS, "sku": "anything?token=x"}, {**FILTERS, "unknown": "value"}, {**FILTERS, "service": []}):
            with self.subTest(filters=filters), self.assertRaises(ConnectorError):
                aws_request(filters)
        self.assertIn("AmazonLightsail/current/region_index.json", aws_request(FILTERS).url)

    def test_native_prices_preserve_precision_units_and_attributes_without_gpu_quotes(self):
        for unit in ("Hrs", "GB-Hours", "vCPU-Hours", "1000 Tokens", "Quantity"):
            batch = parse_aws(raw(payload(unit=unit)), policy(), filters=FILTERS)
            self.assertEqual(batch.observations, ())
            row = batch.catalog_records[0]
            self.assertEqual(row["native_price"], {"amount": "0.123456789012345678901234567890", "currency": "USD", "unit": unit})
            self.assertFalse(row["gpu_hour_benchmark_eligible"])
            self.assertFalse(row["physical_inventory_verified"])
            self.assertFalse(row["execution_enabled"])
            self.assertEqual(row["observed_at"], "2026-10-14T12:00:00Z")
            self.assertEqual(row["effective_at"], "2020-01-01T00:00:00Z")
            self.assertEqual(row["extensions"]["product_attributes"]["vcpu"], "4")
            self.assertEqual(row["extensions"]["unknown_product_attribute_names"], ["new_attribute"])
            self.assertEqual(row["extensions"]["unknown_dimension_field_names"], ["future_field"])
            for field in ("source_product", "source_offer", "source_dimension"):
                self.assertNotIn(field, row["extensions"])

    def test_reserved_upfront_native_quantity_never_divided_by_month_hours(self):
        batch = parse_aws(raw(payload(unit="Quantity", amount="999", term_type="Reserved")), policy(), filters=FILTERS)
        row = batch.catalog_records[0]
        self.assertEqual(row["native_price"]["amount"], "999")
        self.assertEqual(row["native_price"]["unit"], "Quantity")
        self.assertEqual(row["term_type"], "Reserved")

    def test_explicit_zero_is_preserved_but_missing_negative_nan_prices_refuse(self):
        self.assertEqual(parse_aws(raw(payload(amount="0")), policy(), filters=FILTERS).catalog_records[0]["native_price"]["amount"], "0")
        for amount in (None, "-1", "NaN", "Infinity"):
            with self.subTest(amount=amount), self.assertRaises(ConnectorError):
                parse_aws(raw(payload(amount=amount)), policy(), filters=FILTERS)

    def test_wrong_service_region_unit_range_join_and_future_publication_refuse(self):
        wrong = []
        wrong.append(payload(service="AmazonEC2")); wrong.append(payload(region="us-west-2")); wrong.append(payload(unit=""))
        a = payload(); a["publicationDate"] = "2026-10-15T00:00:00Z"; wrong.append(a)
        a = payload(); a["terms"]["OnDemand"]["NEWSKU"]["NEWSKU.TERM"]["priceDimensions"]["NEWSKU.TERM.RATE"]["endRange"] = "0"; wrong.append(a)
        a = payload(); a["terms"]["OnDemand"]["NEWSKU"]["NEWSKU.TERM"]["sku"] = "DIFFERENT"; wrong.append(a)
        for packet in wrong:
            with self.subTest(packet=packet.get("offerCode")), self.assertRaises(ConnectorError):
                parse_aws(raw(packet), policy(), filters=FILTERS)

    def test_unknown_term_structure_and_future_effective_rates_have_incomplete_coverage(self):
        packet = payload(); packet["terms"]["FlatRate"] = {"plans": []}
        self.assertFalse(parse_aws(raw(packet), policy(), filters=FILTERS).coverage["complete"])
        packet = payload(); packet["terms"]["OnDemand"]["NEWSKU"]["NEWSKU.TERM"]["effectiveDate"] = "2026-10-15T00:00:00Z"
        batch = parse_aws(raw(packet), policy(), filters=FILTERS)
        self.assertEqual(batch.catalog_records, ())
        self.assertFalse(batch.coverage["complete"])

    def test_optional_sku_is_selection_not_an_independent_synthetic_product(self):
        batch = parse_aws(raw(payload()), policy(), filters={**FILTERS, "sku": "MISSING"})
        self.assertEqual(batch.catalog_records, ())
        self.assertEqual(batch.coverage["products_received"], 1)
        self.assertEqual(batch.coverage["tariffs_received"], 1)

    def transport(self, responses):
        tick, calls = [10.0], []
        def exchange(*args):
            calls.append(args)
            return responses[len(calls) - 1]
        def sleep(seconds): tick[0] += seconds
        self.calls = calls
        return ReadOnlyTransport(clock=lambda: NOW, monotonic=lambda: tick[0], sleep=sleep,
            resolver=lambda *args, **kw: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))], exchange=exchange)

    def index_response(self, target=None):
        return 200, {"content-type": "application/json"}, json.dumps({"formatVersion": "v1.0", "regions": {"us-east-1": {
            "regionCode": "us-east-1", "currentVersionUrl": target or "/offers/v1.0/aws/AmazonLightsail/20261013120000/us-east-1/index.json"}}}).encode()

    def test_collector_follows_only_matching_region_service_url_and_records_two_hashes(self):
        client = self.transport([self.index_response(), (200, {"content-type": "application/octet-stream"}, json.dumps(payload()).encode())])
        batch = collect_source("aws_public_pricing", {"aws_public_pricing": policy()}, transport=client, filters=FILTERS)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(batch.coverage["request_count"], 2)
        self.assertEqual(len(batch.raw_metadata["pages"]), 2)
        self.assertFalse(batch.coverage["all_services"])
        self.assertFalse(batch.coverage["all_market_inventory"])

    def test_region_index_cannot_redirect_to_other_host_service_region_or_query(self):
        for url in ("https://elsewhere.example/offers/v1.0/aws/AmazonLightsail/current/us-east-1/index.json",
                    "/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json", "/offers/v1.0/aws/AmazonLightsail/current/us-west-2/index.json",
                    "https://pricing.us-east-1.amazonaws.com:444/offers/v1.0/aws/AmazonLightsail/current/us-east-1/index.json",
                    "/offers/v1.0/aws/AmazonLightsail/current/us-east-1/index.json?key=invalid"):
            client = self.transport([self.index_response(url)])
            with self.subTest(url=url), self.assertRaises(ConnectorError):
                collect_source("aws_public_pricing", {"aws_public_pricing": policy()}, transport=client, filters=FILTERS)
            self.assertEqual(len(self.calls), 1)

    def test_rights_for_native_comparison_are_checked_before_network(self):
        client = self.transport([])
        held = policy(permissions={"observe": "PASS", "retain": "FAIL", "benchmark": "PASS", "execution": "FAIL"})
        with self.assertRaisesRegex(ConnectorError, "admission_blocked"):
            collect_source("aws_public_pricing", {"aws_public_pricing": held}, transport=client, filters=FILTERS)
        self.assertEqual(self.calls, [])

    def test_azure_cpu_prefix_is_explicit_and_never_infers_hardware(self):
        request = azure_request({"region": "eastus", "sku_prefix": "Standard_D", "sku": "Standard_DInvented"})
        request.validate()
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.url).query)
        self.assertIn("Standard_DInvented", query["$filter"][0])
        meter = {"currencyCode": "USD", "tierMinimumUnits": "0", "retailPrice": "1.900001", "armRegionName": "eastus", "meterId": "invented", "skuId": "invented",
            "productName": "Invented CPU VM", "meterName": "Invented meter", "serviceName": "Virtual Machines", "unitOfMeasure": "1 Hour", "type": "Consumption", "isPrimaryMeterRegion": True, "armSkuName": "Standard_DInvented"}
        response = RawResponse("azure", "2026-10-14T12:00:00Z", "/api/retail/prices", 200, {}, json.dumps({"Items": [meter], "NextPageLink": None}).encode())
        self.assertEqual(parse_azure(response, policy("azure")).observations, ())
        item = parse_azure(response, policy("azure"), sku_prefix="Standard_D").observations[0]
        self.assertEqual(item["price"]["unit"], "node_hour")
        self.assertIsNone(item["hardware"]["model"])
        self.assertIsNone(item["hardware"]["accelerator_count"])
        self.assertTrue(item["extensions"]["hardware_class_not_inferred_from_sku"])
        for prefix in ("Standard_D' or true", "", "Standard_"):
            with self.assertRaises(ConnectorError):
                azure_request({"region": "eastus", "sku_prefix": prefix})

    def test_new_catalog_candidates_do_not_get_automatic_collection_rights(self):
        policies = load_policies(Path(__file__).resolve().parents[1] / "examples/source-admission.json")
        statuses = {row["source_id"]: row for row in source_status(policies)}
        for name in ("oracle", "ovhcloud", "aws_ec2", "scaleway"):
            self.assertFalse(statuses[name]["can_attempt_read"])
        self.assertTrue(statuses["aws_public_pricing"]["can_attempt_read"])
        self.assertEqual(statuses["aws_public_pricing"]["collection_parameters"]["required"], ["service", "region"])
        self.assertTrue(statuses["openrouter"]["can_attempt_read"])
        self.assertFalse(statuses["openrouter"]["auth_required"])

    def models(self, ids=("invented/alpha",), *, count=None, next_url=None, **changes):
        packet = {"data": [{"id": model_id, "name": "Invented model", "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "description": "invented text omitted", "benchmarks": {"third_party": "omitted"}, "links": {"invented": "omitted"},
            "new_field": "not retained", "pricing": {"prompt": "0.000000123456789012345678901234567890", "completion": "0",
                "request": "0.1", "overrides": [{"min_prompt_tokens": 12345, "prompt": "0.2", "future_condition": "unknown"}]}} for model_id in ids],
            "total_count": len(ids) if count is None else count, "links": {"next": next_url}}
        packet.update(changes)
        return packet

    def model_response(self, packet):
        return 200, {"content-type": "application/json"}, json.dumps(packet).encode()

    def test_openrouter_public_request_budgets_do_not_accept_auth_or_provider_endpoints(self):
        for filters in ({"limit": 101}, {"limit": True}, {"offset": -1}, {"max_pages": 4}, {"q": ""},
                        {"q": "bad\nquery"}, {"input_modalities": "unknown"}, {"output_modalities": "text,text"},
                        {"model_id": "invented/alpha"}, {"api_key": "invented"}):
            with self.subTest(filters=filters), self.assertRaises(ConnectorError):
                openrouter_request(filters)
        request = openrouter_request({"q": "invented", "limit": 2, "max_pages": 2})
        self.assertIsNone(request.spec.secret_env)
        self.assertEqual(request.spec.method, "GET")
        self.assertNotIn("max_pages", request.url)

    def test_openrouter_minimized_catalog_exact_rates_unapplied_conditions_and_explicit_zero(self):
        packet = self.models()
        response = RawResponse("openrouter", "2026-10-14T12:00:00Z", "/api/v1/models", 200, {}, json.dumps(packet).encode())
        batch = parse_openrouter(response, policy("openrouter"))
        serialized = batch.to_dict()
        self.assertEqual(serialized["observations"][0]["price"]["amount"], "0.123456789012345678901234567890")
        self.assertEqual(serialized["observations"][1]["price"]["amount"], "0")
        self.assertTrue(serialized["catalog_records"][0]["conditional_pricing_present"])
        self.assertFalse(serialized["catalog_records"][0]["qualification_verified"])
        metadata = serialized["catalog_records"][0]["metadata"]
        for field in ("description", "benchmarks", "links", "new_field"):
            self.assertNotIn(field, metadata)
        extensions = serialized["observations"][0]["extensions"]
        self.assertNotIn("source_row", extensions)
        self.assertEqual(extensions["pricing_overrides_unapplied"][0]["prompt"], "0.2")

    def test_openrouter_two_scoped_pages_complete_preserve_hashes_and_no_auth_header(self):
        first = self.models(count=2, next_url="/api/v1/models?offset=1&limit=1&q=invented")
        second = self.models(("invented/beta",), count=2)
        client = self.transport([self.model_response(first), self.model_response(second)])
        batch = collect_source("openrouter", {"openrouter": policy("openrouter")}, transport=client,
            filters={"q": "invented", "limit": 1, "max_pages": 2})
        self.assertTrue(batch.coverage["complete"])
        self.assertEqual(batch.coverage["request_count"], 2)
        self.assertEqual(len(batch.catalog_records), 2)
        self.assertEqual(len(batch.raw_metadata["pages"]), 2)
        self.assertFalse(batch.raw_metadata["raw_body_retained"])
        for args in self.calls:
            self.assertNotIn("Authorization", args[-1])

    def test_openrouter_pagination_cannot_change_scope_host_path_port_or_duplicate_keys(self):
        bad = ("https://elsewhere.example/api/v1/models?offset=1&limit=1&q=invented",
            "https://openrouter.ai:444/api/v1/models?offset=1&limit=1&q=invented",
            "/api/v1/models/invented/alpha/endpoints?offset=1&limit=1&q=invented",
            "/api/v1/models?offset=1&limit=1", "/api/v1/models?offset=1&limit=1&q=other",
            "/api/v1/models?offset=1&offset=2&limit=1&q=invented", "/api/v1/models?offset=0&limit=1&q=invented",
            "/api/v1/models?offset=2&limit=1&q=invented")
        for next_url in bad:
            client = self.transport([self.model_response(self.models(count=10, next_url=next_url))])
            with self.subTest(next_url=next_url), self.assertRaises(ConnectorError):
                collect_source("openrouter", {"openrouter": policy("openrouter")}, transport=client,
                    filters={"q": "invented", "limit": 1, "max_pages": 2})
            self.assertEqual(len(self.calls), 1)

    def test_openrouter_missing_pagination_or_budget_limit_never_claims_full_index(self):
        for packet in (self.models(links=None), self.models(count=2, next_url="/api/v1/models?offset=1&limit=1")):
            client = self.transport([self.model_response(packet)])
            batch = collect_source("openrouter", {"openrouter": policy("openrouter")}, transport=client, filters={"limit": 1})
            self.assertFalse(batch.coverage["complete"])
            self.assertFalse(batch.coverage["all_model_universe"])

    def test_openrouter_duplicate_models_bad_counts_limit_and_modality_scope_refuse(self):
        packets = [self.models(("invented/alpha", "invented/beta")), self.models(count=True), self.models(count=0), self.models(count=2)]
        a = self.models(); a["data"][0]["architecture"]["output_modalities"] = ["image"]; packets.append(a)
        for packet in packets:
            client = self.transport([self.model_response(packet)])
            with self.subTest(packet=packet.get("total_count")), self.assertRaises(ConnectorError):
                collect_source("openrouter", {"openrouter": policy("openrouter")}, transport=client, filters={"limit": 1})
        first = self.models(count=2, next_url="/api/v1/models?offset=1&limit=1")
        client = self.transport([self.model_response(first), self.model_response(self.models(count=2))])
        with self.assertRaisesRegex(ConnectorError, "duplicate_model_across_pages"):
            collect_source("openrouter", {"openrouter": policy("openrouter")}, transport=client, filters={"limit": 1, "max_pages": 2})

    def test_openrouter_retention_is_checked_before_public_network_read(self):
        denied = policy("openrouter", permissions={"observe": "PASS", "retain": "FAIL", "benchmark": "PASS", "execution": "FAIL"})
        client = self.transport([])
        with self.assertRaises(ConnectorError):
            collect_source("openrouter", {"openrouter": denied}, transport=client, filters={"limit": 1})
        self.assertEqual(self.calls, [])

    def test_aws_version_pinned_region_index_cannot_join_different_catalog_version(self):
        client = self.transport([self.index_response(), self.model_response({**payload(), "version": "20261012120000"})])
        with self.assertRaisesRegex(ConnectorError, "aws_region_price_version_mismatch"):
            collect_source("aws_public_pricing", {"aws_public_pricing": policy()}, transport=client, filters=FILTERS)

    def test_aws_transfer_origin_is_distinct_and_unlocated_meter_is_excluded(self):
        packet = payload(); attributes = packet["products"]["NEWSKU"]["attributes"]
        attributes.pop("regionCode"); attributes["fromRegionCode"] = "us-east-1"; attributes["toRegionCode"] = "eu-west-1"
        row = parse_aws(raw(packet), policy(), filters=FILTERS).catalog_records[0]
        self.assertEqual(row["native_region_basis"], "published_transfer_from_region_code")
        self.assertEqual(row["extensions"]["product_attributes"]["toRegionCode"], "eu-west-1")
        attributes["fromRegionCode"] = ""
        attributes["toRegionCode"] = ""
        batch = parse_aws(raw(packet), policy(), filters=FILTERS)
        self.assertEqual(batch.catalog_records, ())
        self.assertFalse(batch.coverage["complete"])
        self.assertEqual(batch.coverage["excluded_terms"][0]["reason"], "native_meter_region_unknown")

    def test_aws_traversal_budgets_apply_before_optional_sku_selection(self):
        from unittest.mock import patch
        packet = payload()
        dimension = packet["terms"]["OnDemand"]["NEWSKU"]["NEWSKU.TERM"]["priceDimensions"]["NEWSKU.TERM.RATE"]
        dimension["pricePerUnit"]["EUR"] = "0.2"
        with patch("compute_pricing.control.connectors.aws.MAX_TARIFFS", 1), self.assertRaisesRegex(ConnectorError, "aws_tariff_budget_exceeded"):
            parse_aws(raw(packet), policy(), filters={**FILTERS, "sku": "MISSING"})
        packet = payload(); packet["products"]["NEWSKU"]["attributes"] = {"regionCode": "us-east-1", **{str(n): "x" for n in range(128)}}
        with self.assertRaisesRegex(ConnectorError, "aws_product_attributes_invalid"):
            parse_aws(raw(packet), policy(), filters=FILTERS)

    def test_openrouter_invalid_model_keeps_technical_metadata_but_no_partial_or_zero_rates(self):
        for field, value in (("prompt", "-1"), ("completion", "-0.5"), ("request", None), ("input_cache_read", True),
                             ("image", "not-a-rate"), ("new_native_price_dimension", "-4")):
            packet = self.models(("invented/valid", "invented/unpriced"))
            packet["data"][1]["context_length"] = 12345
            packet["data"][1]["pricing"][field] = value
            response = RawResponse("openrouter", "2026-10-14T12:00:00Z", "/api/v1/models", 200, {}, json.dumps(packet).encode())
            with self.subTest(field=field):
                batch = parse_openrouter(response, policy("openrouter"))
                self.assertEqual(len(batch.observations), 2)
                self.assertTrue(all(row["hardware"]["model"] == "invented/valid" for row in batch.observations))
                self.assertEqual(batch.observations[0]["price"]["amount"], "0.123456789012345678901234567890")
                model = batch.catalog_records[1]
                self.assertEqual(model["metadata"]["context_length"], 12345)
                self.assertIsNone(model["metadata"]["pricing"])
                self.assertFalse(model["price_eligible"])
                self.assertEqual(model["price_status"], "unpriced_invalid_advertised_dimensions")
                self.assertEqual(model["invalid_dimensions"], [{"dimension": field, "code": "invalid_price"}])
                self.assertEqual(batch.coverage["invalid_price_model_count"], 1)
                self.assertFalse(batch.coverage["price_coverage_complete"])
                if value in ("-1", "-0.5", "-4", "not-a-rate"):
                    self.assertNotIn(json.dumps(value), json.dumps(model))

    def test_openrouter_invalid_conditional_rate_holds_all_model_rates(self):
        for override in ({"min_prompt_tokens": 12345, "prompt": "-1"}, {"utc_start": 1, "request": "Infinity"},
                         {"future_condition": "unapplied", "input_cache_write": None}, "not-an-override"):
            packet = self.models(); packet["data"][0]["pricing"]["overrides"] = [override]
            response = RawResponse("openrouter", "2026-10-14T12:00:00Z", "/api/v1/models", 200, {}, json.dumps(packet).encode())
            with self.subTest(override=override):
                batch = parse_openrouter(response, policy("openrouter"))
                self.assertEqual(batch.observations, ())
                self.assertIsNone(batch.catalog_records[0]["metadata"]["pricing"])
                self.assertFalse(batch.catalog_records[0]["price_eligible"])
                self.assertEqual(batch.coverage["invalid_price_dimension_count"], 1)
        packet = self.models(); packet["data"][0]["pricing"]["overrides"] = None
        response = RawResponse("openrouter", "2026-10-14T12:00:00Z", "/api/v1/models", 200, {}, json.dumps(packet).encode())
        self.assertEqual(parse_openrouter(response, policy("openrouter")).observations, ())

    def test_openrouter_missing_rate_is_unknown_and_explicit_zero_is_an_observation(self):
        packet = self.models(("invented/missing", "invented/zero", "invented/partial"))
        packet["data"][0]["pricing"] = {}
        packet["data"][1]["pricing"] = {"prompt": "0", "completion": "0"}
        packet["data"][2]["pricing"] = {"prompt": "0.1"}
        response = RawResponse("openrouter", "2026-10-14T12:00:00Z", "/api/v1/models", 200, {}, json.dumps(packet).encode())
        batch = parse_openrouter(response, policy("openrouter"))
        self.assertEqual(len(batch.observations), 3)
        self.assertEqual([row["price"]["amount"] for row in batch.observations], ["0", "0", "100000"])
        self.assertEqual([row["price_status"] for row in batch.catalog_records], ["unpriced_missing_token_rates", "advertised_token_rates", "partial_token_rates"])
        self.assertEqual(batch.coverage["models_without_token_rates"], 1)
        self.assertEqual(batch.coverage["models_with_partial_token_rates"], 1)
        self.assertFalse(batch.coverage["price_coverage_complete"])

    def test_openrouter_catalog_completion_and_price_completion_are_distinct(self):
        packet = self.models(("invented/valid", "invented/unpriced")); packet["data"][1]["pricing"]["prompt"] = "-1"
        client = self.transport([self.model_response(packet)])
        batch = collect_source("openrouter", {"openrouter": policy("openrouter")}, transport=client, filters={"limit": 2})
        self.assertTrue(batch.coverage["complete"])
        self.assertFalse(batch.coverage["price_coverage_complete"])
        self.assertEqual(batch.coverage["rows_received"], 2)
        self.assertEqual(batch.coverage["models_with_token_rates"], 1)
        self.assertEqual(batch.coverage["models_without_token_rates"], 1)
        self.assertEqual(batch.coverage["invalid_price_model_count"], 1)
        self.assertEqual(batch.coverage["price_exclusions"][0]["model_id"], "invented/unpriced")

    def test_openrouter_structural_record_identity_or_pricing_container_error_still_fails_batch(self):
        for update in ({"id": None}, {"pricing": []}, {"pricing": None}):
            packet = self.models(("invented/valid", "invented/invalid")); packet["data"][1].update(update)
            response = RawResponse("openrouter", "2026-10-14T12:00:00Z", "/api/v1/models", 200, {}, json.dumps(packet).encode())
            with self.subTest(update=update), self.assertRaisesRegex(ConnectorError, "invalid_model_catalog_entry"):
                parse_openrouter(response, policy("openrouter"))

    def test_openrouter_scaled_output_precision_overflow_quarantines_only_affected_model(self):
        # Source rate fits 128 characters, but multiplying the unit by one
        # million produces 134 characters. No live values are used here.
        huge = "1" + "0" * 127
        for dimension in ("prompt", "completion", "conditional_prompt"):
            packet = self.models(("invented/healthy", "invented/oversized"))
            packet["data"][0]["pricing"] = {"prompt": "0.000001", "completion": "0.000002"}
            packet["data"][1]["pricing"] = {"prompt": "0", "completion": "0"}
            field = "prompt" if dimension == "conditional_prompt" else dimension
            if dimension == "conditional_prompt":
                packet["data"][1]["pricing"]["overrides"] = [{"min_prompt_tokens": 12345, "prompt": huge}]
            else:
                packet["data"][1]["pricing"][field] = huge
            response = RawResponse("openrouter", "2026-10-14T12:00:00Z", "/api/v1/models", 200, {}, json.dumps(packet).encode())
            with self.subTest(dimension=dimension):
                batch = parse_openrouter(response, policy("openrouter"))
                self.assertEqual([row["price"]["amount"] for row in batch.observations], ["1", "2"])
                self.assertTrue(all(row["hardware"]["model"] == "invented/healthy" for row in batch.observations))
                model = batch.catalog_records[1]
                self.assertFalse(model["price_eligible"])
                self.assertIsNone(model["metadata"]["pricing"])
                expected_dimension = "overrides[0].prompt" if dimension == "conditional_prompt" else dimension
                self.assertEqual(model["invalid_dimensions"], [{"dimension": expected_dimension, "code": "numeric_precision_limit"}])
                self.assertEqual(batch.coverage["invalid_price_model_count"], 1)


if __name__ == "__main__":
    unittest.main()
