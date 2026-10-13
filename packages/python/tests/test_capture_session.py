import hashlib
import stat
import tempfile
import unittest
from collections import deque
from pathlib import Path

from comtus_ai.capture_session import (
    CaptureSessionConfig,
    CaptureWindow,
    CapturedFrame,
    ReadOnlyCaptureSession,
    V26_BUNDLE_IDENTIFIER,
)
from comtus_ai.database import SQLiteStore
from comtus_ai.screens import SCREEN_PROFILE_VERSION


def ocr_document(*, state="UNKNOWN", status="UNKNOWN", confidence=None, anchors=None):
    return {
        "schema_version": 1,
        "source": "vision",
        "screen_state": state,
        "screen_status": status,
        "screen_confidence": confidence,
        "screen_anchor_indices": anchors or [],
        "screen_profile_version": SCREEN_PROFILE_VERSION,
        "ocr_engine_version": "synthetic-vision-v1",
        "frame_size": [640, 480],
        "active_panel": None,
        "observations": [],
    }


class FakeCaptureAdapter:
    def __init__(self, windows, images, documents=None, frame_size=(640, 480), visual_signatures=None,
                 key_region_signatures=None):
        self.windows = deque(windows)
        self.images = deque(images)
        self.documents = documents or {}
        self.frame_size = frame_size
        self.visual_signatures = deque(visual_signatures or [])
        self.key_region_signatures = deque(key_region_signatures or [])
        self.ocr_calls = []
        self.capture_calls = []

    def list_windows(self):
        if len(self.windows) > 1:
            return self.windows.popleft()
        return self.windows[0] if self.windows else []

    def capture_window(self, window_id, process_id, bundle_id=None):
        self.capture_calls.append((window_id, process_id, bundle_id))
        image = self.images.popleft()
        signature = self.visual_signatures.popleft() if self.visual_signatures else None
        key_region = self.key_region_signatures.popleft() if self.key_region_signatures else None
        return CapturedFrame(image, *self.frame_size, "2026-10-13T00:00:00+00:00", signature, key_region)

    def run_ocr(self, image_bytes):
        self.ocr_calls.append(image_bytes)
        return self.documents.get(image_bytes, ocr_document())


class CaptureSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "capture.sqlite3"
        self.store = SQLiteStore(self.database)
        self.store.initialize()
        self.window = CaptureWindow(12, "V26", "컴프야V26", 810, 1112,
                                    process_id=81562, bundle_id=V26_BUNDLE_IDENTIFIER)

    def test_window_identity_uses_exact_process_and_separately_checks_bundle_id(self):
        terminal = CaptureWindow(7, "iTerm2", "capture V26", 1800, 1100, process_id=68771)
        misleading_process = CaptureWindow(8, "V26 Helper", "컴프야V26", 810, 1112, process_id=81562)
        wrong_case = CaptureWindow(10, "v26", "컴프야V26", 810, 1112, process_id=81562)
        wrong_bundle = CaptureWindow(9, "V26", "컴프야V26", 810, 1112,
                                     process_id=81562, bundle_id="com.example.not-v26")
        self.assertFalse(terminal.is_v26)
        self.assertFalse(misleading_process.is_v26)
        self.assertFalse(wrong_case.is_v26)
        self.assertFalse(wrong_bundle.is_v26)
        self.assertTrue(self.window.is_v26)

    def test_smaller_game_window_is_selected_over_larger_terminal(self):
        terminal = CaptureWindow(7, "iTerm2", "v26 capture session", 1800, 1100, process_id=68771)
        adapter = FakeCaptureAdapter(windows=[[terminal, self.window]], images=[b"frame-a", b"frame-a"])
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001),
        ).run(max_polls=2)

        self.assertEqual(report.status, "EXEC_PASS")
        self.assertEqual(adapter.capture_calls, [(12, 81562, V26_BUNDLE_IDENTIFIER)] * 2)

    def test_multiple_game_windows_are_ambiguous_and_fail_closed(self):
        second_game = CaptureWindow(13, "V26", "컴프야V26 (2)", 900, 1000,
                                    process_id=81563, bundle_id=V26_BUNDLE_IDENTIFIER)
        adapter = FakeCaptureAdapter(windows=[[self.window, second_game]], images=[])
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001),
        ).run(max_polls=1)

        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.ambiguous_window_polls, 1)
        self.assertEqual(adapter.capture_calls, [])

    def test_pid_change_for_same_window_id_is_detected_before_capture(self):
        replacement = CaptureWindow(12, "V26", "컴프야V26", 810, 1112,
                                    process_id=81563, bundle_id=V26_BUNDLE_IDENTIFIER)
        adapter = FakeCaptureAdapter(
            windows=[[self.window], [self.window], [replacement], [replacement]],
            images=[b"frame-a"] * 4,
        )
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001),
        ).run(max_polls=4)

        self.assertEqual(report.window_identity_changes, 1)
        self.assertEqual(adapter.capture_calls,
                         [(12, 81562, V26_BUNDLE_IDENTIFIER), (12, 81562, V26_BUNDLE_IDENTIFIER),
                          (12, 81563, V26_BUNDLE_IDENTIFIER), (12, 81563, V26_BUNDLE_IDENTIFIER)])

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_session_waits_for_stability_skips_duplicate_frames_and_records_metrics(self):
        adapter = FakeCaptureAdapter(
            windows=[[self.window]] * 5 + [[]],
            images=[b"frame-a", b"frame-a", b"frame-a", b"frame-b", b"frame-b"],
        )
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001, stable_samples=2),
        ).run(max_polls=6)

        self.assertEqual(report.status, "EXEC_PASS")
        self.assertEqual(report.polls, 6)
        self.assertEqual(report.captured_frames, 5)
        self.assertEqual(report.stable_frames, 2)
        self.assertEqual(report.ocr_frames, 2)
        self.assertEqual(report.duplicate_frames, 1)
        self.assertEqual(report.no_window_polls, 1)
        self.assertEqual(adapter.ocr_calls, [b"frame-a", b"frame-b"])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_evidence").fetchone()[0], 2)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_session_frames WHERE status='COMPLETE'").fetchone()[0], 2)
        self.assertGreaterEqual(report.cpu_percent, 0)

    def test_visual_signature_ignores_small_animation_but_detects_screen_changes(self):
        stable = bytes(1000)
        animated = bytearray(stable)
        animated[:4] = bytes([80, 80, 80, 80])
        animated_twice = bytearray(stable)
        animated_twice[:4] = bytes([88, 88, 88, 88])
        animated_thrice = bytearray(stable)
        animated_thrice[:4] = bytes([96, 96, 96, 96])
        changed_screen = bytes([255]) * 1000
        adapter = FakeCaptureAdapter(
            windows=[[self.window]] * 6,
            images=[b"frame-a", b"frame-a-animated", b"frame-a-animated-2", b"frame-a-animated-3",
                    b"frame-b", b"frame-b-animated"],
            visual_signatures=[stable, bytes(animated), bytes(animated_twice), bytes(animated_thrice),
                               changed_screen, changed_screen],
        )

        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001, stable_samples=2),
        ).run(max_polls=6)

        self.assertEqual(report.status, "EXEC_PASS")
        self.assertEqual(report.ocr_frames, 2)
        self.assertEqual(report.duplicate_frames, 2)
        self.assertEqual(adapter.ocr_calls,
                         [b"frame-a-animated", b"frame-a-animated-2", b"frame-a-animated-3",
                          b"frame-b-animated"])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_evidence").fetchone()[0], 2)

    def test_small_numeric_change_within_visual_tolerance_is_not_suppressed(self):
        signature = bytes(1000)
        first = ocr_document()
        first["observations"] = [{"schema_version": 1, "source": "vision", "field": "stat",
                                  "text": "100", "confidence": 0.99, "bbox": [0.4, 0.4, 0.1, 0.1]}]
        second = ocr_document()
        second["observations"] = [{"schema_version": 1, "source": "vision", "field": "stat",
                                   "text": "101", "confidence": 0.99, "bbox": [0.4, 0.4, 0.1, 0.1]}]
        adapter = FakeCaptureAdapter(
            windows=[[self.window]] * 4,
            images=[b"number-100-a", b"number-100-b", b"number-101-a", b"number-101-b"],
            documents={b"number-100-b": first, b"number-101-a": second, b"number-101-b": second},
            visual_signatures=[signature] * 4,
        )
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001),
        ).run(max_polls=4)

        self.assertEqual(report.ocr_frames, 2)
        self.assertEqual(adapter.ocr_calls, [b"number-100-b", b"number-101-a", b"number-101-b"])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_evidence").fetchone()[0], 2)

    def test_page_and_player_text_changes_are_not_deduplicated_by_same_background_signature(self):
        docs = {}
        images = [b"hurado-page-1-a", b"hurado-page-1-b", b"hurado-page-2", b"different-player"]
        labels = ["후라도'26 페이지1", "후라도'26 페이지1", "후라도'26 페이지2", "다른선수'26 페이지2"]
        for image, label in zip(images, labels, strict=True):
            doc = ocr_document()
            doc["observations"] = [{"schema_version": 1, "source": "vision", "field": "card_label",
                                    "text": label, "confidence": 0.98, "bbox": [0.2, 0.2, 0.4, 0.1]}]
            docs[image] = doc
        adapter = FakeCaptureAdapter(
            windows=[[self.window]] * len(images), images=images, documents=docs,
            visual_signatures=[bytes(1000)] * len(images),
        )
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001),
        ).run(max_polls=len(images))

        self.assertEqual(report.ocr_frames, 3)
        self.assertEqual(len(adapter.ocr_calls), 3)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_evidence").fetchone()[0], 3)

    def test_changed_key_region_is_kept_for_manual_review_even_when_ocr_text_matches(self):
        repeated_text = ocr_document()
        repeated_text["observations"] = [{"schema_version": 1, "source": "vision", "field": "stat",
                                          "text": "100", "confidence": 0.5, "bbox": [0.4, 0.4, 0.1, 0.1]}]
        images = [b"roi-a-1", b"roi-a-2", b"roi-b-1", b"roi-b-2"]
        changed_region = bytearray(1000)
        changed_region[:20] = bytes([255]) * 20
        adapter = FakeCaptureAdapter(
            windows=[[self.window]] * 4, images=images,
            documents={image: repeated_text for image in images},
            visual_signatures=[bytes(1000)] * 4,
            key_region_signatures=[bytes(1000), bytes(1000), bytes(changed_region), bytes(changed_region)],
        )
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001),
        ).run(max_polls=4)

        self.assertEqual(report.ocr_frames, 2)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_evidence").fetchone()[0], 2)
        self.assertEqual(report.duplicate_frames, 1)

    def test_session_rewaits_for_a_window_and_fails_closed_on_classifier_disagreement(self):
        mismatch = ocr_document(state="PITCHER_ORDER", status="CANDIDATE", confidence=0.5, anchors=[0, 1, 2, 3])
        adapter = FakeCaptureAdapter(
            windows=[[], [], [self.window], [self.window]],
            images=[b"frame-c", b"frame-c"],
            documents={b"frame-c": mismatch},
        )
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001, stable_samples=2),
        ).run(max_polls=4)

        self.assertEqual(report.status, "EXEC_PASS")
        self.assertEqual(report.no_window_polls, 2)
        self.assertEqual(report.ocr_frames, 1)
        self.assertEqual(report.screen_profile_mismatches, 1)
        row = self.store.connection.execute("SELECT screen_state,status FROM screen_observations").fetchone()
        self.assertEqual(tuple(row), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual(self.store.capture_frame_is_processed(
            sha256=hashlib.sha256(b"frame-c").hexdigest(),
            profile_version=SCREEN_PROFILE_VERSION,
        ), True)

    def test_missing_v26_window_is_reported_without_mutating_capture_data(self):
        adapter = FakeCaptureAdapter(windows=[[]], images=[])
        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001),
        ).run(max_polls=1)
        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.no_window_polls, 1)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_evidence").fetchone()[0], 0)

    def test_session_can_keep_a_restricted_local_png_linked_to_ocr_and_window_metadata(self):
        image = (Path(__file__).parent / "fixtures" / "vision-test.png").read_bytes()
        root = Path(self.temporary.name) / "private-fixtures"
        adapter = FakeCaptureAdapter(
            windows=[[self.window], [self.window]], images=[image, image], frame_size=(640, 240),
        )
        report = ReadOnlyCaptureSession(
            adapter, self.store,
            CaptureSessionConfig(poll_interval_seconds=0.001, stable_samples=2,
                                 preserve_images=True, private_fixture_root=root),
        ).run(max_polls=2)

        self.assertEqual(report.ocr_frames, 1)
        row = self.store.connection.execute(
            "SELECT relative_path,sha256,captured_at,window_size_json,screen_state,ocr_engine_version,status "
            "FROM private_fixture_assets",
        ).fetchone()
        path = root.parent.parent / row["relative_path"]
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(row["sha256"], hashlib.sha256(image).hexdigest())
        self.assertEqual(row["captured_at"], "2026-10-13T00:00:00+00:00")
        self.assertEqual(row["window_size_json"], "[640,240]")
        self.assertEqual(row["screen_state"], "UNKNOWN")
        self.assertEqual(row["status"], "PRESENT")


if __name__ == "__main__":
    unittest.main()
