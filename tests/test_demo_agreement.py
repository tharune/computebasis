"""Fresh invented evaluated schedules test unsigned PDF bindings, not legal effect."""
from copy import deepcopy
import hashlib
from io import BytesIO
import unittest
from unittest.mock import patch

from pypdf import PdfReader

from compute_pricing.control.demo_pricing.agreement import MARKING, render_agreement_pdf
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.reporting.store import canonical_document


def seal(document):
    return {"snapshot_id": hashlib.sha256(canonical_document(document, max_bytes=2 * 1024 * 1024).encode()).hexdigest(),
        "created_at": "2043-05-09T15:20:00Z", "document": document}


def fixture(mode="invoice"):
    terms = {"classification": "synthetic", "execution_enabled": False,
        "provider": {"id": "invented-doc-provider-04", "label": "Example Contract Supplier",
            "credit_score": "87", "credit_band": "B", "uptime_fraction": "0.996",
            "sla_fraction": "0.99", "response_hours": "3", "compliance": "Declared SOC 2 claim - unverified",
            "privacy": "Declared isolated tenant - unverified", "ratings": {"credit": 3}},
        "capacity": {"model": "Example Accelerator", "memory_gib": 80, "gpus_per_node": 8,
            "node_count": 2, "total_gpu_count": 16, "country_code": "GB", "location": "Invented West Site",
            "colocation": "Demo Colocation Host - invented facility", "ownership": "declared supplier-owned nodes",
            "starts_at": "2043-05-11T00:00:00Z", "ends_at": "2043-05-18T00:00:00Z"},
        "pricing": {"currency": "USD", "price_unit": "gpu_hour", "supplier_rate": "4.13",
            "rate_type": "fixed" if mode == "invoice" else "variable", "variable_low": "3.89", "variable_high": "4.57",
            "buyer_rate": "6.12", "billed_utilization": "0.81", "collection_share": "0.97",
            "fee_on_collected": "0.009", "fee_on_gross": "0.006", "required_margin": "0.1",
            "target_margin": "0.17", "tick_size": "0.01", "fixed_operating_cost": "139.42",
            "risk_allowance_per_gpu_hour": "0.09", "discount_apr": "0.07", "power": {"idle_watts_per_gpu": "70", "load_watts_per_gpu": "680",
                "shared_it_watts": "310", "pue": "1.19", "utilization": "0.81", "tariff_per_kwh": "0.071",
                "inclusion": "excluded", "cost_owner": "invented-power-model/1.0", "payer": "broker"}},
        "settlement": {"mode": mode, "buyer_label": "Example Contract Buyer", "down_payment_fraction": "0.31", "financing_apr": "0.082",
            "provider_collateral_usd": "600.17", "collateral_owner": "supplier", "vesting_basis": "available_sla",
            "prefunded_principal": "17111.34", "asset_kind": "bank_deposit" if mode != "stable_asset" else "stable_asset",
            "asset_unit": "USD" if mode != "stable_asset" else "SIMUNIT", "asset_price_usd": "1",
            "liquidity": "liquid", "depeg_status": "not_applicable" if mode != "stable_asset" else "normal",
            "yield_apr": "0.025", "yield_share_provider": "0.15", "yield_share_broker": "0.2",
            "yield_share_buyer": "0.65", "yield_access": "accrued_only", "release_authorized": True, "refund_at_end": True, "buffer_hours": 12},
        "treasury": {"opening_cash": "16000.31", "minimum_cash": "1000", "supplier_payment_on": "2043-05-11", "supplier_balance_on": "2043-05-18",
            "buyer_invoice_on": "2043-05-18", "buyer_receipt_on": "2043-05-20", "operating_cost_on": "2043-05-11",
            "fees_on": "2043-05-20", "writeoff_on": "2043-05-20"},
        "summary": {"supplier_rate": "4.13", "purchase_ceiling": "4.61", "sell_floor": "5.47",
            "target_ask": "5.91", "expected_margin": "0.157", "expected_profit": "1521.369",
            "margin_basis": "gross_billings", "cash_required": "7311.22", "npv": "1381.017", "npv_basis": "declared_ACT365_operating_cash",
            "irr": None, "irr_basis": "equity_timeline_not_declared"}}
    document = {"schema_version": "compute-snapshot/1.0", "kind": "demo_pricing",
        "input": {"example_id": "independently-invented-document-example", "opaque_extension": "UNRENDERED-EXTENSION"},
        "output": {"classification": "synthetic", "execution_enabled": False, "executable": False,
            "firm_price_eligible": False, "agreement_terms": terms},
        "versions": {"evaluation.model": "invented-test-model/1.0"}}
    return seal(document)


def pages(receipt):
    return PdfReader(BytesIO(render_agreement_pdf(receipt)))


class DemoAgreementTests(unittest.TestCase):
    def test_three_pages_each_unsigned_marked_and_receipt_bound(self):
        receipt = fixture()
        reader = pages(receipt)
        self.assertEqual(len(reader.pages), 3)
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            self.assertGreaterEqual(text.count(MARKING), 2)
            self.assertIn(receipt["snapshot_id"][:12], text)
            self.assertIn(str(index) + " of 3", text)
            self.assertEqual(float(page.mediabox.width), 612)
            self.assertEqual(float(page.mediabox.height), 792)
        text = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn(receipt["snapshot_id"][:32], text)
        self.assertIn(receipt["snapshot_id"][32:], text)
        self.assertIn("2043-05-09T15:20:00Z", text)
        self.assertIn("invented-test-model/1.0", text)

    def test_capacity_service_price_and_economics_are_populated_without_recalculating(self):
        text = "\n".join(page.extract_text() for page in pages(fixture()).pages)
        for term in ("Example Accelerator", "2 nodes x 8 GPUs = 16 GPUs", "Invented West Site",
                "2043-05-11T00:00:00Z", "2043-05-18T00:00:00Z", "USD 4.13 / GPU-hour",
                "USD 5.47 / GPU-hour", "USD 5.91 / GPU-hour", "USD 1,521.37", "gross billings",
                "USD 1,381.02", "31.00%", "8.20%", "15.70%", "20.00%", "65.00%"):
            self.assertIn(term, text)
        self.assertIn("no duplicate all-in charge", " ".join(text.split()))
        self.assertIn("invoice application is noncash", text)

    def test_three_settlement_scenarios_render_and_native_asset_kept_separate(self):
        for mode in ("invoice", "bank_escrow", "stable_asset"):
            with self.subTest(mode=mode):
                reader = pages(fixture(mode))
                self.assertEqual(len(reader.pages), 3)
                text = "\n".join(page.extract_text() for page in reader.pages)
                self.assertIn("Declared settlement mode: " + mode, text)
                if mode == "stable_asset": self.assertIn("17111.34 SIMUNIT", text)

    def test_legal_authority_and_missing_returns_remain_unresolved(self):
        receipt = fixture()
        receipt["document"]["output"]["agreement_terms"]["summary"].update(npv=None,irr=None)
        reader = pages(seal(receipt["document"]))
        text = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn("Governing law: UNRESOLVED", text)
        self.assertIn("Signature authority: UNRESOLVED", text)
        self.assertIn("Signatures: NOT EXECUTED", text)
        self.assertIn("Unresolved / not supplied", text)
        self.assertNotIn("USD 0.00 / 0.00%", text)

    def test_inactive_escrow_and_accrued_only_yield_do_not_imply_spendable_principal(self):
        text = " ".join(page.extract_text() for page in pages(fixture("milestone")).pages)
        text = " ".join(text.split())
        self.assertIn("Inactive in milestone mode; escrow/yield inputs do not create a contract", text)
        self.assertIn("access accrued only", text)
        self.assertIn("Accrued yield, spendable cash and party entitlements remain separate", text)

    def test_evaluated_party_labels_and_only_selected_terms_are_displayed(self):
        reader = pages(fixture())
        text = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn("Example Contract Supplier", text)
        self.assertIn("Example Contract Buyer", text)
        self.assertNotIn("UNRENDERED-EXTENSION", text)
        self.assertEqual(reader.metadata.author, "ComputeBasis")

    def test_edited_supplier_and_buyer_labels_bind_to_evaluated_receipt(self):
        receipt = fixture()
        terms = receipt["document"]["output"]["agreement_terms"]
        terms["provider"]["label"] = "Edited Demo Supplier <b>literal</b>"
        terms["settlement"]["buyer_label"] = "Edited Demo Buyer"
        text = " ".join(page.extract_text() for page in pages(seal(receipt["document"])).pages)
        self.assertIn("Edited Demo Supplier <b>literal</b>", text)
        self.assertIn("Edited Demo Buyer", text)
        self.assertNotIn("Example Contract Supplier", text)
        self.assertNotIn("Example Contract Buyer", text)
        receipt = fixture(); terms = receipt["document"]["output"]["agreement_terms"]
        terms["settlement"]["buyer_label"] = None
        with self.assertRaises(ValidationError): render_agreement_pdf(seal(receipt["document"]))

    def test_input_values_are_text_not_html_links_or_external_assets(self):
        receipt = fixture()
        receipt["document"]["output"]["agreement_terms"]["provider"]["compliance"] = '<b>literal claim</b>'
        receipt = seal(receipt["document"])
        with patch("socket.create_connection", side_effect=AssertionError("No external request")), \
                patch("reportlab.lib.utils.ImageReader", side_effect=AssertionError("No external image")):
            reader = pages(receipt)
        text = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn("<b>literal claim</b>", text)
        for page in reader.pages:
            self.assertFalse(page.get("/Annots"))
        self.assertNotIn("/AcroForm", reader.trailer["/Root"])

    def test_tampered_receipt_and_non_demo_documents_rejected(self):
        receipt = fixture(); receipt["document"]["output"]["agreement_terms"]["pricing"]["supplier_rate"] = "0.01"
        with self.assertRaisesRegex(ValidationError, "integrity"):
            render_agreement_pdf(receipt)
        for kind in ("pricing", "cash", "market_collection"):
            receipt = fixture(); receipt["document"]["kind"] = kind
            with self.assertRaisesRegex(ValidationError, "demo-pricing"):
                render_agreement_pdf(seal(receipt["document"]))
        with self.assertRaises(ValidationError): render_agreement_pdf({"result": fixture()["document"]["output"]})

    def test_firm_live_or_unsigned_boundary_override_cannot_render(self):
        for changes in ({"classification": "live"}, {"execution_enabled": True}, {"executable": True}, {"firm_price_eligible": True}):
            receipt = fixture(); receipt["document"]["output"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                render_agreement_pdf(seal(receipt["document"]))

    def test_whole_allocation_units_and_required_sections_not_guessed(self):
        for category, changes in (("capacity", {"gpus_per_node": True}), ("capacity", {"node_count": "2"}),
                ("capacity", {"total_gpu_count": 17}), ("pricing", {"currency": "EUR"}), ("pricing", {"price_unit": None})):
            receipt = fixture(); receipt["document"]["output"]["agreement_terms"][category].update(changes)
            with self.subTest(category=category, changes=changes), self.assertRaises(ValidationError):
                render_agreement_pdf(seal(receipt["document"]))
        receipt = fixture(); del receipt["document"]["output"]["agreement_terms"]["summary"]
        with self.assertRaises(ValidationError): render_agreement_pdf(seal(receipt["document"]))

    def test_bounded_numeric_and_text_inputs_fail_without_hidden_rounding_or_clipping(self):
        for value in ("NaN", "1e12", True, "9" * 80):
            receipt = fixture(); receipt["document"]["output"]["agreement_terms"]["summary"]["expected_profit"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValidationError):
                render_agreement_pdf(seal(receipt["document"]))
        for value in ("unsafe\x00value", "a" * 513):
            receipt = fixture(); receipt["document"]["output"]["agreement_terms"]["provider"]["privacy"] = value
            with self.assertRaises(ValidationError): render_agreement_pdf(seal(receipt["document"]))

    def test_repeated_render_is_deterministic_and_does_not_mutate_receipt(self):
        receipt = fixture(); before = deepcopy(receipt)
        first, second = render_agreement_pdf(receipt), render_agreement_pdf(receipt)
        self.assertTrue(first.startswith(b"%PDF-"))
        self.assertEqual(first, second)
        self.assertEqual(receipt, before)

    def test_calculated_high_precision_rates_are_marked_as_rounded_not_clipped(self):
        receipt = fixture()
        summary = receipt["document"]["output"]["agreement_terms"]["summary"]
        summary["sell_floor"] = "2." + "3" * 160
        summary["expected_margin"] = "0." + "2" * 160
        sealed = seal(receipt["document"])
        before = deepcopy(sealed)
        text = " ".join(page.extract_text() for page in pages(sealed).pages)
        self.assertIn("USD ~2.333333 / GPU-hour", text)
        self.assertIn("22.22%", text)
        self.assertEqual(sealed, before)


if __name__ == "__main__": unittest.main()
