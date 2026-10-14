"""Explicit physical units and half-open paper positions; no asset verification."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, localcontext
import json
import re
from typing import Any

from compute_pricing.control.capacity import CapacityLot, Maintenance, Reservation, validate_capacity
from compute_pricing.control.reporting.store import canonical_document, SnapshotStoreError
from compute_pricing.control.treasury._validation import calculation_precision, currency_value, decimal_value, utc_instant

SCHEMA_VERSION = "paper-inventory/1.0"
MAX_STATE_BYTES = 1024 * 1024
MAX_SITES, MAX_LOTS, MAX_POSITIONS = 128, 256, 512
MAX_UNITS, MAX_UNIT_REFERENCES = 4096, 8192
COUNTS = ("available", "reserved", "sold", "maintenance", "unavailable", "unsold", "total")


class InventoryError(ValueError):
    def __init__(self, code: str, *, current_revision: int | None = None):
        self.code, self.current_revision = code, current_revision
        super().__init__(code)


def empty_state() -> dict:
    return {"schema_version": SCHEMA_VERSION, "sites": [], "lots": [], "positions": []}


def _id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value):
        raise InventoryError("invalid_inventory_identifier")
    return value


def _text(value: Any, maximum: int = 200) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise InventoryError("invalid_inventory_label")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise InventoryError("invalid_inventory_label") from None
    return value


def _record(value: Any, required: set[str], optional: set[str]) -> dict:
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise InventoryError("invalid_inventory_record_fields")
    return value


def _extensions(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InventoryError("invalid_inventory_extensions")
    try:
        return json.loads(canonical_document(value, max_bytes=16384))
    except SnapshotStoreError:
        raise InventoryError("invalid_inventory_extensions") from None


def _units(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > MAX_UNITS:
        raise InventoryError("invalid_inventory_unit_ids")
    result = [_id(item) for item in value]
    if len(set(result)) != len(result):
        raise InventoryError("duplicate_inventory_unit")
    return sorted(result)


def _interval(row: dict) -> tuple[str, str]:
    try:
        if utc_instant(row["end_at"]) <= utc_instant(row["start_at"]):
            raise ValueError
    except (ValueError, TypeError):
        raise InventoryError("invalid_inventory_interval") from None
    return row["start_at"], row["end_at"]


def _money(value: Any, unit: str) -> dict | None:
    if value is None:
        return None
    row = _record(value, {"amount", "currency", "unit"}, set())
    try:
        decimal_value(row["amount"], "inventory amount")
        currency_value(row["currency"])
    except (ValueError, TypeError):
        raise InventoryError("invalid_inventory_money") from None
    if row["unit"] != unit:
        raise InventoryError("invalid_inventory_value_unit")
    return dict(row)


def validate_inventory(value: Any) -> dict:
    state = _record(value, {"schema_version", "sites", "lots", "positions"}, {"provenance"})
    if state["schema_version"] != SCHEMA_VERSION:
        raise InventoryError("unsupported_inventory_schema")
    if "provenance" in state and state["provenance"] not in ("declared", "synthetic"):
        raise InventoryError("invalid_inventory_provenance")
    for name, limit in (("sites", MAX_SITES), ("lots", MAX_LOTS), ("positions", MAX_POSITIONS)):
        if not isinstance(state[name], list) or len(state[name]) > limit:
            raise InventoryError("inventory_record_budget")
    try:
        canonical_document(state, max_bytes=MAX_STATE_BYTES)
    except SnapshotStoreError:
        raise InventoryError("inventory_state_budget_or_invalid_json") from None
    sites, lots, positions = [], [], []
    site_ids, lot_ids, position_ids, unit_kinds = set(), set(), set(), {}
    references = 0
    for raw in state["sites"]:
        row = _record(raw, {"site_id"}, {"name", "country_code", "latitude", "longitude", "extensions"})
        key = _id(row["site_id"])
        if key in site_ids:
            raise InventoryError("duplicate_inventory_site")
        site_ids.add(key)
        country = row.get("country_code")
        if country is not None and (not isinstance(country, str) or not re.fullmatch(r"[A-Z]{2}", country)):
            raise InventoryError("invalid_inventory_country")
        latitude, longitude = row.get("latitude"), row.get("longitude")
        if (latitude is None) != (longitude is None):
            raise InventoryError("inventory_coordinates_must_be_paired")
        if latitude is not None:
            try:
                if decimal_value(latitude, "latitude", nonnegative=False).copy_abs() > 90 or decimal_value(longitude, "longitude", nonnegative=False).copy_abs() > 180:
                    raise ValueError
            except (ValueError, TypeError):
                raise InventoryError("invalid_inventory_coordinates") from None
        sites.append({"site_id": key, "name": _text(row.get("name")), "country_code": country,
            "latitude": latitude, "longitude": longitude, "extensions": _extensions(row.get("extensions"))})
    capacity_lots = []
    for raw in state["lots"]:
        row = _record(raw, {"lot_id", "site_id", "unit_kind", "unit_ids", "start_at", "end_at"}, {"hardware_model", "purchase_value", "extensions"})
        key, site = _id(row["lot_id"]), _id(row["site_id"])
        if key in lot_ids or site not in site_ids:
            raise InventoryError("duplicate_or_unknown_inventory_lot_site")
        lot_ids.add(key)
        units, interval = _units(row["unit_ids"]), _interval(row)
        kind = row["unit_kind"]
        if kind not in ("gpu", "node", "cpu", "accelerator"):
            raise InventoryError("invalid_inventory_unit_kind")
        for unit in units:
            if unit in unit_kinds and unit_kinds[unit] != kind:
                raise InventoryError("inventory_unit_kind_changed")
            unit_kinds[unit] = kind
        references += len(units)
        if len(unit_kinds) > MAX_UNITS or references > MAX_UNIT_REFERENCES:
            raise InventoryError("inventory_unit_budget")
        normalized = {"lot_id": key, "site_id": site, "unit_kind": kind, "unit_ids": units,
            "start_at": interval[0], "end_at": interval[1], "hardware_model": _text(row.get("hardware_model")),
            "purchase_value": _money(row.get("purchase_value"), "lot_total"), "extensions": _extensions(row.get("extensions"))}
        capacity_lots.append(CapacityLot(key, site, kind, tuple(units), *interval))
        lots.append(normalized)
    reservations, maintenance = [], []
    for raw in state["positions"]:
        row = _record(raw, {"position_id", "lot_id", "unit_ids", "status", "start_at", "end_at"}, {"contract_id", "sale_value", "extensions"})
        key, lot = _id(row["position_id"]), _id(row["lot_id"])
        if key in position_ids:
            raise InventoryError("duplicate_inventory_position")
        position_ids.add(key)
        units, interval = _units(row["unit_ids"]), _interval(row)
        references += len(units)
        if references > MAX_UNIT_REFERENCES:
            raise InventoryError("inventory_unit_budget")
        status = row["status"]
        if status not in ("reserved", "sold", "maintenance"):
            raise InventoryError("invalid_inventory_position_status")
        money = _money(row.get("sale_value"), "position_total")
        if money is not None and status != "sold":
            raise InventoryError("inventory_sale_value_requires_sold_status")
        normalized = {"position_id": key, "lot_id": lot, "unit_ids": units, "status": status,
            "start_at": interval[0], "end_at": interval[1], "contract_id": _text(row.get("contract_id")),
            "sale_value": money, "extensions": _extensions(row.get("extensions"))}
        if status == "maintenance":
            maintenance.append(Maintenance(key, lot, tuple(units), *interval))
        else:
            reservations.append(Reservation(key, key, lot, tuple(units), *interval))
        positions.append(normalized)
    try:
        validate_capacity(capacity_lots, reservations, maintenance)
    except ValueError:
        raise InventoryError("inventory_capacity_conflict") from None
    normalized = {"schema_version": SCHEMA_VERSION, "sites": sorted(sites, key=lambda row: row["site_id"]),
        "lots": sorted(lots, key=lambda row: row["lot_id"]), "positions": sorted(positions, key=lambda row: row["position_id"])}
    # Absence stays absent so prior normalized revisions and hashes remain valid.
    if "provenance" in state:
        normalized["provenance"] = state["provenance"]
    try:
        canonical_document(normalized, max_bytes=MAX_STATE_BYTES)
    except SnapshotStoreError:
        raise InventoryError("inventory_state_budget_or_invalid_json") from None
    return normalized


def _counts() -> dict:
    return dict.fromkeys(COUNTS, 0)


def _increment(group: dict, kind: str, status: str):
    counts = group.setdefault(kind, _counts())
    counts[status] += 1
    counts["total"] += 1
    if status in ("available", "reserved", "maintenance"):
        counts["unsold"] += 1


def evaluate_inventory(value: Any, *, as_of: str | None = None) -> dict:
    state = validate_inventory(value)
    as_of = as_of if as_of is not None else dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        utc_instant(as_of)
    except ValueError:
        raise InventoryError("invalid_inventory_as_of") from None
    units, timeline, lots, sites = {}, [], [], {row["site_id"]: {**row, "by_unit_kind": {}, "active_lot_ids": []} for row in state["sites"]}
    positions = {}
    for position in state["positions"]:
        positions.setdefault(position["lot_id"], []).append(position)
    for lot in state["lots"]:
        active = lot["start_at"] <= as_of < lot["end_at"]
        counts, entries = _counts(), positions.get(lot["lot_id"], [])
        active_positions = {unit: row for row in entries if row["start_at"] <= as_of < row["end_at"] for unit in row["unit_ids"]}
        for unit in lot["unit_ids"]:
            if unit not in units:
                units[unit] = {"unit_id": unit, "unit_kind": lot["unit_kind"], "lot_id": None, "site_id": None, "status": "unavailable", "position_id": None}
            status = active_positions[unit]["status"] if active and unit in active_positions else "available" if active else "unavailable"
            counts[status] += 1
            counts["total"] += 1
            if status in ("available", "reserved", "maintenance"):
                counts["unsold"] += 1
            if active:
                units[unit] = {"unit_id": unit, "unit_kind": lot["unit_kind"], "lot_id": lot["lot_id"], "site_id": lot["site_id"], "status": status,
                    "position_id": active_positions[unit]["position_id"] if unit in active_positions else None}
                _increment(sites[lot["site_id"]]["by_unit_kind"], lot["unit_kind"], status)
        if active:
            sites[lot["site_id"]]["active_lot_ids"].append(lot["lot_id"])
        lots.append({**lot, "active": active, "counts": counts, "positions": entries})
        for entry in ({"kind": "availability", "position_id": None, **lot}, *({"kind": row["status"], **row} for row in entries)):
            timeline.append({"kind": entry["kind"], "position_id": entry["position_id"], "lot_id": lot["lot_id"], "site_id": lot["site_id"],
                "unit_kind": lot["unit_kind"], "unit_ids": entry["unit_ids"], "start_at": entry["start_at"], "end_at": entry["end_at"],
                "active_at_as_of": entry["start_at"] <= as_of < entry["end_at"]})
    grouped, unlocated_units = {}, []
    for unit in units.values():
        _increment(grouped, unit["unit_kind"], unit["status"])
        site = sites.get(unit["site_id"])
        if site is None or site["latitude"] is None:
            unlocated_units.append(unit["unit_id"])
    amounts = [row[field]["amount"] for field, rows in (("purchase_value", state["lots"]), ("sale_value", state["positions"])) for row in rows if row[field] is not None]
    exposure = {"purchase_values_by_currency": {}, "sold_position_values_by_currency": {}, "basis": "full_declared_records_not_prorated_or_market_valued"}
    with localcontext() as context:
        context.prec = calculation_precision(amounts, len(amounts))
        for field, rows, label in (("purchase_value", state["lots"], "purchase_values_by_currency"), ("sale_value", state["positions"], "sold_position_values_by_currency")):
            sums = {}
            for row in rows:
                money = row[field]
                if money is not None:
                    sums[money["currency"]] = sums.get(money["currency"], Decimal(0)) + Decimal(money["amount"])
            exposure[label] = {currency: format(amount, "f") for currency, amount in sorted(sums.items())}
    site_rows = list(sites.values())
    missing_contracts = sorted(row["position_id"] for row in state["positions"]
                               if row["status"] == "sold" and row["contract_id"] is None)
    provenance = state.get("provenance", "unspecified")
    return {"schema_version": SCHEMA_VERSION, "as_of": as_of, "state": state, "summary": {"by_unit_kind": grouped,
        "unsold_definition": "available_plus_reserved_plus_maintenance_within_active_availability", "unavailable_definition": "physical_units_without_availability_at_as_of"},
        "sites": site_rows, "located_sites": [row for row in site_rows if row["latitude"] is not None], "unlocated_sites": [row for row in site_rows if row["latitude"] is None],
        "unlocated_unit_ids": sorted(unlocated_units), "lots": lots, "units": sorted(units.values(), key=lambda row: row["unit_id"]),
        "timeline": sorted(timeline, key=lambda row: (row["start_at"], row["lot_id"], row["position_id"] or "")), "monetary_exposure": exposure,
        "provenance": provenance, "provenance_verification": "caller_declared_unverified",
        "position_evidence": {"sold_position_ids_without_contract": missing_contracts, "contract_references_verified": False},
        "execution_enabled": False, "paper_only": True, "asset_verification": "caller_declared_unverified", "warnings": [
            "sold_and_signed_status_do_not_authorize_external_execution", "unit_kinds_are_not_interchangeable",
            "declared_values_are_not_cash_flows_revenue_or_current_market_marks", "extensions_preserved_but_unpriced",
            "provenance_declarations_do_not_verify_assets_or_contracts",
            *(["synthetic_inventory_is_preview_only"] if provenance == "synthetic" else []),
            *(["inventory_provenance_declaration_required_for_new_writes"] if provenance == "unspecified" else []),
            *(["sold_positions_without_contract_reference"] if missing_contracts else [])]}
