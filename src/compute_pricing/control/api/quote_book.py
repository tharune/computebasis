"""Routes for the simulated quote book: a local, seeded market of providers and quotes.

``GET /v1/book`` returns the current book as one snapshot with a weak ETag, and answers 304 when
the caller already holds the current tag. ``POST /v1/book/control`` pauses, resumes or resets the
simulated clock, or applies a named scenario. The book lives in process memory only: nothing is
read from or written to the evidence store, every response says ``simulated: true`` and
execution stays disabled. Both routes use the app's shared authentication; browser sessions need
the dedicated ``book`` scope for control (see ``sessions.request_scope``) and a CSRF token.
"""
from __future__ import annotations

import re
import threading
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from compute_pricing.control.quote_book import QuoteBook


def etag_matches(header: str | None, etag: str) -> bool:
    """RFC 9110 weak comparison of an If-None-Match field against one entity tag."""
    if header is None:
        return False
    if header.strip() == "*":
        return True
    wanted = etag.removeprefix("W/")
    return any(candidate.strip().removeprefix("W/") == wanted for candidate in re.findall(r'(?:W/)?"[^"]*"', header))


def attach_quote_book(app: FastAPI, *, authenticated: Callable[..., Awaitable[None]],
                      json_body: Callable[..., Awaitable[dict[str, Any]]]) -> None:
    """Register the two routes directly on the app, like ``attach_sessions``, so ``app.routes`` stays flat."""
    lock = threading.Lock()

    def book(request: Request) -> QuoteBook:
        # Built on first use: the simulation is process memory only and most callers never open it.
        with lock:
            state = request.app.state
            if getattr(state, "quote_book", None) is None:
                state.quote_book = QuoteBook()
            return state.quote_book

    @app.get("/v1/book", dependencies=[Depends(authenticated)],
                responses={200: {"description": "Simulated quote book", "content": {"application/json": {"schema": {"type": "object"}}}},
                           304: {"description": "The book has not moved since the tag the client holds"}})
    async def snapshot(request: Request) -> Response:
        etag, body = await run_in_threadpool(lambda: book(request).encoded())
        headers = {"ETag": etag, "Cache-Control": "no-store"}
        if etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return Response(body, media_type="application/json", headers=headers)

    @app.post("/v1/book/control", dependencies=[Depends(authenticated)])
    async def control(request: Request) -> dict[str, Any]:
        payload = await json_body(request)
        action, scenario = payload.get("action"), payload.get("scenario")
        if set(payload) - {"action", "scenario"} or not isinstance(action, str) or not (scenario is None or isinstance(scenario, str)):
            raise HTTPException(422, detail="invalid_book_control")
        try:
            state = await run_in_threadpool(book(request).control, action, scenario)
        except ValueError:
            raise HTTPException(422, detail="invalid_book_control") from None
        return {"simulated": True, **state, "execution_enabled": False}
