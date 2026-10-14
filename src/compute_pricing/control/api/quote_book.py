"""Authenticated, process-local controls for an independently generated simulation."""
import re
import threading

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response


def etag_matches(header, etag):
    if not isinstance(header, str):
        return False
    if header.strip() == "*":
        return True
    target = etag.removeprefix("W/")
    return any(tag.removeprefix("W/") == target
               for tag in re.findall(r'(?:W/)?"[^"\r\n]*"', header))


def attach_quote_book(app, *, authenticated, json_body):
    from compute_pricing.control.quote_book import QuoteBook
    creation = threading.Lock()

    def get_book():
        with creation:
            if getattr(app.state, "quote_book", None) is None:
                app.state.quote_book = QuoteBook()
            return app.state.quote_book

    @app.get("/v1/book", dependencies=[Depends(authenticated)])
    async def read_book(request: Request):
        etag, encoded = await run_in_threadpool(lambda: get_book().encoded())
        headers = {"ETag": etag, "Cache-Control": "no-store", "Vary": "Cookie, Authorization"}
        if etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return Response(encoded, media_type="application/json", headers=headers)

    @app.post("/v1/book/control", dependencies=[Depends(authenticated)])
    async def control_book(request: Request):
        payload = await json_body(request)
        if (set(payload) not in ({"action"}, {"action", "scenario"})
                or type(payload.get("action")) is not str
                or "scenario" in payload and type(payload["scenario"]) is not str):
            raise HTTPException(422, detail="invalid_book_control")
        try:
            result = await run_in_threadpool(get_book().control, payload["action"], payload.get("scenario"))
        except ValueError:
            raise HTTPException(422, detail="invalid_book_control") from None
        return {**result, "simulated": True, "execution_enabled": False}
