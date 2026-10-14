"""Invented bounded-display cases; no collection, quotes or live records."""
import copy
import datetime as dt
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.api.market import market_index
from compute_pricing.control.connectors import SourcePolicy

NOW = dt.datetime(2035, 1, 15, tzinfo=dt.timezone.utc)
STAMP, EXPIRY = "2035-01-15T00:00:00Z", "2035-01-16T00:00:00Z"


class FixedDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


def policy(source, **changes):
    values = dict(enabled=True, rights_status="allowed", rights_evidence="invented-comparison-scope",
        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        verified_by="invented-reviewer", max_age_s=86400)
    values.update(changes)
    return SourcePolicy(source, **values)


def snapshot(source, scope, *, observations=0, catalog=0, complete=True):
    digest = hashlib.sha256((source + ":" + scope).encode()).hexdigest()
    rows = [{"id": f"invented-{scope}-obs-{index}", "source_id": source,
        "kind": "aggregate_advertised_index" if source == "getdeploying" else "model_token_price" if source == "openrouter" else "listing_ask",
        "observed_at": STAMP, "expires_at": EXPIRY, "status": "claimed",
        "price": {"amount": "0.123456789", "currency": "USD", "unit": "gpu_hour" if source == "getdeploying" else "input_million_tokens" if source == "openrouter" else "node_hour"}}
        for index in range(observations)]
    records = [{"id": f"invented-{scope}-catalog-{index}", "source_id": source,
        "kind": "reference_fx" if source == "ecb" else "model_metadata" if source in ("huggingface", "huggingface_catalog") else "cloud_meter_tariff",
        "observed_at": STAMP, "expires_at": EXPIRY, "price_eligible": False, "execution_enabled": False}
        for index in range(catalog)]
    packet = {"snapshot_id": digest, "created_at": STAMP, "document": {
        "input": {"source_id": source, "filters": {"invented_scope": scope}},
        "output": {"source_id": source, "raw_metadata": {"captured_at": STAMP}, "observations": rows,
            "catalog_records": records, "coverage": {"complete": complete}, "execution_enabled": False}}}
    return SimpleNamespace(digest=digest, to_dict=lambda: copy.deepcopy(packet))


def store(snapshots, *, history_partial=False):
    return SimpleNamespace(latest_refresh=lambda: None, latest_collection_scan=lambda: SimpleNamespace(
        snapshots=tuple(snapshots), scan_limit=512, rows_scanned=len(snapshots), has_older_history=history_partial))


class FairSelectionV6Tests(unittest.TestCase):
    def index(self, snapshots, *, row_limit=5000, policies=None, history_partial=False):
        policies = policies if policies is not None else {item.to_dict()["document"]["output"]["source_id"]: policy(item.to_dict()["document"]["output"]["source_id"]) for item in snapshots}
        with patch("compute_pricing.control.api.market.dt.datetime", FixedDateTime):
            return market_index(store(snapshots, history_partial=history_partial), policies, [], row_limit=row_limit)

    def test_default_budget_giant_new_cloud_does_not_starve_older_price_or_discovery_roles(self):
        inputs = [snapshot("azure", "new-cloud", observations=6000), snapshot("aws_public_pricing", "new-native", catalog=6000),
            snapshot("getdeploying", "older-gpu", observations=2), snapshot("openrouter", "older-token", observations=2, catalog=2),
            snapshot("ecb", "older-fx", catalog=2), snapshot("huggingface", "older-models", catalog=2)]
        result = self.index(inputs)
        self.assertEqual(len(result["observations"]), 5000)
        self.assertEqual(len(result["catalog_records"]), 5000)
        self.assertEqual({row["source_id"] for row in result["observations"]}, {"azure", "getdeploying", "openrouter"})
        self.assertEqual({row["source_id"] for row in result["catalog_records"]}, {"aws_public_pricing", "openrouter", "ecb", "huggingface"})
        self.assertEqual(result["coverage"]["total_observations"], 6004)
        self.assertEqual(result["coverage"]["total_catalog_records"], 6006)
        self.assertTrue(result["coverage"]["display_truncated"])
        self.assertFalse(result["coverage"]["selection_is_benchmark_weighting"])
        self.assertFalse(result["execution_enabled"])

    def test_within_source_regions_share_budget_and_keep_full_scope_counts(self):
        result = self.index([snapshot("azure", scope, observations=20, catalog=20) for scope in ("newest", "middle", "oldest")], row_limit=6)
        self.assertEqual(len(result["observations"]), 6)
        self.assertEqual(len(result["catalog_records"]), 6)
        for summary in result["snapshots"]:
            self.assertEqual(summary["observation_count"], 20)
            self.assertEqual(summary["catalog_record_count"], 20)
            self.assertEqual(summary["returned_observation_count"], 2)
            self.assertEqual(summary["returned_catalog_record_count"], 2)
            self.assertTrue(summary["observation_display_truncated"])
            self.assertTrue(summary["catalog_display_truncated"])
            self.assertTrue(summary["display_truncated"])
            self.assertTrue(summary["coverage"]["complete"])
        self.assertEqual(result["coverage"]["total_observations"], 60)
        source = next(row for row in result["sources"] if row["source_id"] == "azure")
        self.assertEqual(source["latest"]["filters"], {"invented_scope": "newest"})
        self.assertEqual(source["scopes"], result["snapshots"])

    def test_many_scopes_in_one_source_do_not_buy_more_global_source_share(self):
        inputs = [snapshot("azure", "region-" + str(index), observations=10) for index in range(20)]
        inputs.extend([snapshot("getdeploying", "gpu", observations=10), snapshot("openrouter", "tokens", observations=10)])
        result = self.index(inputs, row_limit=9)
        self.assertEqual({source: sum(row["source_id"] == source for row in result["observations"]) for source in ("azure", "getdeploying", "openrouter")},
            {"azure": 3, "getdeploying": 3, "openrouter": 3})
        returned = [row["returned_observation_count"] for row in result["snapshots"] if row["source_id"] == "azure"]
        self.assertEqual(sum(returned), 3)
        self.assertEqual(sum(count > 0 for count in returned), 3)
        self.assertTrue(all(row["display_truncated"] for row in result["snapshots"]))

    def test_exhausted_sources_and_empty_scopes_reallocate_without_duplicates(self):
        inputs = [snapshot("azure", "empty"), snapshot("azure", "large", observations=10, catalog=10),
            snapshot("getdeploying", "small", observations=1), snapshot("ecb", "fx", catalog=1)]
        result = self.index(inputs, row_limit=6)
        self.assertEqual(len(result["observations"]), 6)
        self.assertEqual(len(result["catalog_records"]), 6)
        self.assertEqual(len({row["id"] for row in result["observations"]}), 6)
        empty = next(row for row in result["snapshots"] if row["filters"]["invented_scope"] == "empty")
        self.assertEqual(empty["returned_observation_count"], 0)
        self.assertFalse(empty["display_truncated"])
        small = next(row for row in result["snapshots"] if row["source_id"] == "getdeploying")
        self.assertEqual(small["returned_observation_count"], 1)
        self.assertFalse(small["display_truncated"])

    def test_revocation_removes_source_before_display_allocation_and_counts(self):
        inputs = [snapshot("azure", "denied", observations=6000, catalog=6000), snapshot("getdeploying", "allowed", observations=2)]
        policies = {"azure": policy("azure", permissions={"observe": "PASS", "retain": "FAIL", "benchmark": "PASS", "execution": "FAIL"}), "getdeploying": policy("getdeploying")}
        result = self.index(inputs, policies=policies, row_limit=2)
        self.assertEqual({row["source_id"] for row in result["observations"]}, {"getdeploying"})
        self.assertEqual(result["catalog_records"], [])
        self.assertEqual(result["coverage"]["total_observations"], 2)
        self.assertEqual(result["coverage"]["total_catalog_records"], 0)
        self.assertEqual(result["coverage"]["distinct_scopes_returned"], 1)
        self.assertEqual(result["coverage"]["distinct_scopes_in_bounded_scan"], 2)
        self.assertFalse(result["coverage"]["display_truncated"])

    def test_partial_history_and_partial_collection_stay_partial_with_fair_display(self):
        result = self.index([snapshot("azure", "bounded", observations=20, complete=False), snapshot("ecb", "fx", catalog=2)],
            row_limit=2, history_partial=True)
        self.assertTrue(result["coverage"]["history_scan_truncated"])
        self.assertTrue(result["coverage"]["possible_missing_scopes"])
        self.assertFalse(result["snapshots"][0]["coverage"]["complete"])
        self.assertTrue(result["snapshots"][0]["display_truncated"])
        self.assertIn("collection_history_scan_truncated_scopes_may_be_missing", result["warnings"])

    def test_selection_is_deterministic_and_keeps_row_freshness_checks(self):
        inputs = [snapshot("azure", "one", observations=10), snapshot("getdeploying", "two", observations=2)]
        first = self.index(inputs, row_limit=4)
        second = self.index(inputs, row_limit=4)
        self.assertEqual(first, second)
        self.assertTrue(all(not row["index_stale"] for row in first["observations"]))
        changed = inputs[1].to_dict(); changed["document"]["output"]["observations"][0]["expires_at"] = STAMP
        inputs[1] = SimpleNamespace(digest=changed["snapshot_id"], to_dict=lambda: copy.deepcopy(changed))
        result = self.index(inputs, row_limit=4)
        self.assertTrue(next(row for row in result["observations"] if row["id"] == "invented-two-obs-0")["index_stale"])

    def test_zero_boolean_and_out_of_range_budget_fail_before_reading_store(self):
        fake = SimpleNamespace(latest_refresh=lambda: self.fail("Invalid budget must not read store"))
        for limit in (0, -1, True, 0.5, 10001):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "invalid_index_row_limit"):
                market_index(fake, {}, [], row_limit=limit)


if __name__ == "__main__":
    unittest.main()
