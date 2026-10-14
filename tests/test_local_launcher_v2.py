"""Actual isolated loopback lifecycle; no vendor calls or permanent jobs."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def offline_child_environment(runtime):
    """Guard subprocesses too: only loopback DNS/connect is permitted in tests."""
    guard = runtime / "python-network-guard"
    guard.mkdir()
    attempts = runtime / "non-loopback-attempt"
    (guard / "sitecustomize.py").write_text('''import os
import sys
from pathlib import Path

with Path(''' + repr(str(runtime / "network-guard-pids")) + ''').open("a") as registration:
    registration.write(str(os.getpid()) + "\\n")

def offline_network_guard(event, arguments):
    host = None
    if event == "socket.getaddrinfo":
        host = arguments[0]
    elif event == "socket.connect":
        address = arguments[1]
        if isinstance(address, tuple):
            host = address[0]
    else:
        return
    if host not in (None, "127.0.0.1", "::1", "localhost"):
        Path(''' + repr(str(attempts)) + ''').write_text("non_loopback_network_forbidden")
        raise RuntimeError("offline_non_loopback_network_forbidden")

sys.addaudithook(offline_network_guard)
''')
    task_environment = dict(os.environ)
    paths = [str(guard), str(ROOT / "src")]
    if task_environment.get("PYTHONPATH"):
        paths.append(task_environment["PYTHONPATH"])
    task_environment.update(PYTHONPATH=os.pathsep.join(paths), PYTHONDONTWRITEBYTECODE="1",
                            NO_PROXY="127.0.0.1,localhost,::1", no_proxy="127.0.0.1,localhost,::1")
    return task_environment, attempts


class LocalLauncherTests(unittest.TestCase):
    def test_start_reuse_stop_restart_and_secret_not_in_normal_output(self):
        with tempfile.TemporaryDirectory(prefix="compute-local-test-") as folder:
            runtime = Path(folder)
            with socket.socket() as socket_probe:
                socket_probe.bind(("127.0.0.1", 0))
                port = socket_probe.getsockname()[1]
            base = [sys.executable, str(ROOT / "scripts/local.py")]
            task_environment, attempts = offline_child_environment(runtime)
            def command(action):
                return subprocess.run([*base, action, "--runtime", str(runtime), "--port", str(port), "--no-auto-refresh"],
                                      capture_output=True, text=True, timeout=20, env=task_environment)
            def assert_offline_server():
                url = f"http://127.0.0.1:{port}"
                def read(path):
                    request = urllib.request.Request(url + path, headers={"Authorization": "Bearer " + key})
                    with urllib.request.urlopen(request, timeout=2) as response:
                        return json.load(response)
                state = read("/v1/market/refresh/status")
                self.assertFalse(state["enabled"])
                self.assertFalse(state["running"])
                self.assertTrue(all(row["status"] == "disabled" for row in state["scopes"]))
                index = read("/v1/market/index")
                self.assertEqual(index["observations"], [])
                self.assertEqual(index["catalog_records"], [])
                self.assertFalse(attempts.exists(), "offline server attempted non-loopback network access")
                server_pid = json.loads((runtime / "server.json").read_text())["pid"]
                self.assertIn(str(server_pid), (runtime / "network-guard-pids").read_text().splitlines())
            try:
                first = command("start")
                self.assertEqual(first.returncode, 0, first.stderr)
                key = (runtime / "api-key").read_text().strip()
                self.assertNotIn(key, first.stdout + first.stderr)
                self.assertFalse(json.loads(first.stdout)["execution_enabled"])
                assert_offline_server()
                second = command("start")
                self.assertTrue(json.loads(second.stdout)["reused_existing_service"])
                self.assertTrue(json.loads(command("status").stdout)["running"])
                self.assertEqual(command("stop").returncode, 0)
                self.assertFalse(json.loads(command("status").stdout)["running"])
                self.assertTrue((runtime / "decisions.sqlite").exists())
                self.assertEqual(command("start").returncode, 0)
                self.assertEqual((runtime / "api-key").read_text().strip(), key)
                assert_offline_server()
            finally:
                command("stop")
                self.assertFalse(attempts.exists(), "offline lifecycle attempted non-loopback network access")

    def test_occupied_port_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder, socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            task_environment, attempts = offline_child_environment(Path(folder))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/local.py"), "start", "--runtime", folder, "--port", str(port), "--no-auto-refresh"],
                                    capture_output=True, text=True, timeout=10, env=task_environment)
            self.assertEqual(result.returncode, 2)
            self.assertFalse((Path(folder) / "server.json").exists())
            self.assertFalse(attempts.exists())

    def test_child_network_guard_rejects_external_event_without_dns_or_connect(self):
        with tempfile.TemporaryDirectory() as folder:
            task_environment, attempts = offline_child_environment(Path(folder))
            result = subprocess.run([sys.executable, "-c", "import sys; sys.audit('socket.getaddrinfo', 'non-local.example', 443, 0, 0, 0)"],
                                    capture_output=True, text=True, timeout=10, env=task_environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(attempts.read_text(), "non_loopback_network_forbidden")


if __name__ == "__main__":
    unittest.main()
