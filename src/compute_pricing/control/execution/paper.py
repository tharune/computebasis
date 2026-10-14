"""Immutable paper-only decisions, independent approvals and held intents.

Actors/evidence are trusted-service assertions supplied by a caller, not a
replacement for production authentication, digital signatures or bank proof.
There is no broker, wallet, provider order or payment execution capability.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import threading
from typing import Mapping
from compute_pricing.control.treasury._validation import currency_value, decimal_value, identifier, utc_instant


APPROVER_ROLES = frozenset({"risk_approver", "treasury_approver"})
INTENT_STATES = frozenset({"draft", "held", "approved", "paper_submitted", "unknown", "reconciled", "cancelled"})


def _canonical(value) -> str:
    def validate(item):
        if isinstance(item, float) or not isinstance(item, (str, int, bool, type(None), list, tuple, dict)):
            raise ValueError("snapshots require finite JSON values and Decimal strings")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("snapshot object keys must be strings")
            for child in item.values():
                validate(child)
        if isinstance(item, (list, tuple)):
            for child in item:
                validate(child)
    validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class Actor:
    actor_id: str
    roles: tuple[str, ...]
    currency: str
    amount_limit: str

    def __post_init__(self):
        identifier(self.actor_id, "actor_id")
        if not isinstance(self.roles, tuple) or not self.roles or any(not isinstance(role, str) for role in self.roles) or len(set(self.roles)) != len(self.roles) or not set(self.roles) <= APPROVER_ROLES | {"proposer", "reconciler"}:
            raise ValueError("actor roles must be explicit unique supported roles")
        currency_value(self.currency)
        decimal_value(self.amount_limit, "actor amount limit")


@dataclass(frozen=True)
class DecisionSnapshot:
    canonical_json: str
    snapshot_hash: str

    def __post_init__(self):
        try:
            data = json.loads(self.canonical_json)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid snapshot JSON") from exc
        if _canonical(data) != self.canonical_json or hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest() != self.snapshot_hash:
            raise ValueError("snapshot is not canonical or hash does not match")
        expected = {"format", "paper_only", "proposer_id", "as_of", "expires_at", "amount", "currency", "versions", "economic_inputs"}
        if not isinstance(data, dict) or set(data) != expected or data["format"] != "paper-decision-v1" or data["paper_only"] is not True:
            raise ValueError("unsupported paper decision format")
        identifier(data["proposer_id"], "proposer_id")
        currency_value(data["currency"])
        decimal_value(data["amount"], "decision amount")
        if utc_instant(data["expires_at"]) <= utc_instant(data["as_of"]):
            raise ValueError("decision expiry must follow its as-of")
        versions = data["versions"]
        if not isinstance(versions, dict) or not {"schema", "policy", "model", "data"} <= set(versions):
            raise ValueError("schema, policy, model and data versions required")
        for key, value in versions.items():
            identifier(key, "version key")
            identifier(value, "version value")
        if not isinstance(data["economic_inputs"], dict):
            raise ValueError("economic inputs must be an explicit JSON object")

    @classmethod
    def create(cls, *, proposer_id: str, as_of: str, expires_at: str, amount: str,
               currency: str, versions: Mapping[str, str], economic_inputs: dict):
        payload = dict(format="paper-decision-v1", paper_only=True, proposer_id=proposer_id,
            as_of=as_of, expires_at=expires_at, amount=amount, currency=currency,
            versions=dict(versions), economic_inputs=economic_inputs)
        canonical = _canonical(payload)
        return cls(canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest())

    def to_dict(self) -> dict:
        # A new detached object on every call; later input mutations cannot alter the hash.
        return json.loads(self.canonical_json)

    def assert_current(self, *, now: str, active_versions: Mapping[str, str]) -> dict:
        data = self.to_dict()
        if not utc_instant(data["as_of"]) <= utc_instant(now) < utc_instant(data["expires_at"]):
            raise ValueError("decision is future-dated or expired")
        if dict(active_versions) != data["versions"]:
            raise ValueError("decision versions are stale; approvals invalidated")
        return data


@dataclass(frozen=True)
class Approval:
    snapshot_hash: str
    actor_id: str
    role: str
    approved_at: str
    expires_at: str
    currency: str
    amount_limit: str

    def __post_init__(self):
        identifier(self.snapshot_hash, "snapshot_hash")
        identifier(self.actor_id, "actor_id")
        if self.role not in APPROVER_ROLES:
            raise ValueError("approval requires a supported approval role")
        currency_value(self.currency)
        decimal_value(self.amount_limit, "approval amount limit")
        if utc_instant(self.expires_at) <= utc_instant(self.approved_at):
            raise ValueError("approval expiry must follow approval time")


def approve_snapshot(snapshot: DecisionSnapshot, actor: Actor, *, role: str, now: str,
                     expires_at: str, active_versions: Mapping[str, str]) -> Approval:
    data = snapshot.assert_current(now=now, active_versions=active_versions)
    if role not in actor.roles or role not in APPROVER_ROLES or actor.actor_id == data["proposer_id"]:
        raise ValueError("proposer cannot approve; independent approval role required")
    if actor.currency != data["currency"] or decimal_value(actor.amount_limit, "limit") < decimal_value(data["amount"], "amount"):
        raise ValueError("actor currency or amount limit cannot approve this decision")
    if utc_instant(expires_at) > utc_instant(data["expires_at"]):
        raise ValueError("approval cannot outlive decision")
    return Approval(snapshot.snapshot_hash, actor.actor_id, role, now, expires_at, actor.currency, actor.amount_limit)


def validate_approvals(snapshot: DecisionSnapshot, approvals: tuple[Approval, ...], *,
                       now: str, active_versions: Mapping[str, str]) -> None:
    data = snapshot.assert_current(now=now, active_versions=active_versions)
    if len(approvals) != 2 or {approval.role for approval in approvals} != APPROVER_ROLES or len({approval.actor_id for approval in approvals}) != 2:
        raise ValueError("two distinct risk and treasury approvers required")
    for approval in approvals:
        if approval.snapshot_hash != snapshot.snapshot_hash or approval.actor_id == data["proposer_id"]:
            raise ValueError("approval is not independent or binds a different decision")
        if not utc_instant(data["as_of"]) <= utc_instant(approval.approved_at) <= utc_instant(now) < utc_instant(approval.expires_at) or utc_instant(approval.expires_at) > utc_instant(data["expires_at"]):
            raise ValueError("approval is future-dated or expired")
        if approval.currency != data["currency"] or decimal_value(approval.amount_limit, "limit") < decimal_value(data["amount"], "amount"):
            raise ValueError("approval currency or limit mismatch")


@dataclass(frozen=True)
class PaperLeg:
    leg_id: str
    state: str

    def __post_init__(self):
        identifier(self.leg_id, "leg_id")
        if self.state not in {"paper_pending", "unknown", "matched", "failed"}:
            raise ValueError("unknown paper leg state")


@dataclass(frozen=True)
class PaperIntent:
    economic_intent_id: str
    snapshot: DecisionSnapshot
    state: str = "draft"
    hold_ids: tuple[str, ...] = ()
    approvals: tuple[Approval, ...] = ()
    legs: tuple[PaperLeg, ...] = ()
    reconciliation_evidence_id: str | None = None
    reconciler_id: str | None = None
    submitted_at: str | None = None
    reconciled_at: str | None = None
    cancellation_reason_id: str | None = None

    def __post_init__(self):
        identifier(self.economic_intent_id, "economic_intent_id")
        if not isinstance(self.snapshot, DecisionSnapshot) or self.state not in INTENT_STATES:
            raise ValueError("unknown paper intent state")
        if not isinstance(self.hold_ids, tuple) or len(set(self.hold_ids)) != len(self.hold_ids):
            raise ValueError("hold identifiers must be unique immutable tuple")
        for hold in self.hold_ids:
            identifier(hold, "hold_id")
        if not isinstance(self.approvals, tuple) or not isinstance(self.legs, tuple):
            raise ValueError("intent records must be immutable tuples")


class PaperJournal:
    """Process-local linearizable paper state; not a durable institutional outbox."""

    def __init__(self):
        self._lock = threading.RLock()
        self._intents: dict[str, PaperIntent] = {}
        self._hold_owners: dict[str, str] = {}

    def create(self, economic_intent_id: str, snapshot: DecisionSnapshot) -> PaperIntent:
        with self._lock:
            existing = self._intents.get(economic_intent_id)
            if existing:
                if existing.snapshot.snapshot_hash != snapshot.snapshot_hash:
                    raise ValueError("economic intent already exists with a different immutable decision")
                return existing
            intent = PaperIntent(economic_intent_id, snapshot)
            self._intents[economic_intent_id] = intent
            return intent

    def get(self, economic_intent_id: str) -> PaperIntent:
        with self._lock:
            if economic_intent_id not in self._intents:
                raise ValueError("unknown economic intent")
            return self._intents[economic_intent_id]

    def hold(self, economic_intent_id: str, hold_ids: tuple[str, ...]) -> PaperIntent:
        with self._lock:
            intent = self.get(economic_intent_id)
            if intent.state == "held" and intent.hold_ids == hold_ids:
                return intent
            if intent.state != "draft" or not hold_ids:
                raise ValueError("only a draft can acquire explicit holds")
            updated = replace(intent, state="held", hold_ids=hold_ids)
            if any(hold in self._hold_owners for hold in hold_ids):
                raise ValueError("hold already belongs to another economic intent")
            for hold in hold_ids:
                self._hold_owners[hold] = economic_intent_id
            self._intents[economic_intent_id] = updated
            return updated

    def approve(self, economic_intent_id: str, actor: Actor, *, role: str, now: str,
                expires_at: str, active_versions: Mapping[str, str]) -> PaperIntent:
        with self._lock:
            intent = self.get(economic_intent_id)
            if intent.state not in {"held", "approved"}:
                raise ValueError("intent must hold its resources before approval")
            approval = approve_snapshot(intent.snapshot, actor, role=role, now=now, expires_at=expires_at, active_versions=active_versions)
            if any(item.actor_id == actor.actor_id or item.role == role for item in intent.approvals):
                raise ValueError("duplicate actor or approval role")
            approvals = (*intent.approvals, approval)
            state = "held"
            if len(approvals) == 2:
                validate_approvals(intent.snapshot, approvals, now=now, active_versions=active_versions)
                state = "approved"
            updated = replace(intent, approvals=approvals, state=state)
            self._intents[economic_intent_id] = updated
            return updated

    def submit_paper(self, economic_intent_id: str, leg_ids: tuple[str, ...], *, now: str,
                     active_versions: Mapping[str, str]) -> PaperIntent:
        with self._lock:
            intent = self.get(economic_intent_id)
            if intent.state in {"paper_submitted", "unknown", "reconciled"}:
                if tuple(leg.leg_id for leg in intent.legs) != leg_ids:
                    raise ValueError("submitted economic intent cannot mutate paper legs")
                return intent
            if intent.state != "approved" or not leg_ids or len(set(leg_ids)) != len(leg_ids):
                raise ValueError("approved intent and explicit unique paper legs required")
            validate_approvals(intent.snapshot, intent.approvals, now=now, active_versions=active_versions)
            updated = replace(intent, state="paper_submitted", legs=tuple(PaperLeg(key, "paper_pending") for key in leg_ids), submitted_at=now)
            self._intents[economic_intent_id] = updated
            return updated

    def mark_unknown(self, economic_intent_id: str, leg_id: str) -> PaperIntent:
        with self._lock:
            intent = self.get(economic_intent_id)
            if intent.state not in {"paper_submitted", "unknown"} or leg_id not in {leg.leg_id for leg in intent.legs}:
                raise ValueError("unknown state requires a submitted paper leg")
            updated = replace(intent, state="unknown", legs=tuple(replace(leg, state="unknown") if leg.leg_id == leg_id else leg for leg in intent.legs))
            self._intents[economic_intent_id] = updated  # All holds intentionally survive.
            return updated

    def reconcile(self, economic_intent_id: str, outcomes: Mapping[str, str], actor: Actor, *,
                  evidence_id: str, now: str, release_hold_ids: tuple[str, ...] = ()) -> PaperIntent:
        with self._lock:
            intent = self.get(economic_intent_id)
            if intent.state not in {"paper_submitted", "unknown"} or "reconciler" not in actor.roles:
                raise ValueError("submitted intent and independent reconciler required")
            excluded = {intent.snapshot.to_dict()["proposer_id"], *(approval.actor_id for approval in intent.approvals)}
            if actor.actor_id in excluded or set(outcomes) != {leg.leg_id for leg in intent.legs}:
                raise ValueError("reconciliation must be independent and cover every paper leg")
            identifier(evidence_id, "reconciliation evidence")
            if utc_instant(now) < utc_instant(intent.submitted_at):
                raise ValueError("reconciliation cannot precede paper submission")
            if any(state not in {"matched", "failed", "unknown"} for state in outcomes.values()):
                raise ValueError("unsupported paper reconciliation outcome")
            if len(set(release_hold_ids)) != len(release_hold_ids) or not set(release_hold_ids) <= set(intent.hold_ids):
                raise ValueError("can release only unique holds owned by this intent")
            unknown = "unknown" in outcomes.values()
            if unknown and release_hold_ids:
                raise ValueError("uncertain external effects must retain every hold")
            legs = tuple(PaperLeg(leg.leg_id, outcomes[leg.leg_id]) for leg in intent.legs)
            updated = replace(intent, state="unknown" if unknown else "reconciled", legs=legs,
                hold_ids=tuple(hold for hold in intent.hold_ids if hold not in release_hold_ids), reconciliation_evidence_id=evidence_id,
                reconciler_id=actor.actor_id, reconciled_at=now)
            for hold in release_hold_ids:
                del self._hold_owners[hold]
            self._intents[economic_intent_id] = updated
            return updated

    def cancel(self, economic_intent_id: str, *, actor_id: str, reason_id: str) -> PaperIntent:
        with self._lock:
            intent = self.get(economic_intent_id)
            identifier(reason_id, "cancellation reason")
            if intent.state not in {"draft", "held", "approved"} or actor_id != intent.snapshot.to_dict()["proposer_id"]:
                raise ValueError("only proposer can cancel before paper submission; uncertain effects require reconciliation")
            for hold in intent.hold_ids:
                del self._hold_owners[hold]
            updated = replace(intent, state="cancelled", hold_ids=(), cancellation_reason_id=reason_id)
            self._intents[economic_intent_id] = updated
            return updated

    def to_dict(self) -> dict:
        with self._lock:
            return {"format": "paper-journal-v1", "paper_only": True, "durable": False,
                "intents": [{"economic_intent_id": intent.economic_intent_id, "state": intent.state,
                    "snapshot_hash": intent.snapshot.snapshot_hash, "snapshot": intent.snapshot.to_dict(),
                    "hold_ids": list(intent.hold_ids), "approvals": [asdict(item) for item in intent.approvals],
                    "legs": [asdict(leg) for leg in intent.legs], "reconciliation_evidence_id": intent.reconciliation_evidence_id,
                    "reconciler_id": intent.reconciler_id, "submitted_at": intent.submitted_at,
                    "reconciled_at": intent.reconciled_at, "cancellation_reason_id": intent.cancellation_reason_id}
                    for intent in sorted(self._intents.values(), key=lambda item: item.economic_intent_id)]}
