"""Evaluate a JSON request from a file or standard input; no external requests."""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing import InputError, evaluate


def reject_constant(value):
    raise ValueError("Nonstandard JSON constant")


def finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Nonfinite JSON number")
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", help="JSON file, or - for standard input")
    args = parser.parse_args()
    try:
        text = sys.stdin.read() if args.request == "-" else Path(args.request).read_text(encoding="utf-8")
        request = json.loads(text, parse_constant=reject_constant, parse_float=finite_float)
        if not isinstance(request, dict):
            raise InputError("input", "must be an object")
        result = evaluate(request)
        rendered = json.dumps(result, indent=2, allow_nan=False)
    except (InputError, ValueError, OSError, UnicodeError):
        print(json.dumps({"status": "invalid_input", "message": "Request failed input validation; check its schema and units."}), file=sys.stderr)
        return 2
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
