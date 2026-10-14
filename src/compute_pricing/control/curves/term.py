"""Contract-average arithmetic and separately catalogued weekly price references."""
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, localcontext
import json
import re

from ..treasury._validation import calculation_precision, currency_value, decimal_value, identifier, iso_date, utc_instant
from ..domain.contracts import utc_instant as index_instant

COHORT_KEYS = frozenset({"hardware_model", "configuration", "region", "currency", "payment_scope", "cost_scope",
                        "capacity_scope", "gpu_count", "start_date", "service_basis", "cashflow_basis"})
NODE_KEYS = frozenset({"node_id", "cohort", "end_date", "quote_at", "rate_per_gpu_hour", "gpu_count", "billable_gpu_hours", "quote_ref"})
REQUEST_KEYS = frozenset({"as_of", "cohort", "nodes", "requested_end_dates", "max_quote_age_seconds"})
NODE_BUDGET = 128
MARK_BUDGET, GROUP_BUDGET, DISPLAY_NODE_BUDGET, DETAIL_BUDGET = 10000, 128, 512, 4
ZERO = Decimal("0")


def _fields(record, expected):
    if not isinstance(record, dict) or set(record) != expected:
        raise ValueError("exact named fields are required")


def _key(record):
    def visit(value, depth):
        if depth > 8 or isinstance(value, float):
            raise ValueError("bounded exact JSON configuration required")
        if isinstance(value, dict):
            if any(not isinstance(name, str) for name in value):
                raise ValueError("configuration keys must be text")
            for nested in value.values():
                visit(nested, depth + 1)
        elif isinstance(value, list):
            for nested in value:
                visit(nested, depth + 1)
        elif not isinstance(value, (str, int, bool, type(None))):
            raise ValueError("configuration must contain JSON values")
    visit(record, 0)
    result = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(result.encode("utf-8")) > 4096:
        raise ValueError("configuration budget exceeded")
    return result


def _count(raw):
    count = decimal_value(raw, "gpu_count")
    if count <= ZERO or count > 1000000 or count != count.to_integral_value():
        raise ValueError("positive whole GPU count required")
    return count


def _context(record):
    _fields(record, COHORT_KEYS)
    if not isinstance(record["configuration"], dict):
        raise ValueError("explicit configuration object required")
    for name in COHORT_KEYS - {"configuration", "gpu_count", "currency", "start_date"}:
        identifier(record[name], name)
    if record["service_basis"] != "24x7_utc_calendar" or record["cashflow_basis"] != "undiscounted_nominal_total":
        raise ValueError("service must be declared 24x7 UTC and cashflows must be undiscounted nominal amounts")
    currency_value(record["currency"])
    return iso_date(record["start_date"]), _count(record["gpu_count"]), _key(record)


@dataclass(frozen=True)
class _Quote:
    data: dict
    days: int
    amount: Decimal
    hours: Decimal
    stale: bool

    def average(self):
        return {"node_id": self.data["node_id"], "end_date": self.data["end_date"],
            "quote_at": self.data["quote_at"], "quote_ref": self.data["quote_ref"],
            "elapsed_calendar_days": self.days, "billable_gpu_hours": format(self.hours, "f"),
            "rate_per_gpu_hour": self.data["rate_per_gpu_hour"], "nominal_contract_amount": format(self.amount, "f"),
            "status": "held" if self.stale else "declared", "blockers": ["quote_stale_at_as_of"] if self.stale else [],
            "price_role": "reserved_term_average"}


def term_curve_contract():
    return {"contract_version": "term-curve-input/1.0.0", "request_fields": sorted(REQUEST_KEYS),
            "cohort_fields": sorted(COHORT_KEYS), "node_fields": sorted(NODE_KEYS), "maximum_nodes": NODE_BUDGET,
            "service_basis": "24x7_utc_calendar", "cashflow_basis": "undiscounted_nominal_total",
            "money_encoding": "exact_plain_decimal_string", "end_date_is_exclusive": True,
            "same_node_cohort_required": True, "implied_intervals_require_identical_quote_times": True,
            "interpolation_enabled": False, "extrapolation_enabled": False, "execution_enabled": False,
            "warnings": ["cohort_and_contract_scope_are_declarations_not_verified_rights",
                "a_reserved_average_is_not_an_expected_future_spot_or_tradable_forward_price"]}


def evaluate_term_curve_payload(payload):
    """Derive only the arithmetic supported by matching, explicitly dated quotes."""
    _fields(payload, REQUEST_KEYS)
    start, gpu_count, target_key = _context(payload["cohort"])
    now = utc_instant(payload["as_of"])
    age_limit, nodes, requested = payload["max_quote_age_seconds"], payload["nodes"], payload["requested_end_dates"]
    if type(age_limit) is not int or not 1 <= age_limit <= 31536000:
        raise ValueError("positive bounded freshness interval required")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= NODE_BUDGET:
        raise ValueError("bounded nonempty quote nodes required")
    if (not isinstance(requested, list) or len(requested) > NODE_BUDGET or
            any(not isinstance(day, str) for day in requested) or len(set(requested)) != len(requested)):
        raise ValueError("unique bounded requested dates required")
    if any(iso_date(day) <= start for day in requested):
        raise ValueError("requested dates must follow delivery start")
    identities, dates, operands = set(), set(), []
    prepared = []
    for node in nodes:
        _fields(node, NODE_KEYS)
        identifier(node["node_id"], "node_id"); identifier(node["quote_ref"], "quote_ref")
        if _context(node["cohort"])[2] != target_key or _count(node["gpu_count"]) != gpu_count:
            raise ValueError("different cohort, start, capacity or terms cannot form one nested curve")
        end, quoted = iso_date(node["end_date"]), utc_instant(node["quote_at"])
        if not 1 <= (end - start).days <= 36600 or quoted > now:
            raise ValueError("bounded later delivery end and nonfuture quote time required")
        if node["node_id"] in identities or node["end_date"] in dates:
            raise ValueError("quote identities and delivery ends must be unique")
        identities.add(node["node_id"]); dates.add(node["end_date"])
        rate = decimal_value(node["rate_per_gpu_hour"], "rate")
        hours = decimal_value(node["billable_gpu_hours"], "billable hours")
        operands.extend([node["rate_per_gpu_hour"], node["billable_gpu_hours"], node["gpu_count"]])
        prepared.append((end, quoted, node, rate, hours))
    quotes, intervals = [], []
    with localcontext() as arithmetic:
        arithmetic.prec = calculation_precision(operands, 8 * len(nodes))
        for end, quoted, node, rate, stated_hours in sorted(prepared, key=lambda item: item[0]):
            days = (end - start).days
            hours = Decimal(24 * days) * gpu_count
            if hours != stated_hours:
                raise ValueError("declared billable hours differ from the actual 24x7 calendar")
            quote = _Quote(deepcopy(node), days, hours * rate, hours, (now - quoted).total_seconds() >= age_limit)
            previous = quotes[-1] if quotes else None
            delta_amount = quote.amount - (previous.amount if previous else ZERO)
            delta_hours = quote.hours - (previous.hours if previous else ZERO)
            held = []
            if quote.stale or previous is not None and previous.stale:
                held.append("quote_stale_at_as_of")
            if previous is not None and quote.data["quote_at"] != previous.data["quote_at"]:
                held.append("quote_times_not_identical_for_interval_comparison")
            if delta_amount < ZERO:
                held.append("negative_nominal_contract_increment")
            intervals.append({"start_date": previous.data["end_date"] if previous else payload["cohort"]["start_date"],
                "end_date": quote.data["end_date"], "lower_node_id": previous.data["node_id"] if previous else None,
                "upper_node_id": quote.data["node_id"], "incremental_gpu_hours": format(delta_hours, "f"),
                "incremental_nominal_amount": format(delta_amount, "f"),
                "arithmetic_rate_per_gpu_hour": format(delta_amount / delta_hours, "f"),
                "status": "held" if held else "arithmetic_only", "blockers": held,
                "price_role": "implied_interval_arithmetic_not_forward_quote"})
            quotes.append(quote)
    gaps = sorted(set(requested) - dates)
    return {"schema_version": "term-curve-assessment/1.0", "model_version": "declared-nested-contract/1.0.0",
            "as_of": payload["as_of"], "cohort": deepcopy(payload["cohort"]),
            "delivery_start_role": "future_start_declared_contract" if start > now.date() else "current_or_elapsed_start_declared_contract",
            "status": "held" if any(quote.stale for quote in quotes) else "indicative",
            "term_average_quotes": [quote.average() for quote in quotes], "implied_interval_arithmetic": intervals,
            "interval_arithmetic_admitted": not any(interval["blockers"] for interval in intervals),
            "coverage": {"observed_end_dates": sorted(dates), "requested_end_dates": sorted(requested),
                "missing_end_dates": gaps, "complete_requested_nodes": not gaps, "interpolated_nodes": 0, "extrapolated_nodes": 0},
            "evidence_status": "caller_declared_unverified_contracts", "calibration_verified": False,
            "firm_price_eligible": False, "execution_enabled": False,
            "warnings": ["arithmetic_does_not_verify_capacity_costs_or_payment_rights",
                "interval_differences_between_bundles_are_not_a_tradable_forward_strip",
                "missing_tenors_and_future_start_contracts_require_their_own_quotes"]}


@dataclass
class _PublishedNode:
    rates: set = field(default_factory=set)
    references: dict = field(default_factory=dict)
    support: set = field(default_factory=set)

    def output(self, tenor):
        conflict = len(self.rates) > 1
        distinct = sorted(self.rates)
        refs = [reference for _, reference in sorted(self.references.items())]
        support = sorted(self.support)
        return {"reservation_months": tenor, "native_unit": "gpu_hour",
            "price_role": "reserved_term_average" if tenor is not None else "nonreserved_advertised_average",
            "rate_per_gpu_hour": None if conflict else format(distinct[0], "f"),
            "conflicting_native_rates": [format(rate, "f") for rate in distinct[:16]] if conflict else [],
            "conflicting_native_rate_count": len(distinct) if conflict else 0,
            "conflicting_native_rates_truncated": len(distinct) > 16,
            "status": "held" if conflict else "observed_reference",
            "blockers": ["conflicting_same_native_node"] if conflict else [],
            "support_counts": [{"provider_count": pair[0], "offering_count": pair[1]} for pair in support[:DETAIL_BUDGET]],
            "support_counts_truncated": len(support) > DETAIL_BUDGET,
            "references": refs[:DETAIL_BUDGET], "reference_count": len(refs), "references_truncated": len(refs) > DETAIL_BUDGET}


def _index_parts(index):
    if not isinstance(index, dict) or index.get("execution_enabled") is not False:
        raise ValueError("retained nonexecuting index required")
    for name, limit in (("observations", MARK_BUDGET), ("sources", 1024), ("snapshots", MARK_BUDGET)):
        if not isinstance(index.get(name), list) or len(index[name]) > limit:
            raise ValueError("retained index collections require bounded arrays")
    # The server index records datetime.isoformat(), including fractional seconds.
    now = index_instant(index.get("as_of"))
    sources, snapshots = {}, {}
    for record in index["sources"]:
        source_id = record.get("source_id") if isinstance(record, dict) else None
        if not isinstance(source_id, str) or source_id in sources:
            raise ValueError("unique index source IDs required")
        sources[source_id] = record
    for record in index["snapshots"]:
        digest = record.get("snapshot_id") if isinstance(record, dict) else None
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or digest in snapshots:
            raise ValueError("unique retained snapshot IDs required")
        snapshots[digest] = record
    return now, sources, snapshots


def _native_point(row, sources, snapshots, now):
    def require(condition, reason):
        if not condition:
            raise ValueError(reason)
    require(isinstance(row, dict) and row.get("source_id") == "getdeploying", "unsupported_native_term_source")
    source = sources.get(row["source_id"], {})
    require(source.get("enabled") is True and source.get("can_attempt_read") is True and source.get("rights_status") == "allowed"
            and all(source.get("permissions", {}).get(right) == "PASS" for right in ("observe", "retain", "benchmark")), "current_source_rights_not_admitted")
    age_limit = source.get("max_age_s")
    require(type(age_limit) is int and age_limit > 0, "source_freshness_policy_missing")
    snapshot = snapshots.get(row.get("snapshot_id"), {})
    captured, event, expiry = utc_instant(snapshot.get("captured_at")), utc_instant(row.get("observed_at")), utc_instant(row.get("expires_at"))
    require(snapshot.get("source_id") == row["source_id"] and snapshot.get("stale") is False and row.get("index_stale") is False
            and row.get("execution_enabled") is False and row.get("status") in {"claimed", "verified"}
            and event <= captured <= now and expiry > now
            and (now - captured).total_seconds() < age_limit and (now - event).total_seconds() < age_limit, "stale_or_unbound_retained_mark")
    rights = row.get("rights")
    require(isinstance(rights, dict) and rights.get("status") == "allowed"
            and all(rights.get(right) == "PASS" for right in ("observe", "retain", "benchmark")), "observation_rights_not_admitted")
    require(rights.get("expires_at") is None or utc_instant(rights["expires_at"]) > now, "observation_rights_expired")
    price, hardware, metadata = row.get("price"), row.get("hardware"), row.get("extensions")
    require(row.get("kind") == "aggregate_advertised_index" and isinstance(price, dict) and price.get("unit") == "gpu_hour"
            and isinstance(hardware, dict) and isinstance(metadata, dict), "unsupported_native_term_price_shape")
    identifier(hardware.get("model"), "model"); identifier(row.get("id"), "id"); identifier(row.get("source_version"), "source version")
    currency_value(price.get("currency"))
    require(price["currency"] == "USD" and metadata.get("currency_conversion") == "publisher_usd_conversion", "native_currency_basis_not_supported")
    require(hardware.get("accelerator_count") is None and row.get("configuration") is None and row.get("region") is None
            and metadata.get("regional_scope") == "market_aggregate", "native_aggregate_configuration_or_region_not_supported")
    require(metadata.get("period") == "weekly_median_of_daily_values" and metadata.get("price_statistic") == "provider_median_price", "native_statistic_not_supported")
    week = iso_date(metadata.get("week_start"))
    complete = utc_instant((week + timedelta(days=7)).isoformat() + "T00:00:00Z")
    require(week.weekday() == 0 and event.isoformat() == week.isoformat() + "T00:00:00+00:00" and complete <= captured, "weekly_period_incomplete_or_mismatched")
    identifier(metadata.get("billing_type"), "billing type")
    tenor = metadata.get("reservation_months")
    require("reservation_months" in metadata and (tenor is None or type(tenor) is int and 1 <= tenor <= 1200), "reservation_tenor_missing_or_invalid")
    require(all(type(metadata.get(name)) is int and metadata[name] >= 0 for name in ("provider_count", "offering_count"))
            and metadata["provider_count"] <= metadata["offering_count"], "native_support_counts_invalid")
    scope = {"source_id": row["source_id"], "source_version": row["source_version"],
             "hardware": {"model": hardware["model"], "accelerator_count": None}, "configuration": None, "region": None,
             "currency": price["currency"], "billing_type": metadata["billing_type"], "week_start": week.isoformat(),
             "period": metadata["period"], "price_statistic": metadata["price_statistic"],
             "regional_scope": metadata["regional_scope"], "currency_conversion": metadata["currency_conversion"]}
    ref = {"observation_id": row["id"], "snapshot_id": row["snapshot_id"], "captured_at": snapshot["captured_at"],
           "observed_at": row["observed_at"], "expires_at": row["expires_at"]}
    return scope, tenor, decimal_value(price.get("amount"), "rate"), ref, (metadata["provider_count"], metadata["offering_count"])


def observed_commitment_curves(index):
    """Group current server-index references; never infer dates from a month label."""
    now, sources, snapshots = _index_parts(index)
    scopes, book, exclusions, admitted = {}, defaultdict(lambda: defaultdict(_PublishedNode)), Counter(), 0
    for row in index["observations"]:
        try:
            scope, tenor, rate, ref, support = _native_point(row, sources, snapshots, now)
            group_key = _key(scope); scopes[group_key] = scope
            node = book[group_key][tenor]
            node.rates.add(rate); node.support.add(support)
            node.references[(ref["observation_id"], ref["snapshot_id"])] = ref
            admitted += 1
        except (ValueError, TypeError, KeyError, ArithmeticError) as error:
            code = str(error)
            exclusions[code if re.fullmatch(r"[a-z][a-z0-9_]{0,80}", code) else "invalid_native_mark"] += 1
    total_nodes, displayed, groups = sum(len(points) for points in book.values()), 0, []
    for group_key in sorted(book)[:GROUP_BUDGET]:
        nodes = []
        for tenor in sorted(book[group_key], key=lambda value: (value is not None, value or 0)):
            if displayed == DISPLAY_NODE_BUDGET:
                break
            nodes.append(book[group_key][tenor].output(tenor)); displayed += 1
        if nodes:
            groups.append({"cohort": scopes[group_key], "nodes": nodes, "configuration_and_region_qualified": False,
                "warnings": ["published_aggregate_does_not_certify_rentable_supply",
                    "unknown_location_machine_scope_and_calendar_are_not_inferred"]})
    return {"schema_version": "observed-commitment-curves/1.0", "model_version": "native-advertised-marks/1.0.0",
            "as_of": index["as_of"], "groups": groups, "coverage": {"input_rows": len(index["observations"]),
                "eligible_rows": admitted, "excluded_rows": sum(exclusions.values()), "exclusions": dict(sorted(exclusions.items())),
                "total_groups": len(book), "returned_groups": len(groups), "total_nodes": total_nodes,
                "returned_nodes": displayed, "display_truncated": len(groups) < len(book) or displayed < total_nodes},
            "interpolation_enabled": False, "extrapolation_enabled": False, "firm_price_eligible": False,
            "execution_enabled": False, "calibration_verified": False,
            "evidence_status": "server_index_references_shape_checked_not_rebound_by_this_function",
            "warnings": ["source_week_currency_and_native_payment_scopes_are_not_averaged",
                "recent_collection_does_not_refresh_a_historical_event_period",
                "commitment_averages_do_not_identify_future_spot_prices_or_derivative_hedge_ratios"]}
