"""The landing page and the workbench are two pages in one document; these hold their wiring together."""
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.workbench.routes import ASSETS

HTML = (ASSETS / "index.html").read_text(encoding="utf-8")
ROUTE = (ASSETS / "route.js").read_text(encoding="utf-8")
SCRIPT = (ASSETS / "workbench.js").read_text(encoding="utf-8")
CSS = (ASSETS / "workbench.css").read_text(encoding="utf-8") + (ASSETS / "landing.css").read_text(encoding="utf-8")


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


TAGS = Tags()
TAGS.feed(HTML)


class LandingWiringTests(unittest.TestCase):
    def test_route_script_names_match_the_views_the_workbench_knows(self):
        known = set(re.search(r"var APP = /\^\(([^)]*)\)\$/;", ROUTE).group(1).split("|"))
        views = set(re.findall(r'"([a-z]+)"', re.search(r"const VIEWS = \[([^\]]*)\];", SCRIPT).group(1)))
        self.assertEqual(known, views - {"brief"}, "route.js and VIEWS in workbench.js must list the same app pages")

    def test_route_script_runs_before_the_stylesheet_and_before_first_paint(self):
        scripts = [attrs for tag, attrs in TAGS.tags if tag == "script" and attrs.get("src", "").endswith("route.js")]
        self.assertEqual(len(scripts), 1)
        self.assertNotIn("defer", scripts[0]); self.assertNotIn("async", scripts[0])
        self.assertLess(HTML.index("route.js"), HTML.index("workbench.css"), "a blocking script after the stylesheet waits for it")
        html = next(attrs for tag, attrs in TAGS.tags if tag == "html")
        self.assertEqual(html.get("data-page"), "landing", "with no script at all the page is the landing page")

    def test_every_view_has_a_section_and_the_landing_is_not_in_the_app_navigation(self):
        targets = {attrs["data-view"] for _, attrs in TAGS.tags if "data-view" in attrs}
        ids = {attrs["id"] for _, attrs in TAGS.tags if "id" in attrs}
        for view in targets:
            self.assertIn(view + "-view", ids, view + " has no section")
        app_nav = re.search(r'<nav class="navigation".*?</nav>', HTML, re.S).group(0)
        self.assertNotIn('data-view="brief"', app_nav, "the landing page is not a tab; the logo goes home")
        brands = [attrs for tag, attrs in TAGS.tags if tag == "a" and "brand" in attrs.get("class", "").split()]
        self.assertEqual(len(brands), 2, "one logo link in each header")
        for brand in brands:
            self.assertEqual(brand.get("data-view"), "brief")
            self.assertEqual(brand.get("href"), "/")

    def test_each_page_shows_only_its_own_chrome(self):
        for rule in ('html[data-page="landing"] .lp-header { display: block; }',
                     'html[data-page="landing"] .app-header, html[data-page="landing"] .app-footer { display: none; }',
                     'html[data-page="app"] #brief-view { display: none; }'):
            self.assertIn(rule, CSS)
        self.assertRegex(CSS, r"\.lp-header \{ display: none;", "the landing header is off until the landing page is showing")

    def test_the_landing_header_has_a_way_in(self):
        ids = {attrs["id"] for _, attrs in TAGS.tags if "id" in attrs}
        self.assertTrue({"lp-open", "lp-go-problem", "lp-go-how", "lp-theme-toggle"} <= ids)


if __name__ == "__main__":
    unittest.main()
