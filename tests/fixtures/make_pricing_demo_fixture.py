"""Regenerate tests/fixtures/pricing-demo.json from the real backend.

    PYTHONPATH=src python tests/fixtures/make_pricing_demo_fixture.py

The fixture holds what /v1/pricing/demo/contract, /evaluate and /references send: the contract with its three invented scenarios, one
saved receipt per scenario, a held receipt (stable asset with unknown depeg status), and a reference response built by the real
demo_references from a small invented market packet. Nothing here describes a real provider or price.
"""
import copy
import hashlib
import json
from pathlib import Path

from compute_pricing.control.api.pricing_demo import demo_references
from compute_pricing.control.demo_pricing.engine import demo_contract, evaluate_demo_pricing

CREATED = "2026-10-14T23:27:30.000000Z"


def packet():
    def observation(source, provider, amount, kind, stale):
        return {"source_id": source, "kind": kind, "hardware": {"model": "H100"}, "price": {"amount": amount, "currency": "USD", "unit": "gpu_hour"},
                "observed_at": "2026-10-14T20:00:00Z", "expires_at": None, "snapshot_id": "snap-" + source, "index_stale": stale,
                "extensions": {"provider": provider, "billing_type": "on_demand"}}
    return {"observations": [observation("source:invented-a", "Invented Cloud A", "2.490", "listing_ask", False),
                             observation("source:invented-b", "Invented Cloud B", "2.915", "listing_ask", True)],
            "catalog_records": [{"source_id": "source:invented-c", "kind": "gpu_vm_reference", "gpu_name": "NVIDIA-H100", "provider": "Invented Cloud C",
                                 "native_price": {"amount": "3.100", "currency": "USD", "unit": "gpu_hour"}, "gpu_count": 8, "billing_mode": "on_demand",
                                 "provider_location": "invented-region", "index_stale": False, "catalog_observed_at": "2026-10-14T19:00:00Z",
                                 "snapshot_id": "snap-c"}],
            "coverage": {"population": "invented"}, "as_of": "2026-10-14T23:00:00Z"}


def receipt(inputs, references):
    result = evaluate_demo_pricing(inputs)
    result["live_references"] = references
    result["evaluated_at"] = CREATED
    result["decision_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    snapshot = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return {"snapshot_id": snapshot, "created_at": CREATED, "versions": {"api": "0.13.0"}, "result": result, "execution_enabled": False}


def main():
    contract = demo_contract()
    market = packet()
    references = {model: demo_references(market, model) for model in ("H100", "L40S", "A4000")}
    receipts = [receipt(case["inputs"], references[case["inputs"]["capacity"]["model"]]) for case in contract["scenarios"]]
    held_inputs = copy.deepcopy(contract["scenarios"][2]["inputs"])
    held_inputs["settlement"].update(asset_kind="stable_asset", asset_unit="USDX", depeg_status="unknown")
    held = receipt(held_inputs, references["A4000"])
    target = Path(__file__).with_name("pricing-demo.json")
    target.write_text(json.dumps({"contract": contract, "receipts": receipts, "held": held, "held_inputs": held_inputs, "references": references}, indent=1, sort_keys=True) + "\n")
    print("wrote", target, target.stat().st_size, "bytes; held status:", held["result"]["status"], held["result"]["hold_reasons"])


if __name__ == "__main__":
    main()
