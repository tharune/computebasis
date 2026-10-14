"""Restartable local paper commands; no external dispatcher.

Transactions commit a command, its historical receipt and simulated leg records
together. Replaying the append-only command chain reconstructs resource owners
and checks receipts. Caller-supplied actors are assertions, not authenticated
mandates. This bounded SQLite primitive is not a production custody ledger.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from .paper import Actor, DecisionSnapshot, PaperJournal, _canonical
from compute_pricing.control.treasury._validation import decimal_value

OPERATIONS = frozenset({"create", "hold", "approve", "submit_paper", "mark_unknown", "reconcile", "cancel"})
MAX_COMMAND_BYTES = 262144
MAX_COMMANDS = 2000
MAX_STORED_BYTES = 32 * 1024 * 1024
GENESIS = "0" * 64


class PaperRepositoryError(ValueError):
    """Only bounded diagnostic codes cross the repository boundary."""


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise PaperRepositoryError("paper_canonical_id_required")
    return value


def _encode(value):
    pending, count = [(value, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if depth > 24 or count > 20000:
            raise PaperRepositoryError("paper_command_structure_limit")
        if isinstance(node, dict):
            pending.extend((child, depth + 1) for child in node.values())
            pending.extend((key, depth + 1) for key in node)
        elif isinstance(node, (tuple, list)):
            pending.extend((child, depth + 1) for child in node)
    try:
        encoded = _canonical(value)
        if len(encoded.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise PaperRepositoryError("paper_command_size_limit")
        return encoded
    except PaperRepositoryError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise PaperRepositoryError("paper_invalid_exact_json") from None


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ids(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 256:
        raise PaperRepositoryError("paper_bounded_ids_required")
    identities = tuple(_id(value) for value in values)
    if len(set(identities)) != len(identities):
        raise PaperRepositoryError("paper_duplicate_identity")
    return identities


def _actor(raw):
    if not isinstance(raw, dict) or set(raw) != {"actor_id", "roles", "currency", "amount_limit"} or not isinstance(raw["roles"], list):
        raise PaperRepositoryError("paper_actor_assertion_required")
    return Actor(_id(raw["actor_id"]), tuple(raw["roles"]), raw["currency"], raw["amount_limit"])


def _intent(journal, identity):
    row = next((value for value in journal.to_dict()["intents"] if value["economic_intent_id"] == identity), None)
    if row is None:
        raise PaperRepositoryError("paper_unknown_intent")
    return row


def _dispatch(journal, request, revisions):
    identity, operation, payload = request["intent_id"], request["operation"], request["payload"]
    if request["expected_revision"] != revisions.get(identity, 0):
        raise PaperRepositoryError("paper_revision_conflict")
    fields = {
        "create": {"snapshot"}, "hold": {"hold_ids"},
        "approve": {"actor", "role", "now", "expires_at", "active_versions"},
        "submit_paper": {"leg_ids", "now", "active_versions"},
        "mark_unknown": {"leg_id"},
        "reconcile": {"outcomes", "actor", "evidence_id", "now", "release_hold_ids"},
        "cancel": {"actor_id", "reason_id"},
    }
    if not isinstance(payload, dict) or set(payload) != fields[operation]:
        raise PaperRepositoryError("paper_operation_fields_required")
    if operation == "create":
        canonical = _encode(payload["snapshot"])
        journal.create(identity, DecisionSnapshot(canonical, _sha(canonical)))
    elif operation == "hold":
        journal.hold(identity, _ids(payload["hold_ids"]))
    elif operation == "approve":
        journal.approve(identity, _actor(payload["actor"]), role=payload["role"], now=payload["now"],
                        expires_at=payload["expires_at"], active_versions=payload["active_versions"])
    elif operation == "submit_paper":
        journal.submit_paper(identity, _ids(payload["leg_ids"]), now=payload["now"], active_versions=payload["active_versions"])
    elif operation == "mark_unknown":
        journal.mark_unknown(identity, _id(payload["leg_id"]))
    elif operation == "reconcile":
        release = payload["release_hold_ids"]
        if not isinstance(release, list):
            raise PaperRepositoryError("paper_release_ids_required")
        actor, before = _actor(payload["actor"]), journal.get(identity)
        terms = before.snapshot.to_dict()
        if actor.currency != terms["currency"] or decimal_value(actor.amount_limit, "reconciliation limit") < decimal_value(terms["amount"], "decision amount"):
            raise PaperRepositoryError("paper_reconciliation_scope_mismatch")
        if not isinstance(payload["outcomes"], dict) or any(leg.state in {"matched", "failed"} and payload["outcomes"].get(leg.leg_id) != leg.state for leg in before.legs):
            raise PaperRepositoryError("paper_known_outcome_cannot_be_rewritten")
        journal.reconcile(identity, payload["outcomes"], actor, evidence_id=_id(payload["evidence_id"]),
                          now=payload["now"], release_hold_ids=_ids(release) if release else ())
    else:
        journal.cancel(identity, actor_id=_id(payload["actor_id"]), reason_id=_id(payload["reason_id"]))
    revisions[identity] = revisions.get(identity, 0) + 1
    return {"format": "durable-paper-receipt/1", "command_id": request["command_id"],
            "revision": revisions[identity], "intent": _intent(journal, identity),
            "paper_only": True, "durable_local": True, "execution_enabled": False}


def _outbox(journal):
    rows = {}
    for intent in journal.to_dict()["intents"]:
        for leg in intent["legs"]:
            identity = _sha(intent["economic_intent_id"] + "\0" + leg["leg_id"])
            body = {"format": "paper-outbox/1", "item_id": identity, "intent_id": intent["economic_intent_id"],
                    "leg_id": leg["leg_id"], "snapshot_hash": intent["snapshot_hash"],
                    "paper_only": True, "execution_enabled": False}
            rows[identity] = (_encode(body), leg["state"])
    return rows


class DurablePaperRepository:
    """Bounded command history with exact historical retry acknowledgements.

    Reads reconstruct the latest state. Retrying an identical command returns
    the receipt at its original point in history. UNKNOWN simulated legs retain
    their holds; they never establish that any external effect was reversed.
    """

    def __init__(self, path: Path):
        if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
            raise PaperRepositoryError("paper_absolute_nonsymlink_path_required")
        self.path = path.resolve()
        if self.path.name == ":memory:" or any((parent / ".git").exists() for parent in self.path.parents):
            raise PaperRepositoryError("paper_store_must_be_outside_git")
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError:
                pass
            self.path.chmod(0o600)
            with self._connect() as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS paper_commands (sequence INTEGER PRIMARY KEY, command_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL, request_hash TEXT NOT NULL, receipt TEXT NOT NULL, receipt_hash TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)")
                for action in ("UPDATE", "DELETE"):
                    connection.execute(f"CREATE TRIGGER IF NOT EXISTS paper_commands_no_{action.lower()} BEFORE {action} ON paper_commands BEGIN SELECT RAISE(ABORT,'paper_append_only'); END")
                connection.execute("CREATE TABLE IF NOT EXISTS paper_outbox (item_id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL)")
                self._replay(connection)
        except (OSError, sqlite3.Error):
            raise PaperRepositoryError("paper_store_unavailable") from None

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                yield connection
        finally:
            connection.close()

    def _replay(self, connection):
        rows = connection.execute("SELECT sequence,command_id,request,request_hash,receipt,receipt_hash,previous_hash,event_hash FROM paper_commands ORDER BY sequence LIMIT ?", (MAX_COMMANDS + 1,)).fetchall()
        if len(rows) > MAX_COMMANDS or sum(len(row[2].encode("utf-8")) + len(row[4].encode("utf-8")) for row in rows) > MAX_STORED_BYTES:
            raise PaperRepositoryError("paper_store_capacity_exceeded")
        journal, revisions, previous, receipts = PaperJournal(), {}, GENESIS, {}
        try:
            for sequence, command_id, request, request_hash, receipt, receipt_hash, prior, event_hash in rows:
                envelope = _encode({"sequence": sequence, "request_hash": request_hash, "receipt_hash": receipt_hash, "previous_hash": prior})
                if sequence != len(receipts) + 1 or prior != previous or _sha(request) != request_hash or _sha(receipt) != receipt_hash or _sha(envelope) != event_hash:
                    raise PaperRepositoryError("paper_integrity_failed")
                packet = json.loads(request)
                if packet["command_id"] != command_id or _encode(packet) != request:
                    raise PaperRepositoryError("paper_integrity_failed")
                generated = _dispatch(journal, packet, revisions)
                if _encode(generated) != receipt:
                    raise PaperRepositoryError("paper_integrity_failed")
                receipts[command_id] = (request_hash, generated)
                previous = event_hash
            stored = {key: (body, state) for key, body, state in connection.execute("SELECT item_id,body,state FROM paper_outbox")}
            if stored != _outbox(journal):
                raise PaperRepositoryError("paper_outbox_integrity_failed")
        except (ValueError, KeyError, TypeError, RecursionError):
            raise PaperRepositoryError("paper_integrity_failed") from None
        return journal, revisions, previous, receipts

    def apply(self, *, command_id: str, intent_id: str, operation: str, payload: dict, expected_revision: int):
        _id(command_id); _id(intent_id)
        if not isinstance(operation, str) or operation not in OPERATIONS or type(expected_revision) is not int or expected_revision < 0:
            raise PaperRepositoryError("paper_operation_and_revision_required")
        request = {"command_id": command_id, "intent_id": intent_id, "operation": operation,
                   "payload": payload, "expected_revision": expected_revision}
        encoded = _encode(request)
        request_hash = _sha(encoded)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                journal, revisions, previous, receipts = self._replay(connection)
                if command_id in receipts:
                    original_hash, original = receipts[command_id]
                    if original_hash != request_hash:
                        raise PaperRepositoryError("paper_idempotency_conflict")
                    return json.loads(_encode(original))
                if len(receipts) >= MAX_COMMANDS:
                    raise PaperRepositoryError("paper_store_capacity_exceeded")
                receipt = _dispatch(journal, request, revisions)
                result = _encode(receipt)
                size = connection.execute("SELECT COALESCE(SUM(length(CAST(request AS BLOB))+length(CAST(receipt AS BLOB))),0) FROM paper_commands").fetchone()[0]
                if size + len(encoded.encode("utf-8")) + len(result.encode("utf-8")) > MAX_STORED_BYTES:
                    raise PaperRepositoryError("paper_store_capacity_exceeded")
                sequence = len(receipts) + 1
                event_hash = _sha(_encode({"sequence": sequence, "request_hash": request_hash, "receipt_hash": _sha(result), "previous_hash": previous}))
                connection.execute("INSERT INTO paper_commands VALUES (?,?,?,?,?,?,?,?)", (sequence, command_id, encoded, request_hash, result, _sha(result), previous, event_hash))
                for item_id, (body, state) in _outbox(journal).items():
                    connection.execute("INSERT INTO paper_outbox VALUES (?,?,?) ON CONFLICT(item_id) DO UPDATE SET state=excluded.state", (item_id, body, state))
                return json.loads(result)
        except sqlite3.Error:
            raise PaperRepositoryError("paper_store_unavailable") from None
        except PaperRepositoryError:
            raise
        except (ValueError, KeyError, TypeError, RecursionError):
            raise PaperRepositoryError("paper_command_rejected") from None

    def get(self, intent_id: str):
        _id(intent_id)
        with self._connect() as connection:
            journal, revisions, _, _ = self._replay(connection)
            return {"intent": _intent(journal, intent_id), "revision": revisions[intent_id],
                    "paper_only": True, "durable_local": True, "execution_enabled": False}

    def pending_outbox(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise PaperRepositoryError("paper_outbox_limit_invalid")
        with self._connect() as connection:
            journal, _, _, _ = self._replay(connection)
            rows = [{**json.loads(body), "state": state} for _, (body, state) in sorted(_outbox(journal).items()) if state in {"paper_pending", "unknown"}]
            return {"items": rows[:limit], "total_pending_or_unknown": len(rows), "truncated": len(rows) > limit,
                    "paper_only": True, "execution_enabled": False, "dispatch_supported": False}

    def audit(self):
        with self._connect() as connection:
            _, _, head, receipts = self._replay(connection)
            return {"command_count": len(receipts), "head_hash": head, "paper_only": True,
                    "execution_enabled": False, "integrity_verified": True}


def actor_payload(actor: Actor):
    """Serialize a caller assertion without creating identity authority."""
    return {**asdict(actor), "roles": list(actor.roles)}
