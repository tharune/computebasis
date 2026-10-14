"""Validate public code, generated contracts, links and invented examples offline."""
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compute_pricing.control.domain.generate import schema_text, typescript_text


def main():
    expected = {"docs/contracts/domain-v1.schema.json": schema_text(),
                "docs/contracts/domain-v1.types.txt": typescript_text()}
    for path, content in expected.items():
        if (ROOT / path).read_text() != content:
            raise ValueError("generated contract drift")
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
        for target in re.findall(r"\[[^\]]*\]\(([^\)]+)\)", path.read_text()):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not (path.parent / unquote(target.split("#", 1)[0])).resolve().exists():
                raise ValueError("broken documentation link")
    commands = [[sys.executable, "-m", "ruff", "check", "--no-cache", "src/compute_pricing/control", "scripts/serve.py", "scripts/validate.py", "scripts/gen_quote_book_seed.py"],
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                [sys.executable, "-m", "compute_pricing.control.cli", "pricing", "examples/control-pricing.json"],
                [sys.executable, "scripts/evaluate.py", "examples/request.json"],
                [sys.executable, "scripts/gen_quote_book_seed.py", "--check"],
                [sys.executable, "scripts/book_deal_example.py"],
                [sys.executable, "scripts/pricing_demo_example.py"]]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)
    print("Offline public validation passed")


if __name__ == "__main__":
    main()
