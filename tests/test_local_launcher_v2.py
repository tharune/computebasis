"""Actual isolated loopback lifecycle; no vendor calls or permanent jobs."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LocalLauncherTests(unittest.TestCase):
    def test_start_reuse_stop_restart_and_secret_not_in_normal_output(self):
        with tempfile.TemporaryDirectory(prefix="compute-local-test-") as folder:
            runtime = Path(folder)
            with socket.socket() as socket_probe:
                socket_probe.bind(("127.0.0.1", 0))
                port = socket_probe.getsockname()[1]
            base = [sys.executable, str(ROOT / "scripts/local.py")]
            def command(action):
                return subprocess.run([*base, action, "--runtime", str(runtime), "--port", str(port)],
                                      capture_output=True, text=True, timeout=20)
            try:
                first = command("start")
                self.assertEqual(first.returncode, 0, first.stderr)
                key = (runtime / "api-key").read_text().strip()
                self.assertNotIn(key, first.stdout + first.stderr)
                self.assertFalse(json.loads(first.stdout)["execution_enabled"])
                second = command("start")
                self.assertTrue(json.loads(second.stdout)["reused_existing_service"])
                self.assertTrue(json.loads(command("status").stdout)["running"])
                self.assertEqual(command("stop").returncode, 0)
                self.assertFalse(json.loads(command("status").stdout)["running"])
                self.assertTrue((runtime / "decisions.sqlite").exists())
                self.assertEqual(command("start").returncode, 0)
                self.assertEqual((runtime / "api-key").read_text().strip(), key)
            finally:
                command("stop")

    def test_occupied_port_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder, socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            result = subprocess.run([sys.executable, str(ROOT / "scripts/local.py"), "start", "--runtime", folder, "--port", str(port)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse((Path(folder) / "server.json").exists())


if __name__ == "__main__":
    unittest.main()
