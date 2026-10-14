"""Independent retained-reference fixtures test permission, cohort and origin."""
from copy import deepcopy
from dataclasses import replace
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compute_pricing.control.api.market_reference import evaluate_market_reference, market_reference_contract
from compute_pricing.control.connectors import SourcePolicy
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.policies.repository import PolicyRepository
from compute_pricing.control.reporting import SnapshotStore, SnapshotStoreError


NOW = dt.datetime(2042, 4, 19, 10, tzinfo=dt.timezone.utc)


def z(instant):
    return instant.isoformat().replace("+00:00", "Z")


def permission(source):
    return SourcePolicy(source, enabled=True, rights_status="allowed", rights_evidence="invented-fixture-permission",
        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        verified_by="review:invented-reference", max_age_s=7200)


def aggregate(source, price, identity=None):
    return {"id": identity or "reference:" + source, "source_id": source, "source_version": "invented-feed/1",
        "kind": "aggregate_advertised_index", "price_side": "ask", "status": "claimed",
        "price": {"amount": price, "currency": "USD", "unit": "gpu_hour"},
        "hardware": {"model": "invented-reference-device-z"}, "observed_at": z(NOW - dt.timedelta(minutes=5)),
        "ingested_at": z(NOW - dt.timedelta(minutes=1)), "expires_at": z(NOW + dt.timedelta(minutes=30)),
        "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS",
                   "execution": "FAIL", "verified_by": "review:invented-reference"},
        "extensions": {"billing_type": "ON_DEMAND", "reservation_months": None, "period": "invented-published-window",
                       "price_statistic": "invented-published-ask-statistic"}}


def aggregate_cohort():
    return {"scope": "aggregate_reference", "hardware_model": "invented-reference-device-z", "hardware_memory_gib": None,
        "currency": "USD", "native_unit": "gpu_hour", "price_side": "ask", "country_code": None,
        "configuration": {}, "starts_at": None, "ends_at": None, "gpu_count": None,
        "aggregate_terms": {"billing_type": "ON_DEMAND", "reservation_months": None},
        "observation_period": "invented-published-window"}


def physical(source):
    row = aggregate(source, "16")
    row.update(kind="listing_ask", offer_id="offer:invented-node", lot_id="lot:invented-node", provider_group_id="group:invented-node",
        hardware={"model": "invented-reference-device-z", "accelerator_count": "8", "memory_gib": "80"},
        region={"country_code": "CA"}, quantity="1", quantity_unit="node",
        configuration={"cpu_cores": "24", "ram_gib": "128", "storage_gib": "960", "network_gbps": "10",
                       "interconnect": "invented-fabric", "privacy_class": "isolated", "tenancy": "exclusive"},
        starts_at="2042-04-20T00:00:00Z", ends_at="2042-04-21T00:00:00Z", extensions={})
    row["price"]["unit"] = "node_hour"
    return row


def physical_cohort():
    row = physical("sample_a")
    return {"scope": "physical_offer", "hardware_model": row["hardware"]["model"], "hardware_memory_gib": "80",
        "currency": "USD", "native_unit": "node_hour", "price_side": "ask", "country_code": "CA",
        "configuration": deepcopy(row["configuration"]), "starts_at": row["starts_at"], "ends_at": row["ends_at"],
        "gpu_count": "8", "aggregate_terms": None, "observation_period": None}


class RetainedReferenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "retained.sqlite"
        self.store, self.repository = SnapshotStore(self.path), PolicyRepository(self.path)
        self.sources = ("sample_a", "sample_b", "sample_c")
        self.policies = {source: permission(source) for source in self.sources}
        self.plan = [{"source_id": source, "filters": {"partition": "invented"}} for source in self.sources]
        self.saved = self.save_policy()
        self.origins = {source: self.retain(source, [aggregate(source, price)]) for source, price in zip(self.sources, ("5", "9", "13"))}

    def tearDown(self):
        self.folder.cleanup()

    def save_policy(self, *, version="1.0.0", previous=None, minimum=1, expiry=None):
        document = {"policy": {"policy_id": "policy:invented-reference", "version": version,
            "model_version": "inverse-linear/1.0.0", "registry_version": "1.0.0", "effective_at": z(NOW - dt.timedelta(days=1)),
            "expires_at": expiry, "parameters": {"benchmark": {"estimator": "weighted_median",
                "max_source_share": "1", "max_provider_share": "1", "min_observations": minimum,
                "min_sources": minimum, "min_provider_groups": minimum,
                "source_rules": {source: {"enabled": True, "quality": "1", "max_age_hours": "1", "half_life_hours": "1"}
                                 for source in self.policies}}}}, "feature_definitions": [], "notes": "Independent invented reference policy"}
        return self.repository.save(document, expected_revision=previous)

    def retain(self, source, rows, *, coverage=None, catalog=None, captured=None, filters=None):
        return self.store.put(kind="market_collection", input_payload={"source_id": source,
            "filters": {"partition": "invented"} if filters is None else filters},
            output_payload={"source_id": source, "observations": rows, "catalog_records": catalog or [],
                "raw_metadata": {"captured_at": z(NOW - dt.timedelta(minutes=1)) if captured is None else captured},
                "coverage": {"complete": True} if coverage is None else coverage, "execution_enabled": False},
            versions={"adapter": "invented/1"}).digest

    def request(self, *, one=False, cohort=None):
        return {"source_scopes": deepcopy(self.plan[:1] if one else self.plan), "policy_revision": self.saved["revision"],
                "cohort": aggregate_cohort() if cohort is None else cohort}

    def evaluate(self, request=None):
        return evaluate_market_reference(self.request() if request is None else request, store=self.store,
            policies=self.policies, repository=self.repository, collection_plan=self.plan, clock=lambda: NOW)

    def test_server_bound_weighted_median_origin_and_same_side_range_no_fabricated_quotes(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "indicative_reference")
        self.assertEqual(result["reference"]["amount"], "9")
        self.assertEqual(result["comparable_price_range"]["range"], "8")
        self.assertTrue(result["source_evidence_eligible"])
        self.assertEqual({row["snapshot_id"] for row in result["eligible"]}, set(self.origins.values()))
        self.assertEqual(len(result["eligible"]), 3)
        for field in ("physical_price_eligible", "firm_price_eligible", "inventory_verified", "execution_enabled"):
            self.assertFalse(result[field])
        for field in ("bid", "ask", "midpoint", "spread"):
            self.assertIsNone(result[field])
        self.assertFalse(result["coverage"]["market_complete"])

    def test_revocation_and_late_missing_or_stale_scope_cannot_leave_partial_price(self):
        self.policies["sample_c"] = replace(self.policies["sample_c"], enabled=False)
        revoked = self.evaluate()
        self.assertEqual(revoked["status"], "held")
        self.assertIsNone(revoked["reference"])
        self.assertFalse(revoked["eligible"])
        self.assertFalse(revoked["source_evidence_eligible"])
        self.assertIn("source_disabled", revoked["scopes"][-1]["reasons"])
        self.policies["sample_c"] = permission("sample_c")
        self.retain("sample_c", [aggregate("sample_c", "13")], captured=z(NOW - dt.timedelta(hours=3)))
        stale = self.evaluate()
        self.assertIsNone(stale["reference"])
        self.assertFalse(stale["eligible"])
        self.assertIn("retained_capture_stale_or_future", stale["scopes"][-1]["reasons"])
        self.plan[-1]["filters"] = {"partition": "absent"}
        missing = self.evaluate()
        self.assertIsNone(missing["reference"])
        self.assertFalse(missing["eligible"])
        self.assertIn("latest_retained_scope_not_found", missing["scopes"][-1]["reasons"])

    def test_duplicate_retained_ids_quarantined_and_other_comparables_remain_visible(self):
        self.retain("sample_a", [aggregate("sample_a", "5", "reference:collision"),
                                  aggregate("sample_a", "500", "reference:collision")])
        result = self.evaluate()
        self.assertNotIn("sample_a", {row["source_id"] for row in result["eligible"]})
        duplicate = [row for row in result["rejected"] if "duplicate_retained_observation_id_quarantined" in row["reasons"]]
        self.assertEqual(len(duplicate), 2)
        self.assertEqual(result["reference"]["amount"], "11")

    def test_stale_expired_wrong_side_currency_model_term_period_are_rejected(self):
        for mutate, expected in (
            (lambda r: r.update(observed_at=z(NOW - dt.timedelta(hours=3))), "observation_stale_under_current_server_policy"),
            (lambda r: r.update(expires_at=z(NOW)), "expired_observation"),
            (lambda r: r.update(price_side="bid"), "price_side_not_requested"),
            (lambda r: r["price"].update(currency="EUR"), "currency_mismatch_no_implicit_fx"),
            (lambda r: r["hardware"].update(model="invented-other-device"), "hardware_mismatch"),
            (lambda r: r["extensions"].update(reservation_months=18), "aggregate_billing_or_reservation_mismatch"),
            (lambda r: r["extensions"].update(period="invented-other-window"), "measurement_period_not_requested"),
        ):
            row = aggregate("sample_a", "5"); mutate(row)
            self.retain("sample_a", [row])
            result = self.evaluate(self.request(one=True))
            self.assertIsNone(result["reference"])
            self.assertTrue(any(expected in row["reasons"] for row in result["rejected"]), result)

    def test_current_source_rule_tightening_and_permission_expiry_hold_without_rejuvenation(self):
        self.policies["sample_a"] = replace(permission("sample_a"), max_age_s=60)
        result = self.evaluate(self.request(one=True))
        self.assertIsNone(result["reference"])
        self.assertFalse(result["source_evidence_eligible"])
        self.policies["sample_a"] = replace(permission("sample_a"), expires_at=z(NOW))
        result = self.evaluate(self.request(one=True))
        self.assertIn("rights_expired", result["scopes"][0]["reasons"])

    def test_saved_policy_revision_must_be_current_and_unexpired(self):
        old = self.request()
        successor = self.save_policy(version="1.1.0", previous=self.saved["revision"])
        result = self.evaluate(old)
        self.assertIn("saved_policy_revision_is_not_current_head", result["hold_reasons"])
        self.assertIsNone(result["reference"])
        self.saved = self.save_policy(version="1.2.0", previous=successor["revision"], expiry=z(NOW))
        result = self.evaluate()
        self.assertIn("saved_policy_expired", result["hold_reasons"])
        self.assertIsNone(result["reference"])

    def test_upstream_partial_sample_is_honest_display_projection_is_held(self):
        self.retain("sample_a", [aggregate("sample_a", "5")], coverage={"complete": False, "pagination_truncated": True})
        result = self.evaluate(self.request(one=True))
        self.assertEqual(result["reference"]["amount"], "5")
        self.assertFalse(result["coverage"]["upstream_complete"])
        self.assertFalse(result["coverage"]["market_complete"])
        self.assertFalse(result["coverage"]["inputs_from_display_index"])
        self.retain("sample_a", [aggregate("sample_a", "5")], coverage={"complete": True, "display_truncated": True})
        result = self.evaluate(self.request(one=True))
        self.assertIsNone(result["reference"])
        self.assertIn("retained_display_projection_not_complete", result["scopes"][0]["reasons"])

    def test_row_cap_is_checked_before_row_parsing_without_prefix_benchmark(self):
        with patch("compute_pricing.control.api.market_reference.MAX_ROWS", 2), patch(
                "compute_pricing.control.api.market_reference.parse_market_observation", side_effect=AssertionError("must not parse over-limit rows")):
            result = self.evaluate()
        self.assertIsNone(result["reference"])
        self.assertFalse(result["eligible"])
        self.assertEqual(result["rejected"], [])
        self.assertEqual(result["coverage"]["selected_observation_count"], 3)
        self.assertEqual(result["coverage"]["not_assessed_observation_count"], 3)
        self.assertIn("selected_population_exceeds_study_limit", result["hold_reasons"])

    def test_native_node_rate_requires_exact_physical_terms_and_whole_allocation(self):
        self.retain("sample_a", [physical("sample_a")])
        request = self.request(one=True, cohort=physical_cohort())
        result = self.evaluate(request)
        self.assertEqual(result["reference"]["amount"], "2")
        self.assertEqual(result["eligible"][0]["native_price"]["unit"], "node_hour")
        self.assertEqual(result["reference"]["unit"], "gpu_hour")
        self.assertFalse(result["physical_price_eligible"])
        request["cohort"]["configuration"]["ram_gib"] = "128.0"
        self.assertEqual(self.evaluate(request)["reference"]["amount"], "2")
        for field, value, reason in (
            ("gpu_count", "4", "requested_quantity_not_whole_nodes"),
            ("ends_at", "2042-04-21T01:00:00Z", "delivery_interval_not_exact_cohort"),
            ("hardware_memory_gib", "40", "hardware_memory_unknown_or_mismatched"),
            ("native_unit", "gpu_hour", "native_unit_not_requested"),
        ):
            altered = deepcopy(request); altered["cohort"][field] = value
            result = self.evaluate(altered)
            self.assertIsNone(result["reference"])
            self.assertTrue(any(reason in item["reasons"] for item in result["rejected"]))

    def test_tokens_energy_fx_and_cloud_catalog_diagnostics_never_enter_compute_price(self):
        for index, source in enumerate(("openrouter", "energinet_day_ahead", "ecb", "azure", "gpuhunt_catalog", "gb_carbon_intensity"), 1):
            self.policies = {source: permission(source)}
            self.plan = [{"source_id": source, "filters": {}}]
            self.saved = self.save_policy(version="1.1." + str(index), previous=self.repository.head("policy:invented-reference")["revision"])
            self.retain(source, [aggregate(source, "900")], filters={})
            result = self.evaluate()
            self.assertIsNone(result["reference"])
            self.assertIn("source_role_not_compute_price_evidence", result["scopes"][0]["reasons"])

    def test_catalog_records_are_counted_but_never_used_as_observations(self):
        self.retain("sample_a", [aggregate("sample_a", "5")], catalog=[{"source_id": "sample_a", "id": "catalog:invented",
            "kind": "energy_market_reference", "price": "-900", "unit": "MWh"}])
        result = self.evaluate(self.request(one=True))
        self.assertEqual(result["reference"]["amount"], "5")
        self.assertEqual(result["coverage"]["excluded_catalog_record_count"], 1)

    def test_contract_unknowns_bad_units_client_prices_and_duplicate_scopes_fail_before_read(self):
        contract = market_reference_contract()
        self.assertIsNone(contract["template_unknown"]["policy_revision"])
        self.assertEqual(contract["template_unknown"]["source_scopes"], [])
        self.assertFalse(contract["vendor_fetch_per_request"])
        for mutate in (
            lambda p: p.update(observations=[aggregate("sample_a", "500")]),
            lambda p: p["cohort"].update(native_unit="token"),
            lambda p: p["cohort"].update(price_side="bid"),
            lambda p: p["cohort"].update(starts_at="2043-01-01T00:00:00Z"),
            lambda p: p["source_scopes"].append(deepcopy(p["source_scopes"][0])),
        ):
            request = self.request(); mutate(request)
            with patch.object(self.store, "requested_collection_scan", side_effect=AssertionError("must not read invalid request")), self.assertRaises(ValidationError):
                self.evaluate(request)

    def test_snapshot_integrity_failure_propagates_and_clock_precision_are_stable(self):
        with patch.object(self.store, "requested_collection_scan", side_effect=SnapshotStoreError("snapshot_integrity_failed")):
            with self.assertRaises(SnapshotStoreError): self.evaluate()
        from decimal import localcontext
        result = self.evaluate()
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.evaluate(), result)


if __name__ == "__main__":
    unittest.main()
