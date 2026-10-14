"""Run a declared read-only pricing or cash scenario from a JSON file."""
import argparse
import json
from pathlib import Path
import sys

from ._numbers import strict_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("pricing", "cash"))
    parser.add_argument("input", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.input.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("input too large")
        payload = strict_json(arguments.input.read_bytes())
        if arguments.kind == "pricing":
            from .pricing import evaluate_pricing
            result = evaluate_pricing(payload)
        else:
            from .treasury import evaluate_cash_payload
            result = evaluate_cash_payload(payload).to_dict()
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError):
        print("Invalid or unreadable scenario; no action executed.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
