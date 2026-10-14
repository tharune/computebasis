"""Require the offline Node suite; no browser, network or package installation."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.workbench.routes import ASSETS


class FrontendBehaviorV3Tests(unittest.TestCase):
    def test_actual_workbench_handlers_with_browserless_dom(self):
        node = os.environ.get("COMPUTEBASIS_NODE") or shutil.which("node")
        self.assertTrue(node, "Node 24 is required for frontend behavior tests. Set COMPUTEBASIS_NODE to an installed Node executable.")
        suite = Path(__file__).with_name("workbench_behavior.test.js")
        result = subprocess.run(
            [node, "--test", str(suite)],
            env={**os.environ, "COMPUTEBASIS_WORKBENCH_ASSETS": str(ASSETS)},
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
