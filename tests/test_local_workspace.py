"""Independently invented public session/lifecycle cases; no live network access."""
import asyncio
from contextlib import redirect_stdout
from dataclasses import replace
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from compute_pricing.control.api import create_app
from compute_pricing.control.api.refresh import AutomaticRefresh, CollectionCoordinator, RefreshConfig
from compute_pricing.control.api.sessions import COOKIE_NAME, request_scope
from compute_pricing.control.connectors import ConnectorError, SourcePolicy

SITE = "http://127.0.0.1:8842"
FETCH = {"Origin": SITE, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}


def admitted(source="ecb"):
    return SourcePolicy(source, enabled=True, rights_status="allowed", rights_evidence="invented-local-feed-review",
        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        verified_by="review:sample", max_age_s=7200, min_interval_s=0)


def snapshot(source):
    return {"snapshot_id": "2" * 64, "result": {"source_id": source, "observations": [], "catalog_records": []}}


class PublicBrowserBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.external = tempfile.TemporaryDirectory()
        self.app = create_app(workbench_origin=SITE, store_path=Path(self.external.name) / "local.sqlite")
        self.browser = TestClient(self.app, base_url=SITE)

    def tearDown(self):
        self.browser.close()
        self.external.cleanup()

    def open_session(self):
        response = self.browser.post("/v1/session/bootstrap", json={}, headers=FETCH)
        self.assertEqual(response.status_code, 200)
        return response

    def test_automatic_browser_auth_uses_cookie_and_never_html_secret(self):
        response = self.open_session()
        cookie = response.headers["set-cookie"]
        self.assertTrue(all(flag in cookie for flag in ("HttpOnly", "SameSite=strict", "Path=/v1", "Max-Age=900")))
        self.assertNotIn("Domain=", cookie)
        page = self.browser.get("/").text
        self.assertNotIn(response.json()["csrf_token"], page)
        self.assertNotIn(self.browser.cookies.get(COOKIE_NAME), response.text)
        self.assertEqual(self.browser.get("/v1/sources", headers=FETCH).status_code, 200)

    def test_bootstrap_rejects_origin_port_host_and_cross_site_before_json(self):
        for headers in ({**FETCH, "Origin": "http://127.0.0.1:8843"}, {**FETCH, "Host": "unrelated.example:8842"},
                        {**FETCH, "Sec-Fetch-Site": "same-site"}, {**FETCH, "Sec-Fetch-Dest": "iframe"}, {}):
            self.assertEqual(self.browser.post("/v1/session/bootstrap", content=b"malformed", headers=headers).status_code, 403)

    def test_read_and_write_authentication_precedes_bad_body(self):
        self.assertEqual(self.browser.get("/v1/market/refresh/status", headers=FETCH).status_code, 401)
        response = self.browser.post("/v1/portfolio/evaluate", content=b'{"amount":NaN}', headers={**FETCH, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 401)

    def test_mutation_needs_current_csrf_and_exact_origin(self):
        token = self.open_session().json()["csrf_token"]
        for headers in (FETCH, {**FETCH, "X-Compute-CSRF": "f" * 64},
                        {**FETCH, "Origin": "null", "X-Compute-CSRF": token}):
            self.assertEqual(self.browser.post("/v1/requests/parse", json={}, headers=headers).status_code, 403)
        self.assertEqual(self.browser.post("/v1/requests/parse", json={}, headers={**FETCH, "X-Compute-CSRF": token}).status_code, 200)

    def test_normal_browser_read_may_omit_origin_without_weakening_fetch_metadata(self):
        self.open_session()
        headers = {key: value for key, value in FETCH.items() if key != "Origin"}
        self.assertEqual(self.browser.get("/v1/contracts/schema", headers=headers).status_code, 200)
        self.assertEqual(self.browser.get("/v1/contracts/schema").status_code, 403)

    def test_active_tabs_have_distinct_valid_tokens_one_cookie_original_expiry(self):
        first = self.open_session().json()
        cookie = self.browser.cookies.get(COOKIE_NAME)
        second = self.open_session().json()
        self.assertEqual(cookie, self.browser.cookies.get(COOKIE_NAME))
        self.assertEqual(first["expires_at"], second["expires_at"])
        self.assertNotEqual(first["csrf_token"], second["csrf_token"])
        for response in (first, second):
            self.assertEqual(self.browser.post("/v1/requests/parse", json={}, headers={**FETCH, "X-Compute-CSRF": response["csrf_token"]}).status_code, 200)

    def test_logout_revokes_shared_session(self):
        token = self.open_session().json()["csrf_token"]
        old = self.browser.cookies.get(COOKIE_NAME)
        response = self.browser.post("/v1/session/logout", json={}, headers={**FETCH, "X-Compute-CSRF": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.browser.get("/v1/sources", headers={**FETCH, "Cookie": f"{COOKIE_NAME}={old}"}).status_code, 401)

    def test_expiry_requires_new_bootstrap_and_unknown_write_scope_is_held(self):
        now = [2000000.0]
        self.app.state.browser_sessions.clock = lambda: now[0]
        self.open_session()
        now[0] += 1000
        self.assertEqual(self.browser.get("/v1/sources", headers=FETCH).status_code, 401)
        self.open_session()
        self.assertEqual(self.browser.get("/v1/sources", headers=FETCH).status_code, 200)
        self.assertEqual(request_scope(Request({"type": "http", "path": "/v1/orders", "method": "POST", "headers": []})), "unsupported")

    def test_blank_portfolio_contract_held_and_immutable_replay(self):
        csrf = self.open_session().json()["csrf_token"]
        draft = self.browser.get("/v1/portfolio/template", headers=FETCH).json()["request"]
        self.assertIsNone(draft["cash"]["opening_cash"])
        response = self.browser.post("/v1/portfolio/evaluate", json=draft, headers={**FETCH, "X-Compute-CSRF": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["status"], "held")
        replay = self.browser.get("/v1/decisions/" + response.json()["snapshot_id"], headers=FETCH).json()["document"]
        self.assertEqual(replay["kind"], "portfolio")
        self.assertEqual(replay["input"], draft)

    def test_explicit_api_client_key_remains_independent_of_browser_bootstrap(self):
        key = "invented-public-api-consumer-key-0001"
        app = create_app(api_key=key, store_path=Path(self.external.name) / "client.sqlite")
        with TestClient(app) as client:
            self.assertEqual(client.get("/v1/sources", headers={"Authorization": "Bearer " + key}).status_code, 200)
            self.assertEqual(client.post("/v1/session/bootstrap", json={}, headers=FETCH).status_code, 404)
            self.assertFalse(client.get("/v1/market/refresh/status", headers={"Authorization": "Bearer " + key}).json()["enabled"])


class PublicRefreshLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_scope_is_shared_and_survives_cancelled_client(self):
        gate, entered, calls = asyncio.Event(), asyncio.Event(), []
        async def worker(source, filters):
            calls.append(filters)
            entered.set()
            await gate.wait()
            return snapshot(source)
        shared = CollectionCoordinator(worker)
        a = asyncio.create_task(shared.collect("ecb", {}))
        await entered.wait()
        b = asyncio.create_task(shared.collect("ecb", {}))
        await asyncio.sleep(0)
        a.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await a
        gate.set()
        self.assertEqual((await b)["snapshot_id"], "2" * 64)
        self.assertEqual(calls, [{}])
        await shared.stop()

    async def test_only_configured_approved_anonymous_feeds_pass_all_three_rights(self):
        calls = []
        async def worker(source, filters):
            calls.append(source)
            return snapshot(source)
        policies = {source: admitted(source) for source in ("ecb", "vast", "oracle", "huggingface")}
        policies["huggingface"] = replace(policies["huggingface"], permissions={"observe": "PASS", "retain": "FAIL", "benchmark": "PASS"})
        service = AutomaticRefresh(RefreshConfig.parse({}), [{"source_id": source, "filters": {}} for source in policies],
                                   policies, CollectionCoordinator(worker))
        await service.cycle()
        self.assertEqual(calls, ["ecb"])
        self.assertEqual(sum(row["status"] == "held" for row in service.status()["scopes"]), 3)

    async def test_server_retry_hold_wins_over_backoff_cap(self):
        clock = [3000000.0]
        async def worker(*args):
            raise ConnectorError("source_cooldown_active")
        service = AutomaticRefresh(RefreshConfig.parse({"backoff_max_s": 120}), [{"source_id": "ecb", "filters": {}}],
            {"ecb": admitted()}, CollectionCoordinator(worker), cooldown=lambda _: 36000, clock=lambda: clock[0])
        await service.cycle()
        row = service.status()["scopes"][0]
        self.assertEqual(row["next_due_at"], "1970-02-05T03:20:00Z")
        self.assertEqual(row["status"], "held")

    async def test_manual_success_defers_periodic_scope_and_revocation_blocks_next_due(self):
        clock, calls = [3000000.0], []
        async def worker(source, filters):
            calls.append(source)
            return snapshot(source)
        policies = {"ecb": admitted()}
        shared = CollectionCoordinator(worker)
        service = AutomaticRefresh(RefreshConfig.parse({}), [{"source_id": "ecb", "filters": {}}], policies, shared, clock=lambda: clock[0])
        await shared.collect("ecb", {})
        await service.cycle()
        self.assertEqual(calls, ["ecb"])
        policies["ecb"] = replace(policies["ecb"], enabled=False)
        clock[0] += 7200
        await service.cycle()
        self.assertEqual(calls, ["ecb"])
        self.assertEqual(service.status()["scopes"][0]["status"], "held")

    async def test_stop_drains_active_worker_and_stops_new_scopes(self):
        gate, entered, calls = asyncio.Event(), asyncio.Event(), []
        async def worker(source, filters):
            calls.append(source)
            entered.set()
            await gate.wait()
            return snapshot(source)
        service = AutomaticRefresh(RefreshConfig.parse({}), [{"source_id": source, "filters": {}} for source in ("ecb", "azure")],
            {source: admitted(source) for source in ("ecb", "azure")}, CollectionCoordinator(worker))
        await service.start()
        await entered.wait()
        stop = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        self.assertFalse(stop.done())
        gate.set()
        await stop
        self.assertEqual(calls, ["ecb"])
        self.assertFalse(service.status()["running"])

    async def test_one_source_failure_is_safe_and_other_scope_still_updates(self):
        async def worker(source, filters):
            if source == "ecb":
                raise RuntimeError("invented-unretained-diagnostic")
            return snapshot(source)
        service = AutomaticRefresh(RefreshConfig.parse({}), [{"source_id": source, "filters": {}} for source in ("ecb", "azure")],
            {source: admitted(source) for source in ("ecb", "azure")}, CollectionCoordinator(worker))
        await service.cycle()
        self.assertEqual([row["status"] for row in service.status()["scopes"]], ["failed", "ready"])
        self.assertNotIn("invented-unretained", str(service.status()))

    async def test_status_filters_are_detached_and_startup_false_is_not_due(self):
        async def worker(*args):
            self.fail("must not read")
        service = AutomaticRefresh(RefreshConfig.parse({"on_startup": False}), [{"source_id": "azure", "filters": {"region": "sample-north"}}],
            {"azure": admitted("azure")}, CollectionCoordinator(worker))
        status = service.status()
        status["scopes"][0]["filters"]["region"] = "changed"
        await service.cycle()
        self.assertEqual(service.status()["scopes"][0]["filters"]["region"], "sample-north")

    async def test_no_auto_http_during_default_library_startup(self):
        key = "invented-public-default-off-key-0001"
        with tempfile.TemporaryDirectory() as external:
            app = create_app(api_key=key, store_path=Path(external) / "store.sqlite", source_policies={"ecb": admitted()},
                             collection_plan=[{"source_id": "ecb", "filters": {}}])
            with patch("compute_pricing.control.api.app.collect_source") as collect, TestClient(app):
                collect.assert_not_called()
            self.assertFalse(app.state.auto_refresh.status()["enabled"])


class PublicProcessDrainTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("public_local_helper", Path(__file__).resolve().parents[1] / "scripts/local.py")
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.external = tempfile.TemporaryDirectory()
        self.folder = Path(self.external.name)
        self.metadata = {"pid": 34567, "url": SITE, "local_instance_id": "b" * 32}

    def tearDown(self):
        self.external.cleanup()

    def test_live_ownership_requires_the_declared_script_store_and_port(self):
        helper = self.helper
        command = f"python {helper.REPO / 'scripts/serve.py'} --store {self.folder / 'decisions.sqlite'} --port 8842"
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="S " + command)):
            self.assertEqual(helper.process_state(self.metadata, self.folder), "owned")
        for foreign in (command.replace("8842", "8843"), "bash -c '" + command + "'", command.replace("decisions.sqlite", "other.sqlite")):
            with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="S " + foreign)):
                self.assertEqual(helper.process_state(self.metadata, self.folder), "unrelated")

    def test_closed_listener_is_not_a_process_exit_and_start_is_blocked(self):
        helper = self.helper
        (self.folder / "server.json").write_text(json.dumps({**self.metadata, "stop_requested": True}))
        for command in ("status", "start"):
            stream = io.StringIO()
            with (patch.object(helper.sys, "argv", ["local.py", command, "--runtime", str(self.folder)]),
                  patch.object(helper, "process_state", return_value="owned"), patch.object(helper, "health", side_effect=OSError()),
                  patch.object(helper.subprocess, "Popen") as launch, redirect_stdout(stream)):
                helper.main()
                launch.assert_not_called()
            output = json.loads(stream.getvalue())
            self.assertTrue(output["draining"])
            self.assertTrue(output["process_alive"])
            self.assertFalse(output["running"])

    def test_drain_timeout_is_bounded_without_any_signal(self):
        helper, clock = self.helper, [0.0]
        def sleep(delay):
            clock[0] += delay
        with patch.object(helper.os, "kill") as kill:
            stopped = helper.wait_for_process_exit(self.metadata, self.folder, probe=lambda *_: "owned",
                monotonic=lambda: clock[0], sleep=sleep)
            self.assertFalse(stopped)
            self.assertLessEqual(clock[0], 60)
            kill.assert_not_called()

    def test_existing_stop_request_drains_once_without_resignalling(self):
        helper = self.helper
        (self.folder / "server.json").write_text(json.dumps({**self.metadata, "stop_requested": True}))
        output = io.StringIO()
        with (patch.object(helper.sys, "argv", ["local.py", "stop", "--runtime", str(self.folder)]),
              patch.object(helper, "process_state", return_value="owned"), patch.object(helper, "health") as health,
              patch.object(helper, "wait_for_process_exit", return_value=True), patch.object(helper.os, "kill") as kill,
              redirect_stdout(output)):
            helper.main()
            health.assert_not_called()
            kill.assert_not_called()
        self.assertTrue(json.loads(output.getvalue())["stopped"])
        self.assertFalse((self.folder / "server.json").exists())

    def test_bad_or_nonlocal_metadata_never_invokes_health_network(self):
        helper = self.helper
        with patch.object(helper.urllib.request, "urlopen") as read:
            for url in ("https://remote.example", "http://127.0.0.1:8842?token=not-accepted"):
                with self.assertRaises(ValueError):
                    helper.health({**self.metadata, "url": url})
            read.assert_not_called()

    def test_exited_or_zombie_is_distinct_from_probe_failure(self):
        helper = self.helper
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="Z sample")):
            self.assertEqual(helper.process_state(self.metadata, self.folder), "exited")
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=2, stdout="")), self.assertRaises(ValueError):
            helper.process_state(self.metadata, self.folder)


    def test_separate_command_cannot_enter_held_lifecycle_lock(self):
        helper, failures = self.helper, []
        def compete():
            try:
                with helper.lifecycle_lock(self.folder):
                    failures.append("unexpected entry")
            except helper.LifecycleBusy:
                failures.append("busy")
        with helper.lifecycle_lock(self.folder):
            thread = threading.Thread(target=compete)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, ["busy"])
        with helper.lifecycle_lock(self.folder):
            pass

    def test_contended_stop_cannot_check_health_or_signal_process(self):
        helper = self.helper
        (self.folder / "server.json").write_text(json.dumps(self.metadata))
        with (helper.lifecycle_lock(self.folder), patch.object(helper.sys, "argv", ["local.py", "stop", "--runtime", str(self.folder)]),
              patch.object(helper, "process_state") as process, patch.object(helper, "health") as health,
              patch.object(helper.os, "kill") as signal_process, self.assertRaises(SystemExit)):
            helper.main()
        process.assert_not_called()
        health.assert_not_called()
        signal_process.assert_not_called()

    def test_defunct_linux_worker_is_finished_even_when_the_pid_still_exists(self):
        helper = self.helper
        (self.folder / "server.json").write_text(json.dumps(self.metadata))
        output = io.StringIO()
        with (patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="Z+\t[python] <defunct>\n")),
              patch.object(helper.os, "kill") as signal_process, patch.object(helper, "health") as health):
            self.assertTrue(helper.wait_for_process_exit(self.metadata, self.folder,
                probe=helper.process_state, sleep=lambda _: self.fail("finished zombie cannot need more time")))
            with patch.object(helper.sys, "argv", ["local.py", "stop", "--runtime", str(self.folder)]), redirect_stdout(output):
                helper.main()
            self.assertTrue(json.loads(output.getvalue())["stopped"])
            health.assert_not_called()
            signal_process.assert_not_called()

    def test_reused_live_pid_stays_unrelated_and_cannot_be_signalled(self):
        helper = self.helper
        (self.folder / "server.json").write_text(json.dumps(self.metadata))
        with (patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="S\tpython unrelated-worker.py\n")),
              patch.object(helper.sys, "argv", ["local.py", "stop", "--runtime", str(self.folder)]),
              patch.object(helper.os, "kill") as signal_process, self.assertRaises(SystemExit)):
            helper.main()
        signal_process.assert_not_called()
        self.assertTrue((self.folder / "server.json").exists())


if __name__ == "__main__":
    unittest.main()
