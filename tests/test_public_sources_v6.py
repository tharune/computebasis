"""Invented public-recipe/native-service scope cases; no requests or real rows."""
import datetime as dt
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.connectors import ConnectorError, ReadOnlyTransport, SourcePolicy, collect_source, load_policies, source_status
from compute_pricing.control.connectors.aws import aws_request, parse_aws
from compute_pricing.control.connectors.huggingface_catalog import catalog_request, parse_catalog
from compute_pricing.control.connectors.transport import RawResponse, ReadRequest, SOURCE_SPECS

NOW = dt.datetime(2026, 10, 14, 12, tzinfo=dt.timezone.utc)
FILTERS = {"task": "text-generation", "accelerator": "gpu", "engine": "vllm", "limit": 10}


def policy(name="huggingface_catalog", **changes):
    values = {"source_id": name, "enabled": True, "rights_status": "allowed", "rights_evidence": "invented-purpose-review",
        "permissions": {"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        "verified_by": "invented-reviewer", "max_age_s": 86400, "min_interval_s": 0}
    values.update(changes)
    return SourcePolicy(**values)


def payload():
    return {"items": [{"repoId": "invented-author/unseen-model", "modelName": "Invented unseen model", "authorName": "Invented Author",
        "license": "Invented license requires review", "task": "text-generation", "createdAt": "2026-01-01T00:00:00.000Z",
        "extra_unretained": "never-retain-invented-model-marker", "recipes": [{"publicId": "invented-new-recipe",
            "accelerator": "gpu", "engineType": "vllm", "revision": "main", "ggufFile": "invented-quantization.gguf",
            "extra_unretained": "never-retain-invented-recipe-marker"}]}]}


def raw(packet, name="huggingface_catalog"):
    return RawResponse(name, "2026-10-14T12:00:00Z", "/api/v1/catalog/list", 200, {}, json.dumps(packet).encode())


class PublicSourceV6Tests(unittest.TestCase):
    def test_catalog_request_requires_bounded_explicit_scope_and_no_account_fields(self):
        for options in (None, {}, {"limit": 10}, {**FILTERS, "limit": 101}, {**FILTERS, "limit": True},
                        {**FILTERS, "namespace": "invented"}, {**FILTERS, "accelerator": "future"},
                        {**FILTERS, "engine": "future"}, {**FILTERS, "task": "invalid"}, {**FILTERS, "search": ""}):
            with self.subTest(options=options), self.assertRaises(ConnectorError):
                catalog_request(options)
        request = catalog_request({**FILTERS, "search": "invented & unusual"})
        self.assertEqual(request.spec.method, "GET")
        self.assertIsNone(request.spec.secret_env)
        self.assertEqual(request.validate().path, "/api/v1/catalog/list")
        for path in ("/api/v1/catalog/model/invented/model/deploy", "/api/v1/catalog/recipe/invented/deploy", "/api/v1/catalog/list?token=invented"):
            with self.assertRaises(ConnectorError):
                ReadRequest(SOURCE_SPECS["huggingface_catalog"], "https://endpoints.huggingface.co" + path).validate()

    def test_dynamic_recipes_preserve_selected_facts_but_never_price_or_verify(self):
        batch = parse_catalog(raw(payload()), policy(), filters=FILTERS)
        self.assertEqual(batch.observations, ())
        self.assertFalse(batch.coverage["complete"])
        row = batch.catalog_records[0]
        self.assertEqual(row["model_id"], "invented-author/unseen-model")
        self.assertEqual(row["catalog_created_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(row["observed_at"], "2026-10-14T12:00:00Z")
        self.assertIsNone(row["price"])
        self.assertFalse(row["price_eligible"])
        self.assertFalse(row["gpu_hour_benchmark_eligible"])
        self.assertFalse(row["qualification_verified"])
        self.assertEqual(row["license_claim"], "Invented license requires review")
        recipe = row["recipes"][0]
        self.assertEqual(recipe["repository_revision"], "main")
        self.assertFalse(recipe["revision_is_immutable_commit_claim"])
        self.assertIsNone(recipe["physical_accelerator_count"])
        self.assertFalse(recipe["performance_verified"])
        self.assertFalse(recipe["execution_enabled"])
        serialized = json.dumps(batch.to_dict())
        self.assertNotIn("never-retain-invented", serialized)
        self.assertNotIn("source_row", serialized)
        self.assertFalse(batch.raw_metadata["raw_body_retained"])

    def test_recipe_commit_claim_is_distinct_from_branch_and_unknown_future_labels_remain_unqualified(self):
        packet = payload(); recipe = packet["items"][0]["recipes"][0]
        recipe.update(revision="a" * 40, accelerator="future-accelerator", engineType="future-engine")
        batch = parse_catalog(raw(packet), policy(), filters={"task": "text-generation", "limit": 1})
        item = batch.catalog_records[0]["recipes"][0]
        self.assertTrue(item["revision_is_immutable_commit_claim"])
        self.assertEqual(item["accelerator"], "future-accelerator")
        self.assertFalse(item["qualification_verified"])

    def test_model_filter_is_exact_and_nonmatching_recipes_are_explicitly_excluded(self):
        packet = payload(); packet["items"][0]["recipes"].append({"publicId": "invented-cpu-recipe", "accelerator": "cpu", "engineType": "llamacpp"})
        batch = parse_catalog(raw(packet), policy(), filters=FILTERS)
        self.assertEqual(batch.coverage["recipes_received"], 2)
        self.assertEqual(batch.coverage["recipes_selected"], 1)
        self.assertEqual(batch.coverage["recipe_exclusions"][0]["reason"], "outside_requested_recipe_scope")
        for options in ({**FILTERS, "task": "sentence-similarity"}, {**FILTERS, "license": "Different license"}):
            with self.assertRaisesRegex(ConnectorError, "response_scope_mismatch"):
                parse_catalog(raw(packet), policy(), filters=options)

    def test_duplicate_models_or_recipe_identities_and_wrong_policy_fail_closed(self):
        for kind in ("model", "recipe"):
            packet = payload()
            if kind == "model": packet["items"].append(packet["items"][0])
            else: packet["items"][0]["recipes"].append(packet["items"][0]["recipes"][0])
            with self.subTest(kind=kind), self.assertRaises(ConnectorError):
                parse_catalog(raw(packet), policy(), filters=FILTERS)
        with self.assertRaisesRegex(ConnectorError, "source_policy_mismatch"):
            parse_catalog(raw(payload()), policy("huggingface"), filters=FILTERS)

    def test_future_time_private_visibility_and_malformed_recipes_are_not_retained(self):
        updates = [{"createdAt": "2026-10-15T00:00:00Z"}, {"private": True}, {"private": "false"},
            {"recipes": {}}, {"repoId": "../invented"}, {"authorName": ""}]
        for update in updates:
            packet = payload(); packet["items"][0].update(update)
            with self.subTest(update=update), self.assertRaises(ConnectorError):
                parse_catalog(raw(packet), policy(), filters=FILTERS)
        for value in (None, [], {"items": {}}):
            with self.assertRaises(ConnectorError):
                parse_catalog(raw(value), policy(), filters=FILTERS)

    def test_recipe_and_model_budgets_are_checked_before_filter_selection(self):
        packet = payload(); packet["items"] *= 2
        with self.assertRaisesRegex(ConnectorError, "shape_or_limit"):
            parse_catalog(raw(packet), policy(), filters={**FILTERS, "limit": 1})
        packet = payload(); packet["items"][0]["recipes"] *= 65
        with self.assertRaisesRegex(ConnectorError, "recipe_shape_or_budget"):
            parse_catalog(raw(packet), policy(), filters=FILTERS)
        packet = payload(); packet["items"][0]["recipes"].append({"publicId": "invented-out-of-scope", "accelerator": "cpu", "engineType": "llamacpp"})
        with patch("compute_pricing.control.connectors.huggingface_catalog.MAX_RECIPES", 1), self.assertRaisesRegex(ConnectorError, "recipe_budget"):
            parse_catalog(raw(packet), policy(), filters=FILTERS)

    def test_controlled_anonymous_get_scope_and_retention_gate(self):
        calls = []
        def exchange(request, parts, addresses, headers):
            calls.append((request, headers))
            return 200, {"content-type": "application/json"}, json.dumps(payload()).encode()
        client = ReadOnlyTransport(clock=lambda: NOW, resolver=lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))], exchange=exchange)
        blocked = policy(permissions={"observe": "PASS", "retain": "FAIL", "benchmark": "PASS", "execution": "FAIL"})
        with self.assertRaises(ConnectorError):
            collect_source("huggingface_catalog", {"huggingface_catalog": blocked}, transport=client, filters=FILTERS)
        self.assertEqual(calls, [])
        batch = collect_source("huggingface_catalog", {"huggingface_catalog": policy()}, transport=client, filters=FILTERS)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Authorization", calls[0][1])
        self.assertEqual(batch.coverage["scope"], FILTERS)
        self.assertFalse(batch.coverage["all_model_universe"])

    def test_new_public_source_is_admitted_only_for_metadata_and_bounded_services_are_declared(self):
        policies = load_policies(Path(__file__).resolve().parents[1] / "examples/source-admission.json")
        status = {item["source_id"]: item for item in source_status(policies)}
        item = status["huggingface_catalog"]
        self.assertTrue(item["can_attempt_read"])
        self.assertFalse(item["auth_required"])
        self.assertFalse(item["collection_parameters"]["price_eligible"])
        self.assertEqual(policies["huggingface_catalog"].permissions["execution"], "FAIL")
        self.assertIn("AWSLambda", status["aws_public_pricing"]["collection_parameters"]["approved_services"])
        for source in ("oracle", "ovhcloud", "aws_ec2", "scaleway", "kalshi"):
            self.assertFalse(status[source]["can_attempt_read"])

    def test_new_aws_service_native_meters_remain_separate_from_gpu_rates(self):
        for service, unit in (("AWSLambda", "GB-Second"), ("AmazonS3", "GB-Mo"), ("AmazonSageMaker", "Hrs")):
            options = {"service": service, "region": "us-east-1"}
            self.assertIn(service + "/current/region_index.json", aws_request(options).url)
            dimension = {"rateCode": "INVENTEDSKU.TERM.RATE", "unit": unit, "beginRange": "0", "endRange": "Inf",
                "pricePerUnit": {"USD": "0.012345678901234567890123456789"}}
            term = {"sku": "INVENTEDSKU", "offerTermCode": "TERM", "effectiveDate": "2026-10-01T00:00:00Z",
                "priceDimensions": {"INVENTEDSKU.TERM.RATE": dimension}}
            packet = {"formatVersion": "v1.0", "offerCode": service, "version": "20261001000000", "publicationDate": "2026-10-01T00:00:00Z",
                "products": {"INVENTEDSKU": {"sku": "INVENTEDSKU", "attributes": {"servicecode": service, "regionCode": "us-east-1"}}},
                "terms": {"OnDemand": {"INVENTEDSKU": {"INVENTEDSKU.TERM": term}}}}
            batch = parse_aws(raw(packet, "aws_public_pricing"), policy("aws_public_pricing"), filters=options)
            self.assertEqual(batch.observations, ())
            self.assertEqual(batch.catalog_records[0]["native_price"]["unit"], unit)
            self.assertEqual(batch.catalog_records[0]["native_price"]["amount"], "0.012345678901234567890123456789")
            self.assertFalse(batch.catalog_records[0]["gpu_hour_benchmark_eligible"])

    def test_response_length_budget_keeps_specific_safe_code_without_reading_body(self):
        request = catalog_request(FILTERS)
        for header, code in (("1025", "response_too_large"), ("-1", "invalid_content_length"), ("bad", "invalid_content_length")):
            class FakeConnection:
                sock = None
                closed = False
                def request(self, *args, **kwargs): pass
                def getresponse(self): return self
                def getheaders(self): return [("content-length", header)]
                def read1(self, size): raise AssertionError("Refused length must not read response body")
                def close(self): self.closed = True
            connection = FakeConnection()
            with self.subTest(header=header), patch("compute_pricing.control.connectors.transport._PinnedHTTPSConnection", return_value=connection):
                with self.assertRaisesRegex(ConnectorError, "^" + code + "$"):
                    ReadOnlyTransport(max_bytes=1024)._exchange(request, request.validate(), ["93.184.216.34"], {})
                self.assertTrue(connection.closed)

    def test_regional_transfer_meters_may_reference_region_as_origin_or_destination(self):
        from test_public_sources_v4 import payload as aws_packet
        for origin, destination, basis in (("us-east-1", "eu-west-1", "published_transfer_from_region_code"),
                                          ("eu-west-1", "us-east-1", "published_transfer_to_region_code"),
                                          ("", "us-east-1", "published_transfer_to_region_code")):
            packet = aws_packet(service="AmazonS3", unit="GB")
            attributes = packet["products"]["NEWSKU"]["attributes"]
            attributes.pop("regionCode"); attributes.update(fromRegionCode=origin, toRegionCode=destination)
            batch = parse_aws(raw(packet, "aws_public_pricing"), policy("aws_public_pricing"), filters={"service": "AmazonS3", "region": "us-east-1"})
            row = batch.catalog_records[0]
            self.assertEqual(row["native_region_basis"], basis)
            self.assertEqual(row["extensions"]["product_attributes"]["fromRegionCode"], origin)
            self.assertEqual(row["extensions"]["product_attributes"]["toRegionCode"], destination)
            self.assertFalse(row["region_is_physical_delivery_claim"])
            self.assertEqual(row["native_price"]["unit"], "GB")
        packet = aws_packet(service="AmazonS3"); attributes = packet["products"]["NEWSKU"]["attributes"]
        attributes.pop("regionCode"); attributes.update(fromRegionCode="eu-west-1", toRegionCode="us-west-2")
        with self.assertRaisesRegex(ConnectorError, "aws_response_scope_mismatch"):
            parse_aws(raw(packet, "aws_public_pricing"), policy("aws_public_pricing"), filters={"service": "AmazonS3", "region": "us-east-1"})


if __name__ == "__main__":
    unittest.main()
