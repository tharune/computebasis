"""Invented records demonstrate durable writer/read-snapshot concurrency."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from compute_pricing.control.reporting import SnapshotStore


def save(store, sequence):
    return store.put(kind="paper_decision", input_payload={"example_sequence": sequence, "declared_rate": "2.713"},
        output_payload={"classification": "synthetic", "execution_enabled": False}, versions={"example": "independent-concurrency/1"})


class SnapshotConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "concurrent.sqlite"
        self.store = SnapshotStore(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def test_writer_commits_while_reader_retains_stable_old_snapshot(self):
        save(self.store, 1)
        reader = sqlite3.connect(self.path)
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            reader.execute("BEGIN")
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
            future = executor.submit(save, self.store, 2)
            # DELETE mode cannot commit until this reader releases its lock.
            # WAL must return without ending the independent read transaction.
            written = future.result(timeout=1)
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
            self.assertIsNone(reader.execute("SELECT digest FROM snapshots WHERE digest=?", (written.digest,)).fetchone())
            self.assertEqual(self.store.get(written.digest).to_dict(), written.to_dict())
            reader.commit()
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 2)
        finally:
            reader.rollback()
            reader.close()
            executor.shutdown(wait=True)

    def test_concurrent_identical_puts_are_one_immutable_integrity_checked_receipt(self):
        gate = threading.Barrier(6)

        def concurrent_save():
            gate.wait(timeout=2)
            return save(self.store, 41)

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(concurrent_save) for _ in range(6)]
            results = [future.result(timeout=3) for future in futures]
        self.assertEqual(len({result.digest for result in results}), 1)
        self.assertEqual(len({result.created_at for result in results}), 1)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "snapshots_append_only"):
                connection.execute("UPDATE snapshots SET created_at='2049-01-01T00:00:00Z'")
        packet = results[0].to_dict()
        packet["document"]["input"]["declared_rate"] = "999"
        self.assertEqual(self.store.get(results[0].digest).document["input"]["declared_rate"], "2.713")

    def test_concurrent_distinct_puts_are_all_retained_and_full_durability_is_connection_local(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda n: save(self.store, n), range(8)))
        self.assertEqual(len({result.digest for result in results}), 8)
        for result in results:
            self.assertEqual(self.store.get(result.digest).to_dict(), result.to_dict())
        for _ in range(2):
            with self.store._connect() as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 2)
                self.assertEqual(connection.execute("PRAGMA trusted_schema").fetchone()[0], 0)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_existing_delete_journal_database_reopens_as_wal_without_changing_records(self):
        original = save(self.store, 57)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0], "delete")
        reopened = SnapshotStore(self.path)
        self.assertEqual(reopened.get(original.digest).to_dict(), original.to_dict())
        self.assertEqual(save(reopened, 57).to_dict(), original.to_dict())
        with reopened._connect() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
