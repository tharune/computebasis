"""App-owned bounded public reads, with scope coalescing and safe status.

The lifecycle exists only while this local application runs. It installs no jobs
and adds no source permission, credential, financial model or execution authority.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from fastapi import HTTPException

from compute_pricing.control.connectors.transport import ConnectorError, SOURCE_SPECS, SourcePolicy

PUBLIC_AUTO_SOURCES = frozenset({"getdeploying", "azure", "aws_public_pricing", "openrouter",
                                 "ecb", "huggingface", "huggingface_catalog", "energinet_day_ahead"})


def scope_key(source_id: str, filters: dict) -> str:
    encoded = json.dumps({"source_id": source_id, "filters": filters}, sort_keys=True,
                         ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def safe_code(error: BaseException) -> str:
    value = error.code if isinstance(error, ConnectorError) else error.detail if isinstance(error, HTTPException) else "source_collection_failed"
    if not isinstance(value, str) or len(value) > 256 or not re.fullmatch(r"[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)*)?", value):
        return "source_collection_failed"
    return value


def timestamp(value: float) -> str:
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RefreshConfig:
    enabled: bool = True
    on_startup: bool = True
    cadence_s: int = 21600
    source_cadence_s: Mapping[str, int] = field(default_factory=dict)
    backoff_initial_s: int = 60
    backoff_max_s: int = 21600

    @classmethod
    def parse(cls, raw: dict | None) -> "RefreshConfig":
        if raw is None:
            return cls(enabled=False)
        if not isinstance(raw, dict) or set(raw) - {"enabled", "on_startup", "cadence_s", "source_cadence_s", "backoff_initial_s", "backoff_max_s"}:
            raise ValueError("invalid automatic refresh configuration")
        result = cls(**raw)
        if type(result.enabled) is not bool or type(result.on_startup) is not bool:
            raise ValueError("invalid automatic refresh configuration")
        if any(type(value) is not int or not 60 <= value <= 604800 for value in
               (result.cadence_s, result.backoff_initial_s, result.backoff_max_s)) or result.backoff_initial_s > result.backoff_max_s:
            raise ValueError("invalid automatic refresh timing")
        if not isinstance(result.source_cadence_s, dict) or any(source not in PUBLIC_AUTO_SOURCES or type(value) is not int or not 60 <= value <= 604800 for source, value in result.source_cadence_s.items()):
            raise ValueError("invalid automatic source cadence")
        # Detached from caller-owned JSON; no dynamic source discovery admission.
        from types import MappingProxyType
        object.__setattr__(result, "source_cadence_s", MappingProxyType(dict(result.source_cadence_s)))
        return result


class CollectionCoordinator:
    """One worker per identical scope; cancelled callers cannot cancel that read."""
    def __init__(self, worker, *, notify=None):
        self.worker, self.notify = worker, notify
        self._inflight: dict[str, asyncio.Task] = {}
        self.closed = False

    async def collect(self, source_id: str, filters: dict) -> dict:
        if self.closed:
            raise ConnectorError("collection_service_stopping")
        key = scope_key(source_id, filters)
        task = self._inflight.get(key)
        if task is None:
            # No await between lookup and reservation: all callers share one loop.
            detached = json.loads(json.dumps(filters, allow_nan=False))
            task = asyncio.create_task(self._run(key, source_id, detached))
            self._inflight[key] = task
            task.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)
        return await asyncio.shield(task)

    async def _run(self, key: str, source_id: str, filters: dict):
        if self.notify:
            self.notify(key, "started", None)
        try:
            result = await self.worker(source_id, filters)
        except BaseException as error:
            if self.notify:
                self.notify(key, "failed", error)
            raise
        else:
            if self.notify:
                self.notify(key, "succeeded", result)
            return result
        finally:
            self._inflight.pop(key, None)

    async def stop(self):
        self.closed = True
        # Drain the bounded network workers rather than cancel a blocking thread.
        if self._inflight:
            await asyncio.gather(*tuple(self._inflight.values()), return_exceptions=True)


class AutomaticRefresh:
    def __init__(self, config: RefreshConfig, plan: list[dict], policies: Mapping[str, SourcePolicy],
                 coordinator: CollectionCoordinator, *, cooldown: Callable[[str], float] = lambda _: 0,
                 clock: Callable[[], float] = time.time):
        self.config, self.policies, self.coordinator = config, policies, coordinator
        self.cooldown, self.clock = cooldown, clock
        if not isinstance(plan, list) or len(plan) > 32 or any(not isinstance(row, dict) or
                set(row) != {"source_id", "filters"} or not isinstance(row["source_id"], str) or
                not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", row["source_id"]) or not isinstance(row["filters"], dict) for row in plan):
            raise ValueError("bounded explicit automatic refresh plan required")
        self.rows = json.loads(json.dumps(plan, allow_nan=False))
        keys = [scope_key(row["source_id"], row["filters"]) for row in self.rows]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate automatic refresh scope")
        self._state = {}
        for key, row in zip(keys, self.rows):
            self._state[key] = {"source_id": row["source_id"], "scope_id": key, "filters": row["filters"],
                "status": "waiting" if config.enabled else "disabled", "last_attempt_at": None,
                "last_success_at": None, "last_error": None, "snapshot_id": None,
                "observation_count": None, "catalog_record_count": None, "consecutive_failures": 0,
                "next_due": clock() if config.on_startup else clock() + self.cadence(row["source_id"])}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._cycle_lock = asyncio.Lock()
        self.coordinator.notify = self.note

    def cadence(self, source_id: str) -> int:
        configured = self.config.source_cadence_s.get(source_id, self.config.cadence_s)
        policy = self.policies.get(source_id)
        # Cadence is operational only. Freshness still uses actual source dates.
        return min(configured, max(60, policy.max_age_s // 2)) if policy else configured

    def eligibility(self, source_id: str) -> str | None:
        spec, policy = SOURCE_SPECS.get(source_id), self.policies.get(source_id)
        if source_id not in PUBLIC_AUTO_SOURCES or spec is None or spec.method != "GET" or spec.secret_env is not None:
            return "automatic_public_source_not_allowed"
        if policy is None:
            return "source_not_admitted"
        blockers = []
        for purpose in ("observe", "retain", "benchmark"):
            blockers += policy.blockers(purpose)
        return "admission_blocked:" + ",".join(dict.fromkeys(blockers)) if blockers else None

    def note(self, key: str, event: str, value: Any):
        state = self._state.get(key)
        if state is None:
            return
        now = self.clock()
        if event == "started":
            state.update(status="in_progress", last_attempt_at=timestamp(now))
            return
        if event == "succeeded":
            result = value.get("result", {})
            state.update(status="ready", last_success_at=timestamp(now), last_error=None,
                         snapshot_id=value.get("snapshot_id"), observation_count=len(result.get("observations", [])),
                         catalog_record_count=len(result.get("catalog_records", [])), consecutive_failures=0,
                         next_due=now + self.cadence(state["source_id"]))
            return
        code = safe_code(value)
        failures = min(state["consecutive_failures"] + 1, 32)
        delay = min(self.config.backoff_max_s, self.config.backoff_initial_s * 2 ** (failures - 1))
        # Retry-After can exceed our retry cap; never shorten the source hold.
        source_hold = self.cooldown(state["source_id"])
        if not isinstance(source_hold, (int, float)) or not math.isfinite(source_hold) or source_hold < 0:
            source_hold = 0
        state.update(status="held" if code.startswith("admission_blocked") or code in
                     {"source_not_admitted", "automatic_public_source_not_allowed", "source_cooldown_active", "source_cooldown_exceeds_pagination_budget", "collection_capacity_exceeded"} else "failed",
                     last_error=code, consecutive_failures=failures, next_due=now + max(delay, source_hold))

    async def cycle(self):
        if not self.config.enabled or self._cycle_lock.locked():
            return
        async with self._cycle_lock:
            for row in self.rows:
                if self._stop.is_set():
                    break
                key = scope_key(row["source_id"], row["filters"])
                state = self._state[key]
                if state["next_due"] > self.clock() or state["status"] == "in_progress":
                    continue
                hold = self.eligibility(row["source_id"])
                if hold:
                    self.note(key, "started", None)
                    self.note(key, "failed", ConnectorError(hold))
                    continue
                try:
                    await self.coordinator.collect(row["source_id"], row["filters"])
                except (ConnectorError, HTTPException):
                    pass  # The coordinator recorded a safe, source-local status.
                except Exception:
                    pass  # The worker boundary must not leak external exception text.

    async def _loop(self):
        while not self._stop.is_set():
            await self.cycle()
            deadlines = [state["next_due"] for state in self._state.values()]
            wait = max(1, min(60, min(deadlines, default=self.clock() + 60) - self.clock()))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except TimeoutError:
                pass

    async def start(self):
        if self.config.enabled and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._stop.set()
        if self._task is not None:
            await self._task
        await self.coordinator.stop()

    def status(self) -> dict:
        scopes = []
        for state in self._state.values():
            scopes.append({key: value for key, value in state.items() if key != "next_due"} | {
                "next_due_at": timestamp(state["next_due"]), "cadence_s": self.cadence(state["source_id"]),
                "admission_hold": self.eligibility(state["source_id"])})
        result = {"enabled": self.config.enabled, "running": self._task is not None and not self._task.done(),
                "owner": "local_application_process", "scope_count": len(scopes), "scopes": scopes,
                "updates_available_via": "/v1/market/index", "execution_enabled": False}
        return json.loads(json.dumps(result, allow_nan=False))
