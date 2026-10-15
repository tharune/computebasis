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
LANDING = (ASSETS / "landing.css").read_text(encoding="utf-8")
CSS = (ASSETS / "workbench.css").read_text(encoding="utf-8") + LANDING
BRIEF = re.search(r'<section id="brief-view".*?\n      </section>\n(?=      <section id="desk-view")', HTML, re.S).group(0)
FOOTER = re.search(r'<footer id="lp-footer" class="lp-footer">.*?</footer>', HTML, re.S).group(0)
HEADER = re.search(r'<header id="lp-header".*?</header>', HTML, re.S).group(0)


def plain(markup):
    """The words a visitor reads: tags dropped, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup)).strip()


def region(css, title):
    """The CSS region that opens with /* title */ and runs to the motion block that follows it."""
    start = css.index("/* " + title + " */")
    return css[start:css.index("/* Motion.", start)]


def clamp_at(value, viewport):
    """Evaluate clamp(Npx, Apx + Bvw, Mpx) at a viewport width, in px."""
    low, mid, high = re.fullmatch(r"clamp\(\s*([\d.]+)px,\s*(.+?),\s*([\d.]+)px\s*\)", value.strip()).groups()
    total = 0.0
    for sign, number, unit in re.findall(r"([+-]?)\s*([\d.]+)(px|vw)", mid):
        amount = float(number) * (viewport / 100 if unit == "vw" else 1)
        total += -amount if sign == "-" else amount
    return min(float(high), max(float(low), total))


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

    def test_landmarks_are_clean_and_the_footer_is_outside_main(self):
        main = re.search(r"<main\b.*?</main>", HTML, re.S).group(0)
        self.assertEqual(HTML.count("<main"), 1)
        self.assertNotIn("<footer", main, "a footer inside main is not a page footer landmark")
        self.assertIn('class="lp-footer"', HTML)
        brief = re.search(r'<section id="brief-view"[^>]*>', HTML).group(0)
        self.assertNotIn("aria-labelledby", brief, "a named section becomes a redundant region landmark")
        self.assertIn(">Skip to main content<", HTML)

    def test_the_formula_reads_as_a_sentence_to_a_screen_reader(self):
        formula = re.search(r'<ul class="bf-sum">.*?</ul>', HTML, re.S).group(0)
        self.assertIn('<span class="sr-only">plus </span>financing', formula)
        self.assertIn('<span class="sr-only">equals </span>all-in cost', formula)

    def test_the_landing_header_has_a_way_in(self):
        ids = {attrs["id"] for _, attrs in TAGS.tags if "id" in attrs}
        self.assertTrue({"lp-open", "lp-go-problem", "lp-go-how", "lp-theme-toggle", "lp-header", "lp-footer"} <= ids)

    def test_every_slot_the_brief_script_fills_is_in_the_page(self):
        script = (ASSETS / "page-brief.js").read_text(encoding="utf-8")
        wanted = set(re.findall(r'(?:byId|replace|refresh|slotFrame)\(\s*"(brief-[a-z-]+)"', script)) | set(re.findall(r'"(brief-[a-z-]+)"', re.search(r"const slots = \[[^\]]*\]", script).group(0)))
        ids = {attrs["id"] for _, attrs in TAGS.tags if "id" in attrs}
        self.assertEqual(wanted - ids, set(), "slots the script fills must exist in index.html")


class LandingCopyTests(unittest.TestCase):
    """The static words say what the simulation does (scoring.py, ASSUMPTIONS) and nothing else."""

    def test_the_rates_odds_and_bands_are_the_simulations_own(self):
        text = plain(BRIEF)
        for fact in ("8.5% a year", "65% of the down payment that is not recovered"):  # the odds, grade bands and weights are drawn from the book, not restated
            self.assertIn(fact, text)
        scoring = (ASSETS.parents[1] / "quote_book" / "scoring.py").read_text(encoding="utf-8")
        for source in ('"deposit_apr": "0.085"', '{"A": "0.008", "B": "0.024", "C": "0.061", "D": "0.173"}', '"recovery_fraction": "0.35"', 'GRADE_BANDS = {"A": "90", "B": "75", "C": "60", "D": "0"}'):
            self.assertIn(source, scoring, "the page restates " + source + " from the scorer")

    def test_eligibility_rules_match_the_scorer(self):
        scoring = (ASSETS.parents[1] / "quote_book" / "scoring.py").read_text(encoding="utf-8")
        for reason in ('"contract_start_precedes_as_of"', '"simulated_quote_expired"', 'reasons.update("missing_" + name for name in missing)', 'missing.add("grade")', '"available_nodes_below_minimum_order"'):
            self.assertIn(reason, scoring)
        rules = re.search(r'<ul class="bf-rules">(.*?)</ul>', BRIEF, re.S).group(1)
        self.assertEqual(re.findall(r"<li>(.*?)</li>", rules), ["Its seller has a grade (grade D passes).", "Every key term is stated.", "The quote has not expired.", "The contract start has not passed.", "The capacity covers the minimum order."])
        self.assertIn("A quote has 17 key terms", plain(BRIEF))
        self.assertEqual(len(re.search(r'KEY_FIELDS = \((.*?)\)', scoring, re.S).group(1).replace("\n", " ").split(",")), 17)

    def test_nothing_stale_or_invented_is_said(self):
        text = plain(BRIEF + FOOTER + HEADER).lower()
        for banned in ("workbook", "placeholder", "mock provider", "12%", "by design", "built for teams", "seamless", "unlock", "ai-powered", "world-class"):
            self.assertNotIn(banned, text)
        self.assertEqual(text.count("is simulated and invented independently"), 1, "the page says it is simulated, once, plainly")
        rest = text.replace("is simulated and invented independently", "").replace("the simulated market", "")
        self.assertNotIn("simulated", rest, "no other sentence restates the disclosure")
        self.assertIn("nothing is inventory, a firm price or executable", text)

    def test_the_grade_premium_is_an_alternative_not_an_addition(self):
        self.assertIn("alternative way to cost the same risk and is never added to the all-in cost", plain(BRIEF))

    def test_only_the_four_stages_are_numbered_and_nothing_is_emoji(self):
        self.assertEqual(re.findall(r'class="bf-stage-n"[^>]*>(\d)<', BRIEF), ["1", "2", "3", "4"])
        self.assertNotRegex(BRIEF + FOOTER + HEADER, r"\b0[1-9]\s*/|[\U0001F300-\U0001FAFF\u2600-\u27BF]")


class LandingTypeAndTokenTests(unittest.TestCase):
    def test_the_scale_grows_with_the_viewport_and_never_goes_under_13px(self):
        tokens = dict(re.findall(r"--(fs-[a-z0-9-]+):\s*(clamp\([^;]+\));", LANDING))
        self.assertTrue({"fs-display", "fs-h2", "fs-h3", "fs-lede", "fs-intro", "fs-body", "fs-body-sm", "fs-small", "fs-ui", "fs-fig"} <= set(tokens))
        for name, value in tokens.items():
            self.assertGreaterEqual(clamp_at(value, 390), 13, name + " at 390px")
            self.assertLessEqual(clamp_at(value, 390), clamp_at(value, 1440) + 1e-9, name + " grows")
            self.assertLessEqual(clamp_at(value, 1440), clamp_at(value, 2000) + 1e-9, name + " keeps growing to the widest size")
        for name in ("fs-body", "fs-body-sm", "fs-lede", "fs-intro"):
            for width in (1024, 1440, 2000):
                self.assertGreaterEqual(clamp_at(tokens[name], width), 17, name + " is body copy: 17px or more from 1024px up, at " + str(width))
        self.assertGreaterEqual(clamp_at(tokens["fs-display"], 1440), 60)
        self.assertGreaterEqual(clamp_at(tokens["fs-display"], 2000), 80)

    def test_no_fixed_text_size_under_13px_outside_the_chart_region(self):
        outside = LANDING.replace(region(LANDING, "Chart marks and text"), "")
        sizes = [float(match) for match in re.findall(r"font-size:\s*([\d.]+)px", outside)]
        self.assertTrue(sizes and min(sizes) >= 13, "smallest fixed size: " + str(min(sizes or [0])))

    def test_no_tracked_capitals_gradients_glows_or_glass(self):
        for banned in ("text-transform: uppercase", "linear-gradient", "radial-gradient", "backdrop-filter", "blur("):
            self.assertNotIn(banned, LANDING, banned)
        self.assertNotRegex(LANDING, r"letter-spacing:\s*\.?\d*\.\d+em", "letter-spacing is only ever negative (tight display type), never tracked out")
        shadows = [match for match in re.findall(r"box-shadow:[^;]+;", LANDING) if "var(--lp-band)" not in match and "drop-shadow" not in match]
        self.assertEqual(shadows, [], "no shadows or glows except the ring that cuts the rule behind a stage dot")

    def test_every_landing_token_has_a_light_a_dark_and_a_system_value(self):
        light = re.search(r'html\[data-page="landing"\] \{(.*?)\n\}', LANDING, re.S).group(1)
        dark = re.search(r'html\[data-page="landing"\]\[data-theme="dark"\] \{(.*?)\n\}', LANDING, re.S).group(1)
        system = re.search(r'@media \(prefers-color-scheme: dark\) \{\s*html\[data-page="landing"\]:not\(\[data-theme\]\) \{(.*?)\n  \}', LANDING, re.S).group(1)
        themed = lambda block: dict(re.findall(r"--(lp-[a-z-]+):\s*([^;]+);", block))
        light_tokens, dark_tokens, system_tokens = themed(light), themed(dark), themed(system)
        self.assertEqual(set(dark_tokens), set(light_tokens) - {"lp-ignored"}, "dark restates every colour the light scope sets")
        self.assertEqual(system_tokens, dark_tokens, "the pre-script system mirror equals the dark scope")
        self.assertNotEqual(light_tokens["lp-band"], dark_tokens["lp-band"])

    def test_surfaces_reset_canvas_so_chart_halos_match_what_they_sit_on(self):
        for selector in (".bf-band", ".bf-panel", ".bf-band-close"):
            self.assertRegex(LANDING, re.escape(selector) + r" \{[^}]*--canvas:")

    def test_the_page_changes_surface_down_its_length(self):
        bands = re.findall(r'class="([^"]*\bbf-band\b[^"]*)"', BRIEF)
        self.assertGreaterEqual(len(bands), 3, "numbers, how it works and the closing band each sit on their own tone")


if __name__ == "__main__":
    unittest.main()
