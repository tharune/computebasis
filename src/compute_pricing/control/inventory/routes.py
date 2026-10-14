"""Bearer-protected local paper records and a separate pure draft evaluator."""
from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .model import InventoryError, evaluate_inventory
from .store import InventoryStore


def _failure(error: InventoryError):
    status = 409 if error.code == "inventory_revision_conflict" else 404 if error.code == "inventory_revision_not_found" else 503 if error.code in ("inventory_store_unavailable", "inventory_integrity_failed") else 422
    detail = {"code": error.code, "current_revision": error.current_revision} if status == 409 else error.code
    raise HTTPException(status, detail=detail) from None


def _query(request: Request):
    if set(request.query_params) - {"as_of"} or len(request.query_params.getlist("as_of")) > 1:
        raise HTTPException(422, detail="invalid_inventory_query")
    return request.query_params.get("as_of")


def attach_inventory(app, *, authenticated, json_body, store_path):
    store = InventoryStore(store_path)
    app.state.inventory_store = store

    @app.get("/v1/inventory", dependencies=[Depends(authenticated)])
    async def get_inventory(request: Request):
        as_of = _query(request)
        try:
            return await run_in_threadpool(store.get, as_of=as_of)
        except InventoryError as error:
            _failure(error)

    @app.get("/v1/inventory/revisions/{revision}", dependencies=[Depends(authenticated)])
    async def get_revision(revision: str, request: Request):
        as_of = _query(request)
        if not revision.isascii() or not revision.isdecimal() or len(revision) > 10:
            raise HTTPException(422, detail="invalid_inventory_revision")
        try:
            return await run_in_threadpool(store.get, as_of=as_of, revision=int(revision))
        except InventoryError as error:
            _failure(error)

    @app.put("/v1/inventory", dependencies=[Depends(authenticated)])
    async def put_inventory(request: Request):
        payload = await json_body(request)
        if set(payload) != {"expected_revision", "state"} or request.query_params:
            raise HTTPException(422, detail="invalid_inventory_write")
        try:
            return await run_in_threadpool(store.put, expected_revision=payload["expected_revision"], state=payload["state"])
        except InventoryError as error:
            _failure(error)

    @app.post("/v1/inventory/evaluate", dependencies=[Depends(authenticated)])
    async def preview_inventory(request: Request):
        payload = await json_body(request)
        if set(payload) != {"state", "as_of"} or not isinstance(payload["as_of"], str) or request.query_params:
            raise HTTPException(422, detail="invalid_inventory_preview")
        try:
            report = await run_in_threadpool(evaluate_inventory, payload["state"], as_of=payload["as_of"])
        except InventoryError as error:
            _failure(error)
        return {**report, "revision": None, "latest_revision": None, "persisted": False,
            "audit": {"recent": [], "truncated": False}, "idempotent_replay": False}

    return store
