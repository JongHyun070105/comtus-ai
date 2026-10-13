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
    def __init__(self, windows, images, documents=None, frame_size=(640, 480), visual_signatures=None):
        self.windows = deque(windows)
        self.images = deque(images)
        self.documents = documents or {}
        self.frame_size = frame_size
        self.visual_signatures = deque(visual_signatures or [])
        self.ocr_calls = []

    def list_windows(self):
        if len(self.windows) > 1:
            return self.windows.popleft()
        return self.windows[0] if self.windows else []

    def capture_window(self, window_id):
        image = self.images.popleft()
        signature = self.visual_signatures.popleft() if self.visual_signatures else None
        return CapturedFrame(image, *self.frame_size, "2026-10-13T00:00:00+00:00", signature)

    def run_ocr(self, image_bytes):
        self.ocr_calls.append(image_bytes)
        return self.documents.get(image_bytes, ocr_document())


class CaptureSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "capture.sqlite3"
        self.store = SQLiteStore(self.database)
        self.store.initialize()
        self.window = CaptureWindow(12, "V26", "Com2uS Baseball V26", 810, 1112)

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
        changed_screen = bytes([255]) * 1000
        adapter = FakeCaptureAdapter(
            windows=[[self.window]] * 6,
            images=[b"frame-a", b"frame-a-animated", b"frame-a-animated-2",
                    b"frame-b", b"frame-b-animated", b"frame-b-animated-2"],
            visual_signatures=[stable, bytes(animated), bytes(animated), changed_screen,
                               changed_screen, changed_screen],
        )

        report = ReadOnlyCaptureSession(
            adapter, self.store, CaptureSessionConfig(poll_interval_seconds=0.001, stable_samples=2),
        ).run(max_polls=6)

        self.assertEqual(report.status, "EXEC_PASS")
        self.assertEqual(report.ocr_frames, 2)
        self.assertEqual(report.duplicate_frames, 2)
        self.assertEqual(adapter.ocr_calls, [b"frame-a-animated", b"frame-b-animated"])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM capture_evidence").fetchone()[0], 2)

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
