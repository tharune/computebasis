#!/usr/bin/env python3
"""Start the local browser workbench and its bounded, approved public feed reads."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    defaults = Path(__file__).resolve().parents[1] / "examples"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path, help="Absolute SQLite path outside every Git checkout")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--source-config", type=Path, default=defaults / "source-admission.json", help="Reviewed source permissions; defaults to the repository example")
    parser.add_argument("--collection-plan", type=Path, default=defaults / "collection-plan.json", help="Explicit bounded public source/filter scopes")
    parser.add_argument("--auto-refresh-config", type=Path, default=defaults / "auto-refresh.json", help="Application-owned refresh cadence/backoff settings")
    parser.add_argument("--no-auto-refresh", action="store_true", help="Disable startup and periodic reads; keep manual refresh available")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be in 1024-65535")
    key = os.environ.get("COMPUTE_PRICING_API_KEY") or None
    from compute_pricing.control.api import create_app
    from compute_pricing.control.connectors import load_policies
    import uvicorn
    try:
        from compute_pricing.control._numbers import strict_json
        def document(path):
            with path.open("rb") as handle:
                encoded = handle.read(256 * 1024 + 1)
            if len(encoded) > 256 * 1024:
                raise ValueError("configuration size limit")
            return strict_json(encoded)
        automatic = {"enabled": False} if args.no_auto_refresh else document(args.auto_refresh_config)
        app = create_app(api_key=key, store_path=args.store,
                         source_policies=load_policies(args.source_config),
                         collection_plan=document(args.collection_plan), auto_refresh=automatic,
                         workbench_origin=f"http://127.0.0.1:{args.port}",
                         local_instance_id=os.environ.get("COMPUTEBASIS_LOCAL_INSTANCE_ID"))
    except (ValueError, OSError):
        parser.error("supply an absolute store path outside Git and valid reviewed configuration; optional API client keys must be strong")
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
