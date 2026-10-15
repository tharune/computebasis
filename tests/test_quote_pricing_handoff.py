"""Backend side of "Price this quote": the ask of any simulated book quote is accepted by the Pricing demo evaluator as a fixed supplier rate."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from compute_pricing.control.api import create_app
from compute_pricing.control.demo_pricing import demo_contract
from compute_pricing.control.quote_book import QuoteBook


def with_ask(inputs, quote):
    """A fixed ask: the supplier rate is the quote's price and the variable range collapses to it. Nothing else changes."""
    priced = deepcopy(inputs)
    priced["pricing"].update(supplier_rate=str(quote["price"]), rate_type="fixed", variable_low=str(quote["price"]), variable_high=str(quote["price"]))
    return priced


class QuotePricingHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quotes = sorted(QuoteBook().snapshot()["quotes"], key=lambda quote: float(quote["price"]))
        cls.contract = demo_contract()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.key = "invented-quote-handoff-reader-token-0032"
        self.auth = {"Authorization": "Bearer " + self.key}
        self.client = TestClient(create_app(api_key=self.key, store_path=Path(self.folder.name) / "pricing.sqlite"))

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def evaluate(self, inputs):
        response = self.client.post("/v1/pricing/demo/evaluate", headers=self.auth, json=inputs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_cheap_median_and_dear_book_quotes_are_accepted_as_scenario_estimates_that_cannot_execute(self):
        for scenario in self.contract["scenarios"]:
            for quote in (self.quotes[0], self.quotes[len(self.quotes) // 2], self.quotes[-1]):
                with self.subTest(scenario=scenario["id"], quote=quote["id"], price=quote["price"]):
                    receipt = self.evaluate(with_ask(scenario["inputs"], quote))
                    result = receipt["result"]
                    self.assertFalse(receipt["execution_enabled"])
                    self.assertIn(result["status"], {"scenario_estimate", "held"})
                    self.assertEqual(result["summary"]["supplier_rate"], str(quote["price"]), "the ask keeps the quote's exact decimal text")
                    self.assertFalse(result["firm_price_eligible"])
                    self.assertFalse(result["source_evidence_eligible"])
                    self.assertIsNone(result["pricing"]["bid"])

    def test_the_selling_floor_follows_the_quotes_ask_and_nothing_else_moves(self):
        cheap, dear = self.quotes[0], self.quotes[-1]
        self.assertLess(float(cheap["price"]), float(dear["price"]))
        for scenario in self.contract["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                low, high = self.evaluate(with_ask(scenario["inputs"], cheap))["result"], self.evaluate(with_ask(scenario["inputs"], dear))["result"]
                self.assertLess(float(low["summary"]["sell_floor"]), float(high["summary"]["sell_floor"]))
                self.assertEqual(low["summary"]["purchase_ceiling"], high["summary"]["purchase_ceiling"], "the buyer-side ceiling does not depend on the supplier ask")
                self.assertEqual(low["terms"], high["terms"])


if __name__ == "__main__":
    unittest.main()
