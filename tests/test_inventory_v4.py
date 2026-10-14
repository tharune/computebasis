"""Independent invented inventory, boundary, persistence and concurrency cases."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from compute_pricing.control.api.app import _json_body
from compute_pricing.control.inventory import InventoryError, InventoryStore, attach_inventory, empty_state, evaluate_inventory, validate_inventory
from compute_pricing.control.inventory.model import MAX_LOTS, MAX_STATE_BYTES, MAX_UNIT_REFERENCES
from compute_pricing.control.inventory.store import HISTORY_LIMIT
from compute_pricing.control.reporting import SnapshotStore

T0, T1, T2, T3, T4 = ("2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z", "2026-10-20T00:00:00Z", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")
AUTH = {"Authorization": "Bearer invented-inventory-test-key"}


def state():
    return {"schema_version": "paper-inventory/1.0", "sites": [
        {"site_id": "invented-a", "latitude": "1.123456789012345678901", "longitude": "-2.0", "country_code": "US"},
        {"site_id": "invented-b"}], "lots": [
        {"lot_id": "invented-gpu-lot", "site_id": "invented-a", "unit_kind": "gpu", "unit_ids": ["invented-gpu-a", "invented-gpu-b"],
         "start_at": T0, "end_at": T4, "purchase_value": {"amount": "12345678901234567890123.0000000000000000000001", "currency": "USD", "unit": "lot_total"}},
        {"lot_id": "invented-node-lot", "site_id": "invented-b", "unit_kind": "node", "unit_ids": ["invented-node-a"],
         "start_at": T0, "end_at": T4, "purchase_value": {"amount": "7", "currency": "EUR", "unit": "lot_total"}}], "positions": [
        {"position_id": "invented-reservation", "lot_id": "invented-gpu-lot", "unit_ids": ["invented-gpu-a"], "status": "reserved", "start_at": T1, "end_at": T2},
        {"position_id": "invented-sale", "lot_id": "invented-gpu-lot", "unit_ids": ["invented-gpu-a"], "status": "sold", "start_at": T2, "end_at": T3,
         "sale_value": {"amount": "9.000000000000000000001", "currency": "USD", "unit": "position_total"}},
        {"position_id": "invented-maintenance", "lot_id": "invented-gpu-lot", "unit_ids": ["invented-gpu-b"], "status": "maintenance", "start_at": T1, "end_at": T2}]}


class InventoryModelTests(unittest.TestCase):
    def test_half_open_positions_and_availability_have_explicit_unsold_meaning(self):
        before = evaluate_inventory(state(), as_of=T0)
        self.assertEqual(before["summary"]["by_unit_kind"]["gpu"]["available"], 2)
        held = evaluate_inventory(state(), as_of=T1)
        self.assertEqual(held["summary"]["by_unit_kind"]["gpu"], {"available": 0, "reserved": 1, "sold": 0, "maintenance": 1, "unavailable": 0, "unsold": 2, "total": 2})
        sold = evaluate_inventory(state(), as_of=T2)
        self.assertEqual(sold["summary"]["by_unit_kind"]["gpu"]["sold"], 1)
        self.assertEqual(sold["summary"]["by_unit_kind"]["gpu"]["available"], 1)
        self.assertEqual(sold["summary"]["by_unit_kind"]["gpu"]["unsold"], 1)
        expired = evaluate_inventory(state(), as_of=T4)
        self.assertEqual(expired["summary"]["by_unit_kind"]["gpu"]["unavailable"], 2)
        self.assertEqual(expired["summary"]["by_unit_kind"]["gpu"]["unsold"], 0)
        self.assertTrue(all(row["site_id"] is None for row in expired["units"]))
        self.assertFalse(expired["execution_enabled"])
        self.assertEqual(expired["asset_verification"], "caller_declared_unverified")

    def test_future_sale_is_a_future_commitment_not_current_sold_inventory(self):
        result = evaluate_inventory(state(), as_of=T0)
        future = next(row for row in result["timeline"] if row["kind"] == "sold")
        self.assertFalse(future["active_at_as_of"])
        self.assertEqual(result["summary"]["by_unit_kind"]["gpu"]["sold"], 0)
        self.assertEqual(len(result["lots"][0]["positions"]), 3)

    def test_declared_money_stays_exact_and_separate_by_currency_and_value_basis(self):
        raw = state()
        raw["lots"].append({"lot_id": "invented-tiny-lot", "site_id": "invented-b", "unit_kind": "cpu", "unit_ids": ["invented-cpu-a"],
            "start_at": T0, "end_at": T4, "purchase_value": {"amount": "0.0000000000000000000001", "currency": "USD", "unit": "lot_total"}})
        result = evaluate_inventory(raw, as_of=T2)
        values = result["monetary_exposure"]
        self.assertEqual(values["purchase_values_by_currency"], {"EUR": "7", "USD": "12345678901234567890123.0000000000000000000002"})
        self.assertEqual(values["sold_position_values_by_currency"], {"USD": "9.000000000000000000001"})
        self.assertNotIn("total", values)
        self.assertEqual(set(result["summary"]["by_unit_kind"]), {"gpu", "node", "cpu"})

    def test_location_is_never_inferred_and_coordinate_bounds_are_exact(self):
        result = evaluate_inventory(state(), as_of=T1)
        self.assertEqual(result["located_sites"][0]["latitude"], "1.123456789012345678901")
        self.assertIsNone(result["unlocated_sites"][0]["longitude"])
        self.assertEqual(result["unlocated_unit_ids"], ["invented-node-a"])
        for latitude, longitude in (("90.000000000000000000000000000000001", "0"), ("0", "180.000000000000000000000000000000001"), (1.0, "0"), ("1", None), ("NaN", "0")):
            raw = state()
            raw["sites"][0].update(latitude=latitude, longitude=longitude)
            with self.subTest(latitude=latitude), self.assertRaises(InventoryError):
                validate_inventory(raw)

    def test_overlapping_hold_sale_and_maintenance_refuse_full_future_horizon(self):
        for status in ("reserved", "sold", "maintenance"):
            raw = state()
            raw["positions"].append({"position_id": "invented-conflict", "lot_id": "invented-gpu-lot", "unit_ids": ["invented-gpu-a"], "status": status, "start_at": T1, "end_at": T3})
            with self.subTest(status=status), self.assertRaisesRegex(InventoryError, "capacity_conflict"):
                evaluate_inventory(raw, as_of=T0)
        raw = state()
        raw["positions"][0]["unit_ids"] = ["invented-nonexistent-unit"]
        with self.assertRaisesRegex(InventoryError, "capacity_conflict"):
            validate_inventory(raw)

    def test_adjacent_relocated_lots_do_not_duplicate_current_unit_counts(self):
        raw = state()
        raw["lots"].append({"lot_id": "invented-next-lot", "site_id": "invented-b", "unit_kind": "gpu", "unit_ids": ["invented-gpu-a"], "start_at": T4, "end_at": "2027-01-01T00:00:00Z"})
        result = evaluate_inventory(raw, as_of=T4)
        self.assertEqual(result["summary"]["by_unit_kind"]["gpu"]["total"], 2)
        self.assertEqual(result["summary"]["by_unit_kind"]["gpu"]["available"], 1)
        self.assertEqual(result["summary"]["by_unit_kind"]["gpu"]["unavailable"], 1)
        current = next(row for row in result["units"] if row["unit_id"] == "invented-gpu-a")
        self.assertEqual(current["site_id"], "invented-b")
        raw["lots"][-1]["start_at"] = T3
        with self.assertRaisesRegex(InventoryError, "capacity_conflict"):
            validate_inventory(raw)
        raw["lots"][-1]["start_at"] = T4
        raw["lots"][-1]["unit_kind"] = "node"
        with self.assertRaisesRegex(InventoryError, "kind_changed"):
            validate_inventory(raw)

    def test_strict_shapes_dates_ids_and_money_do_not_become_silent_defaults(self):
        packets = []
        raw = state(); raw["lots"][0]["unit_ids"].append("invented-gpu-a"); packets.append(raw)
        raw = state(); raw["lots"][0]["start_at"] = "2026-10-01T01:00:00+01:00"; packets.append(raw)
        raw = state(); raw["lots"][0]["unit_count"] = 999; packets.append(raw)
        raw = state(); raw["lots"][0]["purchase_value"]["amount"] = 1.0; packets.append(raw)
        raw = state(); raw["lots"][0]["purchase_value"]["currency"] = "BTC"; packets.append(raw)
        raw = state(); raw["lots"][0]["purchase_value"]["unit"] = "gpu_hour"; packets.append(raw)
        raw = state(); raw["positions"][0]["sale_value"] = {"amount": "1", "currency": "USD", "unit": "position_total"}; packets.append(raw)
        raw = state(); raw["sites"][0]["site_id"] = "\ud800"; packets.append(raw)
        for raw in packets:
            with self.subTest(raw=raw), self.assertRaises(InventoryError):
                validate_inventory(raw)
        with self.assertRaisesRegex(InventoryError, "as_of"):
            evaluate_inventory(state(), as_of="2026-10-14")

    def test_resource_budgets_refuse_before_capacity_traversal(self):
        packets = []
        raw = state(); raw["lots"] *= MAX_LOTS + 1; packets.append(raw)
        raw = state(); raw["sites"][0]["extensions"] = {"too_large": "x" * MAX_STATE_BYTES}; packets.append(raw)
        raw = state(); raw["positions"] = [dict(raw["positions"][0], position_id=f"invented-p-{number}", unit_ids=[f"invented-u-{unit}" for unit in range(MAX_UNIT_REFERENCES // 2)]) for number in range(3)]; packets.append(raw)
        with patch("compute_pricing.control.inventory.model.validate_capacity") as validate:
            for raw in packets:
                with self.assertRaises(InventoryError):
                    validate_inventory(raw)
            validate.assert_not_called()

    def test_extensions_and_source_input_are_preserved_without_mutating_or_qualifying(self):
        raw = state(); raw["lots"][0]["extensions"] = {"new_claim": {"performance": 123, "license": None}}
        original = copy.deepcopy(raw)
        result = evaluate_inventory(raw, as_of=T0)
        self.assertEqual(raw, original)
        self.assertEqual(result["state"]["lots"][0]["extensions"], original["lots"][0]["extensions"])
        result["state"]["lots"][0]["extensions"]["new_claim"]["performance"] = 999
        self.assertEqual(raw, original)


class InventoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "state.sqlite"
        self.store = InventoryStore(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def test_empty_restart_coexistence_and_immutable_revision_replay(self):
        self.assertEqual(self.store.get(as_of=T0)["revision"], 0)
        self.assertEqual(self.store.get(as_of=T0)["state"], empty_state())
        snapshot_store = SnapshotStore(self.path)
        prior = snapshot_store.put(kind="pricing", input_payload={}, output_payload={"execution_enabled": False}, versions={"model": "invented"})
        first = self.store.put(expected_revision=0, state=state())
        restarted = InventoryStore(self.path)
        self.assertEqual(restarted.get(as_of=T2)["state_hash"], first["state_hash"])
        self.assertEqual(snapshot_store.get(prior.digest).digest, prior.digest)
        released = state(); released["positions"] = []
        second = restarted.put(expected_revision=1, state=released)
        self.assertEqual(second["audit"]["recent"][0]["changes"]["removed"]["positions"], ["invented-maintenance", "invented-reservation", "invented-sale"])
        self.assertEqual(restarted.get(as_of=T1)["summary"]["by_unit_kind"]["gpu"]["available"], 2)
        old = restarted.get(as_of=T1, revision=1)
        self.assertEqual(old["summary"]["by_unit_kind"]["gpu"]["reserved"], 1)
        self.assertEqual(old["latest_revision"], 2)
        self.assertEqual(restarted.get(as_of=T0, revision=0)["state"], empty_state())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_exact_retries_preserve_original_revision_even_after_new_changes(self):
        first = self.store.put(expected_revision=0, state=state())
        raw = state(); raw["sites"].reverse(); raw["lots"].reverse(); raw["positions"].reverse()
        retry = self.store.put(expected_revision=0, state=raw)
        self.assertTrue(retry["idempotent_replay"])
        self.assertEqual(retry["created_at"], first["created_at"])
        changed = state(); changed["sites"][0]["name"] = "invented changed name"
        self.store.put(expected_revision=1, state=changed)
        stale_retry = self.store.put(expected_revision=0, state=state())
        self.assertEqual(stale_retry["revision"], 1)
        self.assertEqual(stale_retry["latest_revision"], 2)
        self.assertTrue(stale_retry["idempotent_replay"])
        self.assertEqual(self.store.get(as_of=T0)["state"]["sites"][0]["name"], "invented changed name")

    def test_concurrent_distinct_updates_have_one_cas_winner(self):
        def writer(number):
            raw = state(); raw["sites"][0]["name"] = f"invented writer {number}"
            try:
                return InventoryStore(self.path).put(expected_revision=0, state=raw)["revision"]
            except InventoryError as error:
                return error.code, error.current_revision
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(writer, range(8)))
        self.assertEqual(results.count(1), 1)
        self.assertEqual(results.count(("inventory_revision_conflict", 1)), 7)
        self.assertEqual(self.store.get(as_of=T0)["revision"], 1)

    def test_concurrent_same_request_is_one_durable_revision(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: InventoryStore(self.path).put(expected_revision=0, state=state()), range(8)))
        self.assertEqual({row["audit_hash"] for row in results}, {results[0]["audit_hash"]})
        self.assertEqual(sum(not row["idempotent_replay"] for row in results), 1)
        self.assertEqual(len(self.store.get(as_of=T0)["audit"]["recent"]), 1)

    def test_concurrent_same_unit_reservations_cannot_both_commit_or_merge(self):
        baseline = state(); baseline["positions"] = []
        self.store.put(expected_revision=0, state=baseline)
        def position(number):
            return {"position_id": f"invented-competing-{number}", "lot_id": "invented-node-lot", "unit_ids": ["invented-node-a"], "status": "reserved", "start_at": T1, "end_at": T2}
        def reserve(number):
            candidate = copy.deepcopy(baseline)
            candidate["positions"] = [position(number)]
            try:
                return self.store.put(expected_revision=1, state=candidate)["revision"]
            except InventoryError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, range(2)))
        self.assertEqual(results.count(2), 1)
        self.assertEqual(results.count("inventory_revision_conflict"), 1)
        current = self.store.get(as_of=T1)
        self.assertEqual(current["summary"]["by_unit_kind"]["node"]["reserved"], 1)
        merged = current["state"]
        loser = 1 if merged["positions"][0]["position_id"].endswith("0") else 0
        merged["positions"].append(position(loser))
        with self.assertRaisesRegex(InventoryError, "capacity_conflict"):
            self.store.put(expected_revision=2, state=merged)
        self.assertEqual(self.store.get(as_of=T1)["revision"], 2)

    def test_removing_all_records_retains_removal_history_and_retry_is_idempotent(self):
        self.store.put(expected_revision=0, state=state())
        removed = self.store.put(expected_revision=1, state=empty_state())
        self.assertEqual(removed["summary"]["by_unit_kind"], {})
        self.assertEqual(removed["sites"], [])
        changes = removed["audit"]["recent"][0]["changes"]["removed"]
        self.assertEqual(len(changes["sites"]), 2)
        self.assertEqual(len(changes["lots"]), 2)
        self.assertEqual(len(changes["positions"]), 3)
        retry = InventoryStore(self.path).put(expected_revision=1, state=empty_state())
        self.assertTrue(retry["idempotent_replay"])
        self.assertEqual(retry["audit_hash"], removed["audit_hash"])
        self.assertEqual(len(self.store.get(as_of=T1, revision=1)["units"]), 3)

    def test_invalid_overallocation_or_stale_revision_cannot_mutate_current_inventory(self):
        self.store.put(expected_revision=0, state=state())
        raw = state(); raw["positions"].append(dict(raw["positions"][0], position_id="invented-overbook"))
        with self.assertRaisesRegex(InventoryError, "capacity_conflict"):
            self.store.put(expected_revision=1, state=raw)
        for revision in (True, -1, "1"):
            with self.assertRaises(InventoryError):
                self.store.put(expected_revision=revision, state=state())
        raw = state(); raw["sites"][0]["name"] = "invented stale edit"
        with self.assertRaisesRegex(InventoryError, "revision_conflict"):
            self.store.put(expected_revision=0, state=raw)
        self.assertEqual(self.store.get(as_of=T0)["revision"], 1)

    def test_history_limit_is_explicit_and_old_revisions_remain_replayable(self):
        for revision in range(HISTORY_LIMIT + 2):
            raw = state(); raw["sites"][0]["name"] = f"invented revision {revision}"
            self.store.put(expected_revision=revision, state=raw)
        report = self.store.get(as_of=T0)
        self.assertTrue(report["audit"]["truncated"])
        self.assertEqual(len(report["audit"]["recent"]), HISTORY_LIMIT)
        self.assertEqual(self.store.get(as_of=T0, revision=1)["state"]["sites"][0]["name"], "invented revision 0")
        with self.assertRaisesRegex(InventoryError, "not_found"):
            self.store.get(as_of=T0, revision=999)

    def test_audit_rows_refuse_update_and_delete_and_replay_detects_corruption(self):
        self.store.put(expected_revision=0, state=state())
        with sqlite3.connect(self.path) as connection:
            for statement in ("UPDATE inventory_revisions SET canonical_state='{}'", "DELETE FROM inventory_revisions"):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)
            connection.execute("DROP TRIGGER inventory_no_update")
            connection.execute("UPDATE inventory_revisions SET canonical_state='{}'")
        with self.assertRaisesRegex(InventoryError, "integrity_failed"):
            self.store.get(as_of=T0)

    def test_caller_mutation_never_changes_stored_state(self):
        raw = state()
        response = self.store.put(expected_revision=0, state=raw)
        raw["positions"].clear()
        response["state"]["positions"].clear()
        self.assertEqual(len(self.store.get(as_of=T0)["state"]["positions"]), 3)


class InventoryAPITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        app = FastAPI()
        async def authenticated(request: Request):
            if request.headers.get("authorization") != AUTH["Authorization"]:
                raise HTTPException(401, detail="unauthorized")
        self.store = attach_inventory(app, authenticated=authenticated, json_body=_json_body, store_path=Path(self.folder.name) / "state.sqlite")
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_auth_read_write_cas_and_revision_replay(self):
        self.assertEqual(self.client.get("/v1/inventory?as_of=bad").status_code, 401)
        self.assertEqual(self.client.put("/v1/inventory", json={"expected_revision": 0, "state": state()}).status_code, 401)
        initial = self.client.get("/v1/inventory", params={"as_of": T1}, headers=AUTH)
        self.assertEqual(initial.json()["summary"]["by_unit_kind"], {})
        written = self.client.put("/v1/inventory", json={"expected_revision": 0, "state": state()}, headers=AUTH)
        self.assertEqual(written.status_code, 200)
        self.assertEqual(written.json()["revision"], 1)
        raw = state(); raw["positions"] = []
        conflict = self.client.put("/v1/inventory", json={"expected_revision": 0, "state": raw}, headers=AUTH)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["current_revision"], 1)
        self.assertEqual(self.client.put("/v1/inventory", json={"expected_revision": 1, "state": raw}, headers=AUTH).status_code, 200)
        replay = self.client.get("/v1/inventory/revisions/1", params={"as_of": T1}, headers=AUTH)
        self.assertEqual(replay.json()["summary"]["by_unit_kind"]["gpu"]["reserved"], 1)
        self.assertEqual(self.client.get("/v1/inventory/revisions/999", headers=AUTH).status_code, 404)

    def test_pure_preview_does_not_persist_or_create_audit_or_claim_assets(self):
        result = self.client.post("/v1/inventory/evaluate", json={"state": state(), "as_of": T1}, headers=AUTH)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()["revision"])
        self.assertFalse(result.json()["persisted"])
        self.assertEqual(result.json()["audit"]["recent"], [])
        self.assertEqual(self.store.get(as_of=T1)["revision"], 0)
        self.assertEqual(self.store.get(as_of=T1)["state"], empty_state())

    def test_malformed_queries_and_payloads_fail_without_sensitive_echo(self):
        for query in ("as_of=bad", "as_of=" + T1 + "&as_of=" + T2, "unexpected=true"):
            self.assertEqual(self.client.get("/v1/inventory?" + query, headers=AUTH).status_code, 422)
        for revision in ("true", "-1", "99999999999"):
            self.assertEqual(self.client.get("/v1/inventory/revisions/" + revision, headers=AUTH).status_code, 422)
        self.assertEqual(self.client.post("/v1/inventory/evaluate", json={"state": state(), "as_of": None}, headers=AUTH).status_code, 422)
        raw = state(); raw["lots"][0]["unit_ids"] = ["invented sensitive invalid ID"]
        result = self.client.put("/v1/inventory", json={"expected_revision": 0, "state": raw}, headers=AUTH)
        self.assertEqual(result.status_code, 422)
        self.assertNotIn("invented sensitive invalid", result.text)


class InventoryExampleTests(unittest.TestCase):
    def test_example_is_explicit_invention_not_default_inventory(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "synthetic-inventory.json"
        result = evaluate_inventory(json.loads(path.read_text()), as_of="2026-10-14T00:00:00Z")
        self.assertEqual(result["summary"]["by_unit_kind"]["gpu"]["available"], 1)
        self.assertEqual(result["summary"]["by_unit_kind"]["gpu"]["reserved"], 1)
        self.assertEqual(result["summary"]["by_unit_kind"]["gpu"]["sold"], 1)
        self.assertEqual(result["summary"]["by_unit_kind"]["gpu"]["maintenance"], 1)
        self.assertEqual(result["summary"]["by_unit_kind"]["node"]["sold"], 1)
        self.assertEqual(evaluate_inventory(empty_state(), as_of=T0)["units"], [])


if __name__ == "__main__":
    unittest.main()
