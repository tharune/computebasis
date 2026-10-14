"""Invented reference contracts, independent of vendor data and customer books."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from compute_pricing.control.curves import evaluate_term_curve_payload, observed_commitment_curves, term_curve_contract


def comparison_book():
    context = {"hardware_model": "sample-device", "configuration": {"network": "declared-local-fabric"},
        "region": "sample-zone", "currency": "EUR", "payment_scope": "upfront-single-payment",
        "cost_scope": "compute-only", "capacity_scope": "exclusive-full-allocation", "gpu_count": "3",
        "start_date": "2056-04-01", "service_basis": "24x7_utc_calendar", "cashflow_basis": "undiscounted_nominal_total"}
    rows = []
    for identity, end, rate, hours in (("spring", "2056-05-01", "1.125", "2160"),
                                       ("summer", "2056-06-01", "0.875", "4392")):
        rows.append({"node_id": identity, "cohort": deepcopy(context), "end_date": end,
            "quote_at": "2056-03-30T08:00:00Z", "rate_per_gpu_hour": rate,
            "gpu_count": "3", "billable_gpu_hours": hours, "quote_ref": "example:" + identity})
    return {"cohort": context, "nodes": rows, "as_of": "2056-03-30T08:15:00Z",
            "max_quote_age_seconds": 3600, "requested_end_dates": [row["end_date"] for row in rows]}


def published_point(identity, month=3, rate="0.61", week="2052-06-03"):
    return {"id": identity, "source_id": "getdeploying", "source_version": "example-normalizer/7",
        "snapshot_id": "c" * 64, "index_stale": False, "execution_enabled": False,
        "kind": "aggregate_advertised_index", "status": "claimed",
        "price": {"amount": rate, "unit": "gpu_hour", "currency": "USD"},
        "hardware": {"model": "example-gpu", "accelerator_count": None}, "region": None,
        "observed_at": week + "T00:00:00Z", "expires_at": "2052-07-01T00:00:00Z",
        "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS"},
        "extensions": {"period": "weekly_median_of_daily_values", "week_start": week,
            "price_statistic": "provider_median_price", "reservation_months": month,
            "billing_type": "RESERVED", "regional_scope": "market_aggregate",
            "currency_conversion": "publisher_usd_conversion", "provider_count": 4, "offering_count": 9,
            "source_row": {"example_raw_private_field": "must not be copied"}}}


def retained(rows):
    return {"as_of": "2052-06-12T10:00:00.123456Z", "execution_enabled": False, "observations": rows,
        "sources": [{"source_id": "getdeploying", "enabled": True, "can_attempt_read": True,
            "rights_status": "allowed", "permissions": {"observe": "PASS", "retain": "PASS", "benchmark": "PASS"},
            "max_age_s": 2419200}],
        "snapshots": [{"snapshot_id": "c" * 64, "source_id": "getdeploying", "stale": False,
            "captured_at": "2052-06-11T18:00:00Z"}]}


class CurveEconomicsTests(unittest.TestCase):
    def test_amounts_use_full_calendar_and_interval_is_not_term_average(self):
        result = evaluate_term_curve_payload(comparison_book())
        first, last = result["term_average_quotes"]
        self.assertEqual((first["elapsed_calendar_days"], last["elapsed_calendar_days"]), (30, 61))
        self.assertEqual(Decimal(first["nominal_contract_amount"]), Decimal("2430"))
        self.assertEqual(Decimal(last["nominal_contract_amount"]), Decimal("3843"))
        interval = result["implied_interval_arithmetic"][1]
        self.assertEqual((interval["incremental_gpu_hours"], interval["incremental_nominal_amount"]), ("2232", "1413.000"))
        self.assertNotEqual(Decimal(interval["arithmetic_rate_per_gpu_hour"]), Decimal(last["rate_per_gpu_hour"]))
        self.assertFalse(result["firm_price_eligible"])

    def test_february_leap_days_are_reconciled_with_declared_capacity(self):
        book = comparison_book(); book["cohort"]["start_date"] = "2064-02-01"
        row = book["nodes"][0]; row.update(cohort=deepcopy(book["cohort"]), end_date="2064-03-01", billable_gpu_hours="2088")
        book["nodes"] = [row]; book["requested_end_dates"] = [row["end_date"]]
        self.assertEqual(evaluate_term_curve_payload(book)["term_average_quotes"][0]["elapsed_calendar_days"], 29)
        row["billable_gpu_hours"] = "2190"
        with self.assertRaises(ValueError):
            evaluate_term_curve_payload(book)

    def test_terms_configuration_location_currency_and_start_are_not_blended(self):
        differences = {"payment_scope": "monthly-arrears", "configuration": {"network": "another-fabric"},
            "cost_scope": "power-and-network", "capacity_scope": "shared", "region": "another-zone",
            "currency": "GBP", "start_date": "2056-04-02", "gpu_count": "6", "hardware_model": "other-device"}
        for name, value in differences.items():
            book = comparison_book(); book["nodes"][1]["cohort"][name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                evaluate_term_curve_payload(book)

    def test_discounted_cashflows_and_unstated_utilization_have_no_nominal_curve(self):
        for field, value in (("cashflow_basis", "discounted_pv"), ("service_basis", "assumed_70_percent")):
            book = comparison_book(); book["cohort"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate_term_curve_payload(book)

    def test_missing_nodes_stay_missing_instead_of_becoming_forward_prices(self):
        book = comparison_book(); book["requested_end_dates"].extend(["2056-05-20", "2056-07-01"])
        result = evaluate_term_curve_payload(book)
        self.assertEqual(result["coverage"]["missing_end_dates"], ["2056-05-20", "2056-07-01"])
        self.assertEqual(len(result["term_average_quotes"]), 2)
        self.assertEqual(result["coverage"]["interpolated_nodes"] + result["coverage"]["extrapolated_nodes"], 0)
        self.assertEqual(result["delivery_start_role"], "future_start_declared_contract")

    def test_negative_increment_and_quote_time_mismatch_hold_interval(self):
        book = comparison_book(); book["nodes"][1]["rate_per_gpu_hour"] = "0.125"
        result = evaluate_term_curve_payload(book)
        self.assertIn("negative_nominal_contract_increment", result["implied_interval_arithmetic"][1]["blockers"])
        self.assertFalse(result["interval_arithmetic_admitted"])
        book = comparison_book(); book["nodes"][1]["quote_at"] = "2056-03-30T08:02:00Z"
        result = evaluate_term_curve_payload(book)
        self.assertIn("quote_times_not_identical_for_interval_comparison", result["implied_interval_arithmetic"][1]["blockers"])

    def test_exact_values_are_not_float_or_ambient_context_calculations(self):
        book = comparison_book(); book["nodes"][0]["rate_per_gpu_hour"] = "0.0000000000000000000000000000000000000017"
        with localcontext() as context:
            context.prec = 2
            result = evaluate_term_curve_payload(book)
        with localcontext() as context:
            context.prec = 80
            expected = Decimal(book["nodes"][0]["rate_per_gpu_hour"]) * 2160
        self.assertEqual(Decimal(result["term_average_quotes"][0]["nominal_contract_amount"]), expected)
        for bad in (0.875, "NaN", "-0.1", None):
            book["nodes"][0]["rate_per_gpu_hour"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                evaluate_term_curve_payload(book)
        self.assertFalse(term_curve_contract()["execution_enabled"])

    def test_stale_quote_propagates_to_adjacent_arithmetic_and_duplicate_dates_fail(self):
        book = comparison_book(); book["nodes"][0]["quote_at"] = "2056-03-30T06:00:00Z"
        result = evaluate_term_curve_payload(book)
        self.assertEqual(result["status"], "held")
        self.assertTrue(all(interval["status"] == "held" for interval in result["implied_interval_arithmetic"]))
        book = comparison_book(); book["nodes"][1]["end_date"] = book["nodes"][0]["end_date"]
        with self.assertRaises(ValueError):
            evaluate_term_curve_payload(book)


class PublishedCurveTests(unittest.TestCase):
    def test_curve_display_budget_is_explicit_and_gaps_are_not_filled(self):
        book = retained([published_point("example:a", 3), published_point("example:b", 9)])
        result = observed_commitment_curves(book, group_limit=1, node_limit=1)
        self.assertEqual(result["coverage"]["total_nodes"], 2)
        self.assertEqual(result["coverage"]["returned_nodes"], 1)
        self.assertTrue(result["coverage"]["display_truncated"])
        self.assertEqual(result["coverage"]["node_limit"], 1)
        for kwargs in ({"group_limit": True}, {"group_limit": 0}, {"node_limit": 1025}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "invalid_native_curve_display_budget"):
                observed_commitment_curves(book, **kwargs)

    def test_retained_fractional_capture_and_expiry_preserve_real_server_precision(self):
        book = retained([published_point("example:fractional-capture")])
        book["snapshots"][0]["captured_at"] = "2052-06-11T18:00:00.654321Z"
        book["observations"][0]["expires_at"] = "2052-07-01T00:00:00.123456Z"
        book["observations"][0]["rights"]["expires_at"] = "2052-07-01T00:00:00.999999Z"
        result = observed_commitment_curves(book)
        self.assertEqual(result["coverage"]["eligible_rows"], 1)
        self.assertEqual(result["groups"][0]["nodes"][0]["references"][0]["captured_at"],
                         "2052-06-11T18:00:00.654321Z")

    def test_native_marks_with_fractional_server_asof_keep_period_and_references(self):
        result = observed_commitment_curves(retained([published_point("example:three"), published_point("example:nine", 9, "0.49")]))
        self.assertEqual(len(result["groups"]), 1)
        nodes = result["groups"][0]["nodes"]
        self.assertEqual([row["reservation_months"] for row in nodes], [3, 9])
        self.assertEqual(nodes[0]["support_counts"], [{"provider_count": 4, "offering_count": 9}])
        self.assertNotIn("example_raw_private_field", str(result))
        self.assertIsNone(result["groups"][0]["cohort"]["region"])
        self.assertFalse(result["groups"][0]["configuration_and_region_qualified"])
        self.assertFalse(result["execution_enabled"])

    def test_history_hardware_and_payment_scopes_have_separate_groups(self):
        old = published_point("example:old", week="2052-05-27")
        other = published_point("example:other"); other["hardware"]["model"] = "another-example-gpu"
        demand = published_point("example:demand", None); demand["extensions"]["billing_type"] = "ON_DEMAND"
        result = observed_commitment_curves(retained([published_point("example:base"), old, other, demand]))
        self.assertEqual(len(result["groups"]), 4)

    def test_fresh_capture_cannot_refresh_an_old_period_or_incomplete_week(self):
        for week in ("2052-04-01", "2052-06-10"):
            result = observed_commitment_curves(retained([published_point("example:invalid-period", week=week)]))
            self.assertFalse(result["groups"])
            self.assertEqual(result["coverage"]["excluded_rows"], 1)

    def test_native_usd_conversion_is_not_relabelled_as_another_currency(self):
        point = published_point("example:wrong-currency"); point["price"]["currency"] = "CAD"
        result = observed_commitment_curves(retained([point]))
        self.assertFalse(result["groups"])
        self.assertIn("native_currency_basis_not_supported", result["coverage"]["exclusions"])

    def test_conflicting_node_is_quarantined_without_duplicate_support_weights(self):
        point = published_point("example:copy"); book = retained([published_point("example:original"), point])
        node = observed_commitment_curves(book)["groups"][0]["nodes"][0]
        self.assertEqual(node["support_counts"], [{"provider_count": 4, "offering_count": 9}])
        self.assertEqual(node["reference_count"], 2)
        point["price"]["amount"] = "0.64"
        node = observed_commitment_curves(book)["groups"][0]["nodes"][0]
        self.assertIsNone(node["rate_per_gpu_hour"])
        self.assertEqual(node["status"], "held")

    def test_source_rights_freshness_and_price_roles_are_required(self):
        for mutate in (lambda b: b["sources"][0].update(can_attempt_read=False),
                       lambda b: b["observations"][0].update(index_stale=True),
                       lambda b: b["snapshots"][0].update(stale=True),
                       lambda b: b["observations"][0].update(kind="financial_future_mark"),
                       lambda b: b["observations"][0]["rights"].update(benchmark="FAIL"),
                       lambda b: b["observations"][0].update(region={"country_code": "CA"})):
            book = retained([published_point("example:held")]); mutate(book)
            self.assertFalse(observed_commitment_curves(book)["groups"])


if __name__ == "__main__":
    unittest.main()
