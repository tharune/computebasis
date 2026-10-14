"""Invented domain examples; no source records or live calls."""
import sys
import unittest
from dataclasses import FrozenInstanceError, fields
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compute_pricing.control.domain import (
    FeatureDefinition, FeatureRegistry, MoneyRate, ValidationError, admission_blockers, exact_decimal, parse_feature_observation,
    parse_market_observation, parse_policy_snapshot,
    parse_pricing_request, parse_record, utc_instant,
)
from compute_pricing.control.domain.contracts import RECORDS
from compute_pricing.control.domain.generate import json_schema, schema_text, typescript_text
from compute_pricing.control.domain.spec import SPECS


def observation():
    return {
        "id": "observation:example-a", "source_id": "source:example", "source_version": "2026-01-01",
        "kind": "listing_ask", "price_side": "ask", "offer_id": "offer:example-a", "lot_id": "lot:example-a",
        "provider_group_id": "group:example-a", "price": {"amount": "1.75", "currency": "USD", "unit": "node_hour"},
        "hardware": {"model": "example-gpu", "accelerator_count": "2", "memory_gib": "24"},
        "region": {"country_code": "US"}, "quantity": "3", "starts_at": "2026-01-02T00:00:00Z",
        "ends_at": "2026-01-09T00:00:00Z", "observed_at": "2026-01-01T12:00:00Z",
        "ingested_at": "2026-01-01T12:00:01Z", "expires_at": "2026-01-01T13:00:00Z", "status": "verified",
        "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "UNKNOWN", "verified_by": "review:example"},
    }


def policy():
    return {"policy_id": "policy:example", "version": "1.0.0", "model_version": "normalization-v1", "registry_version": "1.0.0", "effective_at": "2026-01-01T00:00:00Z"}


def feature():
    return {"feature_id": "availability", "value": "0.985", "unit": "fraction", "status": "known", "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2026-01-02T00:00:00Z"}


NOW = "2026-01-01T12:05:00Z"


class DomainV1Tests(unittest.TestCase):
    def test_exact_decimal_precision_and_invalid_financial_types(self):
        number = "12345678901234567890.12345678901234567890123456789"
        self.assertEqual(exact_decimal(number), Decimal(number))
        for raw in (1, 1.1, True, None, "1e2", "Infinity", "NaN", ".5", "01", " 1.2", "1."):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                MoneyRate(raw, "USD", "gpu_hour")
        for raw in ("-1", "-0.0"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                MoneyRate(raw, "USD", "gpu_hour")
        self.assertEqual(MoneyRate("0", "USD", "gpu_hour").amount, "0")

    def test_units_and_currency_are_explicit_boundaries(self):
        for currency, unit in (("usd", "gpu_hour"), ("US", "gpu_hour"), ("USD", "USD/GPU-hour"), ("USD", "hour")):
            with self.subTest(currency=currency, unit=unit), self.assertRaises(ValidationError):
                MoneyRate("1", currency, unit)
        self.assertNotEqual(MoneyRate("1", "USD", "node_hour"), MoneyRate("1", "USD", "gpu_hour"))
        raw = observation()
        raw["quantity_unit"] = "node"
        parsed = parse_market_observation(raw)
        self.assertEqual(parsed.quantity_unit, "node")
        self.assertNotIn("quantity_unit", parsed.extensions)
        with self.assertRaises(ValidationError):
            parse_market_observation({**raw, "quantity_unit": "hour"})

    def test_round_trip_preserves_null_zero_and_dynamic_fields(self):
        raw = observation()
        raw["configuration"] = {"ram_gib": "0", "new_topology": {"links": ["fabric-a"]}}
        raw["future_column"] = {"raw_value": 7.5, "unit": "vendor-specific"}
        parsed = parse_market_observation(raw)
        self.assertIsNone(parsed.configuration.storage_gib)
        self.assertEqual(parsed.configuration.ram_gib, "0")
        self.assertEqual(parsed.configuration.extensions["new_topology"]["links"], ("fabric-a",))
        self.assertEqual(parsed.extensions["future_column"]["raw_value"], 7.5)
        self.assertNotIn("future_column", parsed.to_dict())
        self.assertEqual(parse_market_observation(parsed.to_dict()), parsed)
        self.assertEqual(parsed.admission_blockers(NOW), ())

    def test_extra_fields_are_preserved_not_applied_or_overwritten(self):
        raw = observation()
        raw["price_multiplier"] = "0.001"
        parsed = parse_market_observation(raw)
        self.assertEqual(parsed.price.amount, "1.75")
        self.assertEqual(parsed.extensions["price_multiplier"], "0.001")
        raw["extensions"] = {"price_multiplier": "2"}
        with self.assertRaises(ValidationError):
            parse_market_observation(raw)

    def test_nonfinite_or_non_json_extension_values_reject(self):
        for value in (float("nan"), float("inf"), Decimal("2"), {1: "wrong-key"}):
            raw = observation()
            raw["extensions"] = {"unregistered": value}
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_market_observation(raw)

    def test_records_and_nested_values_are_immutable(self):
        parsed = parse_market_observation(observation())
        with self.assertRaises(FrozenInstanceError):
            parsed.id = "replacement"
        with self.assertRaises(TypeError):
            parsed.extensions["added"] = "1"
        snapshot = parse_policy_snapshot({**policy(), "parameters": {"weights": {"a": "1"}}})
        with self.assertRaises(TypeError):
            snapshot.parameters["weights"]["a"] = "2"
        encoded = snapshot.to_dict()
        encoded["parameters"]["weights"]["a"] = "3"
        self.assertEqual(snapshot.parameters["weights"]["a"], "1")

    def test_canonical_ids_utc_calendar_and_versions(self):
        for identity in ("UPPER", "bad id", "../escape", "foo--bar"):
            raw = observation()
            raw["id"] = identity
            with self.subTest(identity=identity), self.assertRaises(ValidationError):
                parse_market_observation(raw)
        for timestamp in ("2026-02-30T12:00:00Z", "2026-01-01T12:00:00+00:00", "2026-01-01", "2026-01-01T12:00:60Z"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValidationError):
                utc_instant(timestamp)
        raw = observation()
        raw["schema_version"] = "2.0.0"
        with self.assertRaises(ValidationError):
            parse_market_observation(raw)

    def test_invalid_ordered_intervals_and_future_source_time(self):
        cases = (("observed_at", "2026-01-01T12:00:02Z"), ("ends_at", "2026-01-01T00:00:00Z"), ("expires_at", "2026-01-01T12:00:00Z"))
        for key, value in cases:
            raw = observation()
            raw[key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                parse_market_observation(raw)
        raw = observation()
        raw["hardware"]["accelerator_count"] = "1.5"
        with self.assertRaises(ValidationError):
            parse_market_observation(raw)

    def test_missing_critical_terms_return_blockers_without_defaults(self):
        raw = observation()
        for key in ("price", "hardware", "rights", "source_version", "expires_at"):
            raw.pop(key)
        parsed = parse_market_observation(raw)
        self.assertIsNone(parsed.price)
        blockers = parsed.admission_blockers(NOW)
        self.assertIn("missing_critical:price", blockers)
        self.assertIn("missing_critical:hardware.model", blockers)
        self.assertIn("unverified_benchmark_permission", blockers)
        self.assertIn("missing_expiry", blockers)

    def test_permission_claims_do_not_grant_scopes_or_execution(self):
        raw = observation()
        raw["rights"] = {"status": "allowed"}
        parsed = parse_market_observation(raw)
        self.assertEqual(parsed.rights.benchmark, "UNKNOWN")
        self.assertIn("unverified_benchmark_permission", parsed.admission_blockers(NOW))
        raw["rights"] = {**observation()["rights"], "execution": "PASS"}
        raw["kind"] = "firm_supplier_rfq"
        parsed = parse_market_observation(raw)
        self.assertEqual(parsed.admission_blockers(NOW), ())
        self.assertIn("firm_pricing_review_not_implemented", parsed.admission_blockers(NOW, purpose="firm"))
        raw["rights"]["observe"] = "UNKNOWN"
        self.assertIn("unverified_observation_permission", parse_market_observation(raw).admission_blockers(NOW, purpose="indicative"))

    def test_indicative_admission_keeps_claimed_capacity_status(self):
        raw = observation()
        raw.update(kind="aggregate_advertised_index", price_side="mark", status="claimed")
        parsed = parse_market_observation(raw)
        self.assertEqual(parsed.admission_blockers(NOW, purpose="indicative"), ())
        self.assertEqual(parsed.status, "claimed")
        self.assertIn("unverified_observation", parsed.admission_blockers(NOW))
        self.assertIn("claimed_data_not_verified_asset_capacity", parsed.admission_warnings(NOW))
        self.assertIn("aggregate_advertised_prices_not_executable_offers", parsed.admission_warnings(NOW))
        raw["rights"]["benchmark"] = "UNKNOWN"
        self.assertIn("unverified_benchmark_permission", parse_market_observation(raw).admission_blockers(NOW, purpose="indicative"))

    def test_non_compute_marks_and_missing_node_count_do_not_enter_index(self):
        for kind in ("model_token_price", "financial_future_mark", "event_contract_price"):
            raw = observation()
            raw["kind"] = kind
            self.assertIn("incompatible_compute_benchmark_kind", parse_market_observation(raw).admission_blockers(NOW))
        for count in (None, "0"):
            raw = observation()
            raw["hardware"]["accelerator_count"] = count
            self.assertIn("missing_positive_node_accelerator_count", parse_market_observation(raw).admission_blockers(NOW))

    def test_freshness_recomputed_at_each_as_of(self):
        parsed = parse_market_observation(observation())
        self.assertEqual(parsed.admission_blockers(NOW), ())
        self.assertIn("expired_observation", parsed.admission_blockers("2026-01-01T13:00:00Z"))
        self.assertIn("observation_not_yet_available", parsed.admission_blockers("2026-01-01T12:00:00Z"))
        raw = observation()
        raw["rights"]["expires_at"] = "2026-01-01T12:04:59Z"
        self.assertIn("expired_permission", parse_market_observation(raw).admission_blockers(NOW))

    def test_optional_missing_region_is_policy_scoped(self):
        raw = observation()
        raw.pop("region")
        parsed = parse_market_observation(raw)
        self.assertEqual(parsed.admission_blockers(NOW), ())
        scoped = parse_policy_snapshot({**policy(), "critical_market_fields": ["region.country_code"]})
        self.assertIn("missing_critical:region.country_code", admission_blockers(parsed, NOW, policy=scoped))
        for path in ("unknown.factor", "extensions.factor"):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                parse_policy_snapshot({**policy(), "critical_market_fields": [path]})

    def test_feature_requires_registration_and_exact_unit(self):
        definition = FeatureDefinition("availability", "decimal", "loss", "availability-v1", unit="fraction", minimum="0", maximum="1")
        registry = FeatureRegistry("1.0.0", (definition,))
        activated = registry.activate(parse_feature_observation(feature()), as_of=NOW)
        self.assertEqual(activated.value, Decimal("0.985"))
        self.assertEqual(activated.owning_path, "loss")
        for updates in ({"unit": "percent"}, {"value": "98.5"}, {"value": "1e-2"}, {"feature_id": "unregistered"}, {"owner_model": "other-model"}, {"owning_path": "price"}):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                registry.activate(parse_feature_observation({**feature(), **updates}), as_of=NOW)

    def test_feature_missing_and_stale_never_activate(self):
        definition = FeatureDefinition("availability", "decimal", "loss", "availability-v1", unit="fraction", required=True)
        registry = FeatureRegistry("1.0.0", (definition,))
        self.assertEqual(registry.required_blockers((), as_of=NOW), ("missing_required_feature:availability",))
        for updates in ({"status": "missing", "value": None}, {"status": "stale"}, {"valid_until": "2026-01-01T12:05:00Z"}, {"valid_from": None}):
            parsed = parse_feature_observation({**feature(), **updates})
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                registry.activate(parsed, as_of=NOW)
            self.assertEqual(registry.required_blockers((parsed,), as_of=NOW), ("unusable_required_feature:availability",))
        with self.assertRaises(ValidationError):
            parse_feature_observation({**feature(), "status": "missing"})

    def test_registry_updates_require_new_version(self):
        one = FeatureDefinition("availability", "decimal", "loss", "availability-v1")
        two = FeatureDefinition("privacy", "boolean", "constraint", "privacy-v1")
        registry = FeatureRegistry("1.0.0", (one,))
        with self.assertRaises(ValidationError):
            registry.with_definition(two, version="1.0.0")
        updated = registry.with_definition(two, version="1.1.0")
        self.assertEqual(len(registry.definitions), 1)
        self.assertEqual(len(updated.definitions), 2)
        with self.assertRaises(ValidationError):
            FeatureRegistry("1.0.0", (one, one))
        self.assertEqual(registry.required_blockers((), as_of=NOW, policy=parse_policy_snapshot({**policy(), "registry_version": "1.1.0"})), ("registry_version_mismatch",))

    def test_boolean_integer_and_categorical_features(self):
        cases = (("privacy", "boolean", True, "true"), ("rank", "integer", "2", "2.5"), ("mode", "string", "dedicated", "shared"))
        for name, kind, good, bad in cases:
            definition = FeatureDefinition(name, kind, "constraint", "qualification-v1", allowed_values=("dedicated",) if kind == "string" else ())
            registry = FeatureRegistry("1.0.0", (definition,))
            raw = {**feature(), "feature_id": name, "unit": None, "value": good}
            self.assertEqual(registry.activate(parse_feature_observation(raw), as_of=NOW).value, int(good) if kind == "integer" else good)
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                registry.activate(parse_feature_observation({**raw, "value": bad}), as_of=NOW)

    def test_pricing_request_versions_duplicates_and_source_lineage(self):
        raw = {"request_id": "request:example", "as_of": NOW, "observations": [observation()], "policy": policy()}
        parsed = parse_pricing_request(raw)
        self.assertEqual(parsed.observations[0].price.currency, "USD")
        cases = (("observations", [observation(), observation()]), ("features", [feature(), feature()]), ("schema_version", "2.0.0"))
        for key, value in cases:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                parse_pricing_request({**raw, key: value})
        normalized = {"observation_id": "observation:example-a", "source_id": "source:example", "source_price": observation()["price"], "normalized_price": {"amount": "0.875", "currency": "USD", "unit": "gpu_hour"}, "normalization_steps": ["node_hour_divided_by_accelerator_count_2"], "model_version": "normalization-v1", "policy_version": "1.0.0"}
        self.assertEqual(parse_pricing_request({**raw, "normalized_prices": [normalized]}).normalized_prices[0].normalized_price.amount, "0.875")
        for updates in ({"policy_version": "1.1.0"}, {"source_id": "other:source"}, {"observation_id": "other:observation"}, {"source_price": {"amount": "9", "currency": "USD", "unit": "node_hour"}}):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                parse_pricing_request({**raw, "normalized_prices": [{**normalized, **updates}]})

    def test_policy_must_be_active_at_request_as_of(self):
        raw = {"request_id": "request:example", "as_of": NOW, "observations": [], "policy": policy()}
        for updates in ({"effective_at": "2026-01-02T00:00:00Z"}, {"expires_at": NOW}):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                parse_pricing_request({**raw, "policy": {**policy(), **updates}})

    def test_evidence_scope_status_and_hash_preserved(self):
        raw = {"id": "evidence:example", "source_id": "source:example", "accessed_at": NOW, "artifact_sha256": "ab" * 32, "status": "claimed", "scope": ["price"], "vendor_extra": {"unreviewed": True}}
        parsed = parse_record("EvidenceRef", raw)
        self.assertEqual(parsed.status, "claimed")
        self.assertIsNone(parsed.verifier)
        self.assertEqual(parsed.extensions["vendor_extra"]["unreviewed"], True)
        with self.assertRaises(ValidationError):
            parse_record("EvidenceRef", {**raw, "artifact_sha256": "bad-hash"})

    def test_generated_schema_and_types_match_single_contract_source(self):
        self.assertEqual((ROOT / "docs/contracts/domain-v1.schema.json").read_text(), schema_text())
        self.assertEqual((ROOT / "docs/contracts/domain-v1.types.txt").read_text(), typescript_text())
        self.assertEqual(json_schema()["$defs"], SPECS)
        for name, record in RECORDS.items():
            self.assertEqual({item.name for item in fields(record)}, set(SPECS[name]["properties"]))
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json_schema()
        Draft202012Validator.check_schema(schema)
        request = parse_pricing_request({"request_id": "request:example", "as_of": NOW, "observations": [observation()], "policy": policy()})
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(request.to_dict())


if __name__ == "__main__":
    unittest.main()
