"""Shared exact financial arithmetic and strict JSON boundaries."""
from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any

from .domain import ValidationError, exact_decimal, utc_instant


def number(value: Any, name: str, *, positive=False, fraction=False) -> Decimal:
    try:
        result = exact_decimal(value, nonnegative=True)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValidationError(f"{name}: exact nonnegative decimal string required") from exc
    if result > Decimal("1000000000000000000000000") or positive and result <= 0 or fraction and result > 1:
        raise ValidationError(f"{name}: outside supported range")
    return result


def text_number(value: Decimal) -> str:
    if not value.is_finite():
        raise ArithmeticError("nonfinite financial result")
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def hours(start: str, end: str) -> Decimal:
    delta = utc_instant(end) - utc_instant(start)
    if delta.total_seconds() <= 0:
        raise ValidationError("interval: positive duration required")
    return (Decimal(delta.days * 86400 + delta.seconds)
            + Decimal(delta.microseconds) / Decimal(1000000)) / Decimal(3600)


def strict_json(raw: str | bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValidationError("duplicate JSON key")
            result[key] = value
        return result

    def reject(value):
        raise ValidationError("nonstandard JSON number")

    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            reject(value)
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject, parse_float=floating)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValidationError("invalid JSON input") from exc


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def calculation_precision(payload: Any) -> int:
    """Headroom for bounded exact inputs, factor products and large/small sums.

    Canonical financial fields admit at most 128 characters. Decimal divisions
    and transcendental age weights remain finite precision numerical results.
    """
    maximum_integer = maximum_fraction = count = 0
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
        elif isinstance(value, str) and len(value) <= 128 and re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
            integer, _, fraction = value.lstrip("-").partition(".")
            maximum_integer = max(maximum_integer, len(integer))
            maximum_fraction = max(maximum_fraction, len(fraction))
            count += 1
    return max(80, 8 * (maximum_integer + maximum_fraction) + len(str(count)) + 32)
