"""Entirely synthetic examples exercising dynamic pricing and protective holds."""

from copy import deepcopy
from decimal import Decimal
import unittest

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing import InputError, evaluate


def snapshot():
    """A new fictional cohort; values are not commercial or provider records."""
    rule = {"enabled": True, "quality": "1", "max_age_hours": "48", "freshness_half_life_hours": "24"}
    observations = []
    for position, price in enumerate(("1.6", "2.0", "2.4")):
        observations.append({
            "observation_id": f"observation-{position}",
            "source_id": "source-a" if position != 1 else "source-b",
            "provider_group": f"group-{position}", "lot_id": f"lot-{position}",
            "observed_at": "2033-01-08T12:00:00Z", "status": "available",
            "hardware_class": "synthetic-accelerator", "region": "test-region", "currency": "USD",
            "tenor_min_hours": "0", "tenor_max_hours": "1000", "unit": "gpu_hour", "price": price,
        })
    return {
        "api_version": "1.0", "as_of": "2033-01-08T12:00:00Z",
        "target": {"hardware_class": "synthetic-accelerator", "region": "test-region", "currency": "USD", "tenor_hours": "72"},
        "observations": observations,
        "policy": {"estimator": "weighted_median", "max_provider_share": "0.5",
                   "min_observations": 3, "min_provider_groups": 3, "min_sources": 2,
                   "winsor_band_fraction": "0.25", "source_rules": {"source-a": deepcopy(rule), "source-b": deepcopy(rule)}},
        "deal": {
            "start_at": "2033-01-09T00:00:00Z", "end_at": "2033-01-12T00:00:00Z", "gpu_count": "5",
            "buyer_rate_per_gpu_hour": "3.4", "utilization": "0.8", "availability": "0.95",
            "buyer_collection_fraction": "0.97", "required_margin_fraction": "0.15",
            "supplier_advance_fraction": "0.25", "available_advance_funding": "180",
            "buyer_prepayment": "20", "buyer_prepayment_available_for_procurement": True,
            "liquidity_reserve": "10", "capital_charge": "4", "market_discount_fraction": "0.1",
            "costs": {"per_committed_gpu_hour": {"energy": "0.12", "network": "0.04"},
                      "fixed_contract": {"integration": "8"}, "upfront_fixed": {"setup": "11"}},
        },
    }


class CoreTests(unittest.TestCase):
    def test_complete_snapshot_is_indicative_with_explicit_math(self):
        result = evaluate(snapshot())
        self.assertEqual(result["status"], "indicative")
        self.assertFalse(result["execution_ready"])
        self.assertEqual(result["index"]["price_per_gpu_hour"], "2")
        deal = result["deal"]
        self.assertEqual(deal["contract_hours"], "72")
        self.assertEqual(deal["committed_gpu_hours"], "360")
        self.assertEqual(deal["expected_collected_gpu_hours"], "265.392")
        self.assertEqual(deal["expected_revenue"], "902.3328")
        self.assertEqual(deal["nonpurchase_cost"], "80.6")
        self.assertEqual(deal["recommended_bid_per_gpu_hour"], "1.8")
        self.assertEqual(deal["expected_profit"], "173.7328")
        self.assertEqual(deal["binding_bid_caps"], ["market"])
        self.assertLess(Decimal(deal["minimum_ask_per_gpu_hour"]), Decimal("3.4"))

    def test_dynamic_observations_change_index_and_bid(self):
        before = evaluate(snapshot())
        changed = snapshot()
        for observation, price in zip(changed["observations"], ("2.2", "2.8", "3.4")):
            observation["price"] = price
        after = evaluate(changed)
        self.assertEqual(after["index"]["price_per_gpu_hour"], "2.8")
        self.assertGreater(Decimal(after["deal"]["recommended_bid_per_gpu_hour"]), Decimal(before["deal"]["recommended_bid_per_gpu_hour"]))

    def test_dynamic_named_costs_reduce_economics_cap(self):
        before = evaluate(snapshot())
        changed = snapshot()
        changed["deal"]["costs"]["fixed_contract"]["new_review_cost"] = "140"
        after = evaluate(changed)
        self.assertLess(Decimal(after["deal"]["recommended_bid_per_gpu_hour"]), Decimal(before["deal"]["recommended_bid_per_gpu_hour"]))
        self.assertEqual(after["deal"]["binding_bid_caps"], ["economics"])

    def test_node_rate_converts_using_explicit_gpu_count(self):
        changed = snapshot()
        changed["observations"][1].update({"unit": "node_hour", "price": "12", "gpus_per_node": "6"})
        result = evaluate(changed)
        self.assertEqual(result["index"]["price_per_gpu_hour"], "2")
        self.assertEqual(result["index"]["observations"][1]["normalized_price_per_gpu_hour"], "2")

    def test_missing_node_count_does_not_guess(self):
        changed = snapshot()
        changed["observations"][1]["unit"] = "node_hour"
        result = evaluate(changed)
        self.assertEqual(result["status"], "held")
        self.assertEqual(result["index"]["observations"][1]["exclusion_reasons"], ["invalid_input"])

    def test_each_cohort_dimension_and_tenor_blocks_incompatible_data(self):
        mutations = ({"region": "another-region"}, {"currency": "EUR"},
                     {"hardware_class": "different-accelerator"}, {"tenor_max_hours": "24"})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = snapshot()
                changed["observations"][1].update(mutation)
                result = evaluate(changed)
                self.assertEqual(result["index"]["status"], "held")
                self.assertIsNone(result["deal"]["recommended_bid_per_gpu_hour"])

    def test_stale_future_unavailable_and_disabled_data_do_not_price(self):
        for mutation in ({"observed_at": "2033-01-01T12:00:00Z"},
                         {"observed_at": "2033-01-09T12:00:00Z"},
                         {"status": "indicative"}, {"status": "unavailable"}):
            with self.subTest(mutation=mutation):
                changed = snapshot()
                changed["observations"][1].update(mutation)
                self.assertEqual(evaluate(changed)["index"]["status"], "held")
        changed = snapshot()
        changed["policy"]["source_rules"]["source-b"]["enabled"] = False
        self.assertEqual(evaluate(changed)["index"]["observations"][1]["exclusion_reasons"], ["source_not_admitted"])
        del changed["policy"]["source_rules"]["source-b"]
        self.assertEqual(evaluate(changed)["index"]["status"], "held")

    def test_same_lot_relisting_is_deduped_order_independently(self):
        changed = snapshot()
        relisting = deepcopy(changed["observations"][0])
        relisting.update({"observation_id": "new-relisting", "source_id": "source-b", "price": "1.7"})
        changed["observations"][0]["observed_at"] = "2033-01-08T11:59:00Z"
        changed["observations"].append(relisting)
        result = evaluate(changed)
        self.assertEqual(result["index"]["eligible_observation_count"], 3)
        self.assertEqual(result["index"]["observations"][0]["exclusion_reasons"], ["duplicate_lot_superseded"])
        changed["observations"].reverse()
        reversed_result = evaluate(changed)
        self.assertEqual(result["index"]["price_per_gpu_hour"], reversed_result["index"]["price_per_gpu_hour"])

    def test_duplicate_ids_are_ambiguous_and_rejected(self):
        changed = snapshot()
        changed["observations"][1]["observation_id"] = changed["observations"][0]["observation_id"]
        with self.assertRaises(InputError):
            evaluate(changed)

    def test_provider_weight_cap_bounds_relisting_lot_proliferation(self):
        changed = snapshot()
        for position in range(10):
            extra = deepcopy(changed["observations"][0])
            extra.update({"observation_id": f"extra-{position}", "lot_id": f"extra-lot-{position}", "price": "20"})
            changed["observations"].append(extra)
        result = evaluate(changed)
        shares = result["index"]["diagnostics"]["provider_weight_shares"]
        self.assertEqual(Decimal(shares["group-0"]), Decimal("0.5"))
        self.assertTrue(all(Decimal(share) <= Decimal("0.5") for share in shares.values()))
        self.assertEqual(sum(Decimal(share) for share in shares.values()), Decimal("1"))

    def test_infeasible_provider_cap_holds(self):
        changed = snapshot()
        changed["policy"]["max_provider_share"] = "0.3"
        result = evaluate(changed)
        self.assertIn("infeasible_provider_weight_cap", result["index"]["hold_reasons"])

    def test_winsorized_mean_diagnostics_show_outlier_treatment(self):
        changed = snapshot()
        changed["policy"]["estimator"] = "winsorized_mean"
        changed["observations"][2]["price"] = "90"
        result = evaluate(changed)
        diagnostic = result["index"]["diagnostics"]
        self.assertEqual(diagnostic["weighted_median"], "2")
        self.assertEqual(diagnostic["winsor_upper"], "2.5")
        self.assertGreater(Decimal(diagnostic["weighted_mean"]), Decimal("30"))
        self.assertLess(Decimal(result["index"]["price_per_gpu_hour"]), Decimal("2.1"))

    def test_quality_and_freshness_are_dynamic_and_visible(self):
        changed = snapshot()
        changed["policy"]["max_provider_share"] = "1"
        changed["observations"][0]["observed_at"] = "2033-01-07T12:00:00Z"
        result = evaluate(changed)
        rows = result["index"]["observations"]
        self.assertAlmostEqual(float(rows[0]["uncapped_quality_freshness_weight"]), 0.5)
        self.assertEqual(rows[0]["age_hours"], "24")
        changed["policy"]["source_rules"]["source-a"]["quality"] = "0.2"
        after = evaluate(changed)
        self.assertLess(Decimal(after["index"]["observations"][0]["index_weight"]), Decimal(rows[0]["index_weight"]))

    def test_restricted_prepayment_cannot_fund_supplier_advance(self):
        changed = snapshot()
        changed["deal"]["buyer_prepayment_available_for_procurement"] = False
        result = evaluate(changed)
        self.assertEqual(result["deal"]["buyer_prepayment_admitted_to_funding"], "0")
        self.assertEqual(result["deal"]["available_supplier_advance_cash"], "159")
        self.assertLess(Decimal(result["deal"]["recommended_bid_per_gpu_hour"]), Decimal("1.8"))
        self.assertEqual(result["deal"]["binding_bid_caps"], ["advance_funding"])

    def test_prepayment_is_not_double_counted_as_revenue(self):
        changed = snapshot()
        before = evaluate(changed)
        changed["deal"]["buyer_prepayment"] = "100"
        after = evaluate(changed)
        self.assertEqual(after["deal"]["expected_revenue"], before["deal"]["expected_revenue"])
        self.assertEqual(after["deal"]["expected_profit"], before["deal"]["expected_profit"])

    def test_upfront_shortfall_and_zero_revenue_hold(self):
        changed = snapshot()
        changed["deal"].update({"available_advance_funding": "0", "buyer_prepayment": "0", "supplier_advance_fraction": "0"})
        result = evaluate(changed)
        self.assertIn("upfront_funding_shortfall", result["deal"]["hold_reasons"])
        changed = snapshot()
        changed["deal"].update({"utilization": "0", "buyer_prepayment": "0"})
        self.assertIn("no_expected_collected_revenue", evaluate(changed)["deal"]["hold_reasons"])

    def test_actual_leap_month_hours_are_used(self):
        changed = snapshot()
        changed["target"]["tenor_hours"] = "696"
        changed["deal"].update({"start_at": "2036-02-01T00:00:00Z", "end_at": "2036-03-01T00:00:00Z"})
        result = evaluate(changed)
        self.assertEqual(result["deal"]["contract_hours"], "696")
        self.assertEqual(result["deal"]["committed_gpu_hours"], "3480")

    def test_duration_mismatch_missing_costs_and_missing_flags_reject(self):
        for mutation in ("duration", "costs", "permitted"):
            with self.subTest(mutation=mutation):
                changed = snapshot()
                if mutation == "duration":
                    changed["target"]["tenor_hours"] = "71"
                elif mutation == "costs":
                    del changed["deal"]["costs"]["fixed_contract"]
                else:
                    del changed["deal"]["buyer_prepayment_available_for_procurement"]
                with self.assertRaises(InputError):
                    evaluate(changed)

    def test_numeric_floats_exponents_nonfinite_and_negative_rates_reject(self):
        for bad_value in (2.5, "NaN", "Infinity", "1e2", "-1", True):
            with self.subTest(value=bad_value):
                changed = snapshot()
                changed["observations"][1]["price"] = bad_value
                self.assertEqual(evaluate(changed)["index"]["status"], "held")
                changed = snapshot()
                changed["deal"]["buyer_rate_per_gpu_hour"] = bad_value
                with self.assertRaises(InputError):
                    evaluate(changed)

    def test_calendar_timestamp_validation_and_utc_requirement(self):
        for timestamp in ("2033-02-30T00:00:00Z", "2033-01-08T12:00:00+00:00", "2033-01-08"):
            with self.subTest(timestamp=timestamp):
                changed = snapshot()
                changed["as_of"] = timestamp
                with self.assertRaises(InputError):
                    evaluate(changed)

    def test_extensions_preserved_but_not_silently_priced(self):
        original = snapshot()
        changed = deepcopy(original)
        changed["target"]["privacy_class"] = "unassessed"
        changed["observations"][0]["extensions"] = {"invented_latency_ms": "17"}
        changed["deal"]["experimental_premium"] = "100"
        changed["unknown_future_signal"] = {"value": "6"}
        result = evaluate(changed)
        self.assertEqual(result["deal"]["recommended_bid_per_gpu_hour"], evaluate(original)["deal"]["recommended_bid_per_gpu_hour"])
        self.assertEqual(result["target"]["extensions"]["unmapped"]["privacy_class"], "unassessed")
        self.assertEqual(result["index"]["observations"][0]["extensions"]["declared"]["invented_latency_ms"], "17")
        self.assertEqual(result["extensions"]["unmapped"]["unknown_future_signal"], {"value": "6"})

    def test_no_input_mutation_and_detached_policy_snapshot(self):
        source = snapshot()
        original = deepcopy(source)
        result = evaluate(source)
        self.assertEqual(source, original)
        source["policy"]["source_rules"]["source-a"]["quality"] = "0.1"
        self.assertEqual(result["policy_snapshot"]["source_rules"]["source-a"]["quality"], "1")

    def test_nonfinite_or_non_json_extensions_reject_at_library_boundary(self):
        for value in (float("nan"), float("inf"), float("-inf"), {"not-a-json-value"}):
            with self.subTest(value=value):
                changed = snapshot()
                changed["extensions"] = {"unpriced": value}
                with self.assertRaises(InputError):
                    evaluate(changed)

    def test_nested_extensions_are_detached_from_input(self):
        changed = snapshot()
        changed["observations"][0]["extensions"] = {"future_signal": {"value": "7"}}
        result = evaluate(changed)
        changed["observations"][0]["extensions"]["future_signal"]["value"] = "99"
        self.assertEqual(result["index"]["observations"][0]["extensions"]["declared"]["future_signal"]["value"], "7")

    def test_index_only_and_empty_evidence_are_supported(self):
        changed = snapshot()
        del changed["deal"]
        self.assertIsNone(evaluate(changed)["deal"])
        changed["observations"] = []
        self.assertEqual(evaluate(changed)["status"], "held")

    def test_tiny_half_life_is_bounded_without_numeric_failure(self):
        changed = snapshot()
        changed["observations"][1]["observed_at"] = "2033-01-08T11:00:00Z"
        changed["policy"]["source_rules"]["source-b"]["freshness_half_life_hours"] = "0.00000000000000000000000000001"
        result = evaluate(changed)
        self.assertEqual(result["index"]["observations"][1]["exclusion_reasons"], ["weight_underflow"])


if __name__ == "__main__":
    unittest.main()
