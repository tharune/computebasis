"""Configured retained evidence with conditional reads and bounded change events."""
import asyncio
import datetime as dt
from dataclasses import dataclass
import json
import threading
import time
from fastapi import HTTPException

from compute_pricing.control._numbers import digest
from compute_pricing.control.curves import observed_commitment_curves
from compute_pricing.control.connectors.transport import parse_utc
from compute_pricing.control.reporting import SnapshotStoreError
from .market import market_index

VERSION = "current-market/1.0"
DISPLAY_LIMIT = 1000
MAX_CACHE_SECONDS = 60


def configured_market(store, policies, plan):
    class ConfiguredDisplay:
        def latest_collection_scan(self):
            return store.requested_collection_scan(plan)

        def latest_refresh(self):
            return None

    packet = market_index(ConfiguredDisplay(), policies, plan, row_limit=DISPLAY_LIMIT)
    packet["schema_version"] = VERSION
    packet["commitment_curves"] = observed_commitment_curves(packet, group_limit=512, node_limit=1024)
    packet["coverage"].update({"population": "explicit_configured_display_scopes",
        "requested_scope_count": len(plan), "full_history_integrity_scan": False,
        "all_market_sources": False, "selection_method": "latest_per_explicit_source_and_filter"})
    packet["warnings"].append("configured_scope_display_is_not_complete_market_or_benchmark_admission")
    return packet


def cache_lifetime(packet, policies, *, now=None):
    """Rebuild at the next known age/rights deadline, never conceal expiry."""
    valuation = parse_utc(packet["as_of"])
    deadlines = []
    def add(value, age=0):
        if not value:
            return
        try:
            deadline = parse_utc(value) + dt.timedelta(seconds=age)
        except (ValueError, TypeError, ArithmeticError):
            return  # The index already marks unparseable evidence as stale.
        if deadline > valuation:
            deadlines.append(deadline)
    for policy in policies.values():
        add(policy.expires_at)
    for row in packet["snapshots"]:
        policy = policies.get(row["source_id"])
        if policy:
            add(row.get("captured_at"), policy.max_age_s)
    for row in packet["observations"] + packet["catalog_records"]:
        add(row.get("expires_at"))
        add((row.get("rights") or {}).get("expires_at"))
        policy = policies.get(row["source_id"])
        if policy:
            observed = row.get("observed_at") or (row["observed_date"] + "T00:00:00Z" if row.get("observed_date") else None)
            add(observed, policy.max_age_s)
    now = now or dt.datetime.now(dt.timezone.utc)
    remaining = (min(deadlines) - now).total_seconds() if deadlines else MAX_CACHE_SECONDS
    return max(0, min(MAX_CACHE_SECONDS, remaining))


@dataclass(frozen=True)
class CurrentView:
    body: str
    revision: str
    as_of: str
    event_data: str


class MarketReader:
    """Immutable encoded display, invalidated by input changes and deadlines.

    Any database-file or policy change invalidates the cache immediately. The
    Cache deadlines honor source ages/expiry; as_of preserves valuation time.
    Monetary evaluations retain independent current evidence checks. No GET or
    event subscription fetches a vendor.
    """
    def __init__(self, store, policies, plan, operations, *, clock=time.monotonic):
        self.store, self.policies, self.plan, self.operations = store, policies, plan, operations
        self.clock = clock
        self._lock = threading.Lock()
        self._cached = None
        self._signature = None
        self._until = 0

    def _state(self):
        try:
            files = []
            for path in (self.store.path, self.store.path.with_name(self.store.path.name + "-wal")):
                stat = path.stat() if path.exists() else None
                files.append((stat.st_mtime_ns, stat.st_size) if stat else None)
        except OSError:
            raise SnapshotStoreError("snapshot_store_unavailable") from None
        policies = [(name, policy.enabled, policy.rights_status, policy.rights_evidence,
                     tuple(sorted(policy.permissions.items())), policy.expires_at, policy.max_age_s,
                     policy.verified_by, policy.attribution, policy.liveness, policy.min_interval_s)
                    for name, policy in sorted(self.policies.items())]
        return files, policies, digest(self.plan), self.operations()

    def read(self):
        with self._lock:
            signature = self._state()
            now = self.clock()
            if self._cached is not None and signature == self._signature and now < self._until:
                return self._cached
            packet = configured_market(self.store, self.policies, self.plan)
            packet["refresh_operations"] = signature[-1]
            packet["cache_max_age_seconds"] = MAX_CACHE_SECONDS
            packet["cache_basis"] = "input_changes_or_next_known_expiry_deadline"
            # Clock labels alone do not change the evidence revision. Permission,
            # expiry, rows, publisher times, coverage and refresh state all do.
            meaningful = {key: value for key, value in packet.items() if key != "as_of"}
            meaningful["commitment_curves"] = {key: value for key, value in packet["commitment_curves"].items() if key != "as_of"}
            revision = digest(meaningful)
            packet["data_revision"] = revision
            event = {"schema_version": "market-event/1.0", "data_revision": revision,
                "as_of": packet["as_of"], "view_endpoint": "/v1/market/current",
                "source_count": len([row for row in packet["sources"] if row["enabled"]]),
                "returned_observations": len(packet["observations"]),
                "returned_catalog_records": len(packet["catalog_records"]),
                "execution_enabled": False}
            self._cached = CurrentView(json.dumps(packet, separators=(",", ":"), allow_nan=False),
                revision, packet["as_of"], json.dumps(event, separators=(",", ":")))
            self._signature, self._until = signature, self.clock() + cache_lifetime(packet, self.policies)
            return self._cached


class MarketStreams:
    def __init__(self, maximum=8):
        self.maximum = maximum
        self.active = 0
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            if self.active >= self.maximum:
                return None
            self.active += 1
            return StreamLease(self)

    def release(self):
        with self._lock:
            self.active -= 1


class StreamLease:
    def __init__(self, streams):
        self.streams = streams
        self.closed = False
        self._lock = threading.Lock()

    def release(self):
        with self._lock:
            if not self.closed:
                self.closed = True
                self.streams.release()


async def market_events(request, reader, permit, *, lease_seconds, read_view, authorize):
    deadline, previous = time.monotonic() + lease_seconds, None
    try:
        yield "retry: 2000\n\n"
        while time.monotonic() < deadline:
            if await request.is_disconnected():
                break
            try:
                await authorize(request)
            except HTTPException:
                yield 'event: session_expired\ndata: {"reason":"workspace_session_unavailable"}\n\n'
                break
            try:
                view = await read_view(reader.read)
            except SnapshotStoreError:
                yield 'event: market_unavailable\ndata: {"reason":"retained_evidence_unavailable","execution_enabled":false}\n\n'
                break
            try:
                await authorize(request)
            except HTTPException:
                yield 'event: session_expired\ndata: {"reason":"workspace_session_unavailable"}\n\n'
                break
            if view.revision != previous:
                yield f"id: {view.revision}\nevent: market_update\ndata: {view.event_data}\n\n"
                previous = view.revision
            else:
                yield ": retained evidence unchanged\n\n"
            await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
        yield 'event: stream_renew\ndata: {"reconnect":true}\n\n'
    finally:
        permit.release()
