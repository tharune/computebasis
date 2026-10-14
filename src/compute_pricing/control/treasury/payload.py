"""Strict JSON-envelope adapter for the dated accounting API."""

from dataclasses import fields
from .cash import CashEvent, Facility, Reserve, evaluate_cash_schedule


def _record(record, cls):
    if not isinstance(record, dict) or set(record) - {field.name for field in fields(cls)}:
        raise ValueError(f"{cls.__name__} requires known named fields")
    try:
        return cls(**record)
    except TypeError as exc:
        raise ValueError(f"{cls.__name__} has missing or invalid fields") from exc


def evaluate_cash_payload(payload: dict):
    """No raw float conversion, default prices, source fallback or ignored terms."""
    if not isinstance(payload, dict):
        raise ValueError("cash payload must be a JSON object")
    required = {"events", "legal_entity_id", "cash_account_id", "currency", "opening_cash", "start_date", "end_date"}
    optional = {"reserves", "facility", "opening_deposits", "opening_prepaids", "opening_receivables", "opening_earned_for_release", "opening_payables", "opening_advances", "advance_terms"}
    if required - set(payload) or set(payload) - required - optional:
        raise ValueError("cash payload has missing or unregistered fields")
    if not isinstance(payload["events"], list):
        raise ValueError("cash events must be a JSON array")
    reserves = payload.get("reserves", [])
    if not isinstance(reserves, list):
        raise ValueError("reserves must be a JSON array")
    events = tuple(_record(record, CashEvent) for record in payload["events"])
    parsed_reserves = tuple(_record(record, Reserve) for record in reserves)
    facility = _record(payload["facility"], Facility) if payload.get("facility") is not None else None
    settings = {key: value for key, value in payload.items() if key not in {"events", "reserves", "facility"}}
    return evaluate_cash_schedule(events, reserves=parsed_reserves, facility=facility, **settings)
