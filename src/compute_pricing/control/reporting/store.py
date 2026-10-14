"""Append-only SQLite development snapshots, explicitly located outside Git.

SHA-256 covers canonical input/output/versions. Repeated exact decisions are
idempotent. Retrieval rechecks content integrity; timestamps do not alter IDs.
This is not a production ledger, authorization registry or financing system.
"""
from __future__ import annotations

import dataclasses
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from types import MappingProxyType
from typing import Any, Mapping


class SnapshotStoreError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _json_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 32:
        raise SnapshotStoreError("snapshot_nesting_limit")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise SnapshotStoreError("snapshot_invalid_json") from None
        return
    if value is None or isinstance(value, (int, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SnapshotStoreError("snapshot_nonfinite_number")
        return  # Optional raw JSON metadata; monetary fields are validated strings.
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise SnapshotStoreError("snapshot_invalid_json")
        for key in value:
            _json_tree(key, depth=depth + 1)
        for item in value.values():
            _json_tree(item, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_tree(item, depth=depth + 1)
        return
    raise SnapshotStoreError("snapshot_invalid_json")


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def canonical_document(value: Mapping[str, Any], *, max_bytes: int) -> str:
    _json_tree(value)
    try:
        encoded = json.dumps(_plain_json(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise SnapshotStoreError("snapshot_invalid_json") from None
    if len(encoded.encode("utf-8")) > max_bytes:
        raise SnapshotStoreError("snapshot_size_limit")
    return encoded


@dataclasses.dataclass(frozen=True)
class Snapshot:
    digest: str
    created_at: str
    document: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "document", _freeze_json(self.document))

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.digest, "created_at": self.created_at,
                "document": _plain_json(self.document)}


@dataclasses.dataclass(frozen=True)
class CollectionScan:
    snapshots: tuple[Snapshot, ...]
    scan_limit: int
    rows_scanned: int
    has_older_history: bool


class SnapshotStore:
    def __init__(self, path: Path, *, max_bytes: int = 16 * 1024 * 1024):
        if not isinstance(path, Path) or not path.is_absolute():
            raise SnapshotStoreError("absolute_store_path_required")
        if type(max_bytes) is not int or not 1024 <= max_bytes <= 64 * 1024 * 1024:
            raise SnapshotStoreError("invalid_store_size_limit")
        self.path = path.resolve()
        if self.path.name in {"", ":memory:"} or any((parent / ".git").exists() for parent in self.path.parents):
            raise SnapshotStoreError("store_must_be_outside_git")
        self.max_bytes = max_bytes
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
            self.path.chmod(0o600)
            with self._connect() as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS snapshots (digest TEXT PRIMARY KEY CHECK(length(digest)=64), created_at TEXT NOT NULL, canonical_document TEXT NOT NULL)")
                connection.execute("CREATE TRIGGER IF NOT EXISTS snapshots_no_update BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT, 'snapshots_append_only'); END")
                connection.execute("CREATE TRIGGER IF NOT EXISTS snapshots_no_delete BEFORE DELETE ON snapshots BEGIN SELECT RAISE(ABORT, 'snapshots_append_only'); END")
        except (OSError, sqlite3.Error):
            raise SnapshotStoreError("snapshot_store_unavailable") from None

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                yield connection
        finally:
            connection.close()

    def put(self, *, kind: str, input_payload: Mapping[str, Any], output_payload: Mapping[str, Any],
            versions: Mapping[str, str]) -> Snapshot:
        if kind not in {"pricing", "pricing_scenarios", "cash", "market_collection", "market_refresh", "paper_decision", "inference", "calibration", "financing"}:
            raise SnapshotStoreError("unknown_snapshot_kind")
        if not isinstance(input_payload, Mapping) or not isinstance(output_payload, Mapping) or not isinstance(versions, Mapping) or not versions:
            raise SnapshotStoreError("snapshot_object_required")
        if not all(isinstance(key, str) and isinstance(value, str) and key and value for key, value in versions.items()):
            raise SnapshotStoreError("snapshot_versions_required")
        document = {"schema_version": "compute-snapshot/1.0", "kind": kind,
                    "input": dict(input_payload), "output": dict(output_payload), "versions": dict(versions)}
        encoded = canonical_document(document, max_bytes=self.max_bytes)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        created_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute("SELECT created_at, canonical_document FROM snapshots WHERE digest=?", (digest,)).fetchone()
                if existing:
                    if existing[1] != encoded:
                        raise SnapshotStoreError("snapshot_hash_conflict")
                    created_at = existing[0]
                else:
                    connection.execute("INSERT INTO snapshots(digest,created_at,canonical_document) VALUES(?,?,?)", (digest, created_at, encoded))
        except sqlite3.Error:
            raise SnapshotStoreError("snapshot_store_unavailable") from None
        # Round-trip prevents caller mutation from changing a returned or stored result.
        return Snapshot(digest, created_at, json.loads(encoded))

    def get(self, digest: str) -> Snapshot | None:
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise SnapshotStoreError("invalid_snapshot_id")
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT created_at, canonical_document FROM snapshots WHERE digest=?", (digest,)).fetchone()
        except sqlite3.Error:
            raise SnapshotStoreError("snapshot_store_unavailable") from None
        if row is None:
            return None
        if len(row[1].encode("utf-8")) > self.max_bytes or hashlib.sha256(row[1].encode("utf-8")).hexdigest() != digest:
            raise SnapshotStoreError("snapshot_integrity_failed")
        try:
            document = json.loads(row[1])
            if canonical_document(document, max_bytes=self.max_bytes) != row[1]:
                raise SnapshotStoreError("snapshot_integrity_failed")
        except (ValueError, TypeError, RecursionError):
            raise SnapshotStoreError("snapshot_integrity_failed") from None
        return Snapshot(digest, row[0], document)

    def latest_collections(self, *, scan_limit: int = 512) -> tuple[Snapshot, ...]:
        return self.latest_collection_scan(scan_limit=scan_limit).snapshots

    def latest_collection_scan(self, *, scan_limit: int = 512) -> CollectionScan:
        """Latest verified result per explicit source/filter scope, bounded scan.

        A scoped cloud response never replaces another region's observation.
        This is a development index over immutable collection snapshots.
        """
        if type(scan_limit) is not int or not 1 <= scan_limit <= 2048:
            raise SnapshotStoreError("invalid_collection_scan_limit")
        try:
            with self._connect() as connection:
                rows = connection.execute("SELECT digest FROM snapshots WHERE json_extract(canonical_document,'$.kind')='market_collection' ORDER BY created_at DESC, digest DESC LIMIT ?", (scan_limit + 1,)).fetchall()
        except sqlite3.Error:
            raise SnapshotStoreError("snapshot_store_unavailable") from None
        latest, seen = [], set()
        for (digest,) in rows[:scan_limit]:
            snapshot = self.get(digest)
            if snapshot is None:
                raise SnapshotStoreError("snapshot_integrity_failed")
            packet = snapshot.to_dict()["document"]
            if not isinstance(packet, dict) or not isinstance(packet.get("input"), dict) or not isinstance(packet.get("output"), dict) or not isinstance(packet["input"].get("filters", {}), dict):
                raise SnapshotStoreError("snapshot_integrity_failed")
            source = packet["output"].get("source_id")
            filters = {key: value for key, value in packet["input"].get("filters", {}).items() if key not in {"max_pages"}}
            scope = (source, json.dumps(filters, sort_keys=True, separators=(",", ":")))
            if not isinstance(source, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", source):
                raise SnapshotStoreError("snapshot_integrity_failed")
            if scope in seen:
                continue
            seen.add(scope)
            latest.append(snapshot)
        return CollectionScan(tuple(latest), scan_limit, min(len(rows), scan_limit), len(rows) > scan_limit)

    def latest_refresh(self) -> Snapshot | None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT digest FROM snapshots WHERE json_extract(canonical_document,'$.kind')='market_refresh' ORDER BY created_at DESC, digest DESC LIMIT 1").fetchone()
        except sqlite3.Error:
            raise SnapshotStoreError("snapshot_store_unavailable") from None
        return self.get(row[0]) if row else None
