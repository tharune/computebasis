"""Independently invented examples verify load conservation and cost ownership."""
from copy import deepcopy
from decimal import localcontext
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from compute_pricing.control.api import create_app
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.power import evaluate_power_payload, power_contract
from compute_pricing.control.api.power_reference import evaluate_reference_power


def allocation():
    return {"currency": "EUR", "gpu_count": "3", "idle_watts_per_gpu": "80",
        "load_watts_per_gpu": "420", "shared_it_watts": "180", "pue": "1.2",
        "sold_gpu_hours": "9", "compute_power_inclusion": "excluded", "evidence_basis": "invented allocation",
        "intervals": [{"starts_at": "2048-06-02T00:00:00Z", "ends_at": "2048-06-02T10:00:00Z",
            "utilization": "0.25", "rate": {"currency": "EUR", "amount_per_kwh": "0.16",
                "basis": "declared_tariff_energy", "evidence_ref": "invented tariff assertion"}}],
        "demand_charges": [], "cost_items": []}


def reference_packet():
    profile = allocation(); profile.pop("intervals"); profile["sold_gpu_hours"] = "0.5"
    return {"profile": profile, "reference": {"source_id": "energinet_day_ahead", "price_area": "DK2",
        "currency": "EUR", "starts_at": "2048-06-02T00:00:00Z", "ends_at": "2048-06-02T00:30:00Z", "utilization": "0.25"}}


def retained():
    shared = {"source_id": "energinet_day_ahead", "price_area": "DK2", "kind": "energy_market_reference",
        "native_unit": "MWh", "market": "day_ahead", "interval_minutes": 15, "index_stale": False,
        "snapshot_id": "c" * 64}
    rows = [{**shared, "starts_at": "2048-06-02T00:00:00Z", "ends_at": "2048-06-02T00:15:00Z",
        "native_prices": {"EUR": "-40", "DKK": "-300"}},
        {**shared, "starts_at": "2048-06-02T00:15:00Z", "ends_at": "2048-06-02T00:30:00Z",
        "native_prices": {"EUR": "240", "DKK": "1800"}}]
    return {"as_of": "2048-06-02T01:00:00Z", "catalog_records": rows}


class AllocatedElectricityTests(unittest.TestCase):
    def test_three_gpus_independent_watt_hour_oracle(self):
        result = evaluate_power_payload(allocation())
        # 3 * (80*0.75 +420*0.25) +180 =675 IT W; PUE1.2=>810W.
        self.assertEqual(result["energy_kwh"], "8.1")
        self.assertEqual(result["facility_power_cost"], "1.296")
        self.assertEqual(result["capacity_gpu_hours"], "30")
        self.assertEqual(result["unsold_gpu_hours"], "21")
        self.assertEqual(result["facility_cost_per_capacity_gpu_hour"], "0.0432")
        self.assertEqual(result["facility_cost_per_sold_gpu_hour"], "0.144")
        self.assertFalse(result["execution_enabled"])

    def test_idle_unsold_capacity_has_cost_but_no_sold_hour_denominator(self):
        inputs = allocation(); inputs["sold_gpu_hours"] = "0"; inputs["intervals"][0]["utilization"] = "0"
        result = evaluate_power_payload(inputs)
        self.assertEqual(result["energy_kwh"], "5.04")
        self.assertEqual(result["facility_power_cost"], "0.8064")
        self.assertIsNone(result["facility_cost_per_sold_gpu_hour"])

    def test_compute_quote_inclusion_and_missing_are_distinct(self):
        inputs = allocation(); inputs["compute_power_inclusion"] = "included"
        self.assertEqual(evaluate_power_payload(inputs)["incremental_compute_power_cost"], "0")
        inputs["compute_power_inclusion"] = "unknown"
        result = evaluate_power_payload(inputs)
        self.assertIsNone(result["incremental_compute_power_cost"])
        self.assertIn("compute_quote_power_inclusion_unknown", result["blockers"])
        inputs.pop("compute_power_inclusion")
        with self.assertRaises(ValidationError): evaluate_power_payload(inputs)

    def test_demand_period_peaks_use_their_own_full_coverage(self):
        inputs = allocation(); first = inputs["intervals"][0]; first["utilization"] = "0"
        second = deepcopy(first); second.update(starts_at=first["ends_at"], ends_at="2048-06-02T20:00:00Z", utilization="1")
        inputs["intervals"].append(second)
        inputs["demand_charges"] = [{"billing_period_id": "invented off-peak", "starts_at": first["starts_at"],
            "ends_at": first["ends_at"], "allocated_peak_kw": "0.504", "amount_per_kw": "6", "currency": "EUR"},
            {"billing_period_id": "invented peak", "starts_at": second["starts_at"], "ends_at": second["ends_at"],
            "allocated_peak_kw": "1.728", "amount_per_kw": "6", "currency": "EUR"}]
        self.assertEqual(evaluate_power_payload(inputs)["demand_cost"], "13.392")
        for case in ("partial", "overlap", "understated", "duplicate", "missing"):
            changed = deepcopy(inputs)
            if case == "partial": changed["demand_charges"][0]["starts_at"] = "2048-06-01T23:00:00Z"
            elif case == "overlap": changed["demand_charges"][1]["starts_at"] = "2048-06-02T09:00:00Z"
            elif case == "understated": changed["demand_charges"][1]["allocated_peak_kw"] = "1"
            elif case == "duplicate": changed["demand_charges"][1]["billing_period_id"] = changed["demand_charges"][0]["billing_period_id"]
            else: changed["demand_charges"][0].pop("ends_at")
            with self.subTest(case=case), self.assertRaises(ValidationError): evaluate_power_payload(changed)

    def test_all_in_references_cannot_gain_duplicated_tariff_charges(self):
        inputs = allocation(); inputs["intervals"][0]["rate"]["basis"] = "retail_all_in_reference"
        self.assertEqual(evaluate_power_payload(inputs)["status"], "held")
        inputs["cost_items"] = [{"id": "invented tax", "currency": "EUR", "scope": "tax", "amount": "2.4"}]
        with self.assertRaises(ValidationError): evaluate_power_payload(inputs)

    def test_negative_wholesale_amount_preserved_without_credit_inference(self):
        inputs = allocation(); inputs["intervals"][0]["rate"].update(amount_per_kwh="-0.08", basis="wholesale_reference")
        result = evaluate_power_payload(inputs)
        self.assertEqual(result["energy_cost"], "-0.648")
        self.assertEqual(result["status"], "held")
        self.assertIn("negative_energy_cost_requires_contract_credit_terms", result["blockers"])

    def test_registered_contract_and_precision_do_not_depend_on_decimal_context(self):
        self.assertIn("starts_at", power_contract()["demand_fields"])
        self.assertFalse(power_contract()["missing_is_zero"])
        expected = evaluate_power_payload(allocation())
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(evaluate_power_payload(allocation()), expected)

    def test_wrong_currency_fractional_count_gaps_and_unknown_fields_refused(self):
        for case in ("currency", "count", "gap", "unknown", "sale", "float"):
            inputs = allocation()
            if case == "currency": inputs["intervals"][0]["rate"]["currency"] = "USD"
            elif case == "count": inputs["gpu_count"] = "2.5"
            elif case == "gap":
                second = deepcopy(inputs["intervals"][0]); second.update(starts_at="2048-06-02T10:00:01Z", ends_at="2048-06-02T12:00:00Z")
                inputs["intervals"].append(second)
            elif case == "unknown": inputs["automatic_premium"] = "2"
            elif case == "sale": inputs["sold_gpu_hours"] = "31"
            else: inputs["pue"] = 1.2
            with self.subTest(case=case), self.assertRaises(ValidationError): evaluate_power_payload(inputs)

    def test_calendar_duration_uses_leap_day_without_fixed_month_assumption(self):
        inputs = allocation(); inputs["intervals"][0].update(starts_at="2048-02-28T00:00:00Z", ends_at="2048-03-01T00:00:00Z")
        self.assertEqual(evaluate_power_payload(inputs)["powered_hours"], "48")

    def test_server_reference_conversion_has_no_client_price_and_no_duplicate_energy(self):
        index = retained(); index["catalog_records"].append(deepcopy(index["catalog_records"][0]))
        result = evaluate_reference_power(reference_packet(), index)
        self.assertEqual(result["energy_kwh"], "0.405")
        self.assertEqual(result["energy_cost"], "0.0405")
        self.assertEqual(result["source_binding"]["reference_intervals"], 2)
        self.assertEqual(result["status"], "held")
        self.assertEqual(result["source_binding"]["snapshot_ids"], ["c" * 64])
        with localcontext() as context:
            context.prec = 1
            self.assertEqual(evaluate_reference_power(reference_packet(), index)["energy_cost"], "0.0405")

    def test_bad_retained_duplicate_cannot_hide_behind_a_valid_record(self):
        for case in ("unit", "nativecurrency", "shape", "snapshot", "source_interval", "conflict", "stale", "gap"):
            index = retained(); bad = deepcopy(index["catalog_records"][0])
            if case == "unit": bad["native_unit"] = "kWh"
            elif case == "nativecurrency": bad["native_prices"] = {"USD": "3"}
            elif case == "shape": bad["market"] = "imbalance"
            elif case == "snapshot": bad["snapshot_id"] = "unverified"
            elif case == "source_interval": bad["interval_minutes"] = 60
            elif case == "conflict": bad["native_prices"]["EUR"] = "-39"
            elif case == "stale": index["catalog_records"][0]["index_stale"] = True
            else: index["catalog_records"].pop()
            if case not in {"stale", "gap"}: index["catalog_records"].insert(0, bad)
            with self.subTest(case=case), self.assertRaises(ValidationError): evaluate_reference_power(reference_packet(), index)

    def test_invalid_client_reference_selection_is_always_a_domain_error(self):
        for case in ("price", "currency", "arraycurrency", "area"):
            packet = reference_packet()
            if case == "price": packet["reference"]["amount_per_kwh"] = "0.02"
            elif case == "currency": packet["reference"]["currency"] = "USD"
            elif case == "arraycurrency": packet["reference"]["currency"] = []
            else: packet["reference"]["price_area"] = "unknown area"
            with self.subTest(case=case), self.assertRaises(ValidationError): evaluate_reference_power(packet, retained())

    def test_authenticated_routes_persist_declared_model_without_collecting(self):
        token = "test-auth-token-" + "7" * 24
        with TemporaryDirectory() as folder:
            app = create_app(api_key=token, store_path=Path(folder) / "decisions.sqlite")
            with TestClient(app) as client:
                self.assertEqual(client.get("/v1/power/contract").status_code, 401)
                headers = {"Authorization": "Bearer " + token}
                self.assertEqual(client.get("/v1/power/contract", headers=headers).status_code, 200)
                accepted = client.post("/v1/power/evaluate", headers=headers, json=allocation())
                self.assertEqual(accepted.status_code, 200, accepted.text)
                self.assertEqual(accepted.json()["versions"]["evaluation.model"], "allocated-power-cost/1.0.0")
                self.assertFalse(accepted.json()["execution_enabled"])
                self.assertEqual(client.post("/v1/power/from-reference", headers=headers, json=reference_packet()).status_code, 422)
                invalid = reference_packet(); invalid["reference"]["currency"] = []
                self.assertEqual(client.post("/v1/power/from-reference", headers=headers, json=invalid).status_code, 422)


if __name__ == "__main__": unittest.main()
