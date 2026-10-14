"""Authenticated policy configuration for local indicative calculations."""
import sqlite3
from starlette.concurrency import run_in_threadpool
from fastapi import Depends, HTTPException, Request

from compute_pricing.control.connectors import source_status
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.domain.spec import OWNING_PATHS
from .repository import PolicyConflict, PolicyRepository, PolicyStoreError, validate_document


def attach_policies(app, *, authenticated, json_body, store_path, source_policies):
    repository = PolicyRepository(store_path)
    app.state.policy_repository = repository

    async def call(function, *args, **kwargs):
        try:
            return await run_in_threadpool(function, *args, **kwargs)
        except PolicyConflict as exc:
            raise HTTPException(409, detail=str(exc)) from None
        except (ValidationError, ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
            raise HTTPException(422, detail="invalid_policy_input") from None
        except (sqlite3.Error, PolicyStoreError):
            raise HTTPException(503, detail="policy_store_unavailable") from None

    @app.get("/v1/policies", dependencies=[Depends(authenticated)])
    async def policies():
        result = await call(repository.list)
        return {**result, "source_catalog": source_status(source_policies),
                "feature_schema": {"value_types": ["decimal", "integer", "string", "boolean"], "owning_paths": list(OWNING_PATHS)},
                "calibration_state": "unvalidated"}

    @app.post("/v1/policies/validate", dependencies=[Depends(authenticated)])
    async def validate(request: Request):
        payload = await json_body(request)
        if set(payload) != {"document"}:
            raise HTTPException(422, detail="invalid_policy_input")
        return await call(validate_document, payload["document"])

    @app.get("/v1/policies/{revision}", dependencies=[Depends(authenticated)])
    async def replay(revision: str):
        result = await call(repository.get, revision)
        if result is None:
            raise HTTPException(404, detail="policy_not_found")
        return result

    @app.post("/v1/policies", dependencies=[Depends(authenticated)])
    async def save(request: Request):
        payload = await json_body(request)
        if set(payload) != {"expected_revision", "document"}:
            raise HTTPException(422, detail="invalid_policy_input")
        return await call(repository.save, payload["document"], expected_revision=payload["expected_revision"])
