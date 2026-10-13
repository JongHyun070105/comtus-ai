import hashlib
import json
import platform
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from comtus_ai.cli import _analyze_saved_ocr, _swift_command, _swift_manifest_path, _valid_swift_binary, main
from comtus_ai.database import SQLiteStore
from comtus_ai.models import EvidenceSource
from comtus_ai.observations import load_ocr_document
from comtus_ai.optimizer import Opponent, Pitcher, optimize_rotation
from comtus_ai.parsing import card_identity_candidate, parse_ocr_fields
from comtus_ai.screens import NormalizedRect, PanelRole, recognize_screen
from comtus_ai.navigation import PlayerPageTracker, ScreenFrame
from comtus_ai.screens import ClassificationStatus, ScreenState


class SyntheticPipelineTests(unittest.TestCase):
    def test_swift_binary_requires_matching_source_and_binary_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "mac-capture"
            payload = b"synthetic binary"
            binary.write_bytes(payload)
            manifest = {
                "schema_version": 1,
                "source_sha256": "a" * 64,
                "binary_sha256": hashlib.sha256(payload).hexdigest(),
            }
            _swift_manifest_path(binary).write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(_valid_swift_binary(binary, "a" * 64))
            self.assertFalse(_valid_swift_binary(binary, "b" * 64))
            binary.write_bytes(b"changed binary")
            self.assertFalse(_valid_swift_binary(binary, "a" * 64))

    def test_synthetic_player_card_fixture_reaches_account_scoped_snapshot(self):
        fixture = Path(__file__).parent / "fixtures" / "player-card-ocr.synthetic.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        observations = load_ocr_document(json.dumps(document))
        active_panel = NormalizedRect(*document["active_panel"])
        fields = parse_ocr_fields(observations, active_panel=active_panel)
        values = {field.field_key: field.value for field in fields
                  if field.value is not None and field.panel_role == PanelRole.ACTIVE}
        identity = card_identity_candidate(fields)
        self.assertEqual(identity.canonical_name, "홍길동")
        self.assertEqual(identity.season_year, 2025)
        self.assertIsNone(identity.instance_key)
        self.assertEqual(values["card_type"], "SIGNATURE")
        self.assertEqual(values["stars"], 5)
        self.assertEqual(values["enhancement"], 8)
        self.assertEqual(values["overall"], 112.5)

        tracker = PlayerPageTracker()
        frame = ScreenFrame(ScreenState.PLAYER_DETAIL_BATTER, ClassificationStatus.VERIFIED,
                            "synthetic:fixture-player", True, 1, True, PanelRole.ACTIVE)
        self.assertTrue(tracker.observe(frame).accepted)
        self.assertTrue(tracker.can_commit_player_fields)

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "synthetic-player.sqlite3"
            with SQLiteStore(database) as store:
                store.initialize()
                account_id = store.ensure_account("synthetic:fixture-account", "Synthetic Team")
                master_id = store.connection.execute(
                    "INSERT INTO card_masters(canonical_name,team_name,card_type,season_year,created_at) VALUES(?,?,?,?,?)",
                    (identity.canonical_name, "Synthetic Team", values["card_type"], identity.season_year, "fixture"),
                ).lastrowid
                card_id = store.connection.execute(
                    "INSERT INTO card_instances(account_id,card_master_id,instance_key,stars,enhancement,created_at) VALUES(?,?,?,?,?,?)",
                    (account_id, master_id, "synthetic:fixture-card-1", values["stars"], values["enhancement"], "fixture"),
                ).lastrowid
                field_provenance = {
                    field.field_key: {
                        "value": field.value, "status": field.status.value, "confidence": field.confidence,
                        "source": field.source.value, "observation_indices": list(field.observation_indices),
                        "panel_role": field.panel_role.value,
                    }
                    for field in fields
                }
                snapshot_id, inserted = store.save_player_snapshot(
                    account_id=account_id, card_instance_id=card_id,
                    payload={"role": "BATTER", "overall": values["overall"], "field_provenance": field_provenance,
                             "instance_identity_source": "SYNTHETIC_FIXTURE"},
                    source_type=EvidenceSource.SYNTHETIC_TEST, confidence=0.99,
                )
                self.assertTrue(inserted)
                snapshot = store.connection.execute(
                    "SELECT source_type,payload_json FROM player_snapshots WHERE id=?", (snapshot_id,),
                ).fetchone()
                self.assertEqual(snapshot["source_type"], EvidenceSource.SYNTHETIC_TEST.value)
                self.assertEqual(json.loads(snapshot["payload_json"])["overall"], 112.5)
                self.assertEqual(store.counts()["player_snapshots"], 1)

    def test_saved_ocr_analysis_is_append_only_idempotent_and_private_in_output(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "private-analysis.sqlite3"
            with SQLiteStore(database) as store:
                store.initialize()
                evidence_id, _ = store.save_capture_evidence(
                    sha256=hashlib.sha256(b"synthetic-analysis-frame").hexdigest(),
                    source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED,
                )
                rows = (
                    ("{ 선발 투수 변경", 0.5, [0.365, 0.825, 0.244, 0.028]),
                    ("좌측에 표시되는 내 선발 투수의 순서를 변경할 수 있습니다.", 1.0, [0.289, 0.789, 0.435, 0.016]),
                    ("원래대로", 1.0, [0.245, 0.056, 0.080, 0.019]),
                    ("저장", 0.5, [0.696, 0.056, 0.042, 0.019]),
                    ("김선수'24", 0.5, [0.2, 0.4, 0.1, 0.03]),
                )
                for text, confidence, bbox in rows:
                    store.save_ocr_observation(evidence_id=evidence_id, field=None, text=text,
                                               confidence=confidence, bbox=bbox,
                                               source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED)

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(_analyze_saved_ocr(database), 0)
            first = json.loads(output.getvalue())
            self.assertEqual(first["evidence_frames_analyzed"], 1)
            self.assertEqual(first["screen_classifications_by_state"], {"PITCHER_ORDER:CANDIDATE": 1})
            self.assertGreater(first["field_candidates_inserted"], 0)
            self.assertEqual(first["player_snapshots_created"], 0)
            self.assertFalse(first["raw_ocr_text_emitted"])
            self.assertNotIn("김선수", output.getvalue())

            repeated = StringIO()
            with redirect_stdout(repeated):
                self.assertEqual(_analyze_saved_ocr(database), 0)
            second = json.loads(repeated.getvalue())
            self.assertEqual(second["screen_classifications_inserted"], 0)
            self.assertEqual(second["field_candidates_inserted"], 0)
            with SQLiteStore(database) as store:
                self.assertEqual(store.counts()["capture_evidence"], 1)
                self.assertEqual(store.counts()["player_snapshots"], 0)

    def test_synthetic_ocr_candidates_keep_provenance_and_do_not_create_player_facts(self):
        document = {"schema_version": 1, "source": "SYNTHETIC_TEST", "screen_state": "UNKNOWN", "frame_size": [1280, 720],
                    "observations": [
                        {"schema_version": 1, "text": "홍길동'25", "confidence": 0.99,
                         "bbox": [0.42, 0.4, 0.12, 0.03], "source": "SYNTHETIC_TEST"},
                        {"schema_version": 1, "text": "시그니처", "confidence": 0.99,
                         "bbox": [0.42, 0.35, 0.12, 0.03], "source": "SYNTHETIC_TEST"},
                    ]}
        observations = load_ocr_document(json.dumps(document))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "parsing.sqlite3"
            with SQLiteStore(database) as store:
                store.initialize()
                account = store.ensure_account("synthetic-account", "Synthetic Team")
                evidence_id, _ = store.save_capture_evidence(sha256=hashlib.sha256(b"synthetic").hexdigest(),
                                                             source_type=EvidenceSource.SYNTHETIC_TEST)
                observation_ids = []
                for row in observations:
                    observation_id, _ = store.save_ocr_observation(
                        evidence_id=evidence_id, field=row.field, text=row.text, confidence=row.confidence,
                        bbox=list(row.bbox), source_type=row.source,
                    )
                    observation_ids.append(observation_id)
                screen = recognize_screen(observations)
                store.save_screen_observation(evidence_id=evidence_id, screen_state=screen.state.value,
                                              status=screen.status.value, confidence=screen.confidence,
                                              profile_version=screen.profile_version,
                                              anchor_indices=list(screen.anchor_indices))
                candidates = parse_ocr_fields(observations)
                for candidate in candidates:
                    observation_id = observation_ids[candidate.observation_indices[0]]
                    store.save_ocr_field_candidate(
                        observation_id=observation_id, field_key=candidate.field_key, value=candidate.value,
                        status=candidate.status.value, confidence=candidate.confidence, source_type=candidate.source,
                        derivation_version=candidate.derivation_version, context=candidate.context_dict(),
                    )
                self.assertEqual(store.schema_version(), 4)
                self.assertEqual(store.counts()["ocr_field_candidates"], 3)
                self.assertEqual(store.counts()["screen_observations"], 1)
                self.assertEqual(store.counts()["card_masters"], 0)
                self.assertEqual(store.counts()["card_instances"], 0)
                self.assertEqual(store.counts()["player_snapshots"], 0)
                self.assertEqual(account, 1)
                name_value = store.connection.execute(
                    "SELECT value_json,status,source_type FROM ocr_field_candidates WHERE field_key='player_name'"
                ).fetchone()
                self.assertEqual(name_value["value_json"], '"홍길동"')
                self.assertEqual(name_value["status"], "CANDIDATE")
                self.assertEqual(name_value["source_type"], "SYNTHETIC_TEST")

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

    @unittest.skipUnless(platform.system() == "Darwin", "Swift Vision integration requires macOS")
    def test_swift_vision_json_to_python_sqlite_roundtrip_and_deduplication(self):
        image = Path(__file__).parent / "fixtures" / "vision-test.png"
        swift_command = _swift_command(["doctor"])
        if not image.is_file() or not swift_command or not Path(swift_command[0]).is_file():
            self.skipTest("built mac-capture executable or synthetic image fixture is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "swift-integration.sqlite3"
            arguments = ["capture", "ocr", str(image), "--screen-state", "RANKING_LOBBY", "--store",
                         "--evidence-source", "SYNTHETIC_TEST", "--database", str(database)]
            first_stdout = StringIO()
            with redirect_stdout(first_stdout):
                self.assertEqual(main(arguments), 0)
            first = json.loads(first_stdout.getvalue())
            self.assertEqual(first["screen_state"], "UNKNOWN")
            self.assertEqual(first["screen_status"], "UNKNOWN")
            self.assertEqual(first["persistence"]["status"], "EXEC_PASS")
            self.assertEqual(first["persistence"]["screen_state"], "UNKNOWN")
            self.assertEqual(first["persistence"]["player_snapshots_created"], 0)
            self.assertTrue(first["persistence"]["capture_inserted"])
            self.assertGreater(first["persistence"]["observations_inserted"], 0)

            second_stdout = StringIO()
            with redirect_stdout(second_stdout):
                self.assertEqual(main(arguments), 0)
            second = json.loads(second_stdout.getvalue())
            self.assertFalse(second["persistence"]["capture_inserted"])
            self.assertEqual(second["persistence"]["observations_inserted"], 0)
            self.assertEqual(second["persistence"]["observations_duplicated"],
                             len(second["observations"]))

            with SQLiteStore(database) as store:
                self.assertEqual(store.counts()["capture_evidence"], 1)
                self.assertEqual(store.counts()["ocr_observations"], len(first["observations"]))


if __name__ == "__main__":
    unittest.main()
