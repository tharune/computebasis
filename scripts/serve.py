#!/usr/bin/env python3
"""Start the authenticated loopback-only development API; no startup feed calls."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path, help="Absolute SQLite path outside every Git checkout")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--source-config", type=Path, help="Explicit reviewed source admission config; omitted means all feeds blocked")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be in 1024-65535")
    key = os.environ.get("COMPUTE_PRICING_API_KEY", "")
    from compute_pricing.control.api import create_app
    from compute_pricing.control.connectors import load_policies
    import uvicorn
    try:
        app = create_app(api_key=key, store_path=args.store,
                         source_policies=load_policies(args.source_config) if args.source_config else None)
    except ValueError:
        parser.error("supply a strong COMPUTE_PRICING_API_KEY, an absolute store path outside Git, and valid source config")
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
