"""Invented independent cohorts only; no fit to source workbook or live feed."""
from copy import deepcopy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.calibration import evaluate_calibration_payload
from compute_pricing.control.domain import ValidationError


def fixture():
    rows = []
    for label, first_day, count in (("train", 1, 12), ("holdout", 9, 8)):
        for index in range(count):
            latency = 10 + (index % 4) * 5
            region = "US" if (index // 4) % 2 == 0 else "EU"
            premium = 0.3 if region == "US" else 0
            log_price = 0.5 + 0.02 * latency + premium
            observed = f"2026-10-{first_day + index // 4:02d}T00:00:00Z"
            ingested = observed.replace("00:00:00", "00:00:01")
            observation = {"id": f"observation-{label}-{index}", "source_id": "source-a" if index % 2 == 0 else "source-b", "source_version": "1.0",
                "kind": "listing_ask", "price_side": "ask", "lot_id": f"lot-{label}-{index}", "provider_group_id": f"group-{label}-{index % 4}",
                "price": {"amount": format(math.exp(log_price), ".16f"), "currency": "USD", "unit": "gpu_hour"},
                "hardware": {"model": "synthetic-accelerator", "accelerator_count": "1"}, "configuration": {"tenancy": "dedicated"},
                "region": {"country_code": "US" if region == "US" else "DE"},
                "starts_at": "2026-10-20T00:00:00Z", "ends_at": "2026-10-21T00:00:00Z",
                "observed_at": observed, "ingested_at": ingested, "expires_at": "2026-10-25T00:00:00Z", "status": "verified",
                "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL", "verified_by": "synthetic-reviewer"},
                "extensions": {"billing_type": "ON_DEMAND"}}
            rows.append({"observation": observation, "features": {
                "latency": {"value": str(latency), "unit": "ms", "available_at": observed, "status": "verified"},
                "region": {"value": region, "unit": None, "available_at": observed, "status": "verified"}}})
    return {"rows": rows, "cohort": {"hardware_model": "synthetic-accelerator", "currency": "USD", "kind": "listing_ask", "configuration": {"tenancy": "dedicated"}, "duration_hours": "24", "billing_type": "ON_DEMAND"},
        "numeric_features": {"latency": {"unit": "ms"}}, "categorical_features": {"region": {"reference": "EU", "levels": ["EU", "US"], "unit": None}},
        "split_at": "2026-10-08T00:00:00Z", "as_of": "2026-10-14T00:00:00Z",
        "minimum_support": {"training_rows": 8, "holdout_rows": 4, "training_provider_groups": 2, "holdout_provider_groups": 2,
            "training_sources": 2, "holdout_sources": 2, "training_timestamps": 2, "holdout_timestamps": 2, "training_source_times": 2, "holdout_source_times": 2}}


class CalibrationV1Tests(unittest.TestCase):
    def test_known_coefficients_sign_reference_and_holdout_errors(self):
        result = evaluate_calibration_payload(fixture())
        self.assertEqual(result["status"], "research_only")
        self.assertFalse(result["live_pricing_eligible"])
        self.assertFalse(result["execution_enabled"])
        self.assertAlmostEqual(result["coefficients"]["category:region=US"], 0.3, places=12)
        scale = result["numeric_scaling"]["latency"]["standard_deviation"]
        self.assertAlmostEqual(result["coefficients"]["numeric:latency"] / scale, 0.02, places=12)
        self.assertLess(result["holdout_metrics"]["rmse_log"], 1e-12)
        self.assertEqual(result["split"]["feature_scaling"], "training_only")
        self.assertEqual(result["support"]["training"]["rows"], 12)

    def test_non_usd_cohort_keeps_actual_target_currency(self):
        packet = fixture()
        packet["cohort"]["currency"] = "EUR"
        for row in packet["rows"]:
            row["observation"]["price"]["currency"] = "EUR"
        result = evaluate_calibration_payload(packet)
        self.assertEqual(result["holdout_metrics"]["target"], {"transformation": "natural_log", "currency": "EUR", "unit": "gpu_hour"})
        self.assertLess(result["holdout_metrics"]["rmse_log"], 1e-12)

    def test_price_perturbation_changes_fit_and_identity(self):
        original = fixture()
        changed = deepcopy(original)
        changed["rows"][0]["observation"]["price"]["amount"] = "9.50"
        before, after = evaluate_calibration_payload(original), evaluate_calibration_payload(changed)
        self.assertNotEqual(before["coefficients"], after["coefficients"])
        self.assertNotEqual(before["model_hash"], after["model_hash"])

    def test_holdout_prices_never_change_training_coefficients(self):
        original = fixture()
        changed = deepcopy(original)
        changed["rows"][-1]["observation"]["price"]["amount"] = "95"
        before, after = evaluate_calibration_payload(original), evaluate_calibration_payload(changed)
        self.assertEqual(before["coefficients"], after["coefficients"])
        self.assertGreater(after["holdout_metrics"]["rmse_log"], before["holdout_metrics"]["rmse_log"])

    def test_reference_change_reverses_category_effect(self):
        packet = fixture()
        packet["categorical_features"]["region"]["reference"] = "US"
        result = evaluate_calibration_payload(packet)
        self.assertAlmostEqual(result["coefficients"]["category:region=EU"], -0.3, places=12)
        self.assertLess(result["holdout_metrics"]["mae_log"], 1e-12)

    def test_provider_and_lot_leakage_rejected(self):
        for field in ("provider_group_id", "lot_id"):
            packet = fixture()
            packet["rows"][-1]["observation"][field] = packet["rows"][0]["observation"][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValidationError, "holdout_leakage"):
                evaluate_calibration_payload(packet)

    def test_rank_deficient_or_constant_design_rejected(self):
        packet = fixture()
        packet["numeric_features"]["duplicate"] = {"unit": "ms"}
        for row in packet["rows"]:
            row["features"]["duplicate"] = deepcopy(row["features"]["latency"])
        with self.assertRaisesRegex(ValidationError, "rank_deficient"):
            evaluate_calibration_payload(packet)
        packet = fixture()
        for row in packet["rows"]:
            row["features"]["latency"]["value"] = "5"
        with self.assertRaisesRegex(ValidationError, "constant_or_invalid"):
            evaluate_calibration_payload(packet)

    def test_insufficient_source_group_and_time_support_rejected(self):
        for field in ("source_id", "provider_group_id", "observed_at"):
            packet = fixture()
            for row in packet["rows"][:12]:
                row["observation"][field] = packet["rows"][0]["observation"][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValidationError, "insufficient_training_support"):
                evaluate_calibration_payload(packet)

    def test_incompatible_roles_and_unadmitted_rows_excluded(self):
        packet = fixture()
        extras = []
        for index, kind in enumerate(("aggregate_advertised_index", "model_token_price", "event_contract_price", "financial_future_mark")):
            row = deepcopy(packet["rows"][0])
            row["observation"]["id"] = "excluded-role-" + str(index)
            row["observation"]["kind"] = kind
            extras.append(row)
        blocked = deepcopy(packet["rows"][0])
        blocked["observation"]["id"] = "excluded-rights"
        blocked["observation"]["rights"]["benchmark"] = "UNKNOWN"
        extras.append(blocked)
        packet["rows"] += extras
        result = evaluate_calibration_payload(packet)
        self.assertEqual(result["coverage"]["eligible_rows"], 20)
        self.assertEqual(len(result["coverage"]["exclusions"]), 5)

    def test_future_source_and_feature_data_cannot_enter_fit(self):
        packet = fixture()
        future = deepcopy(packet["rows"][0])
        future["observation"]["id"] = "excluded-future"
        future["observation"]["ingested_at"] = "2026-10-15T00:00:00Z"
        feature = deepcopy(packet["rows"][0])
        feature["observation"]["id"] = "excluded-late-feature"
        feature["features"]["latency"]["available_at"] = "2026-10-15T00:00:00Z"
        late_arrival = deepcopy(packet["rows"][0])
        late_arrival["observation"]["id"] = "excluded-late-training"
        late_arrival["observation"]["ingested_at"] = "2026-10-08T00:00:00Z"
        baseline = evaluate_calibration_payload(packet)
        packet["rows"] += [future, feature, late_arrival]
        result = evaluate_calibration_payload(packet)
        self.assertEqual(result["coefficients"], baseline["coefficients"])
        self.assertEqual(len(result["coverage"]["exclusions"]), 3)

    def test_node_denominator_and_configuration_not_silently_normalized(self):
        packet = fixture()
        for row in packet["rows"]:
            row["observation"]["price"]["unit"] = "node_hour"
        with self.assertRaisesRegex(ValidationError, "insufficient_training_support"):
            evaluate_calibration_payload(packet)
        packet = fixture()
        packet["cohort"]["configuration"] = {"tenancy": "shared"}
        with self.assertRaisesRegex(ValidationError, "insufficient_training_support"):
            evaluate_calibration_payload(packet)

    def test_explicit_payload_units_categories_and_bounded_parameters(self):
        for change in ({"split_at": "2026-10-14T00:00:00Z"}, {"minimum_support": {}}, {"numeric_features": {"latency": {}}}):
            packet = {**fixture(), **change}
            with self.subTest(change=change), self.assertRaises(ValidationError):
                evaluate_calibration_payload(packet)
        packet = fixture()
        packet["categorical_features"]["region"]["reference"] = "unlisted"
        with self.assertRaises(ValidationError):
            evaluate_calibration_payload(packet)


if __name__ == "__main__":
    unittest.main()
