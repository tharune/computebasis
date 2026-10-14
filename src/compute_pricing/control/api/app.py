"""Local paper-pricing API with explicit reads and immutable decision snapshots."""
from __future__ import annotations

import dataclasses
import datetime as dt
import hmac
import json
from pathlib import Path
import re
import secrets
from typing import Any, Mapping

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from compute_pricing.control._numbers import strict_json
from compute_pricing.control.connectors import ConnectorError, ReadOnlyTransport, collect_source, source_status
from compute_pricing.control.connectors.transport import SourcePolicy, parse_utc
from compute_pricing.control.domain import SCHEMA_VERSION
from compute_pricing.control.domain.generate import json_schema
from compute_pricing.control.reporting import SnapshotStore, SnapshotStoreError
from compute_pricing.control.treasury import evaluate_cash_payload

SERVICE_VERSION = "0.2.0"
MAX_REQUEST_BYTES = 2 * 1024 * 1024


def _evaluate_pricing(payload: Mapping[str, Any]) -> dict[str, Any]:
    from compute_pricing.control.pricing import evaluate_pricing
    return evaluate_pricing(payload)


def _evaluate_scenarios(payload: Mapping[str, Any]) -> dict[str, Any]:
    from compute_pricing.control.pricing import evaluate_pricing_scenarios
    return evaluate_pricing_scenarios(payload)


def _evaluate_inference(payload: Mapping[str, Any]) -> dict[str, Any]:
    from compute_pricing.control.inference import evaluate_inference_payload
    return evaluate_inference_payload(payload).to_dict()


def _evaluate_calibration(payload: Mapping[str, Any]) -> dict[str, Any]:
    from compute_pricing.control.calibration import evaluate_calibration_payload
    return evaluate_calibration_payload(payload)


def _evaluate_financing(payload: Mapping[str, Any]) -> dict[str, Any]:
    from compute_pricing.control.financing import evaluate_financing_payload
    return evaluate_financing_payload(payload)


async def _json_body(request: Request, *, optional: bool = False) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    size = request.headers.get("content-length")
    if size is not None:
        try:
            if not 0 <= int(size) <= MAX_REQUEST_BYTES:
                raise HTTPException(413, detail="request_size_limit")
        except ValueError:
            raise HTTPException(400, detail="invalid_content_length") from None
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_REQUEST_BYTES:
            raise HTTPException(413, detail="request_size_limit")
    if not data and optional:
        return {}
    if content_type != "application/json":
        raise HTTPException(415, detail="json_content_type_required")
    try:
        payload = strict_json(bytes(data))
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, detail="invalid_json") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, detail="json_object_required")
    return payload


def _latest_collection(batch: Any) -> dict[str, Any]:
    result = batch.to_dict()
    observations = result["observations"]
    if batch.source_id == "getdeploying":
        captured = parse_utc(result["raw_metadata"]["captured_at"])
        complete = [item for item in observations if parse_utc(item["observed_at"]) + dt.timedelta(days=7) <= captured]
        newest = max((item["observed_at"] for item in complete), default=None)
        selected = [item for item in complete if item["observed_at"] == newest]
        result["observations"] = selected
        result["selection"] = {"method": "latest_complete_week", "selected_observed_at": newest,
                               "history_rows_received": len(observations), "returned_rows": len(selected)}
    else:
        result["selection"] = {"method": "catalog_response", "returned_rows": len(observations)}
    return result


def create_app(*, api_key: str, store_path: Path,
               source_policies: Mapping[str, SourcePolicy] | None = None,
               transport: ReadOnlyTransport | None = None,
               collection_plan: list[dict] | None = None,
               local_instance_id: str | None = None) -> FastAPI:
    if not isinstance(api_key, str) or not 32 <= len(api_key) <= 256 or not re.fullmatch(r"[!-~]+", api_key):
        raise ValueError("API key must be an explicit 32-256 character printable ASCII secret without whitespace")
    store = SnapshotStore(store_path)
    if local_instance_id is not None and not re.fullmatch(r"[a-f0-9]{32}", local_instance_id):
        raise ValueError("invalid local instance ID")
    policies = dict(source_policies or {})
    collector_transport = transport or ReadOnlyTransport()
    plan = json.loads(json.dumps(collection_plan or [], allow_nan=False))
    if not isinstance(plan, list) or len(plan) > 32 or any(not isinstance(row, dict) or set(row) != {"source_id", "filters"} or not isinstance(row["source_id"], str) or not isinstance(row["filters"], dict) for row in plan):
        raise ValueError("collection plan requires bounded explicit source/filter records")
    app = FastAPI(title="Compute Pricing", version=SERVICE_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    versions = {"api": SERVICE_VERSION, "domain": SCHEMA_VERSION, "snapshot": "1.0"}

    async def authenticated(request: Request) -> None:
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        authorized = scheme.lower() == "bearer" and bool(separator) and len(token) <= 256
        valid = hmac.compare_digest((token if len(token) <= 256 else "").encode("utf-8"), api_key.encode("ascii"))
        if not authorized or not valid:
            raise HTTPException(401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})

    def save(kind: str, payload: Mapping[str, Any], output: Mapping[str, Any]) -> dict[str, Any]:
        snapshot_versions = dict(versions)
        model_versions = output.get("versions", {})
        if isinstance(model_versions, Mapping):
            snapshot_versions.update({"evaluation." + name: version for name, version in model_versions.items()
                                      if isinstance(name, str) and isinstance(version, str) and name and version})
        for field, label in (("model_version", "model"), ("policy_version", "policy")):
            if isinstance(output.get(field), str) and output[field]:
                snapshot_versions["evaluation." + label] = output[field]
        if kind == "cash":
            snapshot_versions["evaluation.model"] = "dated-cash/1.0.0"
        elif kind == "market_collection":
            snapshot_versions["evaluation.model"] = "readonly-adapter/1.0.0"
        try:
            snapshot = store.put(kind=kind, input_payload=payload, output_payload=output, versions=snapshot_versions)
        except SnapshotStoreError:
            raise HTTPException(503, detail="snapshot_store_unavailable") from None
        return {"snapshot_id": snapshot.digest, "created_at": snapshot.created_at,
                "versions": snapshot_versions, "result": dict(output), "execution_enabled": False}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        result = {"status": "ok", "service": "compute-pricing", "version": SERVICE_VERSION,
                  "mode": "local-paper", "execution_enabled": False}
        if local_instance_id:
            result["local_instance_id"] = local_instance_id
        return result

    @app.get("/v1/contracts/schema", dependencies=[Depends(authenticated)])
    async def schema() -> dict[str, Any]:
        return json_schema()

    @app.get("/v1/sources", dependencies=[Depends(authenticated)])
    async def sources() -> dict[str, Any]:
        return {"sources": source_status(policies), "execution_enabled": False}

    @app.get("/v1/market/index", dependencies=[Depends(authenticated)])
    async def index() -> dict[str, Any]:
        from .market import market_index
        try:
            return await run_in_threadpool(market_index, store, policies, plan)
        except SnapshotStoreError:
            raise HTTPException(503, detail="snapshot_store_unavailable") from None

    def collect_and_save(source_id, filters):
        if source_id not in policies:
            raise ConnectorError("source_not_admitted")
        policy = policies[source_id]
        for scope in ("observe", "retain", "benchmark"):
            policy.require(scope)
        # Multiple explicitly requested regions share a host quota. Wait only
        # inside the configured budget; long Retry-After holds remain enforced.
        collector_transport.wait_for_source(source_id, max_wait_s=collector_transport.max_wait_s)
        batch = collect_source(source_id, policies, transport=collector_transport, filters=filters)
        if batch.source_id != source_id:
            raise ConnectorError("source_policy_mismatch")
        for scope in ("observe", "retain", "benchmark"):
            policy.require(scope)
        admitted_input = {"source_id": source_id, "filters": filters,
                          "source_policy": {field.name: dict(policy.permissions) if field.name == "permissions" else getattr(policy, field.name)
                                            for field in dataclasses.fields(policy)}}
        return save("market_collection", admitted_input, _latest_collection(batch))

    @app.post("/v1/market/refresh", dependencies=[Depends(authenticated)])
    async def refresh(request: Request) -> dict[str, Any]:
        payload = await _json_body(request, optional=True)
        attempted_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        if set(payload) - {"source_ids", "requests"} or "source_ids" in payload and "requests" in payload:
            raise HTTPException(422, detail="invalid_refresh_input")
        if "requests" in payload:
            requests = payload["requests"]
        else:
            source_ids = payload.get("source_ids")
            if source_ids is not None and (not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 32 or any(not isinstance(source, str) for source in source_ids) or len(set(source_ids)) != len(source_ids)):
                raise HTTPException(422, detail="invalid_refresh_input")
            selected = source_ids if source_ids is not None else [name for name, policy in policies.items() if policy.enabled]
            requests = [row for row in plan if row["source_id"] in selected]
            planned_sources = {row["source_id"] for row in requests}
            requests += [{"source_id": source, "filters": {}} for source in selected if source not in planned_sources]
        if not isinstance(requests, list) or not 1 <= len(requests) <= 32 or any(not isinstance(row, dict) or set(row) != {"source_id", "filters"} or not isinstance(row["source_id"], str) or not isinstance(row["filters"], dict) for row in requests):
            raise HTTPException(422, detail="invalid_refresh_input")
        keys = [(row["source_id"], json.dumps(row["filters"], sort_keys=True)) for row in requests]
        if len(set(keys)) != len(keys):
            raise HTTPException(422, detail="duplicate_refresh_scope")
        updated, held, failed = [], [], []
        for row in requests:
            try:
                result = await run_in_threadpool(collect_and_save, row["source_id"], row["filters"])
                updated.append({"source_id": row["source_id"], "filters": row["filters"], "snapshot_id": result["snapshot_id"],
                                "observation_count": len(result["result"].get("observations", [])),
                                "catalog_record_count": len(result["result"].get("catalog_records", [])),
                                "coverage": result["result"].get("coverage", {})})
            except ConnectorError as exc:
                destination = held if exc.code.startswith("admission_blocked") or exc.code in {"source_not_admitted", "authentication_missing", "source_cooldown_active", "source_collection_in_progress"} else failed
                destination.append({"source_id": row["source_id"], "filters": row["filters"], "reason": exc.code})
            except HTTPException:
                failed.append({"source_id": row["source_id"], "reason": "snapshot_store_unavailable"})
        output = {"updated": updated, "held": held, "failed": failed, "execution_enabled": False,
                  "refresh_mode": "explicit_manual_read", "partial_refresh": bool(held or failed),
                  "refresh_event_id": secrets.token_hex(16), "attempted_at": attempted_at,
                  "completed_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")}
        receipt = await run_in_threadpool(save, "market_refresh", {"requests": requests}, output)
        return {**output, "snapshot_id": receipt["snapshot_id"], "created_at": receipt["created_at"]}

    @app.post("/v1/sources/{source_id}/collect", dependencies=[Depends(authenticated)])
    async def collect(source_id: str, request: Request) -> dict[str, Any]:
        payload = await _json_body(request, optional=True)
        if set(payload) - {"filters"} or not isinstance(payload.get("filters", {}), dict):
            raise HTTPException(422, detail="invalid_collection_input")
        if source_id not in policies:
            raise HTTPException(409, detail="source_not_admitted")
        try:
            return await run_in_threadpool(collect_and_save, source_id, payload.get("filters", {}))
        except ConnectorError as exc:
            status = 429 if exc.code in {"source_collection_in_progress", "source_cooldown_active"} else 409 if exc.code.startswith("admission_blocked") or exc.code in {"authentication_missing", "unknown_or_unadmitted_source", "source_transport_not_implemented"} else 502
            # Codes are generated by the connector and contain no input values.
            raise HTTPException(status, detail=exc.code) from None

    @app.post("/v1/pricing/evaluate", dependencies=[Depends(authenticated)])
    async def pricing(request: Request) -> dict[str, Any]:
        payload = await _json_body(request)
        try:
            output = await run_in_threadpool(_evaluate_pricing, payload)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise HTTPException(422, detail="invalid_pricing_input") from None
        return await run_in_threadpool(save, "pricing", payload, output)

    @app.post("/v1/cash/evaluate", dependencies=[Depends(authenticated)])
    async def cash(request: Request) -> dict[str, Any]:
        payload = await _json_body(request)
        try:
            output = (await run_in_threadpool(evaluate_cash_payload, payload)).to_dict()
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise HTTPException(422, detail="invalid_cash_input") from None
        return await run_in_threadpool(save, "cash", payload, output)

    async def pure_evaluation(request: Request, evaluator, kind: str) -> dict[str, Any]:
        payload = await _json_body(request)
        try:
            output = await run_in_threadpool(evaluator, payload)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise HTTPException(422, detail="invalid_" + kind + "_input") from None
        return await run_in_threadpool(save, kind, payload, output)

    @app.post("/v1/pricing/scenarios", dependencies=[Depends(authenticated)])
    async def scenarios(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, _evaluate_scenarios, "pricing_scenarios")

    @app.post("/v1/inference/evaluate", dependencies=[Depends(authenticated)])
    async def inference(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, _evaluate_inference, "inference")

    @app.post("/v1/calibration/evaluate", dependencies=[Depends(authenticated)])
    async def calibration(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, _evaluate_calibration, "calibration")

    @app.post("/v1/financing/evaluate", dependencies=[Depends(authenticated)])
    async def financing(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, _evaluate_financing, "financing")

    @app.get("/v1/decisions/{snapshot_id}", dependencies=[Depends(authenticated)])
    async def decision(snapshot_id: str) -> dict[str, Any]:
        try:
            snapshot = await run_in_threadpool(store.get, snapshot_id)
        except SnapshotStoreError as exc:
            raise HTTPException(400 if exc.code == "invalid_snapshot_id" else 503, detail=exc.code) from None
        if snapshot is None:
            raise HTTPException(404, detail="snapshot_not_found")
        return snapshot.to_dict()

    from compute_pricing.control.workbench import add_workbench
    add_workbench(app)
    return app
