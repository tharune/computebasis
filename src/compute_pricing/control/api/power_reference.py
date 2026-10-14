"""Build a power scenario from retained, scoped electricity delivery intervals."""
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
import re

from ..domain import ValidationError, exact_decimal, utc_instant
from ..power import evaluate_power_payload
from ..power.cost import ROOT_FIELDS


def _select_rows(index, selection):
    begin, finish = utc_instant(selection["starts_at"]), utc_instant(selection["ends_at"])
    if begin >= finish:
        raise ValidationError("reference horizon must have positive duration")
    chosen = {}
    for row in index.get("catalog_records", []):
        if (row.get("source_id") != "energinet_day_ahead" or row.get("kind") != "energy_market_reference"
                or row.get("price_area") != selection["price_area"] or row.get("index_stale") is not False):
            continue
        first, last = utc_instant(row.get("starts_at")), utc_instant(row.get("ends_at"))
        if first < begin or last > finish:
            continue
        prices = row.get("native_prices")
        snapshot = row.get("snapshot_id")
        if (row.get("market") != "day_ahead" or row.get("native_unit") != "MWh"
                or type(row.get("interval_minutes")) is not int or row["interval_minutes"] != 15
                or last - first != timedelta(minutes=15)
                or first.minute % 15 or first.second or first.microsecond or last.microsecond
                or not isinstance(prices, Mapping) or set(prices) != {"EUR", "DKK"}
                or not isinstance(snapshot, str) or not re.fullmatch("[a-f0-9]{64}", snapshot)):
            raise ValidationError("retained electricity record does not match the native interval contract")
        checked = {currency: exact_decimal(value) for currency, value in prices.items()}
        period = (first, last)
        if period in chosen and checked != chosen[period][1]:
            raise ValidationError("conflicting retained delivery prices")
        chosen[period] = (row, checked)
    periods = sorted(chosen)
    if not periods or periods[0][0] != begin or periods[-1][1] != finish:
        raise ValidationError("current retained intervals do not cover the reference horizon")
    if any(left[1] != right[0] for left, right in zip(periods, periods[1:])):
        raise ValidationError("reference horizon contains a gap or overlapping interval")
    return [chosen[period] for period in periods]


def evaluate_reference_power(payload, index):
    if not isinstance(payload, Mapping) or set(payload) != {"profile", "reference"}:
        raise ValidationError("profile and reference selection required")
    profile, selection = payload["profile"], payload["reference"]
    selection_fields = {"source_id", "price_area", "currency", "starts_at", "ends_at", "utilization"}
    if not isinstance(profile, Mapping) or set(profile) != ROOT_FIELDS - {"intervals"}:
        raise ValidationError("profile must supply the registered non-interval power inputs")
    if not isinstance(selection, Mapping) or set(selection) != selection_fields:
        raise ValidationError("reference selection has unregistered or missing fields")
    if (selection["source_id"] != "energinet_day_ahead" or not isinstance(selection["currency"], str)
            or selection["currency"] not in {"EUR", "DKK"}
            or not isinstance(selection["price_area"], str)
            or selection["price_area"] not in {"DK1", "DK2", "DE", "NO2", "SE3", "SE4"}
            or selection["currency"] != profile["currency"]):
        raise ValidationError("native source/currency must match the scenario")
    records = _select_rows(index, selection)
    intervals = []
    for row, prices in records:
        # An exponent shift converts MWh to kWh exactly at any caller precision.
        sign, digits, exponent = prices[selection["currency"]].as_tuple()
        kwh_price = Decimal((sign, digits, exponent - 3))
        intervals.append({"starts_at": row["starts_at"], "ends_at": row["ends_at"],
            "utilization": selection["utilization"], "rate": {"amount_per_kwh": format(kwh_price, "f"),
                "currency": selection["currency"], "basis": "wholesale_reference", "evidence_ref": row["snapshot_id"]}})
    result = evaluate_power_payload({**profile, "intervals": intervals})
    result["source_binding"] = {"mode": "retained_server_reference", "source_id": "energinet_day_ahead",
        "snapshot_ids": sorted({row["snapshot_id"] for row, _ in records}), "price_area": selection["price_area"],
        "reference_intervals": len(records), "index_as_of": index["as_of"],
        "unit_conversion": "native_MWh_price_divided_by_1000_to_kWh", "site_tariff_verified": False}
    return result
