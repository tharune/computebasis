"""Independent comparable-index behavior tests using invented observations."""
import sys
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.benchmark.engine import evaluate_benchmark
from compute_pricing.control.domain import ValidationError


NOW = "2026-01-01T01:00:00Z"


def offer(identity="a", price="2", source="source-a", group="group-a", lot=None, **changes):
    raw = {
        "id": "observation-" + identity, "source_id": source, "source_version": "feed-v1",
        "offer_id": "offer-" + identity, "lot_id": lot or "lot-" + identity, "provider_group_id": group,
        "kind": "listing_ask", "price_side": "ask", "price": price if isinstance(price, dict) else {"amount": price, "currency": "USD", "unit": "gpu_hour"},
        "hardware": {"model": "invented-accelerator", "accelerator_count": "1"},
        "region": {"country_code": "US"}, "configuration": {"tenancy": "dedicated"},
        "quantity": "8", "quantity_unit": "gpu", "starts_at": "2026-01-03T00:00:00Z", "ends_at": "2026-01-04T00:00:00Z",
        "observed_at": "2026-01-01T00:00:00Z", "ingested_at": "2026-01-01T00:00:01Z", "expires_at": "2026-01-01T02:00:00Z",
        "status": "claimed", "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL", "verified_by": "reviewer-example"},
    }
    return {**raw, **changes}


def target(**changes):
    return {"scope": "physical_offer", "hardware_model": "invented-accelerator", "currency": "USD", "country_code": "US", "gpu_count": "1", "duration_hours": "24", "starts_at": "2026-01-03T00:00:00Z", "ends_at": "2026-01-04T00:00:00Z", "configuration": {"tenancy": "dedicated"}, **changes}


def policy(**changes):
    return {"estimator": "weighted_mean", "max_source_share": "1", "max_provider_share": "1", "min_observations": 1, "min_sources": 1, "min_provider_groups": 1,
        "source_rules": {name: {"enabled": True, "quality": "1", "max_age_hours": "72", "half_life_hours": "24"} for name in ("source-a", "source-b", "source-c", "source-d")}, **changes}


class BenchmarkV1Tests(unittest.TestCase):
    def evaluate(self, observations, t=None, p=None, as_of=NOW):
        return evaluate_benchmark(observations, t or target(), p or policy(), as_of)

    def assertHeld(self, result):
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["price"])
        self.assertFalse(result["executable"])

    def assertDecimalClose(self, actual, expected):
        self.assertLessEqual(abs(Decimal(actual) - Decimal(expected)), Decimal("1e-24"))

    def test_dynamic_prices_and_observation_population_recalculate(self):
        observations = [offer("a", "2"), offer("b", "6", "source-b", "group-b")]
        self.assertDecimalClose(self.evaluate(observations)["price"], "4")
        observations[1]["price"]["amount"] = "10"
        self.assertDecimalClose(self.evaluate(observations)["price"], "6")
        observations.append(offer("c", "9", "source-c", "group-c"))
        self.assertDecimalClose(self.evaluate(observations)["price"], "7")

    def test_source_cap_changes_final_weights_and_mark(self):
        observations = [offer("a", "2"), offer("b", "4", "source-a", "group-b"), offer("c", "8", "source-b", "group-c")]
        uncapped = self.evaluate(observations)
        capped = self.evaluate(observations, p=policy(max_source_share="0.5"))
        with localcontext() as context:
            context.prec = 60
            expected = Decimal(14) / Decimal(3)
        self.assertDecimalClose(uncapped["price"], expected)
        self.assertDecimalClose(capped["price"], "5.5")
        self.assertLessEqual(Decimal(capped["diagnostics"]["source_shares"]["source-a"]), Decimal("0.5") + Decimal(capped["diagnostics"]["weight_tolerance"]))

    def test_provider_cap_combines_provider_exposure_across_sources(self):
        observations = [offer("a", "2"), offer("b", "4", "source-b", "group-a"), offer("c", "8", "source-c", "group-b")]
        capped = self.evaluate(observations, p=policy(max_provider_share="0.5"))
        self.assertDecimalClose(capped["price"], "5.5")
        self.assertDecimalClose(capped["diagnostics"]["provider_shares"]["group-a"], "0.5")

    def test_joint_caps_satisfy_both_families_with_sum_one(self):
        observations = [offer("a", "2"), offer("b", "4", "source-a", "group-b"), offer("c", "8", "source-b", "group-a"), offer("d", "10", "source-b", "group-b")]
        p = policy(max_source_share="0.6", max_provider_share="0.6")
        p["source_rules"]["source-b"]["quality"] = "0.1"
        result = self.evaluate(observations, p=p)
        self.assertEqual(result["status"], "indicative")
        tolerance = Decimal(result["diagnostics"]["weight_tolerance"])
        self.assertLessEqual(abs(Decimal(result["diagnostics"]["weight_sum"]) - 1), tolerance)
        for family in ("source_shares", "provider_shares"):
            for weight in result["diagnostics"][family].values():
                self.assertLessEqual(Decimal(weight), Decimal("0.6") + tolerance)
        self.assertDecimalClose(result["price"], "5.4")

    def test_insufficient_support_and_infeasible_caps_hold(self):
        for p in (policy(min_observations=2), policy(min_sources=2), policy(min_provider_groups=2), policy(max_source_share="0.4"), policy(max_provider_share="0.4")):
            with self.subTest(p=p):
                self.assertHeld(self.evaluate([offer()], p=p))

    def test_weighted_median_ties_and_dispersion_are_explicit(self):
        result = self.evaluate([offer("a", "2"), offer("b", "6", "source-b", "group-b")], p=policy(estimator="weighted_median"))
        self.assertEqual(result["price"], "4")
        self.assertEqual(result["diagnostics"]["weighted_dispersion"], "4")
        self.assertEqual(result["diagnostics"]["uncertainty_status"], "dispersion_not_a_calibrated_confidence_interval")
        self.assertNotIn("confidence_interval", result)
        self.assertFalse(result["executable"])

    def test_latest_same_underlying_lot_across_sources_is_one_contributor(self):
        old = offer("a", "2", lot="global-lot-a")
        latest = offer("b", "6", "source-b", "group-a", lot="global-lot-a", observed_at="2026-01-01T00:30:00Z", ingested_at="2026-01-01T00:30:01Z")
        result = self.evaluate([old, latest])
        self.assertEqual(result["price"], "6")
        self.assertEqual(len(result["contributors"]), 1)
        self.assertEqual(result["exclusions"][0]["reasons"], ["underlying_lot_superseded"])

    def test_latest_selection_compares_instants_not_timestamp_text(self):
        older = offer("a", "2", lot="global-lot-a")
        newer = offer("b", "6", "source-b", "group-a", lot="global-lot-a", observed_at="2026-01-01T00:00:00.1Z", ingested_at="2026-01-01T00:00:01Z")
        result = self.evaluate([older, newer])
        self.assertEqual(result["price"], "6")
        self.assertEqual(result["contributors"][0]["observation_id"], "observation-b")

    def test_conflicting_provider_identity_cannot_duplicate_same_lot(self):
        records = [offer("a", "2", lot="global-lot-a"), offer("b", "6", "source-b", "group-b", lot="global-lot-a")]
        self.assertHeld(self.evaluate(records))

    def test_full_node_price_uses_explicit_count_and_quantity_units(self):
        raw = offer()
        raw.update(price={"amount": "8", "currency": "USD", "unit": "node_hour"}, hardware={"model": "invented-accelerator", "accelerator_count": "4"}, quantity="2", quantity_unit="node")
        result = self.evaluate([raw], t=target(gpu_count="6"))
        self.assertEqual(result["price"], "2")
        self.assertIn("full_node_bundle_total_divided_by_explicit_accelerator_count", result["contributors"][0]["steps"])
        raw["hardware"]["accelerator_count"] = None
        self.assertHeld(self.evaluate([raw]))

    def test_quantity_units_must_be_known_not_guessed_from_rate_unit(self):
        raw = offer()
        raw.pop("quantity_unit")
        self.assertHeld(self.evaluate([raw]))

    def test_missing_critical_fields_fail_closed(self):
        for key in ("price", "hardware", "region", "quantity", "rights", "expires_at", "starts_at", "lot_id", "provider_group_id", "source_version"):
            raw = offer()
            raw[key] = None
            with self.subTest(key=key):
                self.assertHeld(self.evaluate([raw]))

    def test_region_configuration_hardware_currency_and_delivery_mismatches(self):
        cases = ({"region": {"country_code": "CA"}}, {"configuration": {"tenancy": "shared"}}, {"hardware": {"model": "other-accelerator", "accelerator_count": "1"}}, {"price": {"amount": "2", "currency": "EUR", "unit": "gpu_hour"}}, {"starts_at": "2026-01-03T01:00:00Z"}, {"quantity": "0"})
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertHeld(self.evaluate([offer(**changes)]))

    def test_disabled_expired_unauthorized_future_and_stale_sources_hold(self):
        p = policy()
        p["source_rules"]["source-a"]["enabled"] = False
        self.assertHeld(self.evaluate([offer()], p=p))
        raw = offer()
        raw["rights"]["benchmark"] = "UNKNOWN"
        self.assertHeld(self.evaluate([raw]))
        raw = offer()
        raw["rights"]["expires_at"] = NOW
        self.assertHeld(self.evaluate([raw]))
        self.assertHeld(self.evaluate([offer()], as_of="2026-01-01T02:00:00Z"))
        self.assertHeld(self.evaluate([offer()], as_of="2025-12-31T23:59:00Z"))
        p = policy()
        p["source_rules"]["source-a"]["max_age_hours"] = "0.5"
        self.assertHeld(self.evaluate([offer()], p=p))

    def test_aggregate_is_global_reference_and_never_physical_supply(self):
        raw = offer(kind="aggregate_advertised_index", region=None, quantity=None, quantity_unit=None, starts_at=None, ends_at=None, provider_group_id=None, lot_id=None,
                    extensions={"billing_type": "ON_DEMAND", "reservation_months": None})
        self.assertHeld(self.evaluate([raw]))
        t = target(scope="aggregate_reference", country_code=None, configuration={}, starts_at=None, ends_at=None,
                   aggregate_terms={"billing_type": "ON_DEMAND", "reservation_months": None})
        result = self.evaluate([raw], t=t)
        self.assertEqual(result["status"], "indicative")
        self.assertEqual(result["contributors"][0]["source_status"], "claimed")
        self.assertIn("advertised_aggregate_is_not_executable_inventory_or_region_premium", result["warnings"])
        self.assertHeld(self.evaluate([raw], t={**t, "country_code": "US"}))

    def test_aggregate_terms_never_mix_on_demand_and_term_commitments(self):
        on_demand = offer("a", "4", kind="aggregate_advertised_index", extensions={"billing_type": "ON_DEMAND", "reservation_months": None})
        reserved = offer("b", "1", kind="aggregate_advertised_index", extensions={"billing_type": "RESERVED", "reservation_months": 12})
        t = target(scope="aggregate_reference", country_code=None, configuration={}, starts_at=None, ends_at=None,
                   aggregate_terms={"billing_type": "ON_DEMAND", "reservation_months": None})
        result = self.evaluate([on_demand, reserved], t=t)
        self.assertEqual(result["price"], "4")
        self.assertIn("aggregate_billing_or_reservation_mismatch", result["exclusions"][0]["reasons"])
        t["aggregate_terms"] = {"billing_type": "RESERVED", "reservation_months": 12}
        self.assertEqual(self.evaluate([on_demand, reserved], t=t)["price"], "1")
        t["aggregate_terms"]["reservation_months"] = 6
        self.assertHeld(self.evaluate([reserved], t=t))

    def test_unknown_aggregate_terms_and_specific_configuration_hold(self):
        raw = offer(kind="aggregate_advertised_index", extensions={"billing_type": "ON_DEMAND", "reservation_months": None})
        t = target(scope="aggregate_reference", country_code=None, configuration={}, starts_at=None, ends_at=None)
        self.assertHeld(self.evaluate([raw], t=t))
        t["aggregate_terms"] = {"billing_type": "ON_DEMAND", "reservation_months": None}
        no_terms = {**raw}
        no_terms["extensions"] = {}
        self.assertHeld(self.evaluate([no_terms], t=t))
        self.assertHeld(self.evaluate([raw], t={**t, "configuration": {"tenancy": "dedicated"}}))

    def test_aggregate_repeated_fetch_same_publisher_model_term_period_deduplicates(self):
        common = {"billing_type": "ON_DEMAND", "reservation_months": None}
        old = offer("a", "4", kind="aggregate_advertised_index", extensions=common)
        fresh = offer("b", "4", kind="aggregate_advertised_index", extensions=common, ingested_at="2026-01-01T00:30:00Z")
        t = target(scope="aggregate_reference", country_code=None, configuration={}, starts_at=None, ends_at=None,
                   aggregate_terms=common)
        result = self.evaluate([old, fresh], t=t)
        self.assertEqual(result["price"], "4")
        self.assertEqual(len(result["contributors"]), 1)
        self.assertEqual(result["diagnostics"]["effective_support"], "1")
        self.assertEqual(result["exclusions"][0]["reasons"], ["underlying_lot_superseded"])

    def test_nonphysical_financial_and_token_units_never_average_into_compute(self):
        for kind, unit in (("model_token_price", "input_million_tokens"), ("financial_future_mark", "contract"), ("event_contract_price", "contract")):
            raw = offer(kind=kind, price={"amount": "2", "currency": "USD", "unit": unit})
            with self.subTest(kind=kind):
                self.assertHeld(self.evaluate([raw]))

    def test_target_intervals_and_declared_duration_cannot_conflict(self):
        cases = ({"ends_at": None}, {"starts_at": None}, {"starts_at": "2026-01-04T00:00:00Z", "ends_at": "2026-01-03T00:00:00Z"}, {"duration_hours": "48"})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.evaluate([offer()], t=target(**changes))

    def test_unsupported_policy_and_inexact_financial_inputs_reject(self):
        for p in (policy(estimator="mystery"), policy(max_source_share=0.5), policy(max_provider_share="1.01"), policy(min_sources=True)):
            with self.subTest(p=p), self.assertRaises(ValidationError):
                self.evaluate([offer()], p=p)
        for changes in ({"duration_hours": None}, {"gpu_count": "1.5"}, {"duration_hours": 24}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.evaluate([offer()], t=target(**changes))

    def test_result_is_independent_of_callers_decimal_precision(self):
        records = [offer("a", "2"), offer("b", "6", "source-b", "group-b")]
        baseline = self.evaluate(records)
        with localcontext() as context:
            context.prec = 2
            result = self.evaluate(records)
        self.assertEqual(result, baseline)

    def test_uniform_prices_remain_exact_despite_weight_projection(self):
        records = [offer("a", "4"), offer("b", "4", "source-b", "group-b"), offer("c", "4", "source-c", "group-c")]
        self.assertEqual(self.evaluate(records)["price"], "4")

    def test_malformed_and_nonpositive_rows_are_quarantined_individually(self):
        good = offer()
        malformed = offer("b", "3", "source-b", "group-b")
        malformed["price"]["amount"] = 3.0
        zero = offer("c", "0", "source-c", "group-c")
        result = self.evaluate([good, malformed, zero])
        self.assertEqual(result["price"], "2")
        self.assertEqual(len(result["contributors"]), 1)
        exclusions = {item["observation_id"]: item["reasons"] for item in result["exclusions"]}
        self.assertEqual(exclusions["observation-b"], ["domain_validation"])
        self.assertEqual(exclusions["observation-c"], ["nonpositive_benchmark_price"])

    def test_duplicate_id_remains_global_input_error(self):
        with self.assertRaises(ValidationError):
            self.evaluate([offer(), offer(price="9")])

    def test_indicative_physical_claim_status_is_visible(self):
        result = self.evaluate([offer()])
        self.assertEqual(result["contributors"][0]["source_status"], "claimed")
        self.assertIn("claimed_data_not_verified_asset_capacity", result["warnings"])


if __name__ == "__main__":
    unittest.main()
