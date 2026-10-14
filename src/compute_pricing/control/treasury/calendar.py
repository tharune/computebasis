"""Calendar helpers with explicit invoice triggers and no fixed-hour month."""

from datetime import date, timedelta
from decimal import Decimal
from ._validation import iso_date, positive_integer


def invoice_due_date(trigger_date: str, *, net_days: int, settlement_lag_days: int,
                     weekend_adjustment: str, holidays: tuple[str, ...] = ()) -> str:
    """Calendar-day net terms and lag, followed by the specified business rule.

    A caller must supply the actual contractual trigger. This function does not
    assume that signing, service delivery, acceptance and invoicing coincide.
    """
    trigger = iso_date(trigger_date, "trigger_date")
    for name, value in (("net_days", net_days), ("settlement_lag_days", settlement_lag_days)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative calendar-day integer")
    if weekend_adjustment not in {"none", "following", "preceding"}:
        raise ValueError("unsupported weekend adjustment")
    closed = {iso_date(day, "holiday") for day in holidays}
    try:
        result = trigger + timedelta(days=net_days + settlement_lag_days)
    except OverflowError as exc:
        raise ValueError("invoice lag leaves supported calendar") from exc
    if weekend_adjustment != "none":
        step = 1 if weekend_adjustment == "following" else -1
        while result.weekday() >= 5 or result in closed:
            try:
                result += timedelta(days=step)
            except OverflowError as exc:
                raise ValueError("business-day adjustment leaves supported calendar") from exc
    return result.isoformat()


def calendar_periods(start_date: str, end_date: str) -> tuple[tuple[str, str], ...]:
    """Split a half-open service interval at actual calendar-month boundaries."""
    start, end = iso_date(start_date), iso_date(end_date)
    if end <= start:
        raise ValueError("service end must follow service start")
    result = []
    cursor = start
    while cursor < end:
        boundary = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
        next_date = min(boundary, end)
        result.append((cursor.isoformat(), next_date.isoformat()))
        cursor = next_date
    return tuple(result)


def calendar_unit_hours(start_date: str, end_date: str, *, quantity: int) -> Decimal:
    """Whole UTC calendar days; sub-day metering requires timestamp evidence."""
    start, end = iso_date(start_date), iso_date(end_date)
    positive_integer(quantity, "quantity")
    if end <= start:
        raise ValueError("service end must follow service start")
    return Decimal((end - start).days * 24 * quantity)
