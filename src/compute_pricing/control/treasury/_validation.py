"""Exact, deliberately narrow validation for the offline financial core."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re

# Supported settlement currencies, not inferred FX or token conversions.
CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SGD", "HKD", "CNY", "INR", "KRW", "BRL", "MXN", "SEK", "NOK", "DKK", "PLN", "ZAR"})
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def decimal_value(value: str, field: str, *, nonnegative: bool = True) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value) or len(value) > 100:
        raise ValueError(f"{field} must be a finite, plain Decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {field}") from exc
    if not result.is_finite() or (nonnegative and result < 0):
        raise ValueError(f"{field} must be finite and nonnegative")
    return result


def iso_date(value: str, field: str = "date") -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError(f"{field} must be an ISO calendar date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc


def utc_instant(value: str, field: str = "instant") -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        raise ValueError(f"{field} must be a UTC second-resolution ISO instant")
    try:
        return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc


def identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{field} must be a nonempty bounded identifier")
    return value


def currency_value(value: str) -> str:
    if not isinstance(value, str) or value not in CURRENCIES:
        raise ValueError("currency must be an explicitly supported settlement currency")
    return value


def positive_integer(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def calculation_precision(values: list[str], operations: int = 1) -> int:
    """Preserve supplied money scales in sums/products; division is finite precision.

    Accepted input strings are bounded at 100 characters. Use sufficient local
    precision for large/small inputs together rather than silently discarding
    a small cash amount against a large balance. Extra headroom covers products,
    aggregations and the repeated interest calculations in the dated horizon.
    """
    integer_digits = max((len(value.lstrip("-").split(".")[0]) for value in values), default=1)
    fractional_digits = max((len(value.split(".")[1]) if "." in value else 0 for value in values), default=0)
    return max(38, 2 * (integer_digits + fractional_digits) + len(str(operations)) + 16)
