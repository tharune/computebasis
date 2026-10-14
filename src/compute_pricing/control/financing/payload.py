"""Strict JSON adapter for borrowing-base and waterfall evaluation."""

from dataclasses import asdict, fields
from decimal import Decimal
from .receivables import BorrowingFacility, BorrowingPolicy, Pledge, Receivable, ReceivableExclusion, evaluate_borrowing_base
from .waterfall import Collection, WaterfallPolicy, evaluate_waterfall


def _record(record, cls):
    if not isinstance(record, dict) or set(record) - {field.name for field in fields(cls)}:
        raise ValueError(f"{cls.__name__} requires known named fields")
    values = dict(record)
    if cls is Receivable:
        if not isinstance(values.get("exclusions"), list):
            raise ValueError("receivable exclusions must be an explicit JSON array")
        values["exclusions"] = tuple(_record(item, ReceivableExclusion) for item in values["exclusions"])
    if cls is WaterfallPolicy:
        if not isinstance(values.get("priority"), list):
            raise ValueError("waterfall priority must be an explicit JSON array")
        values["priority"] = tuple(values["priority"])
    try:
        return cls(**values)
    except TypeError as exc:
        raise ValueError(f"{cls.__name__} has missing or invalid fields") from exc


def _json_money(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_money(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_money(item) for item in value]
    return value


def evaluate_financing_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("financing payload must be a JSON object")
    operation = payload.get("operation")
    common = {"operation", "receivables", "pledges", "facility", "policy", "as_of", "pledge_registry_evidence_id"}
    extra = {"collections", "opening_cash", "start_date", "end_date", "mode"} if operation == "waterfall" else set()
    if not isinstance(operation, str) or operation not in {"borrowing_base", "waterfall"} or set(payload) != common | extra:
        raise ValueError("financing payload has missing or unregistered fields/operation")
    for field in ("receivables", "pledges", *(("collections",) if operation == "waterfall" else ())):
        if not isinstance(payload[field], list):
            raise ValueError(f"{field} must be a JSON array")
    receivables = tuple(_record(record, Receivable) for record in payload["receivables"])
    pledges = tuple(_record(record, Pledge) for record in payload["pledges"])
    facility = _record(payload["facility"], BorrowingFacility)
    policy = _record(payload["policy"], WaterfallPolicy if operation == "waterfall" else BorrowingPolicy)
    if operation == "borrowing_base":
        result = evaluate_borrowing_base(receivables, pledges, facility, policy, as_of=payload["as_of"], pledge_registry_evidence_id=payload["pledge_registry_evidence_id"])
    else:
        collections = tuple(_record(record, Collection) for record in payload["collections"])
        result = evaluate_waterfall(receivables, pledges, facility, policy, collections,
            **{field: payload[field] for field in {"as_of", "pledge_registry_evidence_id", *extra} - {"collections"}})
    return {"model_version": "receivable-financing-v1", "operation": operation, "policy_version": policy.policy_version,
            "as_of": payload["as_of"], **_json_money(asdict(result))}
