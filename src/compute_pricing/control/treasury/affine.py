"""Conservative cash-only inversion of explicitly supplied price coefficients."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, localcontext
from typing import Sequence
from ._validation import calculation_precision, decimal_value, identifier, iso_date


@dataclass(frozen=True)
class AffineCashPoint:
    point_id: str
    on: str
    base_free_cash: str
    purchase_coefficient: str

    def __post_init__(self):
        identifier(self.point_id, "point_id")
        iso_date(self.on)
        decimal_value(self.base_free_cash, "base_free_cash", nonnegative=False)
        decimal_value(self.purchase_coefficient, "purchase_coefficient")


@dataclass(frozen=True)
class AffineCashCap:
    feasible_at_zero: bool
    maximum_purchase_price: Decimal | None
    binding_point_id: str | None
    binding_date: str | None


def affine_purchase_price_cap(points: Sequence[AffineCashPoint], *, minimum_cash: str,
                              maximum_search_price: str) -> AffineCashCap:
    """Bound p >= 0 using cash_i(p) = base_i - coefficient_i * p.

    Each coefficient must include that date's cumulative cash effect. Supply
    EVERY daily/major settlement point, reserves and baseline shared cash.
    This cannot account for nonlinear borrowing, refund optionality or FX;
    those paths require full dated reevaluation. No unused facility is assumed.
    """
    if not points or any(not isinstance(point, AffineCashPoint) for point in points) or len({point.point_id for point in points}) != len(points):
        raise ValueError("nonempty uniquely identified cash points required")
    floor = decimal_value(minimum_cash, "minimum_cash")
    maximum = decimal_value(maximum_search_price, "maximum_search_price")
    with localcontext() as context:
        context.prec = calculation_precision([minimum_cash, maximum_search_price, *[value for point in points for value in (point.base_free_cash, point.purchase_coefficient)]], len(points))
        context.rounding = ROUND_FLOOR
        cap, binding = maximum, None
        for point in points:
            base = decimal_value(point.base_free_cash, "base_free_cash", nonnegative=False)
            coefficient = decimal_value(point.purchase_coefficient, "purchase_coefficient")
            if base < floor:
                return AffineCashCap(False, None, point.point_id, point.on)
            if coefficient > 0:
                limit = (base - floor) / coefficient
                if limit < cap:
                    cap, binding = limit, point
        return AffineCashCap(True, cap, binding.point_id if binding else None, binding.on if binding else None)
