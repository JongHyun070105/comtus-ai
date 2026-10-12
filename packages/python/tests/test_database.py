import sqlite3
import tempfile
import unittest
from pathlib import Path

from comtus_ai.database import SQLiteStore
from comtus_ai.database.store import INITIAL_SCHEMA
from comtus_ai.models import EvidenceSource


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "test.sqlite3"
        self.store = SQLiteStore(self.path)
        self.store.initialize()

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_migration_is_versioned_idempotent_and_foreign_keys_are_enabled(self):
        self.assertEqual(self.store.schema_version(), 2)
        self.assertEqual(self.store.initialize(), 2)
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 2)

    def test_legacy_v1_database_upgrades_to_v2_with_result_provenance(self):
        path = Path(self.temporary.name) / "legacy.sqlite3"
        legacy = sqlite3.connect(path)
        legacy.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL)")
        legacy.executescript(INITIAL_SCHEMA)
        legacy.execute("INSERT INTO schema_migrations VALUES(1,'initial_analysis_schema','now')")
        legacy.commit()
        legacy.close()
        with SQLiteStore(path) as migrated:
            self.assertEqual(migrated.initialize(), 2)
            names = {row["name"] for row in migrated.connection.execute("PRAGMA table_info(match_results)")}
            self.assertIn("source_type", names)
            self.assertEqual(migrated.schema_version(), 2)

    def test_duplicate_team_snapshot_is_ignored_and_changed_state_is_new_immutable_row(self):
        account = self.store.ensure_account("account-a", "Samsung Lions")
        arguments = dict(account_id=account, snapshot_kind="TEST", payload={"roster": ["c1"]}, source_type=EvidenceSource.SYNTHETIC_TEST)
        first_id, inserted = self.store.save_team_snapshot(**arguments)
        duplicate_id, duplicate_inserted = self.store.save_team_snapshot(**arguments)
        changed_id, changed_inserted = self.store.save_team_snapshot(**{**arguments, "payload": {"roster": ["c1"], "skill": "changed"}})
        self.assertTrue(inserted)
        self.assertFalse(duplicate_inserted)
        self.assertEqual(first_id, duplicate_id)
        self.assertTrue(changed_inserted)
        self.assertNotEqual(first_id, changed_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute("UPDATE team_snapshots SET team_ovr=999 WHERE id=?", (first_id,))

    def test_player_snapshots_are_account_scoped_and_idempotent_by_state(self):
        account_a = self.store.ensure_account("a", "Samsung")
        account_b = self.store.ensure_account("b", "Giants")
        master = self.store.connection.execute("INSERT INTO card_masters(canonical_name,team_name,card_type,created_at) VALUES(?,?,?,?)", ("Same name", "Samsung", "LIVE", "now")).lastrowid
        instance_a = self.store.connection.execute("INSERT INTO card_instances(account_id,card_master_id,instance_key,stars,live_version,enhancement,created_at) VALUES(?,?,?,?,?,?,?)", (account_a, master, "a-card", 5, "V2", 5, "now")).lastrowid
        instance_b = self.store.connection.execute("INSERT INTO card_instances(account_id,card_master_id,instance_key,stars,live_version,enhancement,created_at) VALUES(?,?,?,?,?,?,?)", (account_b, master, "b-card", 5, "V2", 5, "now")).lastrowid
        self.store.connection.commit()
        args = dict(payload={"ovr": 80}, source_type=EvidenceSource.SYNTHETIC_TEST)
        a_id, a_new = self.store.save_player_snapshot(account_id=account_a, card_instance_id=instance_a, **args)
        again_id, again_new = self.store.save_player_snapshot(account_id=account_a, card_instance_id=instance_a, **args)
        b_id, b_new = self.store.save_player_snapshot(account_id=account_b, card_instance_id=instance_b, **args)
        self.assertTrue(a_new and b_new)
        self.assertFalse(again_new)
        self.assertEqual(a_id, again_id)
        self.assertNotEqual(a_id, b_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_player_snapshot(account_id=account_b, card_instance_id=instance_a, **args)

    def test_ocr_duplicate_is_ignored_and_corrections_are_append_only(self):
        evidence_id = self.store.connection.execute("INSERT INTO capture_evidence(sha256,source_type,created_at) VALUES(?,?,?)", ("abc", "SYNTHETIC_TEST", "now")).lastrowid
        self.store.connection.commit()
        args = dict(evidence_id=evidence_id, field="player_name", text="후라도", confidence=0.8, bbox=[0.1, 0.2, 0.3, 0.05], source_type=EvidenceSource.SYNTHETIC_TEST)
        first, inserted = self.store.save_ocr_observation(**args)
        second, duplicate_inserted = self.store.save_ocr_observation(**args)
        self.assertTrue(inserted)
        self.assertFalse(duplicate_inserted)
        self.assertEqual(first, second)
        correction_id = self.store.record_ocr_correction(first, "후라도'26", reason="verified by test fixture")
        self.assertGreater(correction_id, 0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute("UPDATE ocr_observations SET text='different' WHERE id=?", (first,))

    def test_schema_rejects_out_of_range_confidence(self):
        account = self.store.ensure_account("account-c", "Samsung")
        with self.assertRaises(ValueError):
            self.store.save_team_snapshot(account_id=account, snapshot_kind="test", payload={}, source_type="SYNTHETIC_TEST", confidence=2.0)

    def test_prediction_and_match_result_recording_is_idempotent_and_keeps_synthetic_out_of_training_count(self):
        account = self.store.ensure_account("result-account", "Samsung")
        team_id, _ = self.store.save_team_snapshot(account_id=account, snapshot_kind="TEST", payload={"team": "fixture"}, source_type=EvidenceSource.SYNTHETIC_TEST)
        batch, new_batch = self.store.create_match_batch(account_id=account, team_snapshot_id=team_id, batch_key="batch-a", rules_version="synthetic-v1", source_type=EvidenceSource.SYNTHETIC_TEST)
        self.assertTrue(new_batch)
        prediction_args = dict(account_id=account, batch_id=batch, opponent_snapshot_id=None, model_version_id=None,
                               recommended_pitcher_card_instance_id=None, score_type="HEURISTIC_SCORE", predicted_score=1.25,
                               predicted_win_probability=None, payload={"score_type": "HEURISTIC_SCORE"})
        prediction_id, prediction_new = self.store.record_match_prediction(**prediction_args)
        duplicate_prediction_id, duplicate_prediction_new = self.store.record_match_prediction(**prediction_args)
        self.assertTrue(prediction_new)
        self.assertFalse(duplicate_prediction_new)
        self.assertEqual(prediction_id, duplicate_prediction_id)
        with self.assertRaises(ValueError):
            self.store.record_match_prediction(**{**prediction_args, "predicted_win_probability": 0.8})
        result_args = dict(account_id=account, match_key="synthetic-match", source_type=EvidenceSource.SYNTHETIC_TEST,
                           batch_id=batch, team_snapshot_id=team_id, actual_score=3, opponent_score=4, result="LOSS",
                           payload={"fixture": True})
        result_id, result_new = self.store.record_match_result(**result_args)
        duplicate_id, duplicate_new = self.store.record_match_result(**result_args)
        self.assertTrue(result_new)
        self.assertFalse(duplicate_new)
        self.assertEqual(result_id, duplicate_id)
        self.assertEqual(self.store.counts()["validated_match_results"], 0)
        self.assertEqual(self.store.counts()["synthetic_match_results"], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_match_result(**{**result_args, "actual_score": 9})

    def test_match_result_cannot_reference_another_accounts_snapshot(self):
        account_a = self.store.ensure_account("account-a", "Samsung")
        account_b = self.store.ensure_account("account-b", "Giants")
        team_a, _ = self.store.save_team_snapshot(account_id=account_a, snapshot_kind="TEST", payload={"owner": "a"}, source_type="SYNTHETIC_TEST")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_match_result(account_id=account_b, match_key="cross-account", source_type="SYNTHETIC_TEST", team_snapshot_id=team_a)


if __name__ == "__main__":
    unittest.main()
