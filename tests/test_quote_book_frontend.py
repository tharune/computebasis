"""Run the offline Node suite that draws the Brief, Overview and Quotes views from real simulator snapshots."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.quote_book import QuoteBook
from compute_pricing.control.workbench.routes import ASSETS


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class QuoteBookFrontendTests(unittest.TestCase):
    def test_overview_modules_draw_server_snapshots_in_a_browserless_dom(self):
        node = os.environ.get("COMPUTEBASIS_NODE") or shutil.which("node")
        self.assertTrue(node, "Node 24 is required for frontend behavior tests. Set COMPUTEBASIS_NODE to an installed Node executable.")
        clock = Clock()
        market = QuoteBook(clock=clock)
        base = market.snapshot()
        market.control("scenario", "price_war")
        clock.now += 12.0
        war = market.snapshot()
        market.control("reset")
        reset = market.snapshot()
        # The other two scenarios, each on a fresh book, for the Brief's figures (workbench_landing_figures.test.js).
        shocked = QuoteBook(clock=Clock())
        shocked.control("scenario", "supply_shock")
        downgraded = QuoteBook(clock=Clock())
        downgraded.control("scenario", "downgrade")
        # Every suite that draws the book: workbench_demo.test.js, plus one per page or component (workbench_overview, _quotes, _map ...).
        # workbench_behavior.test.js has its own runner. demo_harness.js is their shared fake DOM and host.
        suites = sorted(str(path) for path in Path(__file__).parent.glob("workbench_*.test.js") if path.name != "workbench_behavior.test.js")
        self.assertIn("workbench_demo.test.js", [Path(path).name for path in suites])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "snapshots.json"
            target.write_text(json.dumps({"base": base, "war": war, "reset": reset, "shock": shocked.snapshot(), "downgrade": downgraded.snapshot()}))
            result = subprocess.run(
                [node, "--test", *suites],
                env={**os.environ, "COMPUTEBASIS_WORKBENCH_ASSETS": str(ASSETS), "COMPUTEBASIS_BOOK_SNAPSHOTS": str(target)},
                capture_output=True, text=True, timeout=60, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
