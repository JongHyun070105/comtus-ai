import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from comtus_ai.database import SQLiteStore
from comtus_ai.database.store import INITIAL_SCHEMA
from comtus_ai.models import EvidenceSource
from comtus_ai.private_fixtures import PrivateFixtureMetadata, PrivateFixtureStore
from comtus_ai.screens import ScreenState


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
        self.assertEqual(self.store.schema_version(), 4)
        self.assertEqual(self.store.initialize(), 4)
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 4)

    def test_legacy_v1_database_upgrades_to_v2_with_result_provenance(self):
        path = Path(self.temporary.name) / "legacy.sqlite3"
        legacy = sqlite3.connect(path)
        legacy.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL)")
        legacy.executescript(INITIAL_SCHEMA)
        legacy.execute("INSERT INTO schema_migrations VALUES(1,'initial_analysis_schema','now')")
        legacy.commit()
        legacy.close()
        with SQLiteStore(path) as migrated:
            self.assertEqual(migrated.initialize(), 4)
            names = {row["name"] for row in migrated.connection.execute("PRAGMA table_info(match_results)")}
            self.assertIn("source_type", names)
            self.assertEqual(migrated.schema_version(), 4)
            self.assertEqual(migrated.connection.execute("SELECT COUNT(*) FROM screen_observations").fetchone()[0], 0)
            self.assertEqual(migrated.connection.execute("SELECT COUNT(*) FROM ocr_field_candidates").fetchone()[0], 0)

    def test_schema_v2_database_upgrades_to_v4_without_rewriting_evidence(self):
        path = Path(self.temporary.name) / "v2.sqlite3"
        with SQLiteStore(path) as seeded:
            seeded.initialize()
            account = seeded.ensure_account("account-v2", "Synthetic")
            evidence_id, _ = seeded.save_capture_evidence(sha256="a" * 64, source_type=EvidenceSource.SYNTHETIC_TEST)
            observation_id, _ = seeded.save_ocr_observation(
                evidence_id=evidence_id, field=None, text="synthetic OCR", confidence=0.9,
                bbox=[0.1, 0.1, 0.2, 0.1], source_type=EvidenceSource.SYNTHETIC_TEST,
            )
            seeded.connection.execute("DELETE FROM schema_migrations WHERE version=3")
            seeded.connection.execute("DELETE FROM schema_migrations WHERE version=4")
            seeded.connection.execute("DROP TABLE private_fixture_assets")
            seeded.connection.execute("DROP TABLE capture_session_frames")
            seeded.connection.execute("DROP TABLE screen_observations")
            seeded.connection.execute("DROP TABLE ocr_field_candidates")
            seeded.connection.execute("DROP TRIGGER IF EXISTS immutable_screen_observations_update")
            seeded.connection.execute("DROP TRIGGER IF EXISTS immutable_screen_observations_delete")
            seeded.connection.execute("DROP TRIGGER IF EXISTS immutable_ocr_field_candidates_update")
            seeded.connection.execute("DROP TRIGGER IF EXISTS immutable_ocr_field_candidates_delete")
            seeded.connection.commit()
            self.assertEqual(seeded.schema_version(), 2)
        with SQLiteStore(path) as migrated:
            self.assertEqual(migrated.initialize(), 4)
            self.assertEqual(migrated.schema_version(), 4)
            self.assertEqual(migrated.connection.execute("SELECT text FROM ocr_observations WHERE id=?", (observation_id,)).fetchone()[0], "synthetic OCR")

    def test_schema_v3_migration_preserves_rows_and_supports_unresolved_years(self):
        evidence_id, _ = self.store.save_capture_evidence(sha256="b" * 64,
                                                           source_type=EvidenceSource.SYNTHETIC_TEST)
        observation_id, _ = self.store.save_ocr_observation(
            evidence_id=evidence_id, field=None, text="이름'80", confidence=0.99,
            bbox=[0.4, 0.4, 0.1, 0.03], source_type=EvidenceSource.SYNTHETIC_TEST,
        )
        screen_id, _ = self.store.save_screen_observation(
            evidence_id=evidence_id, screen_state="UNKNOWN", status="UNKNOWN", confidence=None,
            profile_version="before-v4", anchor_indices=[],
        )
        self.store.save_ocr_field_candidate(
            observation_id=observation_id, field_key="season_year", value=None, status="UNRESOLVED",
            confidence=0.99, source_type=EvidenceSource.SYNTHETIC_TEST,
            derivation_version="year-test", context={"raw_value": "이름'80", "year_candidates": []},
        )
        self.store.connection.execute("DELETE FROM schema_migrations WHERE version=4")
        self.store.connection.execute("DROP TABLE private_fixture_assets")
        self.store.connection.execute("DROP TABLE capture_session_frames")
        self.store.connection.commit()
        self.assertEqual(self.store.schema_version(), 3)

        self.assertEqual(self.store.initialize(), 4)

        self.assertEqual(self.store.connection.execute("SELECT id FROM screen_observations WHERE id=?", (screen_id,)).fetchone()[0], screen_id)
        row = self.store.connection.execute(
            "SELECT status,context_json FROM ocr_field_candidates WHERE observation_id=?", (observation_id,),
        ).fetchone()
        self.assertEqual(row["status"], "UNRESOLVED")
        self.assertIn("year_candidates", row["context_json"])
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

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

    def _verified_capture_fixture(self):
        account_id = self.store.ensure_account("capture-account", "Local capture")
        card_master_id = self.store.connection.execute(
            "INSERT INTO card_masters(canonical_name,team_name,card_type,season_year,created_at) VALUES(?,?,?,?,?)",
            ("후라도", "삼성", "LIVE", 2026, "now"),
        ).lastrowid
        card_instance_id = self.store.connection.execute(
            """INSERT INTO card_instances(account_id,card_master_id,instance_key,stars,live_version,enhancement,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (account_id, card_master_id, "hurado-live-v2-5star-plus5", 5, "V2", 5, "now"),
        ).lastrowid
        assets = PrivateFixtureStore(self.store, self.path.parent / "private-fixtures")
        page_proofs = []
        observation_ids = {}
        for page in (1, 2):
            image = b"\x89PNG\r\n\x1a\nsynthetic-page-" + str(page).encode()
            sha256 = hashlib.sha256(image).hexdigest()
            evidence_id, _ = self.store.save_capture_evidence(
                sha256=sha256, source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED, media_type="image/png",
            )
            assets.save(
                evidence_id=evidence_id, image_bytes=image,
                metadata=PrivateFixtureMetadata(
                    captured_at=f"2026-10-13T12:00:0{page}+09:00", window_size=(640, 480),
                    screen_state=ScreenState.PLAYER_DETAIL_PITCHER,
                    ocr_engine_version="synthetic-vision-v1", roi=(0.1, 0.1, 0.8, 0.8),
                    ocr_document={"observations": []},
                ),
            )
            screen_id, _ = self.store.save_screen_observation(
                evidence_id=evidence_id, screen_state="PLAYER_DETAIL_PITCHER", status="VERIFIED",
                confidence=0.99, profile_version=f"verified-detail-page-{page}",
                anchor_indices=[0, 1], panel_layout={"active": [0.1, 0.1, 0.8, 0.8]},
            )
            identity_observation_id, _ = self.store.save_ocr_observation(
                evidence_id=evidence_id, field="card_label", text="후라도'26", confidence=0.99,
                bbox=[0.2, 0.2, 0.2, 0.05], source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED,
            )
            page_proofs.append({
                "status": "VERIFIED", "reviewed_from_image": True,
                "player_key": "후라도-2026-live-v2", "canonical_name": "후라도",
                "page": page, "evidence_id": evidence_id, "screen_observation_id": screen_id,
                "identity_observation_id": identity_observation_id,
            })
            observation_id, _ = self.store.save_ocr_observation(
                evidence_id=evidence_id, field="overall", text="101", confidence=0.99,
                bbox=[0.2, 0.2, 0.1, 0.05], source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED,
            )
            observation_ids[page] = (observation_id, evidence_id, screen_id)
        identity = {
            "status": "VERIFIED", "reviewed_from_image": True,
            "player_key": "후라도-2026-live-v2", "canonical_name": "후라도",
            "season_year": 2026, "card_type": "LIVE", "stars": 5, "live_version": "V2", "enhancement": 5,
        }
        field_proofs = {
            "overall": {"status": "VERIFIED", "reviewed_from_image": True, "value": 101,
                        "confidence": 0.99, "ocr_text": "101", "observation_id": observation_ids[1][0],
                        "evidence_id": observation_ids[1][1], "screen_observation_id": observation_ids[1][2],
                        "page": 1, "player_key": "후라도-2026-live-v2", "panel_role": "ACTIVE"},
        }
        return account_id, card_instance_id, identity, page_proofs, field_proofs

    def test_verified_partial_player_snapshot_requires_image_and_field_proofs_and_is_idempotent(self):
        account_id, card_id, identity, pages, field_proofs = self._verified_capture_fixture()
        args = {
            "account_id": account_id, "card_instance_id": card_id, "payload": {"overall": 101},
            "identity": identity, "page_proofs": pages, "field_proofs": field_proofs,
            "confidence": 0.99, "game_version": "V26",
        }

        snapshot_id, inserted = self.store.save_verified_player_snapshot(**args)
        same_id, inserted_again = self.store.save_verified_player_snapshot(**args)

        self.assertTrue(inserted)
        self.assertFalse(inserted_again)
        self.assertEqual(snapshot_id, same_id)
        row = self.store.connection.execute(
            "SELECT source_type,payload_json FROM player_snapshots WHERE id=?", (snapshot_id,),
        ).fetchone()
        stored = json.loads(row["payload_json"])
        self.assertEqual(row["source_type"], EvidenceSource.SCREEN_CAPTURE_VERIFIED.value)
        self.assertEqual(stored["overall"], 101)
        self.assertEqual(stored["_verification"]["status"], "VERIFIED")
        self.assertEqual(len(stored["_verification"]["page_proofs"]), 2)
        self.assertEqual(set(stored["_verification"]["field_proofs"]), {"overall"})
        self.assertEqual(self.store.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_unverified_capture_fields_and_unverified_generic_promotion_are_blocked(self):
        account_id, card_id, identity, pages, field_proofs = self._verified_capture_fixture()
        unverified = {**field_proofs, "overall": {**field_proofs["overall"], "status": "CANDIDATE"}}
        with self.assertRaisesRegex(ValueError, "explicitly verified"):
            self.store.save_verified_player_snapshot(
                account_id=account_id, card_instance_id=card_id, payload={"overall": 101}, identity=identity,
                page_proofs=pages, field_proofs=unverified,
            )
        with self.assertRaisesRegex(ValueError, "save_verified_player_snapshot"):
            self.store.save_player_snapshot(
                account_id=account_id, card_instance_id=card_id, payload={"overall": 101},
                source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED,
            )
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM player_snapshots").fetchone()[0], 0)

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
