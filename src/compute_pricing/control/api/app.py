"""Local paper-pricing API, scoped sessions and immutable decision snapshots."""
from __future__ import annotations

import dataclasses
import datetime as dt
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from typing import Any, Mapping

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from compute_pricing.control import __version__ as SERVICE_VERSION
from compute_pricing.control._numbers import strict_json
from compute_pricing.control.connectors import ConnectorError, ReadOnlyTransport, collect_source, source_status
from compute_pricing.control.connectors.transport import SourcePolicy, parse_utc
from compute_pricing.control.domain import SCHEMA_VERSION
from compute_pricing.control.domain.generate import json_schema
from compute_pricing.control.reporting import SnapshotStore, SnapshotStoreError
from compute_pricing.control.treasury import evaluate_cash_payload
from .refresh import AutomaticRefresh, CollectionCoordinator, RefreshConfig
from .sessions import BrowserSessions, attach_sessions, request_scope
from .provenance import PricingProvenance
from compute_pricing.control.policies.repository import PolicyStoreError

MAX_REQUEST_BYTES = 2 * 1024 * 1024
# Leave room for the canonical snapshot envelope and evaluation output wrappers.
MAX_REQUEST_DEPTH = 24
MAX_REQUEST_NODES = 50000
MAX_CONCURRENT_COLLECTIONS = 2


def _request_tree(payload: Any) -> None:
    """Bound work before dispatch; reject strings that cannot be stored as UTF-8."""
    pending, nodes = [(payload, 0)], 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > MAX_REQUEST_DEPTH:
            raise ValueError("request_nesting_limit")
        if nodes > MAX_REQUEST_NODES:
            raise ValueError("request_structure_limit")
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
            pending.extend((key, depth + 1) for key in value)
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise ValueError("invalid_json_unicode") from None


def _connector_code(error: ConnectorError) -> str:
    """An unexpected connector diagnostic must not become a response-body leak."""
    code = error.code
    if not isinstance(code, str) or len(code) > 256 or not re.fullmatch(r"[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)*)?", code):
        return "source_collection_failed"
    return code


def _source_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value))


class _CollectionAdmission:
    """Keep a permit until the worker actually stops, even if HTTP is cancelled."""
    def __init__(self, slots: threading.BoundedSemaphore):
        if not slots.acquire(blocking=False):
            raise HTTPException(429, detail="collection_capacity_exceeded", headers={"Retry-After": "1"})
        self._slots, self._guard = slots, threading.Lock()
        self._workers, self._closed, self._released = 0, False, False

    def _release_if_finished(self):
        if self._closed and not self._workers and not self._released:
            self._slots.release()
            self._released = True

    def run(self, function, *args):
        with self._guard:
            if self._closed:
                raise ConnectorError("collection_request_cancelled")
            self._workers += 1
        try:
            return function(*args)
        finally:
            with self._guard:
                self._workers -= 1
                self._release_if_finished()

    def close(self):
        with self._guard:
            self._closed = True
            self._release_if_finished()


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


def _evaluate_portfolio(payload: Mapping[str, Any]) -> dict[str, Any]:
    from compute_pricing.control.portfolio import evaluate_portfolio_payload
    return evaluate_portfolio_payload(payload)


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
    try:
        _request_tree(payload)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from None
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
        result["selection"] = {"method": "catalog_response", "returned_rows": len(observations),
                               "returned_catalog_records": len(result.get("catalog_records", []))}
    return result


def create_app(*, api_key: str | None = None, store_path: Path,
               source_policies: Mapping[str, SourcePolicy] | None = None,
               transport: ReadOnlyTransport | None = None,
               collection_plan: list[dict] | None = None,
               local_instance_id: str | None = None,
               workbench_origin: str | None = None,
               auto_refresh: dict | None = None) -> FastAPI:
    if api_key is not None and (not isinstance(api_key, str) or not 32 <= len(api_key) <= 256 or not re.fullmatch(r"[!-~]+", api_key)):
        raise ValueError("API key must be an explicit 32-256 character printable ASCII secret without whitespace")
    sessions = BrowserSessions(workbench_origin) if workbench_origin is not None else None
    if api_key is None and sessions is None:
        raise ValueError("an explicit API key or loopback browser origin is required")
    refresh_config = RefreshConfig.parse(auto_refresh)
    store = SnapshotStore(store_path)
    if local_instance_id is not None and (not isinstance(local_instance_id, str) or not re.fullmatch(r"[a-f0-9]{32}", local_instance_id)):
        raise ValueError("invalid local instance ID")
    if source_policies is not None and not isinstance(source_policies, Mapping):
        raise ValueError("source policies require an explicit identity mapping")
    policies = dict(source_policies or {})
    if any(not _source_id(name) or not isinstance(policy, SourcePolicy) or name != policy.source_id for name, policy in policies.items()):
        raise ValueError("source policy keys must match admitted source identities")
    collector_transport = transport or ReadOnlyTransport()
    try:
        _request_tree(collection_plan if collection_plan is not None else [])
        plan = json.loads(json.dumps(collection_plan if collection_plan is not None else [], allow_nan=False))
    except (ValueError, TypeError, RecursionError):
        raise ValueError("collection plan requires bounded explicit source/filter records") from None
    if not isinstance(plan, list) or len(plan) > 32 or any(not isinstance(row, dict) or set(row) != {"source_id", "filters"} or not _source_id(row["source_id"]) or not isinstance(row["filters"], dict) for row in plan):
        raise ValueError("collection plan requires bounded explicit source/filter records")
    @asynccontextmanager
    async def lifespan(application):
        await application.state.auto_refresh.start()
        try:
            yield
        finally:
            await application.state.auto_refresh.stop()

    app = FastAPI(title="Compute Pricing", version=SERVICE_VERSION, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store
    app.state.browser_sessions = sessions
    # Legacy manual refreshes hold a permit for the full sequence. Automatic
    # mode shares one permit per coalesced scope through read and persistence.
    collection_slots = threading.BoundedSemaphore(MAX_CONCURRENT_COLLECTIONS)
    versions = {"api": SERVICE_VERSION, "domain": SCHEMA_VERSION, "snapshot": "1.0"}

    async def authenticated(request: Request) -> None:
        authorization = request.headers.getlist("authorization")
        if authorization:
            scheme, separator, token = authorization[0].partition(" ")
            authorized = len(authorization) == 1 and scheme.lower() == "bearer" and bool(separator) and len(token) <= 256
            valid = api_key is not None and hmac.compare_digest((token if len(token) <= 256 else "").encode("utf-8"), api_key.encode("ascii"))
            if authorized and valid:
                return
            raise HTTPException(401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})
        if sessions is not None:
            sessions.authorize(request, scope=request_scope(request))
            return
        raise HTTPException(401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})

    attach_sessions(app, sessions, json_body=_json_body)

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
            snapshot_versions["evaluation.model"] = output.get("accounting_extension", {}).get("model", "dated-cash/1.0.0")
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

    @app.get("/v1/cash/contract", dependencies=[Depends(authenticated)])
    async def cash_input_contract() -> dict[str, Any]:
        from .treasury_contract import cash_contract
        return cash_contract()

    @app.get("/v1/cash/template", dependencies=[Depends(authenticated)])
    async def cash_input_template() -> dict[str, Any]:
        from .treasury_contract import cash_template
        return cash_template()

    @app.get("/v1/sources", dependencies=[Depends(authenticated)])
    async def sources() -> dict[str, Any]:
        return {"sources": source_status(policies), "execution_enabled": False}

    @app.post("/v1/requests/parse", dependencies=[Depends(authenticated)])
    async def parse_request(request: Request) -> dict[str, Any]:
        # A pure editor boundary: no evaluation, persistence or semantic approval.
        payload = await _json_body(request)
        return {"request": payload, "boundary_validation": "json_only", "execution_enabled": False}

    @app.get("/v1/market/index", dependencies=[Depends(authenticated)])
    async def index() -> dict[str, Any]:
        from .market import market_index
        try:
            return await run_in_threadpool(market_index, store, policies, plan)
        except SnapshotStoreError:
            raise HTTPException(503, detail="snapshot_store_unavailable") from None

    @app.get("/v1/market/curves", dependencies=[Depends(authenticated)])
    async def current_curves() -> dict[str, Any]:
        from .market import market_index
        from compute_pricing.control.curves import observed_commitment_curves
        try:
            packet = await run_in_threadpool(market_index, store, policies, plan, row_limit=10000)
            return await run_in_threadpool(observed_commitment_curves, packet)
        except SnapshotStoreError:
            raise HTTPException(503, detail="snapshot_store_unavailable") from None

    @app.get("/v1/power/contract", dependencies=[Depends(authenticated)])
    async def power_input_contract():
        from compute_pricing.control.power import power_contract
        return power_contract()

    @app.get("/v1/curves/contract", dependencies=[Depends(authenticated)])
    async def curve_input_contract():
        from compute_pricing.control.curves import term_curve_contract
        return term_curve_contract()

    def collect_and_save(source_id, filters):
        if source_id not in policies:
            raise ConnectorError("source_not_admitted")
        policy = policies[source_id]
        for scope in ("observe", "retain", "benchmark"):
            policy.require(scope)
        # Multiple explicitly requested regions share a host quota. Wait only
        # inside the configured budget; long Retry-After holds remain enforced.
        try:
            collector_transport.wait_for_source(source_id, max_wait_s=collector_transport.max_wait_s)
            batch = collect_source(source_id, policies, transport=collector_transport, filters=filters)
            if batch.source_id != source_id:
                raise ConnectorError("source_policy_mismatch")
            output = _latest_collection(batch)
        except ConnectorError:
            raise
        except Exception:
            # External parsing/transport failures stay local to this source. No
            # response body, endpoint, credentials or exception text is exposed.
            raise ConnectorError("source_collection_failed") from None
        current_policy = policies.get(source_id)
        if current_policy is None or current_policy != policy:
            raise ConnectorError("source_policy_changed_during_collection")
        for scope in ("observe", "retain", "benchmark"):
            current_policy.require(scope)
        admitted_input = {"source_id": source_id, "filters": filters,
                          "source_policy": {field.name: dict(policy.permissions) if field.name == "permissions" else getattr(policy, field.name)
                                            for field in dataclasses.fields(policy)}}
        return save("market_collection", admitted_input, output)

    async def coordinated_worker(source_id, filters):
        admission = _CollectionAdmission(collection_slots)
        try:
            return await run_in_threadpool(admission.run, collect_and_save, source_id, filters)
        finally:
            admission.close()

    coordinator = CollectionCoordinator(coordinated_worker)
    automatic = AutomaticRefresh(refresh_config, plan, policies, coordinator,
                                 cooldown=collector_transport.cooldown_remaining)
    app.state.auto_refresh = automatic
    app.state.collection_coordinator = coordinator

    @app.get("/v1/market/refresh/status", dependencies=[Depends(authenticated)])
    async def refresh_status():
        return automatic.status()

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
            if "source_ids" in payload and (not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 32 or any(not _source_id(source) for source in source_ids) or len(set(source_ids)) != len(source_ids)):
                raise HTTPException(422, detail="invalid_refresh_input")
            selected = source_ids if source_ids is not None else [name for name, policy in policies.items() if policy.enabled]
            requests = [row for row in plan if row["source_id"] in selected]
            planned_sources = {row["source_id"] for row in requests}
            requests += [{"source_id": source, "filters": {}} for source in selected if source not in planned_sources]
        if not isinstance(requests, list) or not 1 <= len(requests) <= 32 or any(not isinstance(row, dict) or set(row) != {"source_id", "filters"} or not _source_id(row["source_id"]) or not isinstance(row["filters"], dict) for row in requests):
            raise HTTPException(422, detail="invalid_refresh_input")
        keys = [(row["source_id"], json.dumps(row["filters"], sort_keys=True)) for row in requests]
        if len(set(keys)) != len(keys):
            raise HTTPException(422, detail="duplicate_refresh_scope")
        admission = None if refresh_config.enabled else _CollectionAdmission(collection_slots)
        try:
            updated, held, failed = [], [], []
            for row in requests:
                try:
                    result = await coordinator.collect(row["source_id"], row["filters"]) if refresh_config.enabled else await run_in_threadpool(admission.run, collect_and_save, row["source_id"], row["filters"])
                    updated.append({"source_id": row["source_id"], "filters": row["filters"], "snapshot_id": result["snapshot_id"],
                                    "observation_count": len(result["result"].get("observations", [])),
                                    "catalog_record_count": len(result["result"].get("catalog_records", [])),
                                    "coverage": result["result"].get("coverage", {})})
                except ConnectorError as exc:
                    code = _connector_code(exc)
                    destination = held if code.startswith("admission_blocked") or code in {"source_not_admitted", "authentication_missing", "source_cooldown_active", "source_collection_in_progress"} else failed
                    destination.append({"source_id": row["source_id"], "filters": row["filters"], "reason": code})
                except HTTPException as exc:
                    code = "collection_capacity_exceeded" if exc.status_code == 429 else "snapshot_store_unavailable"
                    (held if exc.status_code == 429 else failed).append({"source_id": row["source_id"], "filters": row["filters"], "reason": code})
            output = {"updated": updated, "held": held, "failed": failed, "execution_enabled": False,
                      "refresh_mode": "explicit_manual_read", "partial_refresh": bool(held or failed),
                      "refresh_event_id": secrets.token_hex(16), "attempted_at": attempted_at,
                      "completed_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")}
            receipt = await run_in_threadpool(save, "market_refresh", {"requests": requests}, output) if admission is None else await run_in_threadpool(admission.run, save, "market_refresh", {"requests": requests}, output)
            return {**output, "snapshot_id": receipt["snapshot_id"], "created_at": receipt["created_at"]}
        finally:
            if admission is not None:
                admission.close()

    @app.post("/v1/sources/{source_id}/collect", dependencies=[Depends(authenticated)])
    async def collect(source_id: str, request: Request) -> dict[str, Any]:
        payload = await _json_body(request, optional=True)
        if set(payload) - {"filters"} or not isinstance(payload.get("filters", {}), dict):
            raise HTTPException(422, detail="invalid_collection_input")
        if source_id not in policies:
            raise HTTPException(409, detail="source_not_admitted")
        admission = None if refresh_config.enabled else _CollectionAdmission(collection_slots)
        try:
            return await coordinator.collect(source_id, payload.get("filters", {})) if refresh_config.enabled else await run_in_threadpool(admission.run, collect_and_save, source_id, payload.get("filters", {}))
        except ConnectorError as exc:
            code = _connector_code(exc)
            status = 429 if code in {"source_collection_in_progress", "source_cooldown_active"} else 409 if code.startswith("admission_blocked") or code in {"authentication_missing", "unknown_or_unadmitted_source", "source_transport_not_implemented"} else 502
            # Codes are generated by the connector and contain no input values.
            raise HTTPException(status, detail=code) from None
        finally:
            if admission is not None:
                admission.close()

    @app.post("/v1/pricing/evaluate", dependencies=[Depends(authenticated)])
    async def pricing(request: Request) -> dict[str, Any]:
        payload = await _json_body(request)
        try:
            output = await run_in_threadpool(bound_pricing, payload)
        except (SnapshotStoreError, PolicyStoreError, sqlite3.Error):
            raise HTTPException(503, detail="pricing_evidence_store_unavailable") from None
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise HTTPException(422, detail="invalid_pricing_input") from None
        return await run_in_threadpool(save, "pricing", payload, output)

    def bound_pricing(payload):
        output = _evaluate_pricing(payload)
        boundary = PricingProvenance(store, policies, app.state.policy_repository)
        return boundary.apply(payload, output)

    def bound_scenarios(payload):
        output = _evaluate_scenarios(payload)
        boundary = PricingProvenance(store, policies, app.state.policy_repository)
        if isinstance(output.get("baseline"), dict) and isinstance(output.get("scenarios"), list):
            output["baseline"] = boundary.apply(payload["baseline"], output["baseline"])
            for request_row, result_row in zip(payload["scenarios"], output["scenarios"], strict=True):
                result_row["result"] = boundary.apply(request_row["request"], result_row["result"])
            output["status"] = "held" if any(item["status"] == "held" for item in [output["baseline"], *[row["result"] for row in output["scenarios"]]]) else "indicative"
            return output
        return boundary.apply(payload, output)

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
        except (SnapshotStoreError, PolicyStoreError, sqlite3.Error):
            raise HTTPException(503, detail="evaluation_evidence_store_unavailable") from None
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise HTTPException(422, detail="invalid_" + kind + "_input") from None
        return await run_in_threadpool(save, kind, payload, output)

    @app.post("/v1/cash/calendar", dependencies=[Depends(authenticated)])
    async def cash_calendar(request: Request) -> dict[str, Any]:
        from .treasury_contract import evaluate_calendar
        return await pure_evaluation(request, evaluate_calendar, "cash_calendar")

    @app.post("/v1/power/evaluate", dependencies=[Depends(authenticated)])
    async def power_evaluation(request: Request):
        from compute_pricing.control.power import evaluate_power_payload
        return await pure_evaluation(request, evaluate_power_payload, "power")

    @app.post("/v1/power/from-reference", dependencies=[Depends(authenticated)])
    async def reference_power_evaluation(request: Request):
        from .market import market_index
        from .power_reference import evaluate_reference_power
        def bound_power(payload):
            packet = market_index(store, policies, plan, row_limit=10000)
            return evaluate_reference_power(payload, packet)
        return await pure_evaluation(request, bound_power, "power")

    @app.get("/v1/hedges/contract", dependencies=[Depends(authenticated)])
    async def hedge_input_contract():
        from compute_pricing.control.hedging import hedge_contract
        return {"contract_version": "hedge-input/1.0.0", "template": hedge_contract(),
                "paper_only": True, "missing_is_zero": False, "execution_enabled": False}

    @app.post("/v1/curves/evaluate", dependencies=[Depends(authenticated)])
    async def curve_evaluation(request: Request):
        from compute_pricing.control.curves import evaluate_term_curve_payload
        return await pure_evaluation(request, evaluate_term_curve_payload, "term_curve")

    @app.post("/v1/hedges/evaluate", dependencies=[Depends(authenticated)])
    async def hedge_evaluation(request: Request):
        from compute_pricing.control.hedging import evaluate_hedge_payload
        return await pure_evaluation(request, evaluate_hedge_payload, "hedge_study")

    @app.post("/v1/pricing/scenarios", dependencies=[Depends(authenticated)])
    async def scenarios(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, bound_scenarios, "pricing_scenarios")

    @app.post("/v1/inference/evaluate", dependencies=[Depends(authenticated)])
    async def inference(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, _evaluate_inference, "inference")

    @app.post("/v1/calibration/evaluate", dependencies=[Depends(authenticated)])
    async def calibration(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, _evaluate_calibration, "calibration")

    @app.post("/v1/financing/evaluate", dependencies=[Depends(authenticated)])
    async def financing(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, _evaluate_financing, "financing")

    @app.post("/v1/portfolio/evaluate", dependencies=[Depends(authenticated)])
    async def portfolio(request: Request) -> dict[str, Any]:
        return await pure_evaluation(request, _evaluate_portfolio, "portfolio")

    @app.get("/v1/portfolio/template", dependencies=[Depends(authenticated)])
    async def portfolio_draft():
        from compute_pricing.control.portfolio import portfolio_template
        return portfolio_template()

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
    from compute_pricing.control.policies.routes import attach_policies
    from compute_pricing.control.inventory import attach_inventory
    from compute_pricing.control.underwriting.routes import attach_underwriting
    attach_policies(app, authenticated=authenticated, json_body=_json_body,
                    store_path=store.path, source_policies=policies)
    attach_inventory(app, authenticated=authenticated, json_body=_json_body, store_path=store.path)
    attach_underwriting(app, authenticated=authenticated, json_body=_json_body)
    add_workbench(app)
    return app
