"""Serve static local UI without embedding secrets or fetching market data."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ASSETS = Path(__file__).resolve().parent / "assets"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def add_workbench(app: FastAPI) -> None:
    """Mount a public shell; existing authenticated APIs supply every live row."""
    app.mount("/workbench/assets", StaticFiles(directory=ASSETS), name="workbench-assets")

    @app.middleware("http")
    async def workbench_headers(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/workbench/assets/"):
            for name, value in SECURITY_HEADERS.items():
                response.headers[name] = value
        return response

    @app.get("/", include_in_schema=False)
    async def workbench() -> FileResponse:
        return FileResponse(ASSETS / "index.html", media_type="text/html", headers=SECURITY_HEADERS)
