"""Transactional local paper revisions sharing an external SQLite file.

CAS protects complete-state replacements; immutable audits retain removals.
This is not an execution ledger, certified asset register or distributed store.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3

from compute_pricing.control.reporting import SnapshotStore, SnapshotStoreError
from compute_pricing.control.reporting.store import canonical_document
from .model import InventoryError, MAX_STATE_BYTES, empty_state, evaluate_inventory, validate_inventory

HISTORY_LIMIT = 20
MAX_REVISION = 2**31 - 1


def _canonical(value) -> str:
    # The admitted state has its own tighter budget; request/audit envelopes
    # add bounded version, revision and change metadata around that state.
    return canonical_document(value, max_bytes=2 * MAX_STATE_BYTES)


def _hash(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _changes(before, after) -> dict:
    result = {"added": {}, "removed": {}, "changed": {}}
    for field, key in (("sites", "site_id"), ("lots", "lot_id"), ("positions", "position_id")):
        old, new = {row[key]: row for row in before[field]}, {row[key]: row for row in after[field]}
        result["added"][field] = sorted(new.keys() - old.keys())
        result["removed"][field] = sorted(old.keys() - new.keys())
        result["changed"][field] = sorted(key for key in old.keys() & new.keys() if old[key] != new[key])
    return result


def _revision(value, *, allow_zero=True):
    if type(value) is not int or not (0 if allow_zero else 1) <= value <= MAX_REVISION:
        raise InventoryError("invalid_inventory_revision")


class InventoryStore:
    def __init__(self, path: Path):
        try:
            self.path = SnapshotStore(path).path
            with self._connect() as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS inventory_revisions (revision INTEGER PRIMARY KEY CHECK(revision>0), request_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, state_hash TEXT NOT NULL, previous_hash TEXT, audit_hash TEXT UNIQUE NOT NULL, canonical_state TEXT NOT NULL, canonical_changes TEXT NOT NULL)")
                connection.execute("CREATE TRIGGER IF NOT EXISTS inventory_no_update BEFORE UPDATE ON inventory_revisions BEGIN SELECT RAISE(ABORT, 'inventory_append_only'); END")
                connection.execute("CREATE TRIGGER IF NOT EXISTS inventory_no_delete BEFORE DELETE ON inventory_revisions BEGIN SELECT RAISE(ABORT, 'inventory_append_only'); END")
        except (SnapshotStoreError, OSError, sqlite3.Error):
            raise InventoryError("inventory_store_unavailable") from None

    @contextmanager
    def _connect(self):
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA busy_timeout=5000")
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
        except sqlite3.Error:
            raise InventoryError("inventory_store_unavailable") from None

    @staticmethod
    def _metadata(row) -> dict:
        try:
            changes = json.loads(row["canonical_changes"])
            packet = {"schema_version": "paper-inventory-audit/1.0", "revision": row["revision"],
                "request_hash": row["request_hash"], "created_at": row["created_at"], "state_hash": row["state_hash"],
                "previous_hash": row["previous_hash"], "changes": changes}
            if _canonical(changes) != row["canonical_changes"] or _hash(packet) != row["audit_hash"]:
                raise ValueError
            return {**packet, "audit_hash": row["audit_hash"]}
        except (ValueError, TypeError, KeyError, RecursionError):
            raise InventoryError("inventory_integrity_failed") from None

    def _snapshot(self, row) -> dict:
        if row is None:
            return {"revision": 0, "created_at": None, "state_hash": _hash(empty_state()), "audit_hash": None, "state": empty_state()}
        metadata = self._metadata(row)
        try:
            if len(row["canonical_state"].encode("utf-8")) > MAX_STATE_BYTES:
                raise ValueError
            state = validate_inventory(json.loads(row["canonical_state"]))
            if _canonical(state) != row["canonical_state"] or _hash(state) != row["state_hash"]:
                raise ValueError
        except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
            raise InventoryError("inventory_integrity_failed") from None
        return {"revision": metadata["revision"], "created_at": metadata["created_at"],
            "state_hash": metadata["state_hash"], "audit_hash": metadata["audit_hash"], "state": state}

    def _history(self, connection, upper_revision: int) -> dict:
        rows = connection.execute("SELECT revision,request_hash,created_at,state_hash,previous_hash,audit_hash,canonical_changes FROM inventory_revisions WHERE revision<=? ORDER BY revision DESC LIMIT ?", (upper_revision, HISTORY_LIMIT + 1)).fetchall()
        recent = [self._metadata(row) for row in rows[:HISTORY_LIMIT]]
        # Verify links for the returned range, including the next older row.
        for newer, older in zip(rows, rows[1:]):
            if newer["revision"] != older["revision"] + 1 or newer["previous_hash"] != older["audit_hash"]:
                raise InventoryError("inventory_integrity_failed")
        if rows and rows[-1]["revision"] == 1 and rows[-1]["previous_hash"] is not None:
            raise InventoryError("inventory_integrity_failed")
        if rows and len(rows) <= HISTORY_LIMIT and rows[-1]["revision"] != 1:
            raise InventoryError("inventory_integrity_failed")
        return {"recent": recent, "truncated": len(rows) > HISTORY_LIMIT, "limit": HISTORY_LIMIT,
            "integrity_scope": "returned_audit_metadata_and_adjacent_links_state_verified_on_replay"}

    @staticmethod
    def _report(snapshot, history, *, as_of=None, latest_revision=None, replayed=False):
        report = evaluate_inventory(snapshot["state"], as_of=as_of)
        return {**report, **snapshot, "audit": history, "persisted": True, "idempotent_replay": replayed,
            "latest_revision": snapshot["revision"] if latest_revision is None else latest_revision}

    def get(self, *, as_of=None, revision: int | None = None) -> dict:
        if revision is not None:
            _revision(revision)
        with self._connect() as connection:
            connection.execute("BEGIN")
            latest = connection.execute("SELECT * FROM inventory_revisions ORDER BY revision DESC LIMIT 1").fetchone()
            latest_revision = latest["revision"] if latest else 0
            row = latest if revision is None else connection.execute("SELECT * FROM inventory_revisions WHERE revision=?", (revision,)).fetchone()
            if revision not in (None, 0) and row is None:
                raise InventoryError("inventory_revision_not_found")
            snapshot = self._snapshot(row)
            history = self._history(connection, snapshot["revision"])
        return self._report(snapshot, history, as_of=as_of, latest_revision=latest_revision)

    def put(self, *, expected_revision: int, state) -> dict:
        _revision(expected_revision)
        normalized = validate_inventory(state)
        encoded, state_hash = _canonical(normalized), _hash(normalized)
        request_hash = _hash({"expected_revision": expected_revision, "state": normalized})
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute("SELECT * FROM inventory_revisions ORDER BY revision DESC LIMIT 1").fetchone()
            current = self._snapshot(latest)
            existing = connection.execute("SELECT * FROM inventory_revisions WHERE request_hash=?", (request_hash,)).fetchone()
            if existing:
                snapshot = self._snapshot(existing)
                if snapshot["state_hash"] != state_hash or snapshot["revision"] != expected_revision + 1:
                    raise InventoryError("inventory_integrity_failed")
                history = self._history(connection, snapshot["revision"])
                return self._report(snapshot, history, latest_revision=current["revision"], replayed=True)
            if current["revision"] != expected_revision:
                raise InventoryError("inventory_revision_conflict", current_revision=current["revision"])
            if expected_revision == MAX_REVISION:
                raise InventoryError("inventory_revision_limit")
            changes = _changes(current["state"], normalized)
            metadata = {"schema_version": "paper-inventory-audit/1.0", "revision": expected_revision + 1,
                "request_hash": request_hash, "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "state_hash": state_hash, "previous_hash": current["audit_hash"], "changes": changes}
            audit_hash = _hash(metadata)
            connection.execute("INSERT INTO inventory_revisions(revision,request_hash,created_at,state_hash,previous_hash,audit_hash,canonical_state,canonical_changes) VALUES(?,?,?,?,?,?,?,?)",
                (metadata["revision"], request_hash, metadata["created_at"], state_hash, metadata["previous_hash"], audit_hash, encoded, _canonical(changes)))
            snapshot = {"revision": metadata["revision"], "created_at": metadata["created_at"], "state_hash": state_hash, "audit_hash": audit_hash, "state": normalized}
            history = self._history(connection, snapshot["revision"])
        return self._report(snapshot, history)
