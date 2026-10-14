"""The "Price this quote" handoff: a simulated quote's ask goes into the shipped example and the real evaluator accepts it."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.pricing.engine import evaluate_pricing
from compute_pricing.control.quote_book import QuoteBook
from compute_pricing.control.workbench.routes import ASSETS

EXAMPLE = json.loads((ASSETS / "synthetic-pricing-request.json").read_text(encoding="utf-8"))
SCRIPT = (ASSETS / "workbench.js").read_text(encoding="utf-8")


def handoff_packet(quote):
    """The packet workbench.js builds in loadPricingExample(quote): only the supplier ask comes from the quote."""
    packet = copy.deepcopy(EXAMPLE)
    packet["commercial"]["supplier_ask"] = str(quote["price"])
    return packet


class QuotePricingHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quotes = sorted(QuoteBook().snapshot()["quotes"], key=lambda quote: float(quote["price"]))

    def test_the_script_builds_the_packet_this_test_models(self):
        self.assertIn("packet.commercial.supplier_ask = String(quote.price);", SCRIPT)

    def test_cheap_median_and_dear_book_quotes_price_as_indicative_scenarios_that_cannot_execute(self):
        for quote in (self.quotes[0], self.quotes[len(self.quotes) // 2], self.quotes[-1]):
            with self.subTest(quote=quote["id"], price=quote["price"]):
                result = evaluate_pricing(handoff_packet(quote))
                self.assertEqual(result["status"], "indicative")
                self.assertFalse(result["firm_price_eligible"])
                self.assertFalse(result["executable"])
                self.assertEqual(result["hold_reasons"], [])

    def test_the_selling_floor_follows_the_quotes_ask_and_nothing_else_moves(self):
        cheap, dear = self.quotes[0], self.quotes[-1]
        self.assertLess(float(cheap["price"]), float(dear["price"]))
        low, high = evaluate_pricing(handoff_packet(cheap)), evaluate_pricing(handoff_packet(dear))
        self.assertLess(float(low["ask"]["sell_floor_tick"]), float(high["ask"]["sell_floor_tick"]))
        self.assertEqual(handoff_packet(cheap)["market"], handoff_packet(dear)["market"])
        self.assertEqual({key: value for key, value in handoff_packet(cheap)["commercial"].items() if key != "supplier_ask"},
                         {key: value for key, value in handoff_packet(dear)["commercial"].items() if key != "supplier_ask"})


if __name__ == "__main__":
    unittest.main()
