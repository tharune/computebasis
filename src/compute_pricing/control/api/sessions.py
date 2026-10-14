"""Short-lived, origin-bound loopback workbench sessions.

This is local browser convenience, not an enterprise identity system. Session
cookies and CSRF tokens never enter HTML, URLs, logs or persistent storage.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

COOKIE_NAME = "compute_workbench_session"
CSRF_HEADER = "x-compute-csrf"
SESSION_SCOPES = frozenset({"read", "evaluate", "inventory", "collection", "session", "book"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}")
MAX_CSRF_TOKENS = 16


def loopback_origin(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("explicit loopback origin required")
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        raise ValueError("invalid loopback origin") from None
    if (parts.scheme not in {"http", "https"} or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or port is None or not 1024 <= port <= 65535 or parts.username is not None or parts.password is not None
            or parts.path or parts.query or parts.fragment or value != parts.scheme + "://" + parts.netloc):
        raise ValueError("invalid loopback origin")
    return value


@dataclass(frozen=True)
class _Session:
    csrf_hashes: tuple[bytes, ...]
    expires: float
    scopes: frozenset[str] = SESSION_SCOPES


class BrowserSessions:
    def __init__(self, origin: str, *, ttl_s: int = 900, maximum: int = 128,
                 clock: Callable[[], float] = time.time):
        self.origin = loopback_origin(origin)
        self.host = urllib.parse.urlsplit(self.origin).netloc
        self.secure = self.origin.startswith("https://")
        if type(ttl_s) is not int or not 60 <= ttl_s <= 3600 or type(maximum) is not int or not 1 <= maximum <= 1024:
            raise ValueError("invalid browser session limits")
        self.ttl_s, self.maximum, self.clock = ttl_s, maximum, clock
        self._sessions: dict[bytes, _Session] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _hash(token: str) -> bytes:
        return hashlib.sha256(token.encode("ascii")).digest()

    def boundary(self, request: Request, *, require_origin: bool = False) -> None:
        hosts, origins = request.headers.getlist("host"), request.headers.getlist("origin")
        if len(hosts) != 1 or hosts[0] != self.host:
            raise HTTPException(403, detail="browser_host_not_allowed")
        if len(origins) > 1 or origins and origins[0] != self.origin or require_origin and not origins:
            raise HTTPException(403, detail="browser_origin_not_allowed")
        metadata = {name: request.headers.getlist(name) for name in ("sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest")}
        if (metadata["sec-fetch-site"] != ["same-origin"] or metadata["sec-fetch-dest"] != ["empty"]
                or metadata["sec-fetch-mode"] not in (["cors"], ["same-origin"])):
            raise HTTPException(403, detail="browser_fetch_metadata_not_allowed")

    def _cookie(self, request: Request) -> str | None:
        # Ambiguous duplicate cookies must not silently select a session.
        cookies = request.headers.getlist("cookie")
        values = []
        for header in cookies:
            for part in header.split(";"):
                name, separator, value = part.strip().partition("=")
                if name == COOKIE_NAME and separator:
                    values.append(value)
        return values[0] if len(values) == 1 and TOKEN_PATTERN.fullmatch(values[0]) else None

    def issue(self, request: Request) -> tuple[str, str, float]:
        self.boundary(request, require_origin=True)
        now = self.clock()
        identifier, csrf = secrets.token_hex(32), secrets.token_hex(32)
        previous = self._cookie(request)
        with self._lock:
            self._sessions = {key: value for key, value in self._sessions.items() if value.expires > now}
            if previous is not None:
                previous_session = self._sessions.get(self._hash(previous))
                if previous_session is not None:
                    # Browser tabs share cookies but keep separate CSRF tokens.
                    # Reuse the same lifetime and retain only a bounded hash ring.
                    hashes = (*previous_session.csrf_hashes, self._hash(csrf))[-MAX_CSRF_TOKENS:]
                    self._sessions[self._hash(previous)] = _Session(hashes, previous_session.expires)
                    return previous, csrf, previous_session.expires
            if len(self._sessions) >= self.maximum:
                raise HTTPException(503, detail="browser_session_capacity_reached")
            self._sessions[self._hash(identifier)] = _Session((self._hash(csrf),), now + self.ttl_s)
        return identifier, csrf, now + self.ttl_s

    def authorize(self, request: Request, *, scope: str) -> None:
        self.boundary(request, require_origin=request.method not in SAFE_METHODS)
        identifier = self._cookie(request)
        if identifier is None:
            raise HTTPException(401, detail="browser_session_required")
        now = self.clock()
        with self._lock:
            session = self._sessions.get(self._hash(identifier))
            if session is None or session.expires <= now:
                if session is not None:
                    self._sessions.pop(self._hash(identifier), None)
                raise HTTPException(401, detail="browser_session_expired")
            if scope not in session.scopes:
                raise HTTPException(403, detail="browser_session_scope_not_allowed")
            if request.method not in SAFE_METHODS:
                csrf = request.headers.getlist(CSRF_HEADER)
                valid = len(csrf) == 1 and bool(TOKEN_PATTERN.fullmatch(csrf[0]))
                candidate = self._hash(csrf[0]) if valid else bytes(32)
                matches = sum(hmac.compare_digest(candidate, stored) for stored in session.csrf_hashes)
                if not valid or not matches:
                    raise HTTPException(403, detail="browser_csrf_required")

    def revoke(self, request: Request) -> None:
        self.authorize(request, scope="session")
        identifier = self._cookie(request)
        with self._lock:
            self._sessions.pop(self._hash(identifier), None)


def request_scope(request: Request) -> str:
    path = request.url.path
    if path.startswith("/v1/session/"):
        return "session"
    if request.method in SAFE_METHODS:
        return "read"
    if request.method == "PUT" and path == "/v1/inventory":
        return "inventory"
    if request.method == "POST" and path == "/v1/book/control":
        return "book"
    if request.method == "POST" and (path == "/v1/market/refresh" or path.startswith("/v1/sources/") and path.endswith("/collect")):
        return "collection"
    if request.method == "POST" and path in {
        "/v1/requests/parse", "/v1/pricing/evaluate", "/v1/pricing/scenarios",
        "/v1/cash/evaluate", "/v1/cash/calendar", "/v1/inference/evaluate", "/v1/calibration/evaluate",
        "/v1/financing/evaluate", "/v1/underwriting/assess", "/v1/portfolio/evaluate",
        "/v1/inventory/evaluate", "/v1/policies", "/v1/policies/validate",
        "/v1/power/evaluate", "/v1/power/from-reference", "/v1/curves/evaluate", "/v1/hedges/evaluate",
        "/v1/demo/scenario",
        "/v1/quotes/evaluate",
    }:
        return "evaluate"
    # Future write routes require an explicit browser-session scope decision.
    return "unsupported"


def attach_sessions(app, sessions: BrowserSessions | None, *, json_body) -> None:
    @app.post("/v1/session/bootstrap")
    async def bootstrap(request: Request):
        if sessions is None:
            raise HTTPException(404, detail="browser_sessions_not_configured")
        sessions.boundary(request, require_origin=True)
        payload = await json_body(request)
        if payload:
            raise HTTPException(422, detail="invalid_browser_bootstrap_input")
        identifier, csrf, expiry = sessions.issue(request)
        import datetime as dt
        response = JSONResponse({"auth_mode": "local_session", "csrf_token": csrf,
            "expires_at": dt.datetime.fromtimestamp(expiry, dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "scopes": sorted(SESSION_SCOPES), "execution_enabled": False},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        remaining = max(1, math.ceil(expiry - sessions.clock()))
        response.set_cookie(COOKIE_NAME, identifier, max_age=remaining, httponly=True,
            secure=sessions.secure, samesite="strict", path="/v1")
        return response

    @app.post("/v1/session/logout")
    async def logout(request: Request):
        if sessions is None:
            raise HTTPException(404, detail="browser_sessions_not_configured")
        sessions.authorize(request, scope="session")
        payload = await json_body(request)
        if payload:
            raise HTTPException(422, detail="invalid_browser_logout_input")
        sessions.revoke(request)
        response = JSONResponse({"auth_mode": "disconnected", "execution_enabled": False},
                                headers={"Cache-Control": "no-store"})
        response.delete_cookie(COOKIE_NAME, path="/v1", secure=sessions.secure, httponly=True, samesite="strict")
        return response
