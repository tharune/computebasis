"""Pure physical-unit capacity validation over half-open UTC intervals.

The caller supplies the complete authoritative active ledger. Database locking,
hold expiry, leases and external-effect reconciliation belong in the store.
An in-memory check by itself is not a concurrency-safe reservation operation.
"""

from dataclasses import dataclass
from typing import Sequence
from compute_pricing.control.treasury._validation import identifier, utc_instant


def _units(values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or not values:
        raise ValueError("physical unit identifiers must be a nonempty unique tuple")
    for value in values:
        identifier(value, "physical unit")
    if len(set(values)) != len(values):
        raise ValueError("physical unit identifiers must be a nonempty unique tuple")


def _interval(start_at: str, end_at: str) -> None:
    if utc_instant(end_at) <= utc_instant(start_at):
        raise ValueError("capacity intervals must be nonempty and half-open")


@dataclass(frozen=True)
class CapacityLot:
    lot_id: str
    site_id: str
    unit_kind: str
    unit_ids: tuple[str, ...]
    start_at: str
    end_at: str

    def __post_init__(self):
        identifier(self.lot_id, "lot_id")
        identifier(self.site_id, "site_id")
        if self.unit_kind not in {"gpu", "node", "cpu", "accelerator"}:
            raise ValueError("unsupported capacity unit kind")
        _units(self.unit_ids)
        _interval(self.start_at, self.end_at)


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    allocation_id: str
    lot_id: str
    unit_ids: tuple[str, ...]
    start_at: str
    end_at: str

    def __post_init__(self):
        identifier(self.reservation_id, "reservation_id")
        identifier(self.allocation_id, "allocation_id")
        identifier(self.lot_id, "lot_id")
        _units(self.unit_ids)
        _interval(self.start_at, self.end_at)


@dataclass(frozen=True)
class Maintenance:
    maintenance_id: str
    lot_id: str
    unit_ids: tuple[str, ...]
    start_at: str
    end_at: str

    def __post_init__(self):
        identifier(self.maintenance_id, "maintenance_id")
        identifier(self.lot_id, "lot_id")
        _units(self.unit_ids)
        _interval(self.start_at, self.end_at)


@dataclass(frozen=True)
class CapacityReport:
    reservation_unit_seconds: dict[str, int]
    maintenance_unit_seconds: dict[str, int]
    remaining_unit_seconds: dict[str, int]


def _overlap(left, right) -> bool:
    return max(left.start_at, right.start_at) < min(left.end_at, right.end_at)


def validate_capacity(lots: Sequence[CapacityLot], reservations: Sequence[Reservation],
                      maintenance: Sequence[Maintenance] = ()) -> CapacityReport:
    """Reject double sold physical units, duplicate lots and maintenance overlap."""
    by_lot = {}
    for lot in lots:
        if not isinstance(lot, CapacityLot) or lot.lot_id in by_lot:
            raise ValueError("duplicate or invalid capacity lot")
        for prior in by_lot.values():
            if set(lot.unit_ids) & set(prior.unit_ids) and _overlap(lot, prior):
                raise ValueError("physical unit appears in overlapping supply lots")
        by_lot[lot.lot_id] = lot
    entries, entry_ids, reservation_seconds, maintenance_seconds = [], set(), {}, {}
    remaining = {lot.lot_id: int((utc_instant(lot.end_at) - utc_instant(lot.start_at)).total_seconds()) * len(lot.unit_ids) for lot in lots}
    for entry in (*reservations, *maintenance):
        if not isinstance(entry, (Reservation, Maintenance)):
            raise ValueError("invalid capacity entry")
        key = entry.reservation_id if isinstance(entry, Reservation) else entry.maintenance_id
        if key in entry_ids:
            raise ValueError("duplicate capacity entry identifier")
        entry_ids.add(key)
        if entry.lot_id not in by_lot:
            raise ValueError("capacity entry refers to unknown lot")
        lot = by_lot[entry.lot_id]
        if not set(entry.unit_ids) <= set(lot.unit_ids):
            raise ValueError("reservation contains units outside supply lot")
        if entry.start_at < lot.start_at or entry.end_at > lot.end_at:
            raise ValueError("reservation exceeds supply availability interval")
        for prior in entries:
            if set(entry.unit_ids) & set(prior.unit_ids) and _overlap(entry, prior):
                raise ValueError("physical capacity overlap between reservations/maintenance")
        entries.append(entry)
        seconds = int((utc_instant(entry.end_at) - utc_instant(entry.start_at)).total_seconds()) * len(entry.unit_ids)
        remaining[entry.lot_id] -= seconds
        (reservation_seconds if isinstance(entry, Reservation) else maintenance_seconds)[key] = seconds
    return CapacityReport(reservation_seconds, maintenance_seconds, remaining)
