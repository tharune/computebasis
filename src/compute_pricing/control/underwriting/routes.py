"""Authenticated pure underwriting diagnostics, with no document persistence."""
from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from compute_pricing.control.domain import ValidationError
from .catalog import underwriting_template
from .engine import assess_underwriting


def attach_underwriting(app, *, authenticated, json_body):
    @app.get("/v1/underwriting/template", dependencies=[Depends(authenticated)])
    async def template():
        return underwriting_template()

    @app.post("/v1/underwriting/assess", dependencies=[Depends(authenticated)])
    async def assess(request: Request):
        payload = await json_body(request)
        try:
            return await run_in_threadpool(assess_underwriting, payload)
        except (ValidationError, ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
            raise HTTPException(422, detail="invalid_underwriting_input") from None
