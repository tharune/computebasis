"""HTTPS reads with pinned public DNS, TLS verification and bounded resource use.

No proxy environment, cookie jar, URL credentials, arbitrary endpoints or write API
exist here. Search POSTs are restricted to a documented query-only contract.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import email.utils
import hashlib
import http.client
import ipaddress
import json
import math
import os
import queue
import re
import socket
import ssl
import threading
import time
import urllib.parse
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

UTC = dt.timezone.utc
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
SAFE_RESPONSE_HEADERS = frozenset({"content-type", "date", "etag", "last-modified",
                                   "retry-after", "content-length", "cache-control"})


class ConnectorError(ValueError):
    """Safe diagnostics contain a code, never response bodies or credential values."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def utc_string(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise ConnectorError("timezone_required")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> dt.datetime:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", value):
        raise ConnectorError("utc_timestamp_required")
    try:
        return dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ConnectorError("invalid_timestamp") from None


@dataclasses.dataclass(frozen=True)
class SourcePolicy:
    source_id: str
    enabled: bool = False
    rights_status: str = "pending"
    rights_evidence: str = ""
    permissions: Mapping[str, str] = dataclasses.field(default_factory=dict)
    expires_at: str | None = None
    max_age_s: int = 0
    liveness: str = "not_verified"
    attribution: str = ""
    verified_by: str | None = None
    min_interval_s: float = 1.0

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.source_id):
            raise ConnectorError("invalid_source_id")
        if type(self.enabled) is not bool or self.rights_status not in {"allowed", "pending", "denied"}:
            raise ConnectorError("invalid_source_policy")
        if type(self.max_age_s) is not int or self.max_age_s <= 0:
            raise ConnectorError("positive_freshness_required")
        if isinstance(self.min_interval_s, bool) or not isinstance(self.min_interval_s, (int, float)) or not math.isfinite(self.min_interval_s) or not 0 <= self.min_interval_s <= 86400:
            raise ConnectorError("invalid_source_interval")
        if not isinstance(self.rights_evidence, str) or not isinstance(self.attribution, str):
            raise ConnectorError("invalid_policy_evidence")
        if self.verified_by is not None and (not isinstance(self.verified_by, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*", self.verified_by)):
            raise ConnectorError("invalid_policy_reviewer")
        if not isinstance(self.permissions, Mapping) or set(self.permissions) - {"observe", "retain", "benchmark", "execution"}:
            raise ConnectorError("invalid_permission_scope")
        if any(v not in {"PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"} for v in self.permissions.values()):
            raise ConnectorError("invalid_permission_result")
        object.__setattr__(self, "permissions", MappingProxyType(dict(self.permissions)))
        if self.liveness not in {"not_verified", "probe_verified", "unavailable"}:
            raise ConnectorError("invalid_liveness")
        if self.expires_at is not None:
            parse_utc(self.expires_at)

    def blockers(self, purpose: str, now: dt.datetime | None = None) -> list[str]:
        if purpose not in {"observe", "retain", "benchmark", "execution"}:
            raise ConnectorError("unknown_permission_purpose")
        now = now or dt.datetime.now(UTC)
        result: list[str] = []
        if not self.enabled:
            result.append("source_disabled")
        if self.rights_status != "allowed" or not self.rights_evidence or not self.verified_by:
            result.append("rights_not_admitted")
        if self.permissions.get(purpose) != "PASS":
            result.append(f"{purpose}_permission_missing")
        if self.expires_at is not None and parse_utc(self.expires_at) <= now:
            result.append("rights_expired")
        return result

    def require(self, purpose: str, now: dt.datetime | None = None) -> None:
        blockers = self.blockers(purpose, now)
        if blockers:
            raise ConnectorError("admission_blocked:" + ",".join(blockers))


def load_policies(path: str | Path) -> dict[str, SourcePolicy]:
    def unique_keys(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ConnectorError("duplicate_source_config_key")
            result[key] = value
        return result
    try:
        with Path(path).open("rb") as handle:
            encoded = handle.read(256 * 1024 + 1)
        if len(encoded) > 256 * 1024:
            raise ConnectorError("source_config_size_limit")
        content = json.loads(encoded.decode("utf-8"), object_pairs_hook=unique_keys,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(content, dict) or content.get("schema") != "computebasis-source-admission/1.0" or not isinstance(content.get("sources"), dict):
            raise ConnectorError("unsupported_source_config")
        return {name: SourcePolicy(source_id=name, **values) for name, values in content["sources"].items()}
    except (TypeError, json.JSONDecodeError, OSError, ValueError, RecursionError) as exc:
        if isinstance(exc, ConnectorError):
            raise
        raise ConnectorError("invalid_source_config") from None


@dataclasses.dataclass(frozen=True)
class SourceSpec:
    source_id: str
    host: str
    path_pattern: str
    query_keys: frozenset[str] = frozenset()
    method: str = "GET"
    secret_env: str | None = None
    content_types: frozenset[str] = frozenset({"application/json"})
    post_contract: str | None = None


SOURCE_SPECS = {
    "energinet_day_ahead": SourceSpec("energinet_day_ahead", "api.energidataservice.dk", r"/dataset/DayAheadPrices",
        query_keys=frozenset({"start", "end", "limit", "filter", "columns", "sort"})),
    "huggingface_catalog": SourceSpec("huggingface_catalog", "endpoints.huggingface.co", r"/api/v1/catalog/list",
        query_keys=frozenset({"task", "accelerator", "engine", "license", "search", "limit"})),
    "aws_public_pricing": SourceSpec("aws_public_pricing", "pricing.us-east-1.amazonaws.com",
        r"/offers/v1\.0/aws/(?:AmazonLightsail|AmazonECS|AmazonBedrock|AWSLambda|AmazonS3|AmazonSageMaker)/(?:current|[0-9]{14})/(?:region_index\.json|[a-z0-9-]+/index\.json)",
        content_types=frozenset({"application/json", "application/octet-stream", "binary/octet-stream"})),
    "oracle": SourceSpec("oracle", "apexapps.oracle.com", r"/pls/apex/cetools/api/v1/products/",
        query_keys=frozenset({"partNumber", "currencyCode"})),
    "azure": SourceSpec("azure", "prices.azure.com", r"/api/retail/prices",
                        query_keys=frozenset({"api-version", "currencyCode", "$filter", "$skip", "meterRegion"})),
    "ecb": SourceSpec("ecb", "www.ecb.europa.eu", r"/stats/eurofxref/eurofxref-daily\.xml",
                      content_types=frozenset({"application/xml", "text/xml"})),
    "scaleway": SourceSpec("scaleway", "api.scaleway.com", r"/product-catalog/v2alpha1/public-catalog/products",
                           query_keys=frozenset({"page", "page_size", "product_types", "service_category"})),
    "huggingface": SourceSpec("huggingface", "huggingface.co", r"/api/models",
                              query_keys=frozenset({"author", "pipeline_tag", "limit", "full"})),
    "getdeploying": SourceSpec("getdeploying", "getdeploying.com", r"/dataset/gpu-prices/weekly\.csv",
                               content_types=frozenset({"text/csv", "application/csv"})),
    "vast": SourceSpec("vast", "console.vast.ai", r"/api/v0/bundles", method="POST",
                       secret_env="COMPUTEBASIS_VAST_READ_API_KEY", post_contract="vast_offer_search_v1"),
    "openrouter": SourceSpec("openrouter", "openrouter.ai", r"/api/v1/models",
        query_keys=frozenset({"offset", "limit", "q", "input_modalities", "output_modalities"})),
    "runpod": SourceSpec("runpod", "api.runpod.io", r"/v2/catalog/gpus",
                         query_keys=frozenset({"include", "product", "count", "cloud", "countryCodes", "cudaVersions"}),
                         secret_env="COMPUTEBASIS_RUNPOD_READ_API_KEY"),
    "kalshi": SourceSpec("kalshi", "external-api.kalshi.com", r"/trade-api/v2/markets",
                         query_keys=frozenset({"limit", "cursor", "status", "series_ticker"})),
}


@dataclasses.dataclass(frozen=True)
class ReadRequest:
    spec: SourceSpec
    url: str
    payload: Mapping[str, Any] | None = None

    def validate(self) -> urllib.parse.SplitResult:
        if SOURCE_SPECS.get(self.spec.source_id) != self.spec:
            raise ConnectorError("unregistered_request_contract")
        try:
            parts = urllib.parse.urlsplit(self.url)
            port = parts.port
        except ValueError:
            raise ConnectorError("invalid_endpoint") from None
        if parts.scheme != "https" or parts.hostname != self.spec.host or port not in (None, 443):
            raise ConnectorError("endpoint_not_allowed")
        if parts.username is not None or parts.password is not None or parts.fragment:
            raise ConnectorError("url_credentials_or_fragment_forbidden")
        if not re.fullmatch(self.spec.path_pattern, parts.path) or "%" in parts.path:
            raise ConnectorError("endpoint_path_not_allowed")
        try:
            query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            raise ConnectorError("invalid_endpoint_query") from None
        if any(key not in self.spec.query_keys for key, _ in query) or len({k for k, _ in query}) != len(query):
            raise ConnectorError("query_key_not_allowed")
        if self.spec.method == "GET":
            if self.payload is not None:
                raise ConnectorError("get_payload_forbidden")
        elif self.spec.method == "POST" and self.spec.post_contract == "vast_offer_search_v1":
            validate_vast_search(self.payload)
        else:
            raise ConnectorError("write_method_forbidden")
        return parts


def validate_vast_search(payload: Mapping[str, Any] | None) -> None:
    if not isinstance(payload, Mapping) or type(payload.get("limit")) is not int or not 1 <= payload["limit"] <= 1000:
        raise ConnectorError("invalid_search_limit")
    if payload.get("type") not in {"on-demand", "bid", "reserved"}:
        raise ConnectorError("invalid_search_billing_type")
    for field, predicate in payload.items():
        if field in {"limit", "type"}:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field) or not isinstance(predicate, Mapping) or not predicate:
            raise ConnectorError("invalid_search_filter")
        if set(predicate) - {"eq", "neq", "gt", "lt", "gte", "lte", "in", "notin"}:
            raise ConnectorError("invalid_search_operator")
    try:
        encoded = json.dumps(payload, allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ConnectorError("invalid_search_payload") from None
    if len(encoded) > 64 * 1024:
        raise ConnectorError("search_payload_too_large")


def resolve_public(host: str, resolver: Callable[..., Any] = socket.getaddrinfo, *, timeout_s: float = 15) -> list[str]:
    resolved: queue.Queue[Any] = queue.Queue(maxsize=1)
    def lookup() -> None:
        try:
            resolved.put((True, resolver(host, 443, type=socket.SOCK_STREAM)))
        except (OSError, ValueError):
            resolved.put((False, None))
    # A hung system resolver must not hold the collection request indefinitely.
    # The daemon cannot send an HTTP request and only performs this DNS lookup.
    threading.Thread(target=lookup, daemon=True).start()
    try:
        ok, records = resolved.get(timeout=timeout_s)
        if not ok:
            raise ConnectorError("dns_resolution_failed")
        addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ConnectorError("nonpublic_dns_address")
        return addresses
    except ConnectorError:
        raise
    except queue.Empty:
        raise ConnectorError("dns_resolution_timeout") from None
    except (OSError, ValueError):
        raise ConnectorError("dns_resolution_failed") from None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float):
        context = ssl.create_default_context()
        try:
            import certifi
        except ImportError:
            pass
        else:
            # Add the pinned Mozilla CA bundle when installed. Verification and
            # hostname checks stay enabled; failure never falls back to insecure TLS.
            context.load_verify_locations(cafile=certifi.where())
        super().__init__(host, port=443, timeout=timeout, context=context)
        self._address = address

    def connect(self) -> None:
        # Connect to the validated numeric IP rather than resolving the host again.
        sock = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


@dataclasses.dataclass(frozen=True)
class RawResponse:
    source_id: str
    captured_at: str
    endpoint_path: str
    status: int
    headers: Mapping[str, str]
    body: bytes = dataclasses.field(repr=False)
    attempts: int = 1

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def metadata(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "captured_at": self.captured_at,
                "endpoint_path": self.endpoint_path, "status": self.status,
                "headers": dict(self.headers), "bytes": len(self.body),
                "sha256": self.sha256, "attempts": self.attempts}


class ReadOnlyTransport:
    def __init__(self, *, timeout_s: float = 15, max_bytes: int = 4 * 1024 * 1024,
                 max_attempts: int = 2, max_wait_s: float = 5,
                 clock: Callable[[], dt.datetime] | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 resolver: Callable[..., Any] = socket.getaddrinfo,
                 exchange: Callable[..., Any] | None = None):
        if not math.isfinite(timeout_s) or not 0 < timeout_s <= 60 or type(max_bytes) is not int or not 1 <= max_bytes <= 16 * 1024 * 1024:
            raise ConnectorError("invalid_transport_limits")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 4 or not math.isfinite(max_wait_s) or not 0 <= max_wait_s <= 60:
            raise ConnectorError("invalid_retry_limits")
        self.timeout_s, self.max_bytes = timeout_s, max_bytes
        self.max_attempts, self.max_wait_s = max_attempts, max_wait_s
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.monotonic, self.sleep, self.resolver = monotonic, sleep, resolver
        self.exchange = exchange or self._exchange
        self._cooldown: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._lock_guard = threading.Lock()

    def _exchange(self, request: ReadRequest, parts: urllib.parse.SplitResult,
                  addresses: list[str], headers: Mapping[str, str]) -> tuple[int, dict[str, str], bytes]:
        connection = _PinnedHTTPSConnection(parts.hostname or "", addresses[0], self.timeout_s)
        path = parts.path + ("?" + parts.query if parts.query else "")
        body = None if request.payload is None else json.dumps(request.payload, allow_nan=False).encode()
        deadline = self.monotonic() + self.timeout_s
        try:
            connection.request(request.spec.method, path, body=body, headers=dict(headers))
            response = connection.getresponse()
            response_headers = {k.lower(): v for k, v in response.getheaders()}
            encoding = response_headers.get("content-encoding", "identity").lower()
            if encoding not in {"", "identity"}:
                raise ConnectorError("compressed_response_forbidden")
            length = response_headers.get("content-length")
            if length is not None:
                try:
                    parsed_length = int(length)
                except ValueError:
                    raise ConnectorError("invalid_content_length") from None
                if parsed_length < 0:
                    raise ConnectorError("invalid_content_length")
                if parsed_length > self.max_bytes:
                    raise ConnectorError("response_too_large")
            chunks, size = [], 0
            while True:
                remaining = deadline - self.monotonic()
                if remaining <= 0:
                    raise ConnectorError("response_deadline_exceeded")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, self.max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > self.max_bytes:
                    raise ConnectorError("response_too_large")
            return response.status, response_headers, b"".join(chunks)
        finally:
            connection.close()

    def _retry_wait(self, headers: Mapping[str, str], attempt: int) -> float:
        raw = headers.get("retry-after")
        if raw is not None:
            try:
                value = float(raw)
                if not math.isfinite(value) or value < 0:
                    raise ValueError
                return value
            except ValueError:
                try:
                    parsed = email.utils.parsedate_to_datetime(raw)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    return max(0, (parsed - self.clock()).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    raise ConnectorError("invalid_retry_after") from None
        return min(2 ** (attempt - 1), self.max_wait_s)

    def fetch(self, request: ReadRequest, policy: SourcePolicy) -> RawResponse:
        parts = request.validate()
        with self._lock_guard:
            lock = self._host_locks.setdefault(parts.hostname or "", threading.Lock())
        if not lock.acquire(blocking=False):
            raise ConnectorError("source_collection_in_progress")
        try:
            return self._fetch_locked(request, policy)
        finally:
            lock.release()

    def _fetch_locked(self, request: ReadRequest, policy: SourcePolicy) -> RawResponse:
        if request.spec.source_id != policy.source_id:
            raise ConnectorError("source_policy_mismatch")
        policy.require("observe", self.clock())
        parts = request.validate()
        host = parts.hostname or ""
        if self._cooldown.get(host, 0) > self.monotonic():
            raise ConnectorError("source_cooldown_active")
        headers = {"Accept": ", ".join(sorted(request.spec.content_types)),
                   "Accept-Encoding": "identity", "User-Agent": "RelayReadOnly/1.0"}
        if request.spec.secret_env:
            secret = os.environ.get(request.spec.secret_env)
            if not secret:
                raise ConnectorError("authentication_missing")
            if "\r" in secret or "\n" in secret:
                raise ConnectorError("invalid_authentication")
            headers["Authorization"] = "Bearer " + secret
        if request.payload is not None:
            headers["Content-Type"] = "application/json"
        redirects = 0
        attempts = 0
        while attempts < self.max_attempts:
            policy.require("observe", self.clock())
            addresses = resolve_public(host, self.resolver, timeout_s=self.timeout_s)
            attempts += 1
            try:
                status, incoming, body = self.exchange(request, parts, addresses, headers)
            except ConnectorError:
                raise
            except (OSError, http.client.HTTPException):
                # Keep untrusted exception messages (possibly containing URLs) out of diagnostics.
                raise ConnectorError("network_request_failed") from None
            incoming = {k.lower(): v for k, v in incoming.items()}
            if len(body) > self.max_bytes:
                raise ConnectorError("response_too_large")
            if status in {301, 302, 303, 307, 308}:
                if request.spec.method != "GET" or redirects >= 2 or not incoming.get("location"):
                    raise ConnectorError("redirect_forbidden")
                redirected = urllib.parse.urljoin(request.url, incoming["location"])
                candidate = dataclasses.replace(request, url=redirected)
                next_parts = candidate.validate()  # Same host, standard port, paths, query and credential rules.
                if next_parts.path != parts.path or dict(urllib.parse.parse_qsl(next_parts.query)) != dict(urllib.parse.parse_qsl(parts.query)):
                    raise ConnectorError("redirect_scope_changed")
                request, parts = candidate, next_parts
                redirects += 1
                attempts -= 1
                continue
            if status in RETRY_STATUSES:
                wait = self._retry_wait(incoming, attempts)
                self._cooldown[host] = self.monotonic() + wait
                if wait > self.max_wait_s:
                    raise ConnectorError("retry_after_exceeds_budget")
                if attempts >= self.max_attempts:
                    raise ConnectorError("retry_attempts_exhausted")
                self.sleep(wait)
                continue
            if status != 200:
                raise ConnectorError(f"http_status_{status}")
            content_type = incoming.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in request.spec.content_types:
                raise ConnectorError("unexpected_content_type")
            if incoming.get("content-encoding", "identity").lower() not in {"identity", ""}:
                raise ConnectorError("compressed_response_forbidden")
            safe_headers = {k: v for k, v in incoming.items() if k in SAFE_RESPONSE_HEADERS}
            self._cooldown[host] = self.monotonic() + policy.min_interval_s
            return RawResponse(policy.source_id, utc_string(self.clock()), parts.path,
                               status, safe_headers, body, attempts)
        raise ConnectorError("retry_attempts_exhausted")

    def cooldown_remaining(self, source_id: str) -> float:
        """Read-only remaining host hold; never expose its endpoint or headers."""
        spec = SOURCE_SPECS.get(source_id)
        if spec is None:
            return 0
        return max(0, self._cooldown.get(spec.host, 0) - self.monotonic())

    def wait_for_source(self, source_id: str, *, max_wait_s: float = 5) -> None:
        """Budgeted pacing for admitted pagination; never truncates server cooldown."""
        spec = SOURCE_SPECS.get(source_id)
        if spec is None or not math.isfinite(max_wait_s) or not 0 <= max_wait_s <= 60:
            raise ConnectorError("invalid_pagination_wait")
        remaining = self.cooldown_remaining(source_id)
        if remaining > max_wait_s:
            raise ConnectorError("source_cooldown_exceeds_pagination_budget")
        if remaining:
            self.sleep(remaining)
