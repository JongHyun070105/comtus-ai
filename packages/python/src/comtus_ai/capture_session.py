from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import resource
import threading
import time
from typing import Any, Mapping, Protocol, Sequence

from .database.store import SQLiteStore
from .models import EvidenceSource
from .observations import load_ocr_document
from .parsing import parse_ocr_fields
from .private_fixtures import PrivateFixtureMetadata, PrivateFixtureStore
from .screens import (
    SCREEN_PROFILE_VERSION,
    ClassificationStatus,
    NormalizedRect,
    ScreenClassification,
    ScreenState,
    classifier_payload_matches,
    recognize_screen,
)


@dataclass(frozen=True, slots=True)
class CaptureWindow:
    window_id: int
    process_name: str | None
    title: str | None
    width_points: float
    height_points: float
    on_screen: bool = True

    @property
    def is_v26(self) -> bool:
        identity = f"{self.process_name or ''} {self.title or ''}".casefold()
        return self.on_screen and "v26" in identity


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    image_bytes: bytes
    width_pixels: int
    height_pixels: int
    captured_at: str | None = None
    visual_signature: bytes | None = None


class CaptureAdapter(Protocol):
    def list_windows(self) -> Sequence[CaptureWindow]: ...
    def capture_window(self, window_id: int) -> CapturedFrame: ...
    def run_ocr(self, image_bytes: bytes) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class CaptureSessionConfig:
    poll_interval_seconds: float = 0.5
    stable_samples: int = 2
    max_visual_change_ratio: float = 0.01
    max_visual_sample_delta: int = 18
    preserve_images: bool = False
    private_fixture_root: Path | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.poll_interval_seconds) or self.poll_interval_seconds <= 0:
            raise ValueError("poll interval must be a positive finite number")
        if self.stable_samples < 2:
            raise ValueError("stable_samples must be at least two")
        if not math.isfinite(self.max_visual_change_ratio) or not 0 <= self.max_visual_change_ratio <= 1:
            raise ValueError("max_visual_change_ratio must be between zero and one")
        if not 0 <= self.max_visual_sample_delta <= 255:
            raise ValueError("max_visual_sample_delta must be between zero and 255")
        if self.preserve_images and self.private_fixture_root is None:
            raise ValueError("private_fixture_root is required when image preservation is enabled")


@dataclass(frozen=True, slots=True)
class CaptureSessionReport:
    status: str
    polls: int
    v26_windows_seen: int
    no_window_polls: int
    captured_frames: int
    stable_frames: int
    ocr_frames: int
    duplicate_frames: int
    failed_frames: int
    missed_frames: int
    screen_profile_mismatches: int
    observations_inserted: int
    field_candidates_inserted: int
    elapsed_seconds: float
    cpu_percent: float
    capture_p50_ms: float | None
    capture_p95_ms: float | None
    ocr_p50_ms: float | None
    ocr_p95_ms: float | None


@dataclass(slots=True)
class _MutableMetrics:
    polls: int = 0
    v26_windows_seen: int = 0
    no_window_polls: int = 0
    captured_frames: int = 0
    stable_frames: int = 0
    ocr_frames: int = 0
    duplicate_frames: int = 0
    failed_frames: int = 0
    missed_frames: int = 0
    screen_profile_mismatches: int = 0
    observations_inserted: int = 0
    field_candidates_inserted: int = 0
    capture_durations_ms: list[float] = field(default_factory=list)
    ocr_durations_ms: list[float] = field(default_factory=list)


class ReadOnlyCaptureSession:
    """Poll only visible V26 windows; never sends input to the game."""

    def __init__(self, adapter: CaptureAdapter, store: SQLiteStore, config: CaptureSessionConfig = CaptureSessionConfig()):
        self.adapter = adapter
        self.store = store
        self.config = config
        self.metrics = _MutableMetrics()
        self._candidate_digest: str | None = None
        self._candidate_anchor_frame: CapturedFrame | None = None
        self._candidate_frame: CapturedFrame | None = None
        self._candidate_window_id: int | None = None
        self._last_attempted_frame: CapturedFrame | None = None
        self._stable_count = 0
        self._active_window_id: int | None = None
        self._capture_start_cpu = 0.0
        self._capture_start_wall = 0.0

    def run(self, *, max_polls: int | None = None, stop_event: threading.Event | None = None) -> CaptureSessionReport:
        if max_polls is not None and max_polls < 0:
            raise ValueError("max_polls must be non-negative")
        wall_start, cpu_start = time.monotonic(), time.process_time()
        children_start = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            while (max_polls is None or self.metrics.polls < max_polls) and not (stop_event and stop_event.is_set()):
                poll_start = time.monotonic()
                self._poll_once()
                self.metrics.polls += 1
                elapsed = time.monotonic() - poll_start
                interval = self.config.poll_interval_seconds
                if elapsed > interval:
                    self.metrics.missed_frames += max(1, math.ceil(elapsed / interval) - 1)
                if max_polls is None or self.metrics.polls < max_polls:
                    time.sleep(max(0.0, interval - elapsed))
        except KeyboardInterrupt:
            pass
        if self.metrics.ocr_frames:
            status = "EXEC_PASS"
        elif self.metrics.failed_frames:
            status = "EXEC_FAIL"
        elif self.metrics.no_window_polls:
            status = "BLOCKED"
        else:
            status = "SKIP"
        elapsed_total = max(time.monotonic() - wall_start, 0.000001)
        children_end = resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu = (children_end.ru_utime - children_start.ru_utime
                     + children_end.ru_stime - children_start.ru_stime)
        cpu_elapsed = max(time.process_time() - cpu_start + child_cpu, 0.0)
        return CaptureSessionReport(
            status=status, polls=self.metrics.polls, v26_windows_seen=self.metrics.v26_windows_seen,
            no_window_polls=self.metrics.no_window_polls, captured_frames=self.metrics.captured_frames,
            stable_frames=self.metrics.stable_frames, ocr_frames=self.metrics.ocr_frames,
            duplicate_frames=self.metrics.duplicate_frames, failed_frames=self.metrics.failed_frames,
            missed_frames=self.metrics.missed_frames, screen_profile_mismatches=self.metrics.screen_profile_mismatches,
            observations_inserted=self.metrics.observations_inserted,
            field_candidates_inserted=self.metrics.field_candidates_inserted,
            elapsed_seconds=elapsed_total, cpu_percent=cpu_elapsed / elapsed_total * 100,
            capture_p50_ms=self._percentile(self.metrics.capture_durations_ms, 0.50),
            capture_p95_ms=self._percentile(self.metrics.capture_durations_ms, 0.95),
            ocr_p50_ms=self._percentile(self.metrics.ocr_durations_ms, 0.50),
            ocr_p95_ms=self._percentile(self.metrics.ocr_durations_ms, 0.95),
        )

    def _poll_once(self) -> None:
        try:
            candidates = [window for window in self.adapter.list_windows() if window.is_v26]
        except Exception:
            self.metrics.failed_frames += 1
            self._reset_candidate()
            return
        if not candidates:
            self.metrics.no_window_polls += 1
            self._active_window_id = None
            self._reset_candidate()
            return
        window = max(candidates, key=lambda item: (item.width_points * item.height_points, item.window_id))
        self.metrics.v26_windows_seen += 1
        if self._active_window_id != window.window_id:
            self._reset_candidate()
            self._active_window_id = window.window_id
        started = time.monotonic()
        try:
            frame = self.adapter.capture_window(window.window_id)
        except Exception:
            self.metrics.failed_frames += 1
            self._reset_candidate()
            return
        self.metrics.capture_durations_ms.append((time.monotonic() - started) * 1000)
        self.metrics.captured_frames += 1
        digest = hashlib.sha256(frame.image_bytes).hexdigest()
        same_candidate = (
            self._candidate_anchor_frame is not None
            and window.window_id == self._candidate_window_id
            and self._frames_similar(self._candidate_anchor_frame, frame)
        )
        if same_candidate:
            self._stable_count += 1
            self._candidate_frame = frame
            self._candidate_digest = digest
        else:
            self._candidate_digest = digest
            self._candidate_anchor_frame = frame
            self._candidate_frame = frame
            self._candidate_window_id = window.window_id
            self._stable_count = 1
        if self._stable_count < self.config.stable_samples:
            return
        if self.store.capture_frame_is_processed(sha256=digest, profile_version=SCREEN_PROFILE_VERSION):
            self.metrics.duplicate_frames += 1
            self._last_attempted_frame = frame
            return
        if (self._last_attempted_frame is not None
                and self._frames_similar(self._last_attempted_frame, frame)):
            self.metrics.duplicate_frames += 1
            return
        self.metrics.stable_frames += 1
        ocr_started = time.monotonic()
        try:
            document = dict(self.adapter.run_ocr(frame.image_bytes))
            self._persist(frame, document)
        except Exception:
            self.metrics.failed_frames += 1
            self._last_attempted_frame = frame
            return
        self._last_attempted_frame = frame
        self.metrics.ocr_durations_ms.append((time.monotonic() - ocr_started) * 1000)
        self.metrics.ocr_frames += 1

    def _persist(self, frame: CapturedFrame, document: dict[str, Any]) -> None:
        observations = load_ocr_document(json.dumps(document, ensure_ascii=False))
        classification = recognize_screen(observations)
        if not classifier_payload_matches(document, classification):
            self.metrics.screen_profile_mismatches += 1
            classification = ScreenClassification(ScreenState.UNKNOWN, ClassificationStatus.UNKNOWN, None,
                                                  profile_version=SCREEN_PROFILE_VERSION)

        digest = hashlib.sha256(frame.image_bytes).hexdigest()
        evidence_id, _ = self.store.save_capture_evidence(
            sha256=digest, source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED, media_type="image/png",
        )
        self.store.mark_capture_frame_processing(
            evidence_id=evidence_id, profile_version=SCREEN_PROFILE_VERSION, complete=False,
        )
        observation_ids: list[int] = []
        for observation in observations:
            observation_id, inserted = self.store.save_ocr_observation(
                evidence_id=evidence_id, field=observation.field, text=observation.text,
                confidence=observation.confidence, bbox=list(observation.bbox),
                source_type=EvidenceSource.SCREEN_CAPTURE_VERIFIED, schema_version=observation.schema_version,
            )
            observation_ids.append(observation_id)
            self.metrics.observations_inserted += int(inserted)
        screen_id, _ = self.store.save_screen_observation(
            evidence_id=evidence_id, screen_state=classification.state.value, status=classification.status.value,
            confidence=classification.confidence, profile_version=classification.profile_version,
            anchor_indices=list(classification.anchor_indices),
            panel_layout=(
                {"active": document.get("active_panel"), "left_preview": None, "right_preview": None}
                if document.get("active_panel") is not None else None
            ),
        )
        panel_values = document.get("active_panel")
        active_panel = NormalizedRect(*panel_values) if panel_values else None
        candidates = parse_ocr_fields(observations, active_panel=active_panel)
        for candidate in candidates:
            if not candidate.observation_indices:
                continue
            primary_index = candidate.observation_indices[0]
            if primary_index >= len(observation_ids):
                continue
            context = candidate.context_dict()
            context.update({
                "screen_observation_id": screen_id,
                "screen_state": classification.state.value,
                "screen_status": classification.status.value,
                "screen_profile_version": classification.profile_version,
                "player_identity": "UNRESOLVED",
                "page_identity": "UNRESOLVED",
                "player_snapshot_eligible": False,
            })
            _, inserted = self.store.save_ocr_field_candidate(
                observation_id=observation_ids[primary_index], field_key=candidate.field_key,
                value=candidate.value, status=candidate.status.value, confidence=candidate.confidence,
                source_type=candidate.source, derivation_version=candidate.derivation_version, context=context,
            )
            self.metrics.field_candidates_inserted += int(inserted)
        if self.config.preserve_images:
            captured_at = str(frame.captured_at or document.get("captured_at")
                              or datetime.now(timezone.utc).isoformat())
            metadata = PrivateFixtureMetadata(
                captured_at=captured_at,
                window_size=(frame.width_pixels, frame.height_pixels),
                screen_state=classification.state,
                ocr_engine_version=str(document.get("ocr_engine_version", "Vision-VNRecognizeTextRequestRevision3")),
                roi=tuple(document["active_panel"]) if document.get("active_panel") else None,
                ocr_document=document,
            )
            assert self.config.private_fixture_root is not None
            PrivateFixtureStore(self.store, self.config.private_fixture_root).save(
                evidence_id=evidence_id, image_bytes=frame.image_bytes, metadata=metadata,
            )
        self.store.mark_capture_frame_processing(
            evidence_id=evidence_id, profile_version=SCREEN_PROFILE_VERSION, complete=True,
        )

    def _reset_candidate(self) -> None:
        self._candidate_digest = None
        self._candidate_anchor_frame = None
        self._candidate_frame = None
        self._candidate_window_id = None
        self._stable_count = 0

    def _frames_similar(self, left: CapturedFrame, right: CapturedFrame) -> bool:
        left_signature, right_signature = left.visual_signature, right.visual_signature
        if left_signature is None or right_signature is None or len(left_signature) != len(right_signature):
            return hashlib.sha256(left.image_bytes).digest() == hashlib.sha256(right.image_bytes).digest()
        changed_samples = sum(
            abs(left_sample - right_sample) > self.config.max_visual_sample_delta
            for left_sample, right_sample in zip(left_signature, right_signature, strict=True)
        )
        return changed_samples / len(left_signature) <= self.config.max_visual_change_ratio

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = max(0, math.ceil(percentile * len(ordered)) - 1)
        return ordered[index]
