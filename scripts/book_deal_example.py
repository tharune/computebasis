"""Run an explicitly invented quote-to-cash example with no network or server."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.api.book_deal import book_deal_sample_inputs, build_book_deal
from compute_pricing.control.api.demo import demo_supplier_cash_schedule
from compute_pricing.control.api.provenance import PricingProvenance
from compute_pricing.control.pricing import evaluate_pricing
from compute_pricing.control.quote_book import QuoteBook


def main():
    book = QuoteBook(clock=lambda: 0)
    revision, _ = book.encoded()
    request = build_book_deal(book_deal_sample_inputs(book.snapshot(), revision), book.snapshot(), revision)
    result = PricingProvenance(None, None, None).apply(request, evaluate_pricing(request))
    cash = demo_supplier_cash_schedule(request)
    assert result["status"] == "held" and result["bid"] is None and not result["firm_price_eligible"]
    assert all(not value for value in cash["unresolved_balances"].values())
    print(json.dumps({"classification": "independent_invented_example", "quote_id": request["demo_scenario"]["book_binding"]["quote_id"],
        "gpu_hours": result["economics"]["supply_gpu_hours"], "selling_floor": result["ask"]["sell_floor_tick"],
        "minimum_free_cash": cash["minimum_free_cash"], "required_extra_cash": cash["required_extra_cash_for_floor"],
        "status": result["status"], "bid": result["bid"], "execution_enabled": False}, indent=2))


if __name__ == "__main__":
    main()
