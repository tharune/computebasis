"""Independent invented books check price comparison, roles and admission holds."""
from copy import deepcopy
from decimal import localcontext
import unittest

from compute_pricing.control.domain import ValidationError
from compute_pricing.control.market_quotes import evaluate_quote_payload, quote_contract


def book():
    target = {
        "product_role": "spot", "hardware_model": "invented-accelerator-r8",
        "configuration": {"cpu_cores": "24", "ram_gib": "128", "storage_gib": "1800",
            "network_gbps": "2.5", "accelerator_memory_gib": "72", "accelerators_per_node": "2",
            "interconnect": "invented-link", "privacy_class": "isolated", "tenancy": "exclusive"},
        "region": {"scope": "country", "country_code": "CA", "subdivision": None, "locality": None},
        "provider_scope": {"kind": "all_declared_providers", "provider_id": None},
        "delivery_start": "2058-11-04T00:00:00Z", "delivery_end": "2058-11-05T00:00:00Z",
        "commitment_months": None, "payment_terms": "invoice after service; 14 calendar days",
        "cost_scope": {"power": "included", "network": "included", "support": "included",
                       "taxes": "excluded", "platform_fees": "included"},
        "unit": "gpu_hour", "currency": "USD", "quantity": "4", "quantity_unit": "gpu", "contract_spec": None,
    }
    quotes = []
    for identity, side, price, quality in (
        ("book:b1", "bid", "5.8", "0.9"), ("book:b2", "bid", "6", "0.05"),
        ("book:a1", "ask", "6.4", "0.8"), ("book:a2", "ask", "6.8", "0.95"),
    ):
        row = {key: deepcopy(value) for key, value in target.items() if key not in {"provider_scope", "quantity"}}
        row.update({"id": identity, "source_id": "invented-book:source", "provider_id": "invented-provider:r8",
                    "side": side, "price": price, "available_quantity": "8", "minimum_quantity": "2",
                    "observed_at": "2058-11-04T11:59:00Z", "expires_at": "2058-11-04T12:05:00Z",
                    "status": "verified", "quote_type": "firm", "evidence_ref": "invented-evidence:book",
                    "source_quality": quality,
                    "rights": {"status": "allowed", "observe": "PASS", "retain": "PASS", "benchmark": "PASS",
                               "execution": "PASS", "verified_by": "invented-review:book", "expires_at": None}})
        quotes.append(row)
    return {"as_of": "2058-11-04T12:00:00Z", "max_age_seconds": "120", "target": target, "quotes": quotes}


def rewrite_terms(packet, **changes):
    packet["target"].update(deepcopy(changes))
    for row in packet["quotes"]:
        row.update(deepcopy(changes))
    return packet


class ComparableQuoteTests(unittest.TestCase):
    def test_best_bid_ask_midpoint_is_not_a_weighted_or_all_quote_average(self):
        result = evaluate_quote_payload(book())
        self.assertEqual(result["status"], "comparable_two_sided")
        self.assertEqual(result["best_bid"]["quote_id"], "book:b2")
        self.assertEqual(result["best_ask"]["quote_id"], "book:a1")
        self.assertEqual(result["midpoint"], "6.2")
        self.assertEqual(result["spread"], "0.4")
        self.assertEqual(result["best_bid"]["declared_source_quality"], "0.05")
        self.assertEqual(result["best_bid"]["age_seconds"], "60")
        self.assertEqual(result["price_weighting"], "none_best_price_not_source_quality_weighted")
        for gate in ("source_evidence_eligible", "inventory_verified", "tradable", "firm_price_eligible", "execution_enabled"):
            self.assertFalse(result[gate])

    def test_crossed_book_never_emits_midpoint_and_locked_book_has_zero_spread(self):
        packet = book(); packet["quotes"][1]["price"] = "7"
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["midpoint"])
        self.assertIsNone(result["spread"])
        self.assertIn("crossed_comparable_book", result["hold_reasons"])
        packet["quotes"][1]["price"] = "6.4"
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["midpoint"], "6.4")
        self.assertEqual(result["spread"], "0")

    def test_ask_only_is_not_a_midpoint_or_a_two_sided_book(self):
        packet = book(); packet["quotes"] = packet["quotes"][2:]
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["best_bid"])
        self.assertEqual(result["best_ask"]["price"], "6.4")
        self.assertIsNone(result["midpoint"])
        self.assertIsNone(result["advertised_reference"])
        self.assertIn("two_sided_comparable_book_required", result["hold_reasons"])

    def test_stale_expired_future_unverified_rights_quotes_are_excluded(self):
        cases = [
            (lambda row: row.update(observed_at="2058-11-04T11:57:59Z"), "quote_future_or_stale"),
            (lambda row: row.update(observed_at="2058-11-04T12:00:01Z"), "quote_future_or_stale"),
            (lambda row: row.update(expires_at="2058-11-04T12:00:00Z"), "quote_expired_or_invalid_expiry"),
            (lambda row: row.update(expires_at=None), "quote_expiry_unknown"),
            (lambda row: row.update(status="claimed"), "quote_evidence_not_verified"),
            (lambda row: row.update(evidence_ref=None), "quote_evidence_unknown"),
            (lambda row: row["rights"].update(benchmark="UNKNOWN"), "source_permission_benchmark_not_pass"),
            (lambda row: row["rights"].update(execution="FAIL"), "source_permission_execution_not_pass"),
            (lambda row: row["rights"].update(verified_by=None), "permission_verifier_unknown"),
            (lambda row: row["rights"].update(expires_at="2058-11-04T11:59:59Z"), "source_permission_expired"),
        ]
        for change, reason in cases:
            packet = book(); packet["quotes"] = packet["quotes"][:2] + [packet["quotes"][2]]
            change(packet["quotes"][2])
            with self.subTest(reason=reason):
                result = evaluate_quote_payload(packet)
                self.assertIsNone(result["midpoint"])
                self.assertIn(reason, result["exclusions"][0]["reasons"])

    def test_each_quote_must_cover_size_no_aggregation_and_unknown_size_holds(self):
        for field, value, reason in (
            ("available_quantity", "3", "requested_quantity_outside_quote_size"),
            ("minimum_quantity", "5", "requested_quantity_outside_quote_size"),
            ("available_quantity", None, "quote_size_unknown"),
        ):
            packet = book()
            for row in packet["quotes"]:
                row[field] = value
            result = evaluate_quote_payload(packet)
            self.assertEqual(result["status"], "held")
            self.assertIsNone(result["midpoint"])
            self.assertTrue(all(reason in row["reasons"] for row in result["exclusions"]))
        packet = book(); packet["target"]["quantity"] = None
        result = evaluate_quote_payload(packet)
        self.assertIn("requested_quantity_unknown", result["hold_reasons"])
        self.assertIsNone(result["midpoint"])

    def test_gpu_request_and_both_quote_size_bounds_must_be_whole_nodes(self):
        packet = book()
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["midpoint"], "6.2")  # 4 requested /8 available /2 minimum on two-GPU nodes.
        packet["target"]["quantity"] = "3"
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["midpoint"])
        self.assertIn("requested_quantity_not_whole_nodes", result["hold_reasons"])
        for field, value, reason in (
            ("available_quantity", "3", "available_quantity_not_whole_nodes"),
            ("minimum_quantity", "1", "minimum_quantity_not_whole_nodes"),
        ):
            packet = book()
            for quote in packet["quotes"]:
                quote[field] = value
            result = evaluate_quote_payload(packet)
            self.assertEqual(result["status"], "held")
            self.assertIsNone(result["midpoint"])
            self.assertTrue(all(reason in row["reasons"] for row in result["exclusions"]))
        packet = rewrite_terms(book(), product_role="physical_forward", delivery_start="2059-05-01T00:00:00Z",
                               delivery_end="2059-05-31T00:00:00Z")
        packet["target"]["quantity"] = "3"
        self.assertIn("requested_quantity_not_whole_nodes", evaluate_quote_payload(packet)["hold_reasons"])
        packet = rewrite_terms(book(), quantity_unit="node", unit="node_hour")
        packet["target"]["quantity"] = "3"
        for quote in packet["quotes"]:
            quote.update(available_quantity="3", minimum_quantity="1")
        self.assertEqual(evaluate_quote_payload(packet)["midpoint"], "6.2")

    def test_unknown_source_quality_is_explicitly_excluded_without_zero_or_policy_default(self):
        packet = book()
        for quote in packet["quotes"][2:]:
            quote["source_quality"] = None
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["midpoint"])
        self.assertIsNone(result["best_ask"])
        self.assertTrue(all("source_quality_unknown" in row["reasons"] for row in result["exclusions"]))
        self.assertTrue(all(row["declared_source_quality"] in {"0.9", "0.05"} for row in result["admitted_quotes"]))

    def test_hardware_memory_allocation_location_payment_scope_unit_currency_are_exact(self):
        mutations = [
            (lambda r: r.update(hardware_model="invented-other-accelerator"), "hardware_model"),
            (lambda r: r["configuration"].update(accelerator_memory_gib="36"), "configuration"),
            (lambda r: r["configuration"].update(accelerators_per_node="4"), "configuration"),
            (lambda r: r["region"].update(country_code="US"), "region"),
            (lambda r: r.update(payment_terms="prepayment before delivery"), "payment_terms"),
            (lambda r: r["cost_scope"].update(power="excluded"), "cost_scope"),
            (lambda r: r.update(unit="node_hour"), "unit"),
            (lambda r: r.update(currency="CAD"), "currency"),
            (lambda r: r.update(delivery_end="2058-11-05T01:00:00Z"), "delivery_end"),
            (lambda r: r.update(quantity_unit="node"), "quantity_unit"),
        ]
        for mutate, field in mutations:
            packet = book(); packet["quotes"] = [packet["quotes"][0], packet["quotes"][2]]
            mutate(packet["quotes"][1])
            with self.subTest(field=field):
                result = evaluate_quote_payload(packet)
                self.assertIsNone(result["midpoint"])
                self.assertIn("incomparable_" + field, result["exclusions"][0]["reasons"])

    def test_unknown_terms_and_unregistered_configuration_keys_hold_without_pricing_them(self):
        for mutate, reason in (
            (lambda t: t.update(payment_terms=None), "payment_terms_unknown"),
            (lambda t: t["configuration"].update(privacy_class=None), "configuration_privacy_class_unknown"),
            (lambda t: t["cost_scope"].update(taxes="unknown"), "cost_scope_unknown"),
            (lambda t: t["configuration"].update(unreviewed_security_premium="0.2"), "unregistered_configuration_keys"),
        ):
            packet = book(); mutate(packet["target"])
            result = evaluate_quote_payload(packet)
            self.assertIsNone(result["midpoint"])
            self.assertIn(reason, result["hold_reasons"])
            self.assertFalse(result["admitted_quotes"])

    def test_single_provider_scope_filters_other_credit_and_delivery_counterparties(self):
        packet = book()
        packet["target"]["provider_scope"] = {"kind": "single_provider", "provider_id": "invented-provider:r8"}
        packet["quotes"][1].update(provider_id="invented-provider:other", price="20")
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["midpoint"], "6.1")
        self.assertIn("incomparable_provider", result["exclusions"][0]["reasons"])
        self.assertNotIn("broad_provider_scope_does_not_equalize_credit_or_delivery_risk", result["warnings"])

    def test_forward_is_future_start_and_never_comparable_to_spot(self):
        packet = rewrite_terms(book(), product_role="physical_forward", delivery_start="2059-05-01T00:00:00Z",
                               delivery_end="2059-05-31T00:00:00Z")
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["midpoint"], "6.2")
        self.assertEqual(result["product_role"], "physical_forward")
        packet["quotes"][2]["product_role"] = "spot"
        packet["quotes"][3]["product_role"] = "spot"
        result = evaluate_quote_payload(packet)
        self.assertIsNone(result["midpoint"])
        self.assertTrue(all("incomparable_product_role" in row["reasons"] for row in result["exclusions"]))
        rewrite_terms(packet, delivery_start="2058-11-04T00:00:00Z", product_role="physical_forward")
        self.assertIn("physical_forward_not_future_start", evaluate_quote_payload(packet)["hold_reasons"])

    def test_advertised_tenor_ask_median_has_no_midpoint_or_future_delivery(self):
        packet = rewrite_terms(book(), product_role="advertised_commitment", delivery_start=None, delivery_end=None,
                               commitment_months="18")
        packet["quotes"] = packet["quotes"][2:]
        for row in packet["quotes"]:
            row["quote_type"] = "advertised"
            row["rights"]["execution"] = "FAIL"
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["status"], "held")
        self.assertIsNone(result["midpoint"])
        self.assertIsNone(result["best_ask"])
        self.assertEqual(result["advertised_reference"]["ask_median"], "6.6")
        self.assertEqual(result["advertised_reference"]["basis"], "median_comparable_advertised_asks_not_midpoint")
        self.assertFalse(result["tradable"])
        packet["quotes"][1]["commitment_months"] = "24"
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["advertised_reference"]["ask_median"], "6.4")
        rewrite_terms(packet, delivery_start="2059-05-01T00:00:00Z", delivery_end="2059-05-31T00:00:00Z")
        result = evaluate_quote_payload(packet)
        self.assertIsNone(result["advertised_reference"])
        self.assertIn("advertised_tenor_is_not_future_start_delivery", result["hold_reasons"])

    def test_financial_future_explicit_spec_does_not_become_physical_inventory(self):
        spec = {"id": "invented-index:contract", "settlement": "cash", "multiplier": "540",
                "multiplier_unit": "gpu_hours", "expires_at": "2059-01-03T00:00:00Z"}
        packet = rewrite_terms(book(), product_role="financial_future", quantity_unit="contract", configuration={},
                               region=None, delivery_start="2058-12-01T00:00:00Z", delivery_end="2059-01-01T00:00:00Z",
                               contract_spec=spec, payment_terms="cash variation settlement each day")
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["midpoint"], "6.2")
        self.assertFalse(result["inventory_verified"])
        self.assertFalse(result["execution_enabled"])
        for row in packet["quotes"][2:]:
            row["contract_spec"]["multiplier"] = "730"
        result = evaluate_quote_payload(packet)
        self.assertIsNone(result["midpoint"])
        self.assertTrue(all("incomparable_contract_spec" in row["reasons"] for row in result["exclusions"]))
        rewrite_terms(packet, contract_spec=None)
        self.assertIn("financial_contract_spec_unknown", evaluate_quote_payload(packet)["hold_reasons"])

    def test_contract_expiry_and_negative_financial_price_are_explicit(self):
        spec = {"id": "invented-index:negative", "settlement": "cash", "multiplier": "90",
                "multiplier_unit": "contract", "expires_at": "2059-01-03T00:00:00Z"}
        packet = rewrite_terms(book(), product_role="financial_future", quantity_unit="contract", unit="contract",
                               configuration={}, region=None, delivery_start="2058-12-01T00:00:00Z",
                               delivery_end="2059-01-01T00:00:00Z", contract_spec=spec)
        packet["quotes"] = [packet["quotes"][0], packet["quotes"][2]]
        packet["quotes"][0]["price"] = "-2"
        packet["quotes"][1]["price"] = "1.5"
        self.assertEqual(evaluate_quote_payload(packet)["midpoint"], "-0.25")
        expired = deepcopy(spec); expired["expires_at"] = packet["as_of"]
        rewrite_terms(packet, contract_spec=expired)
        self.assertIn("financial_contract_expired", evaluate_quote_payload(packet)["hold_reasons"])

    def test_exact_decimal_normalization_precision_and_input_ownership(self):
        packet = book(); packet["quotes"][2]["configuration"]["ram_gib"] = "128.0"
        original = deepcopy(packet)
        result = evaluate_quote_payload(packet)
        self.assertEqual(result["midpoint"], "6.2")
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(evaluate_quote_payload(packet), result)
        self.assertEqual(packet, original)
        packet["target"]["configuration"]["ram_gib"] = "4"
        self.assertEqual(result["target"], original["target"])

    def test_float_exponent_unknown_top_fields_and_duplicate_ids_are_rejected(self):
        for mutate in (
            lambda p: p["quotes"][0].update(price=5.8),
            lambda p: p["quotes"][0].update(price="5.8e0"),
            lambda p: p["quotes"][0].update(price="NaN"),
            lambda p: p["target"].update(quantity="1.5"),
            lambda p: p["quotes"][0].update(available_quantity="2.5"),
            lambda p: p["target"]["configuration"].update(accelerators_per_node="1.5"),
            lambda p: p.update(secret_conversion_rate="1"),
            lambda p: p["quotes"][0].update(unregistered_price_adjustment="0.5"),
            lambda p: p["quotes"][1].update(id=p["quotes"][0]["id"]),
            lambda p: p.update(as_of="2058-11-04T12:00:00+00:00"),
        ):
            packet = book(); mutate(packet)
            with self.assertRaises(ValidationError): evaluate_quote_payload(packet)

    def test_contract_lists_roles_and_no_implicit_market_or_inventory_permission(self):
        contract = quote_contract()
        self.assertEqual(set(contract["product_roles"]), {"spot", "physical_forward", "financial_future", "advertised_commitment"})
        self.assertIn("accelerator_memory_gib", contract["configuration_fields"])
        self.assertIn("commitment_months", contract["quote_fields"])
        self.assertFalse(contract["firm_price_eligible"])
        self.assertFalse(contract["execution_enabled"])


if __name__ == "__main__":
    unittest.main()
