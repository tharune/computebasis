"""End-to-end JSON interface checks using independently invented sample inputs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def run_request(self, raw):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, str(ROOT / "scripts/evaluate.py"), "-"],
                              input=raw, text=True, capture_output=True, cwd=ROOT, env=env)

    def test_documented_example_is_a_serializable_indicative_result(self):
        result = self.run_request((ROOT / "examples/request.json").read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["execution_ready"])
        self.assertEqual(output["index"]["status"], "indicative")
        self.assertEqual(output["index"]["price_per_gpu_hour"], "2.9")

    def test_invalid_json_and_wrong_top_level_do_not_emit_tracebacks_or_values(self):
        for raw in ("[1,2]", '{"private_note":"do-not-echo",', '{"extra":NaN}', '{"extra":Infinity}', '{"extra":1e999}'):
            with self.subTest(raw=raw):
                result = self.run_request(raw)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertEqual(json.loads(result.stderr)["status"], "invalid_input")
                self.assertNotIn("do-not-echo", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_changed_rates_and_stale_observations_change_the_result(self):
        data = json.loads((ROOT / "examples/request.json").read_text())
        data.pop("deal")
        for row in data["observations"]:
            row["price"] = "20"
            row["unit"] = "gpu_hour"
        output = json.loads(self.run_request(json.dumps(data)).stdout)
        self.assertEqual(output["index"]["price_per_gpu_hour"], "20")
        data["as_of"] = "2026-11-04T12:00:00Z"
        output = json.loads(self.run_request(json.dumps(data)).stdout)
        self.assertEqual(output["index"]["status"], "held")
        self.assertIsNone(output["index"]["price_per_gpu_hour"])


if __name__ == "__main__":
    unittest.main()
