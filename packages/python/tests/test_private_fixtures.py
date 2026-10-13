import hashlib
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from comtus_ai.database import SQLiteStore
from comtus_ai.models import EvidenceSource
from comtus_ai.private_fixtures import PrivateFixtureMetadata, PrivateFixtureStore
from comtus_ai.screens import ScreenState


class PrivateFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "data" / "private-fixtures"
        self.store = SQLiteStore(Path(self.temporary.name) / "test.sqlite3")
        self.store.initialize()
        self.image = (Path(__file__).parent / "fixtures" / "vision-test.png").read_bytes()
        digest = hashlib.sha256(self.image).hexdigest()
        self.evidence_id, _ = self.store.save_capture_evidence(
            sha256=digest, source_type=EvidenceSource.SYNTHETIC_TEST,
        )
        self.metadata = PrivateFixtureMetadata(
            captured_at="2026-10-13T01:02:03+00:00",
            window_size=(640, 240),
            screen_state=ScreenState.UNKNOWN,
            ocr_engine_version="test-engine-v1",
            roi=(0.1, 0.1, 0.8, 0.8),
            ocr_document={"observations": [{"text": "synthetic-only"}]},
        )

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_private_image_and_metadata_are_linked_idempotently_and_deletion_keeps_db_consistent(self):
        fixtures = PrivateFixtureStore(self.store, self.root, max_bytes=len(self.image) + 1)

        path, inserted = fixtures.save(evidence_id=self.evidence_id, image_bytes=self.image, metadata=self.metadata)
        duplicate_path, duplicate_inserted = fixtures.save(
            evidence_id=self.evidence_id, image_bytes=self.image, metadata=self.metadata,
        )

        self.assertTrue(inserted)
        self.assertFalse(duplicate_inserted)
        self.assertEqual(path, duplicate_path)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        row = self.store.connection.execute(
            "SELECT sha256,captured_at,window_size_json,screen_state,ocr_engine_version,roi_json,ocr_document_json,status "
            "FROM private_fixture_assets WHERE evidence_id=?", (self.evidence_id,),
        ).fetchone()
        self.assertEqual(row["sha256"], hashlib.sha256(self.image).hexdigest())
        self.assertEqual(row["captured_at"], self.metadata.captured_at)
        self.assertEqual(row["screen_state"], ScreenState.UNKNOWN.value)
        self.assertEqual(row["status"], "PRESENT")

        self.assertTrue(fixtures.delete_image(self.evidence_id))
        self.assertFalse(path.exists())
        self.assertEqual(self.store.connection.execute(
            "SELECT status FROM private_fixture_assets WHERE evidence_id=?", (self.evidence_id,),
        ).fetchone()[0], "DELETED")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_evidence").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_storage_limit_and_hash_mismatch_fail_without_creating_an_asset(self):
        too_small = PrivateFixtureStore(self.store, self.root, max_bytes=len(self.image) - 1)
        with self.assertRaises(OSError):
            too_small.save(evidence_id=self.evidence_id, image_bytes=self.image, metadata=self.metadata)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM private_fixture_assets").fetchone()[0], 0)
        self.assertFalse(self.root.joinpath(f"{hashlib.sha256(self.image).hexdigest()}.png").exists())

        with self.assertRaises(ValueError):
            PrivateFixtureStore(self.store, self.root).save(
                evidence_id=self.evidence_id, image_bytes=self.image + b"different", metadata=self.metadata,
            )

    def test_missing_image_reconciliation_retains_capture_metadata(self):
        fixtures = PrivateFixtureStore(self.store, self.root)
        path, _ = fixtures.save(evidence_id=self.evidence_id, image_bytes=self.image, metadata=self.metadata)
        path.unlink()

        report = fixtures.reconcile()

        self.assertEqual(report, {"verified_images": 0, "marked_deleted": 1})
        row = self.store.connection.execute(
            "SELECT status,ocr_document_json FROM private_fixture_assets WHERE evidence_id=?", (self.evidence_id,),
        ).fetchone()
        self.assertEqual(row["status"], "DELETED")
        self.assertIn("synthetic-only", row["ocr_document_json"])


if __name__ == "__main__":
    unittest.main()
