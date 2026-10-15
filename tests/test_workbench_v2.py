"""Workbench shell security and dynamic API wiring, without external reads."""
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from compute_pricing.control.workbench import add_workbench
from compute_pricing.control.workbench.routes import ASSETS


class ShellParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.asset_urls = []
        self.password_fields = []
        self.inline_scripts = 0
        self.inline_handlers = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        for key, value in attrs:
            if key.startswith("on"):
                self.inline_handlers.append(key)
            if key in {"src", "href"}:
                self.asset_urls.append(value)
        if tag == "script" and not values.get("src"):
            self.inline_scripts += 1
        if tag == "input" and values.get("type") == "password":
            self.password_fields.append(values)


class WorkbenchV2Tests(unittest.TestCase):
    def test_direct_html_asset_cannot_bypass_shell_security_headers(self):
        response = self.client.get("/workbench/assets/index.html")
        self.assertEqual(response.status_code, 200)
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def setUp(self):
        app = FastAPI()
        add_workbench(app)
        self.client = TestClient(app)
        self.script = (ASSETS / "workbench.js").read_text()

    def tearDown(self):
        self.client.close()

    def test_shell_is_static_and_uses_restrictive_same_origin_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        policy = response.headers["content-security-policy"]
        for directive in ("script-src 'self'", "style-src 'self'", "connect-src 'self'", "frame-ancestors 'none'", "object-src 'none'"):
            self.assertIn(directive, policy)
        self.assertNotIn("unsafe-inline", policy)
        self.assertNotIn("unsafe-eval", policy)

    def test_shell_has_no_embedded_key_inline_handlers_or_external_assets(self):
        parser = ShellParser()
        parser.feed(self.client.get("/").text)
        self.assertEqual(parser.inline_scripts, 0)
        self.assertEqual(parser.inline_handlers, [])
        self.assertTrue(all(url.startswith(("/", "#")) for url in parser.asset_urls))
        self.assertEqual(parser.password_fields, [])
        self.assertNotIn("Connect to the local API", self.client.get("/").text)
        for forbidden in ("localStorage", "sessionStorage", "document.cookie", "innerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(forbidden, self.script)
        self.assertIn('"X-Compute-CSRF": state.csrf', self.script)
        self.assertIn('credentials: "same-origin"', self.script)
        self.assertIn('redirect: "error"', self.script)

    def test_every_page_script_and_stylesheet_the_shell_loads_is_served(self):
        parser = ShellParser()
        parser.feed(self.client.get("/").text)
        loaded = [url for url in parser.asset_urls if url.startswith("/workbench/assets/") and url.endswith((".js", ".css"))]
        self.assertIn("/workbench/assets/workbench.js", loaded)
        self.assertIn("/workbench/assets/workbench.css", loaded)
        self.assertEqual(len(loaded), len(set(loaded)), "no script or stylesheet is loaded twice")
        for url in loaded:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn("javascript" if url.endswith(".js") else "text/css", response.headers["content-type"], url)

    def test_every_dom_reference_matches_a_static_element(self):
        parser = ShellParser()
        parser.feed(self.client.get("/").text)
        explicit_ids = set(re.findall(r'byId\("([a-z-]+)"\)', self.script))
        self.assertFalse(explicit_ids - parser.ids, explicit_ids - parser.ids)
        for suffix in ("title", "view"):
            self.assertIn("pricing-" + suffix, parser.ids)

    def test_every_routed_view_has_a_page_and_nothing_else_is_a_page(self):
        """VIEWS in workbench.js is the list of pages; each has a section and a title, and the markup holds no other view."""
        html = self.client.get("/").text
        views = re.findall(r'"([a-z]+)"', re.search(r"const VIEWS = \[([^\]]*)\];", self.script).group(1))
        self.assertEqual(views, ["brief", "desk", "quotes", "pricing"])
        sections = re.findall(r'<section id="([a-z]+)-view"', html)
        self.assertEqual(sorted(sections), sorted(views))
        for view in views:
            self.assertIn('id="' + view + '-title"', html)
        navigation = set(re.findall(r'data-view="([a-z]+)"', html))
        self.assertLessEqual(navigation, set(views))

    def test_a_page_hide_or_session_end_discards_late_work(self):
        self.assertIn('window.addEventListener("pagehide"', self.script)
        self.assertIn('state.epoch++', self.script)
        self.assertIn("epoch !== state.epoch", self.script)

    def test_asset_traversal_cannot_read_parent_source(self):
        response = self.client.get("/workbench/assets/%2e%2e/routes.py")
        self.assertNotEqual(response.status_code, 200)
        response = self.client.get("/workbench/assets/%2e%2e/%2e%2e/api/app.py")
        self.assertNotEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
