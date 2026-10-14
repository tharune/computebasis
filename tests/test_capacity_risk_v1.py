"""Physical exclusivity, baseline concentration and shared funding checks."""

import sys
import unittest
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compute_pricing.control.capacity import CapacityLot, Maintenance, Reservation, validate_capacity
from compute_pricing.control.risk import (CashScenario, Exposure, ExposureLimit, LossComponent,
                        assess_exposures, attribute_losses, evaluate_scenarios)
from compute_pricing.control.treasury import CashEvent


START = "2024-01-01T00:00:00Z"
CUTOVER = "2024-01-02T00:00:00Z"
END = "2024-01-03T00:00:00Z"


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.lot = CapacityLot("lot-a", "site-a", "gpu", ("gpu-a", "gpu-b"), START, END)

    def reservation(self, key, units=("gpu-a",), start=START, end=CUTOVER):
        return Reservation(key, "allocation-a", "lot-a", units, start, end)

    def test_forward_cutover_is_half_open_and_exact(self):
        result = validate_capacity([self.lot], [self.reservation("early"),
            self.reservation("later", start=CUTOVER, end=END)])
        self.assertEqual(result.reservation_unit_seconds["early"], 86400)
        self.assertEqual(result.remaining_unit_seconds["lot-a"], 172800)

    def test_aggregate_quantity_cannot_hide_same_physical_gpu_sale(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_capacity([self.lot], [self.reservation("buyer-a"), self.reservation("buyer-b")])
        report = validate_capacity([self.lot], [self.reservation("buyer-a"), self.reservation("buyer-b", units=("gpu-b",))])
        self.assertEqual(len(report.reservation_unit_seconds), 2)

    def test_maintenance_blocks_units_without_blocking_other_units(self):
        maintenance = Maintenance("service-a", "lot-a", ("gpu-a",), START, CUTOVER)
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_capacity([self.lot], [self.reservation("buyer-a")], [maintenance])
        validate_capacity([self.lot], [self.reservation("buyer-b", units=("gpu-b",))], [maintenance])

    def test_lot_availability_and_physical_identity_are_verified(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_capacity([self.lot], [self.reservation("unknown", units=("gpu-x",))])
        with self.assertRaisesRegex(ValueError, "availability"):
            validate_capacity([self.lot], [self.reservation("late", end="2024-01-04T00:00:00Z")])
        duplicate_supply = CapacityLot("lot-b", "site-b", "gpu", ("gpu-a",), START, END)
        with self.assertRaisesRegex(ValueError, "overlapping supply"):
            validate_capacity([self.lot, duplicate_supply], [])
        later_supply = CapacityLot("lot-c", "site-a", "gpu", ("gpu-a",), END, "2024-01-04T00:00:00Z")
        validate_capacity([self.lot, later_supply], [])

    def test_invalid_time_unit_and_duplicate_entries_rejected(self):
        with self.assertRaises(ValueError):
            self.reservation("offset", start="2024-01-01T00:00:00+00:00")
        with self.assertRaises(ValueError):
            self.reservation("empty", start=CUTOVER, end=CUTOVER)
        with self.assertRaises(ValueError):
            self.reservation("duplicate", units=("gpu-a", "gpu-a"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_capacity([self.lot], [self.reservation("same"), self.reservation("same", units=("gpu-b",))])


class RiskTests(unittest.TestCase):
    def exposure(self, key, amount="60", currency="USD"):
        return Exposure(key, "buyer-a", "parent-a", "site-a", currency, amount)

    def limits(self, maximum="100", currency="USD"):
        return [ExposureLimit(f"limit-{scope}-{currency}", scope, member, currency, maximum)
                for scope, member in (("entity", "buyer-a"), ("group", "parent-a"), ("site", "site-a"), ("currency", currency))]

    def test_candidate_and_baseline_aggregate_each_mandatory_scope(self):
        result = assess_exposures([self.exposure("baseline"), self.exposure("candidate")], self.limits())
        self.assertFalse(result.admitted)
        self.assertEqual(len([limit for limit in result.limits if limit.breached]), 4)
        self.assertEqual(result.totals[("group", "parent-a", "USD")], 120)
        self.assertTrue(assess_exposures([self.exposure("small", "40")], self.limits()).admitted)

    def test_missing_policy_or_duplicate_exposure_is_not_admitted(self):
        result = assess_exposures([self.exposure("candidate")], self.limits()[:2])
        self.assertFalse(result.admitted)
        self.assertEqual(len(result.uncovered), 2)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            assess_exposures([self.exposure("same"), self.exposure("same")], self.limits())
        with self.assertRaisesRegex(ValueError, "coverage"):
            assess_exposures([self.exposure("candidate")], [*self.limits(), ExposureLimit("extra", "group", "parent-a", "USD", "1000")])

    def test_currency_totals_do_not_imply_fx_netting(self):
        report = assess_exposures([self.exposure("usd", "60"), self.exposure("eur", "60", "EUR")], [*self.limits(), *self.limits(currency="EUR")])
        self.assertTrue(report.admitted)
        self.assertEqual(report.totals[("group", "parent-a", "USD")], 60)
        self.assertEqual(report.totals[("group", "parent-a", "EUR")], 60)

    def test_small_excess_over_large_limit_is_not_rounded_away(self):
        large = "1234567890123456789012345678901234567890"
        tiny = "0.000000000000000000000000000000000000001"
        result = assess_exposures([self.exposure("baseline", large), self.exposure("candidate", tiny)], self.limits(large))
        self.assertFalse(result.admitted)
        self.assertTrue(all(item.breached for item in result.limits))

    def test_loss_ownership_is_nonoverlapping_and_reporting_only(self):
        supplier = LossComponent("supplier", "default-a", "supplier_credit", "USD", "20", ("replacement-pay",))
        self.assertEqual(attribute_losses([supplier]), {("USD", "supplier_credit"): Decimal("20")})
        with self.assertRaisesRegex(ValueError, "ownership"):
            attribute_losses([supplier, LossComponent("replacement", "default-a", "replacement", "USD", "20", ())])
        with self.assertRaisesRegex(ValueError, "overlapping"):
            attribute_losses([supplier, LossComponent("replacement", "different-a", "replacement", "USD", "20", ("replacement-pay",))])

    def test_joint_cash_stress_cannot_fund_two_deals_with_one_balance(self):
        events = (CashEvent("deal-a", "cost-a", "2024-01-01", "other_outflow", "60", "USD"),
                  CashEvent("deal-b", "cost-b", "2024-01-01", "other_outflow", "60", "USD"))
        report = evaluate_scenarios([CashScenario("joint-stress", events)], legal_entity_id="operator-a", cash_account_id="bank-a", currency="USD", opening_cash="100", start_date="2024-01-01", end_date="2024-01-02")
        self.assertEqual(report.worst_required_extra_cash, 20)
        self.assertIsNone(report.expected_required_extra_cash)

    def test_probabilities_are_only_explicit_and_complete(self):
        shared = dict(legal_entity_id="operator-a", cash_account_id="bank-a", currency="USD", opening_cash="0", start_date="2024-01-01", end_date="2024-01-01")
        outflow = (CashEvent("cost", "cost-obligation", "2024-01-01", "other_outflow", "100", "USD"),)
        report = evaluate_scenarios([CashScenario("base", (), probability="0.75"), CashScenario("stress", outflow, probability="0.25")], **shared)
        self.assertEqual(report.expected_required_extra_cash, 25)
        with self.assertRaisesRegex(ValueError, "every path"):
            evaluate_scenarios([CashScenario("base", ()), CashScenario("stress", outflow, probability="0.25")], **shared)
        with self.assertRaisesRegex(ValueError, "exactly"):
            evaluate_scenarios([CashScenario("base", (), probability="0.70"), CashScenario("stress", outflow, probability="0.25")], **shared)
        with self.assertRaisesRegex(ValueError, "missing cash"):
            CashScenario("bad-loss", (), losses=(LossComponent("loss", "ownership", "refund", "USD", "1", ("missing",)),))


if __name__ == "__main__":
    unittest.main()
