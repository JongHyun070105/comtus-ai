import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from comtus_ai.database import SQLiteStore
from comtus_ai.models import EvidenceSource
from comtus_ai.observations import load_ocr_document
from comtus_ai.optimizer import Opponent, Pitcher, optimize_rotation


class SyntheticPipelineTests(unittest.TestCase):
    def test_synthetic_ocr_to_database_to_rotation_json_report(self):
        synthetic_capture = b"fixture-only-not-a-real-game-screen"
        capture_hash = hashlib.sha256(synthetic_capture).hexdigest()
        document = {"schema_version": 1, "source": "SYNTHETIC_TEST", "screen_state": "UNKNOWN", "frame_size": [1280, 720],
                    "observations": [{"schema_version": 1, "text": "Pitcher A", "confidence": 0.9,
                                      "bbox": [0.2, 0.3, 0.2, 0.05], "source": "SYNTHETIC_TEST", "field": "player_name"}]}
        observations = load_ocr_document(json.dumps(document))
        with tempfile.TemporaryDirectory() as temp:
            with SQLiteStore(Path(temp) / "integration.sqlite3") as store:
                store.initialize()
                account_id = store.ensure_account("synthetic-account", "Synthetic Team")
                evidence_id = store.connection.execute("INSERT INTO capture_evidence(account_id,sha256,source_type,created_at) VALUES(?,?,?,?)", (account_id, capture_hash, "SYNTHETIC_TEST", "now")).lastrowid
                store.connection.commit()
                for row in observations:
                    store.save_ocr_observation(evidence_id=evidence_id, field=row.field, text=row.text, confidence=row.confidence,
                                               bbox=list(row.bbox), source_type=row.source)
                store.save_team_snapshot(account_id=account_id, snapshot_kind="SYNTHETIC_TEST", payload={"roster": ["card-0"]}, source_type=EvidenceSource.SYNTHETIC_TEST)
                pitchers = [Pitcher(f"card-{i}", f"Pitcher {i}") for i in range(5)]
                opponents = [Opponent(f"opp-{i}", f"Opponent {i}") for i in range(5)]
                scores = {(p.card_id, o.opponent_id): float((i + j) % 3) for i, p in enumerate(pitchers) for j, o in enumerate(opponents)}
                rotation = optimize_rotation(pitchers, opponents, scores)
                report = rotation.to_dict(pitchers, opponents)
                encoded = json.dumps(report)
                self.assertEqual(store.counts()["ocr_observations"], 1)
                self.assertEqual(store.counts()["team_snapshots"], 1)
                self.assertIn('"probability_calibrated": false', encoded)
                self.assertEqual(report["score_type"], "HEURISTIC_SCORE")


if __name__ == "__main__":
    unittest.main()
