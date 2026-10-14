"""Authenticated public demonstrations with separate retained price context."""
from datetime import datetime, timezone
import re

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from compute_pricing.control.reporting import SnapshotStoreError
from compute_pricing.control._numbers import digest


def _model_key(name):
    """Explicit vendor spellings only; memory, fabric and form factor stay distinct."""
    compact = name.casefold().replace(" ", "")
    aliases = {"nvidia-h100": "h100", "nvidia-l40s": "l40s",
        "nvidia-a4000": "a4000", "rtx-a4000": "a4000", "nvidia-rtx-a4000": "a4000"}
    return aliases.get(compact, compact)


def demo_references(packet, model):
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9 _./-]{1,64}", model):
        raise ValueError("bounded hardware model required")
    target = _model_key(model)
    references = []
    for row in packet["observations"]:
        hardware, price = row.get("hardware") or {}, row.get("price")
        name = hardware.get("model")
        if not isinstance(name, str) or _model_key(name) != target or not isinstance(price, dict):
            continue
        if row.get("kind") not in {"aggregate_advertised_index", "listing_ask", "firm_supplier_rfq", "confirmed_rental_trade"}:
            continue
        extensions = row.get("extensions") or {}
        provider = extensions.get("provider") or row["source_id"]
        references.append({"source_id": row["source_id"], "provider": provider,
            "hardware_model": name, "amount": price["amount"], "currency": price["currency"], "unit": price["unit"],
            "kind": row["kind"], "status": "stale reference" if row.get("index_stale", True) else "published reference",
            "stale": row.get("index_stale", True), "terms": extensions.get("billing_type", row["kind"])
                + (" / " + str(extensions["reservation_months"]) + " months" if extensions.get("reservation_months") else ""),
            "observed_at": row.get("observed_at"), "expires_at": row.get("expires_at"),
            "snapshot_id": row.get("snapshot_id"), "model_match_basis": "explicit_model_spelling_only_configuration_unverified",
            "comparable_to_scenario_verified": False,
            "firm_price_eligible": False, "execution_enabled": False})
    for row in packet.get("catalog_records", []):
        name, price = row.get("gpu_name"), row.get("native_price")
        if row.get("kind") != "gpu_vm_reference" or not isinstance(name, str) or _model_key(name) != target or not isinstance(price, dict):
            continue
        references.append({"source_id": row["source_id"], "provider": row.get("provider") or row["source_id"],
            "hardware_model": name, "amount": price["amount"], "currency": price["currency"], "unit": price["unit"],
            "kind": row["kind"], "status": "stale reference" if row.get("index_stale", True) else "published catalog reference",
            "stale": row.get("index_stale", True),
            "terms": str(row.get("gpu_count", "unknown")) + " published GPUs / " + str(row.get("billing_mode", "unknown"))
                + " / " + str(row.get("provider_location", "unknown")),
            "observed_at": row.get("catalog_observed_at"), "expires_at": row.get("expires_at"),
            "snapshot_id": row.get("snapshot_id"), "model_match_basis": "explicit_model_spelling_only_configuration_unverified",
            "comparable_to_scenario_verified": False, "firm_price_eligible": False, "execution_enabled": False})
    # Show current heterogeneous providers before repeated aggregate history.
    # This is display selection, never a benchmark or price estimator.
    references.sort(key=lambda row: row.get("observed_at") or "", reverse=True)
    references.sort(key=lambda row: (row["stale"], row["kind"] == "aggregate_advertised_index"))
    selected, per_group = [], {}
    for row in references:
        group = (row["source_id"], row["provider"], row["kind"])
        if per_group.get(group, 0) >= 4:
            continue
        per_group[group] = per_group.get(group, 0) + 1
        selected.append(row)
        if len(selected) == 24:
            break
    return {"hardware_model": model, "references": selected, "matched_rows": len(references),
        "returned_rows": len(selected), "display_truncated": len(references) > len(selected),
        "source_index_coverage": packet["coverage"], "as_of": packet["as_of"],
        "scope": "same_model_native_unit_reference_display_not_comparable_benchmark",
        "midpoint": None, "bid": None, "firm_price_eligible": False, "execution_enabled": False}


def attach_pricing_demo(app, *, authenticated, json_body, save, market_reader, store):
    @app.get("/v1/pricing/demo/contract", dependencies=[Depends(authenticated)])
    async def contract():
        from compute_pricing.control.demo_pricing.engine import demo_contract
        return demo_contract()

    @app.get("/v1/pricing/demo/references", dependencies=[Depends(authenticated)])
    async def references(hardware_model: str):
        try:
            return await run_in_threadpool(lambda: demo_references(market_reader(), hardware_model))
        except SnapshotStoreError:
            raise HTTPException(503, detail="market_reference_store_unavailable") from None
        except ValueError:
            raise HTTPException(422, detail="invalid_demo_hardware_model") from None

    @app.post("/v1/pricing/demo/evaluate", dependencies=[Depends(authenticated)])
    async def evaluate(request: Request):
        from compute_pricing.control.demo_pricing.engine import evaluate_demo_pricing
        payload = await json_body(request)
        try:
            output = await run_in_threadpool(evaluate_demo_pricing, payload)
            packet = await run_in_threadpool(market_reader)
            output["live_references"] = await run_in_threadpool(demo_references, packet, payload["capacity"]["model"])
            output["evaluated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            output["decision_hash"] = digest({key: value for key, value in output.items() if key != "decision_hash"})
        except SnapshotStoreError:
            raise HTTPException(503, detail="demo_evidence_store_unavailable") from None
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise HTTPException(422, detail="invalid_pricing_demo_input") from None
        return await run_in_threadpool(save, "demo_pricing", payload, output)

    @app.get("/v1/pricing/demo/{snapshot_id}/agreement.pdf", dependencies=[Depends(authenticated)])
    async def agreement(snapshot_id: str):
        if not re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
            raise HTTPException(404, detail="assessment_not_found")
        try:
            snapshot = await run_in_threadpool(store.get, snapshot_id)
            if snapshot is None or snapshot.to_dict()["document"]["kind"] != "demo_pricing":
                raise HTTPException(404, detail="demo_assessment_not_found")
            from compute_pricing.control.demo_pricing.agreement import render_agreement_pdf
            data = await run_in_threadpool(render_agreement_pdf, snapshot.to_dict())
        except SnapshotStoreError:
            raise HTTPException(503, detail="assessment_store_unavailable") from None
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, detail="agreement_terms_not_complete") from None
        return Response(data, media_type="application/pdf", headers={"Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="computebasis-agreement-' + snapshot_id[:12] + '.pdf"',
            "X-Content-Type-Options": "nosniff"})
