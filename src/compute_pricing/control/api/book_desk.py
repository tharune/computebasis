"""Authenticated, read-only desk ledger over the simulated quote book (docs/desk-ledger-contract.md)."""
from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from .quote_book import etag_matches


def attach_book_desk(app, *, get_book, authenticated):
    from compute_pricing.control.quote_book.desk import DeskLedgerError, encode_desk_ledger

    @app.get("/v1/book/desk", dependencies=[Depends(authenticated)])
    async def read_book_desk(request: Request):
        try:
            etag, encoded = await run_in_threadpool(lambda: encode_desk_ledger(get_book().snapshot()))
        except DeskLedgerError:
            raise HTTPException(500, detail="desk_ledger_unavailable") from None
        headers = {"ETag": etag, "Cache-Control": "no-store", "Vary": "Cookie, Authorization"}
        if etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return Response(encoded, media_type="application/json", headers=headers)
