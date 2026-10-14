"""Bounded live evidence index; no aggregation of incompatible price roles."""
import datetime as dt
from collections import deque

from compute_pricing.control.connectors import source_status
from compute_pricing.control.connectors.transport import parse_utc
from compute_pricing.control.reporting import SnapshotStoreError


def _collection_packet(snapshot):
    packet = snapshot.to_dict()
    document = packet.get("document")
    if not isinstance(document, dict) or not isinstance(document.get("input"), dict) or not isinstance(document.get("output"), dict):
        raise SnapshotStoreError("snapshot_integrity_failed")
    output, inputs = document["output"], document["input"]
    source = output.get("source_id")
    if not isinstance(source, str) or inputs.get("source_id", source) != source or not isinstance(inputs.get("filters", {}), dict):
        raise SnapshotStoreError("snapshot_integrity_failed")
    for key in ("observations", "catalog_records"):
        if not isinstance(output.get(key, []), list) or any(not isinstance(row, dict) or row.get("source_id", source) != source or row.get("execution_enabled") is True for row in output.get(key, [])):
            raise SnapshotStoreError("snapshot_integrity_failed")
    if output.get("execution_enabled") is not False or not isinstance(output.get("raw_metadata", {}), dict):
        raise SnapshotStoreError("snapshot_integrity_failed")
    return packet, output, inputs, source


def _fair_rows(scopes, key, limit):
    """Cycle through sources, then their newest retained nonempty scopes.

    This allocates a display budget only. It does not construct benchmark
    weights, infer coverage or expand the admitted population.
    """
    grouped = {}
    for scope in scopes:
        if scope[key]:
            grouped.setdefault(scope["source_id"], deque()).append([scope, 0])
    sources = deque(grouped[source] for source in sorted(grouped))
    returned = 0
    while sources and returned < limit:
        source_scopes = sources.popleft()
        scope, offset = source_scopes.popleft()
        yield scope, scope[key][offset]
        returned += 1
        if offset + 1 < len(scope[key]):
            source_scopes.append([scope, offset + 1])
        if source_scopes:
            sources.append(source_scopes)


def market_index(store, policies, collection_plan, *, row_limit=5000):
    if type(row_limit) is not int or not 1 <= row_limit <= 10000:
        raise ValueError("invalid_index_row_limit")
    now = dt.datetime.now(dt.timezone.utc)
    sources = source_status(policies, now)
    by_source = {item["source_id"]: item for item in sources}
    observations, catalog_records, snapshots, row_scopes = [], [], [], []
    total_observations = total_catalog = 0
    refresh = store.latest_refresh()
    receipt = refresh.to_dict() if refresh else None
    if receipt:
        if not isinstance(receipt.get("document"), dict):
            raise SnapshotStoreError("snapshot_integrity_failed")
        output = receipt["document"].get("output")
        if not isinstance(output, dict) or output.get("execution_enabled") is not False:
            raise SnapshotStoreError("snapshot_integrity_failed")
        for status in ("updated", "held", "failed"):
            records = output.get(status, [])
            if not isinstance(records, list) or any(not isinstance(row, dict) or not isinstance(row.get("source_id"), str) for row in records):
                raise SnapshotStoreError("snapshot_integrity_failed")
            for row in records:
                if row["source_id"] in by_source:
                    by_source[row["source_id"]].setdefault("last_attempts", []).append({**row, "status": status, "at": receipt["created_at"]})
    scan = store.latest_collection_scan()
    for snapshot in scan.snapshots:
        packet, output, inputs, source = _collection_packet(snapshot)
        if source not in by_source:
            continue
        policy = policies.get(source)
        # Revoking rights hides retained rows from the current-use index.
        if policy is None or any(policy.blockers(scope, now) for scope in ("observe", "retain", "benchmark")):
            continue
        rows = output.get("observations", [])
        catalog = output.get("catalog_records", [])
        captured = output.get("raw_metadata", {}).get("captured_at", packet["created_at"])
        try:
            age = (now - parse_utc(captured)).total_seconds()
            collection_stale = age < 0 or age >= policy.max_age_s
        except (ValueError, TypeError):
            collection_stale = True
        summary = {"snapshot_id": packet["snapshot_id"], "created_at": packet["created_at"],
                   "captured_at": captured, "source_id": source, "filters": inputs.get("filters", {}),
                   "observation_count": len(rows), "catalog_record_count": len(catalog),
                   "returned_observation_count": 0, "returned_catalog_record_count": 0,
                   "stale": collection_stale, "coverage": output.get("coverage", {}),
                   "selection": output.get("selection", {}), "warnings": output.get("warnings", [])}
        snapshots.append(summary)
        by_source[source].setdefault("scopes", []).append(summary)
        total_observations += len(rows)
        total_catalog += len(catalog)
        # No one scope can consume more than a whole global category budget.
        # Keep only that bounded prefix while retaining its full count above.
        row_scopes.append({"source_id": source, "summary": summary, "policy": policy,
            "collection_stale": collection_stale, "observations": rows[:row_limit],
            "catalog_records": catalog[:row_limit]})
    for scope, row in _fair_rows(row_scopes, "observations", row_limit):
        expires = row.get("expires_at")
        try:
            stale = scope["collection_stale"] or expires is None or parse_utc(expires) <= now
            age = (now - parse_utc(row["observed_at"])).total_seconds()
            stale = stale or age < 0 or age >= scope["policy"].max_age_s
        except (ValueError, TypeError, KeyError):
            stale = True
        observations.append({**row, "snapshot_id": scope["summary"]["snapshot_id"], "index_stale": stale,
                             "execution_enabled": False})
        scope["summary"]["returned_observation_count"] += 1
    for scope, row in _fair_rows(row_scopes, "catalog_records", row_limit):
        row_stale = scope["collection_stale"]
        expires = row.get("expires_at")
        observed = row.get("observed_at") or (str(row["observed_date"]) + "T00:00:00Z" if row.get("observed_date") else None)
        try:
            if expires is not None:
                row_stale = row_stale or parse_utc(expires) <= now
            if observed is not None:
                age = (now - parse_utc(observed)).total_seconds()
                row_stale = row_stale or age < 0 or age >= scope["policy"].max_age_s
        except (ValueError, TypeError):
            row_stale = True
        catalog_records.append({**row, "source_id": scope["source_id"], "snapshot_id": scope["summary"]["snapshot_id"],
                                "index_stale": row_stale, "execution_enabled": False})
        scope["summary"]["returned_catalog_record_count"] += 1
    for summary in snapshots:
        summary["observation_display_truncated"] = summary["returned_observation_count"] < summary["observation_count"]
        summary["catalog_display_truncated"] = summary["returned_catalog_record_count"] < summary["catalog_record_count"]
        summary["display_truncated"] = summary["observation_display_truncated"] or summary["catalog_display_truncated"]
    for source in sources:
        scopes = source.get("scopes", [])
        source["latest"] = scopes[0] if scopes else None
        source["observed_liveness"] = ("not_found_in_bounded_history" if scan.has_older_history else "not_probed") if not scopes else "stale" if all(scope["stale"] for scope in scopes) else "recent_success"
    warnings = ["catalog_references_are_not_verified_executable_inventory",
                "source_timestamp_and_scope_control_price_use",
                "bounded_display_selection_not_complete_cohort_or_benchmark_weighting"]
    if scan.has_older_history:
        warnings.append("collection_history_scan_truncated_scopes_may_be_missing")
    return {"as_of": now.isoformat().replace("+00:00", "Z"), "sources": sources,
            "observations": observations, "catalog_records": catalog_records, "snapshots": snapshots,
            "collection_plan": collection_plan, "last_refresh": receipt, "execution_enabled": False,
            "coverage": {"history_scan_limit": scan.scan_limit, "history_rows_scanned": scan.rows_scanned,
                         "history_scan_truncated": scan.has_older_history,
                         "possible_missing_scopes": scan.has_older_history,
                         "distinct_scopes_returned": len(snapshots), "distinct_scopes_in_bounded_scan": len(scan.snapshots),
                         "observation_row_limit": row_limit,
                         "catalog_row_limit": row_limit, "total_observations": total_observations,
                         "total_catalog_records": total_catalog,
                         "returned_observation_count": len(observations), "returned_catalog_record_count": len(catalog_records),
                         "row_selection": "source_then_scope_round_robin", "selection_is_benchmark_weighting": False,
                         "display_truncated": total_observations > len(observations) or total_catalog > len(catalog_records)},
            "warnings": warnings}
