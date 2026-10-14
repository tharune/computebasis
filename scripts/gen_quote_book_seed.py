#!/usr/bin/env python3
"""Generate or check the independent simulation fixture, without reading files."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compute_pricing.control.quote_book.seed import AS_OF, DEFAULT_SEED, seed_payload, validate_population


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Bounded independent simulation seed")
    parser.add_argument("--as-of", default=AS_OF, help="Invented simulation date, YYYY-MM-DD within 2000–2099")
    parser.add_argument("--check", action="store_true", help="Verify generated coverage and fields; no external input")
    parser.add_argument("--json", action="store_true", help="Emit the generated fixture to standard output")
    args = parser.parse_args(argv)
    try:
        payload = seed_payload(args.seed, as_of=args.as_of)
        summary = validate_population(payload["providers"], payload["quotes"], as_of=args.as_of)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False))
    else:
        print(json.dumps({**summary, "seed_value": args.seed, "simulation_as_of": args.as_of,
            "checked": args.check}, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
