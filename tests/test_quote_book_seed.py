"""The generated seed stays intact and the quote-book routes stay in their own namespace."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compute_pricing.control.api import create_app
from compute_pricing.control.quote_book import seed

SCRIPT = ROOT / "scripts" / "gen_quote_book_seed.py"


def generator():
    spec = importlib.util.spec_from_file_location("gen_quote_book_seed", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeedIntegrityTests(unittest.TestCase):
    def test_committed_seed_passes_its_own_check_without_the_workbook(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, check=False, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_digest_detects_any_edit_to_a_row(self):
        gen = generator()
        self.assertEqual(gen.content_digest(seed.PROVIDERS, seed.QUOTES), seed.CONTENT_SHA256)
        providers, quotes = copy.deepcopy(list(seed.PROVIDERS)), copy.deepcopy(list(seed.QUOTES))
        quotes[0]["price"] = quotes[0]["price"] + 0.01
        self.assertNotEqual(gen.content_digest(providers, quotes), seed.CONTENT_SHA256)
        providers[0]["tiers"]["sla"] = 4 - providers[0]["tiers"]["sla"]
        self.assertNotEqual(gen.content_digest(providers, list(seed.QUOTES)), seed.CONTENT_SHA256)

    def test_seed_records_where_it_came_from_and_that_it_is_invented(self):
        self.assertEqual(len(seed.SOURCE_SHA256), 64)
        self.assertTrue(seed.SOURCE.endswith(".xlsx"))
        self.assertIn("invented test data", seed.__doc__)
        self.assertEqual(gen_problems(), [])

    def test_the_workbook_itself_is_not_part_of_the_repository(self):
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.split("\n")
        self.assertEqual([name for name in tracked if name.lower().endswith((".xlsx", ".xls", ".xlsm"))], [])


def gen_problems():
    return generator().verify_committed_seed()


class RouteNamespaceTests(unittest.TestCase):
    def test_book_routes_are_flat_on_the_app_and_stay_out_of_the_demo_namespace(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(api_key="offline-quote-book-client-0123456789", store_path=Path(folder) / "store.sqlite")
        # Every route exposes .path; an included router would add objects without it.
        paths = {(route.path, tuple(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}
        self.assertTrue(all(hasattr(route, "path") for route in app.routes))
        self.assertEqual({entry for entry in paths if entry[0].startswith("/v1/book")}, {("/v1/book", ("GET",)), ("/v1/book/control", ("POST",))})


if __name__ == "__main__":
    unittest.main()
