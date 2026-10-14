"""Offline append-only audit snapshots, exact decimals and integrity checks."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.reporting import SnapshotStore, SnapshotStoreError


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compute-snapshot-tests-")
        self.path = Path(self.temp.name) / "decisions.sqlite"
        self.store = SnapshotStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, **changes):
        arguments = {"kind": "pricing", "input_payload": {"price": "0.1234567890123456789012345678901234"},
                     "output_payload": {"bid": "1.05", "execution_enabled": False},
                     "versions": {"policy": "1.0.0", "model": "1.0.0"}}
        return self.store.put(**{**arguments, **changes})

    def test_roundtrip_exact_decimal_and_input_mutation_isolated(self):
        source = {"price": "0.1234567890123456789012345678901234", "future": {"value": "2.3"}}
        result = self.put(input_payload=source)
        source["future"]["value"] = "changed"
        loaded = self.store.get(result.digest)
        self.assertEqual(loaded.document["input"]["price"], "0.1234567890123456789012345678901234")
        self.assertEqual(loaded.document["input"]["future"]["value"], "2.3")
        self.assertEqual(result.to_dict()["snapshot_id"], result.digest)
        with self.assertRaises(TypeError):
            result.document["input"]["future"]["value"] = "changed"
        mutable_copy = result.to_dict()
        mutable_copy["document"]["input"]["future"]["value"] = "changed"
        self.assertEqual(result.document["input"]["future"]["value"], "2.3")

    def test_idempotence_and_canonical_key_order(self):
        first = self.put(input_payload={"a": "1", "b": "2"})
        second = self.put(input_payload={"b": "2", "a": "1"})
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.created_at, second.created_at)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_versions_and_changed_prices_produce_distinct_decisions(self):
        first = self.put()
        changed = self.put(versions={"model": "2.0.0"})
        changed_price = self.put(output_payload={"bid": "1.06"})
        self.assertEqual(len({first.digest, changed.digest, changed_price.digest}), 3)

    def test_sql_update_and_delete_refused(self):
        result = self.put()
        for statement in ("UPDATE snapshots SET canonical_document='{}' WHERE digest=?", "DELETE FROM snapshots WHERE digest=?"):
            with self.subTest(statement=statement), sqlite3.connect(self.path) as connection, self.assertRaises(sqlite3.IntegrityError):
                connection.execute(statement, (result.digest,))
        self.assertIsNotNone(self.store.get(result.digest))

    def test_hash_collision_conflict_and_tampering_rejected(self):
        result = self.put()
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TRIGGER snapshots_no_update")
            connection.execute("UPDATE snapshots SET canonical_document='{}' WHERE digest=?", (result.digest,))
        with self.assertRaisesRegex(SnapshotStoreError, "snapshot_hash_conflict"):
            self.put()
        with self.assertRaisesRegex(SnapshotStoreError, "snapshot_integrity_failed"):
            self.store.get(result.digest)

    def test_snapshot_ids_are_strict_and_missing_is_none(self):
        self.assertIsNone(self.store.get("a" * 64))
        for digest in ("../private", "A" * 64, "a" * 63, "secret"):
            with self.subTest(digest=digest), self.assertRaisesRegex(SnapshotStoreError, "invalid_snapshot_id"):
                self.store.get(digest)

    def test_must_be_absolute_and_outside_git(self):
        with self.assertRaisesRegex(SnapshotStoreError, "absolute_store_path_required"):
            SnapshotStore(Path("decisions.sqlite"))
        git_root = Path(self.temp.name) / "checkout"
        git_root.mkdir()
        (git_root / ".git").write_text("gitdir: managed")
        with self.assertRaisesRegex(SnapshotStoreError, "store_must_be_outside_git"):
            SnapshotStore(git_root / "private.sqlite")
        link = Path(self.temp.name) / "alias"
        link.symlink_to(git_root, target_is_directory=True)
        with self.assertRaisesRegex(SnapshotStoreError, "store_must_be_outside_git"):
            SnapshotStore(link / "private.sqlite")

    def test_nonfinite_unknown_kind_and_missing_versions_fail(self):
        for change in ({"input_payload": {"bad": float("nan")}}, {"output_payload": {"bad": float("inf")}},
                       {"kind": "execute_trade"}, {"versions": {}}, {"versions": {"policy": 1}}):
            with self.subTest(change=change), self.assertRaises(SnapshotStoreError):
                self.put(**change)

    def test_size_limit_and_private_file_mode(self):
        store = SnapshotStore(Path(self.temp.name) / "small.sqlite", max_bytes=1024)
        with self.assertRaisesRegex(SnapshotStoreError, "snapshot_size_limit"):
            store.put(kind="cash", input_payload={"large": "a" * 2048}, output_payload={}, versions={"model": "1"})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_concurrent_same_decision_is_atomic_and_idempotent(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.put(), range(12)))
        self.assertEqual(len({result.digest for result in results}), 1)
        self.assertEqual(len({result.created_at for result in results}), 1)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
