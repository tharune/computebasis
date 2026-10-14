"""Synthetic retained histories test bounded work without weakening integrity."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from compute_pricing.control.reporting import SnapshotStore, SnapshotStoreError
import compute_pricing.control.reporting.store as storage


def populate(book, count=120):
    rows = []
    for revision in range(count):
        document = {"schema_version": "compute-snapshot/1.0", "kind": "market_collection",
            "input": {"filters": {"area": ("north", "south", "coast")[revision % 3], "options": {"labels": ["example"]}, "max_pages": revision + 2}},
            "output": {"source_id": "example_source", "sequence": revision,
                "observations": [{"identity": str(k), "amount": str(407 + revision), "description": "z" * 53} for k in range(65)]},
            "versions": {"adapter": "sample/2"}}
        canonical = storage.canonical_document(document, max_bytes=book.max_bytes)
        identity = hashlib.sha256(canonical.encode()).hexdigest()
        when = (dt.datetime(2058, 7, 9, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=revision)).isoformat().replace("+00:00", "Z")
        rows.append((identity, when, canonical))
    with sqlite3.connect(book.path) as db:
        db.executemany("INSERT INTO snapshots VALUES(?,?,?)", rows)
    return rows


class CollectionHistoryEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.book = SnapshotStore(Path(self.temporary.name) / "history.sqlite")

    def tearDown(self):
        self.temporary.cleanup()

    def test_bounded_one_query_retrieval_checks_history_and_freezes_only_three_scopes(self):
        history = populate(self.book, 180)
        began = time.perf_counter()
        with patch.object(self.book, "get", side_effect=AssertionError("extra connection")), \
             patch.object(storage.Snapshot, "to_dict", side_effect=AssertionError("unneeded full clone")), \
             patch.object(self.book, "_connect", wraps=self.book._connect) as reads, \
             patch.object(self.book, "_decode_saved", wraps=self.book._decode_saved) as checked, \
             patch.object(storage, "Snapshot", wraps=storage.Snapshot) as retained:
            scan = self.book.latest_collection_scan(scan_limit=117)
        self.assertEqual((reads.call_count, checked.call_count, retained.call_count), (1, 117, 3))
        self.assertEqual((scan.rows_scanned, scan.has_older_history), (117, True))
        self.assertEqual({snap.digest for snap in scan.snapshots}, {entry[0] for entry in history[-3:]})
        with self.assertRaises(TypeError):
            scan.snapshots[0].document["input"]["filters"]["area"] = "changed"
        print(f"sample collection scan: 117 verified rows, 3 retained scopes, {time.perf_counter() - began:.3f}s")

    def test_database_plan_avoids_table_scan_and_temporary_ordering(self):
        populate(self.book, 9)
        with sqlite3.connect(self.book.path) as db:
            details = db.execute("EXPLAIN QUERY PLAN SELECT digest,created_at,canonical_document FROM snapshots WHERE json_extract(canonical_document,'$.kind')='market_collection' ORDER BY created_at DESC,digest DESC LIMIT 10").fetchall()
        plan = " ".join(row[3] for row in details)
        self.assertIn("USING INDEX", plan)
        self.assertNotIn("TEMP B-TREE", plan)

    def test_corrupt_old_duplicate_remains_an_error_even_after_scope_found(self):
        entries = populate(self.book, 7)
        forged = json.loads(entries[0][2]); forged["output"]["sequence"] = 999
        with sqlite3.connect(self.book.path) as db:
            db.execute("DROP TRIGGER snapshots_no_update")
            db.execute("UPDATE snapshots SET canonical_document=? WHERE digest=?", (storage.canonical_document(forged, max_bytes=self.book.max_bytes), entries[0][0]))
        with self.assertRaisesRegex(SnapshotStoreError, "snapshot_integrity_failed"):
            self.book.latest_collection_scan(scan_limit=7)
        partial = self.book.latest_collection_scan(scan_limit=2)
        self.assertEqual((partial.rows_scanned, partial.has_older_history), (2, True))

    def test_correct_digest_does_not_excuse_malformed_historical_scope(self):
        populate(self.book, 4)
        invalid = {"schema_version": "compute-snapshot/1.0", "kind": "market_collection", "input": {"filters": ["bad"]},
                   "output": {"source_id": "example_source"}, "versions": {"adapter": "sample/2"}}
        encoded = storage.canonical_document(invalid, max_bytes=self.book.max_bytes)
        with sqlite3.connect(self.book.path) as db:
            db.execute("INSERT INTO snapshots VALUES(?,?,?)", (hashlib.sha256(encoded.encode()).hexdigest(), "2058-07-08T00:00:00Z", encoded))
        with self.assertRaisesRegex(SnapshotStoreError, "snapshot_integrity_failed"):
            self.book.latest_collection_scan(scan_limit=5)

    def test_existing_history_gains_index_without_rehash_and_refresh_reads_once(self):
        rows = populate(self.book, 5)
        with sqlite3.connect(self.book.path) as db:
            db.execute("DROP INDEX snapshot_kind_order")
        reopened = SnapshotStore(self.book.path)
        self.assertEqual(reopened.latest_collection_scan(scan_limit=5).rows_scanned, 5)
        self.assertEqual(reopened.get(rows[0][0]).digest, rows[0][0])
        saved = reopened.put(kind="market_refresh", input_payload={}, output_payload={"phase": "example"}, versions={"adapter": "sample/2"})
        with patch.object(reopened, "get", side_effect=AssertionError("extra get")), patch.object(reopened, "_connect", wraps=reopened._connect) as calls:
            self.assertEqual(reopened.latest_refresh().digest, saved.digest)
        self.assertEqual(calls.call_count, 1)


if __name__ == "__main__":
    unittest.main()
