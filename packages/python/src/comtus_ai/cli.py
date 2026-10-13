from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any

from . import __version__
from .database import SQLiteStore
from .database.store import default_database_path
from .capture_session import (
    CaptureSessionConfig,
    CaptureWindow,
    CapturedFrame,
    ReadOnlyCaptureSession,
)
from .models import EvidenceSource
from .observations import OCRObservation, load_ocr_document
from .private_fixtures import PrivateFixtureMetadata, PrivateFixtureStore
from .optimizer import Opponent, Pitcher, optimize_rotation
from .parsing import parse_ocr_fields
from .screens import (
    SCREEN_PROFILE_VERSION,
    ClassificationStatus,
    NormalizedRect,
    ScreenClassification,
    ScreenState,
    classifier_payload_matches,
    recognize_screen,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PYTHON_SRC = REPO_ROOT / "packages" / "python" / "src"
DATABASE_PATH = default_database_path(REPO_ROOT)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _database(path: Path = DATABASE_PATH) -> SQLiteStore:
    store = SQLiteStore(path)
    store.initialize()
    return store


def _run_swift(arguments: list[str]) -> int:
    command = _prepare_swift_command(arguments)
    if command is None:
        print("BLOCKED: no source-matched Swift CLI binary could be built.", file=sys.stderr)
        return 2
    result = subprocess.run(command, cwd=REPO_ROOT, env=_swift_environment(command), check=False)
    return result.returncode


def _swift_environment(command: list[str]) -> dict[str, str]:
    environment = os.environ.copy()
    binary_directory = Path(command[0]).parent
    if any(binary_directory.glob("*.dylib")):
        environment["DYLD_LIBRARY_PATH"] = str(binary_directory) + (os.pathsep + environment["DYLD_LIBRARY_PATH"] if environment.get("DYLD_LIBRARY_PATH") else "")
    return environment


class _SwiftCaptureAdapter:
    def __init__(self, swift_binary: str):
        self.swift_binary = swift_binary
        self.environment = _swift_environment([swift_binary])
        self.temporary_root = REPO_ROOT / "data" / ".capture-session"
        self.temporary_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.temporary_root, 0o700)

    def _run_json(self, arguments: list[str]) -> dict[str, Any]:
        result = subprocess.run([self.swift_binary, *arguments], cwd=REPO_ROOT, env=self.environment,
                                check=False, capture_output=True, text=True)
        output = result.stdout or result.stderr
        try:
            value = json.loads(output)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Swift capture command returned invalid JSON (exit={result.returncode})") from error
        if result.returncode != 0:
            raise RuntimeError(value.get("message", f"Swift capture command failed ({result.returncode})"))
        if not isinstance(value, dict):
            raise RuntimeError("Swift capture command returned an unexpected document")
        return value

    def list_windows(self) -> list[CaptureWindow]:
        response = self._run_json(["windows"])
        return [CaptureWindow(
            window_id=int(item["window_id"]), process_name=item.get("process_name"), title=item.get("title"),
            width_points=float(item["width_points"]), height_points=float(item["height_points"]),
            on_screen=bool(item.get("on_screen", True)),
            process_id=int(item["process_id"]) if item.get("process_id") is not None else None,
            bundle_id=item.get("bundle_identifier", item.get("bundle_id")),
        ) for item in response.get("windows", [])]

    def capture_window(self, window_id: int, process_id: int, bundle_id: str | None = None) -> CapturedFrame:
        with tempfile.TemporaryDirectory(prefix="capture-", dir=self.temporary_root) as temporary:
            output = Path(temporary) / "frame.png"
            arguments = ["capture", "--window-id", str(window_id), "--expected-process-id", str(process_id),
                         "--output", str(output), "--visual-signature"]
            if bundle_id:
                arguments += ["--expected-bundle-id", bundle_id]
            response = self._run_json(arguments)
            encoded_signature = response.get("visual_signature")
            visual_signature = base64.b64decode(encoded_signature, validate=True) if encoded_signature else None
            encoded_key_region = response.get("key_region_signature")
            key_region_signature = base64.b64decode(encoded_key_region, validate=True) if encoded_key_region else None
            return CapturedFrame(output.read_bytes(), int(response["width_pixels"]),
                                 int(response["height_pixels"]), str(response["captured_at"]),
                                 visual_signature, key_region_signature)

    def run_ocr(self, image_bytes: bytes) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="ocr-", dir=self.temporary_root) as temporary:
            image = Path(temporary) / "frame.png"
            image.write_bytes(image_bytes)
            os.chmod(image, 0o600)
            return self._run_json(["ocr", "--image", str(image), "--screen-state", "UNKNOWN"])


def _run_capture_session(args: argparse.Namespace) -> int:
    command = _prepare_swift_command(["windows"])
    if command is None:
        print("BLOCKED: no source-matched Swift CLI binary could be built.", file=sys.stderr)
        return 2
    adapter = _SwiftCaptureAdapter(command[0])
    config = CaptureSessionConfig(
        poll_interval_seconds=args.interval,
        stable_samples=args.stable_samples,
        preserve_images=args.preserve_images,
        private_fixture_root=REPO_ROOT / "data" / "private-fixtures" if args.preserve_images else None,
    )
    with _database(args.database) as store:
        report = ReadOnlyCaptureSession(adapter, store, config).run(max_polls=args.max_polls)
    _print_json(asdict(report))
    return 0 if report.status == "EXEC_PASS" else 2


def _run_swift_ocr(args: argparse.Namespace) -> int:
    if args.field_panel and not args.store:
        print("--field-panel requires --store so its bounds remain linked to field candidates.", file=sys.stderr)
        return 2
    command = ["ocr", "--image", str(args.image), "--screen-state", args.screen_state]
    if args.active_panel:
        command += ["--active-panel", *(str(value) for value in args.active_panel)]
    if not args.store:
        if getattr(args, "preserve_image", False):
            print("--preserve-image requires --store so the private image remains linked to SQLite evidence.", file=sys.stderr)
            return 2
        return _run_swift(command)

    swift_command = _prepare_swift_command(command)
    if swift_command is None:
        print("BLOCKED: no source-matched Swift CLI binary could be built.", file=sys.stderr)
        return 2
    result = subprocess.run(swift_command, cwd=REPO_ROOT, env=_swift_environment(swift_command),
                            check=False, capture_output=True, text=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    document = json.loads(result.stdout)
    full_frame_observation_count = len(document.get("observations", []))
    field_observation_offset = 0
    if args.field_panel:
        roi_command = ["ocr", "--image", str(args.image), "--screen-state", "UNKNOWN",
                       "--active-panel", *(str(value) for value in args.field_panel)]
        roi_swift_command = _prepare_swift_command(roi_command)
        if roi_swift_command is None:
            print("BLOCKED: no source-matched Swift CLI binary could be built.", file=sys.stderr)
            return 2
        roi_result = subprocess.run(roi_swift_command, cwd=REPO_ROOT, env=_swift_environment(roi_swift_command),
                                    check=False, capture_output=True, text=True)
        if roi_result.returncode != 0:
            print(roi_result.stderr or roi_result.stdout, file=sys.stderr)
            return roi_result.returncode
        roi_document = json.loads(roi_result.stdout)
        roi_observations = roi_document.get("observations", [])
        document["observations"].extend(roi_observations)
        document["field_roi_observation_count"] = len(roi_observations)
        field_observation_offset = full_frame_observation_count
        field_observations_document = dict(document)
        field_observations_document["observations"] = roi_observations
        field_observations = load_ocr_document(json.dumps(field_observations_document, ensure_ascii=False))
    else:
        field_observations = None
    observations = load_ocr_document(json.dumps(document, ensure_ascii=False))
    active_panel_values = document.get("active_panel")
    active_panel = NormalizedRect(*active_panel_values) if active_panel_values else None
    field_panel = NormalizedRect(*args.field_panel) if args.field_panel else active_panel
    document["extraction_panel"] = (
        [field_panel.x, field_panel.y, field_panel.width, field_panel.height] if field_panel else None
    )
    image_bytes = args.image.read_bytes()
    media_type = "image/jpeg" if args.image.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    digest = hashlib.sha256(image_bytes).hexdigest()
    with _database(args.database) as store:
        evidence_id, evidence_inserted = store.save_capture_evidence(
            sha256=digest, source_type=args.evidence_source, media_type=media_type,
        )
        inserted_count = 0
        observation_ids: list[int] = []
        for observation in observations:
            observation_id, inserted = store.save_ocr_observation(
                evidence_id=evidence_id, field=observation.field, text=observation.text,
                confidence=observation.confidence, bbox=list(observation.bbox),
                source_type=args.evidence_source, schema_version=observation.schema_version,
            )
            observation_ids.append(observation_id)
            inserted_count += int(inserted)
        classification = recognize_screen(observations)
        screen_profile_match = classifier_payload_matches(document, classification)
        if not screen_profile_match:
            classification = ScreenClassification(
                ScreenState.UNKNOWN, ClassificationStatus.UNKNOWN, None,
                profile_version=SCREEN_PROFILE_VERSION,
            )
        document["screen_state"] = classification.state.value
        document["screen_status"] = classification.status.value
        document["screen_confidence"] = classification.confidence
        document["screen_anchor_indices"] = list(classification.anchor_indices)
        screen_id, screen_inserted = store.save_screen_observation(
            evidence_id=evidence_id, screen_state=classification.state.value,
            status=classification.status.value, confidence=classification.confidence,
            profile_version=classification.profile_version,
            anchor_indices=list(classification.anchor_indices),
            panel_layout=(
                {"active": document["extraction_panel"], "left_preview": None, "right_preview": None}
                if field_panel is not None else None
            ),
        )
        candidate_observations = field_observations if field_observations is not None else observations
        field_candidates = parse_ocr_fields(candidate_observations, active_panel=field_panel)
        field_candidate_ids: list[int] = []
        field_candidates_inserted = 0
        for candidate in field_candidates:
            if not candidate.observation_indices:
                continue
            primary = candidate.observation_indices[0]
            primary += field_observation_offset
            if primary >= len(observation_ids):
                continue
            context = candidate.context_dict()
            if field_observation_offset:
                context["observation_indices"] = [index + field_observation_offset
                                                  for index in candidate.observation_indices]
            context.update({
                "screen_observation_id": screen_id,
                "screen_state": classification.state.value,
                "screen_status": classification.status.value,
                "player_identity": "UNRESOLVED",
                "page_identity": "UNRESOLVED",
                "player_snapshot_eligible": False,
            })
            candidate_id, candidate_inserted = store.save_ocr_field_candidate(
                observation_id=observation_ids[primary], field_key=candidate.field_key, value=candidate.value,
                status=candidate.status.value, confidence=candidate.confidence, source_type=candidate.source,
                derivation_version=candidate.derivation_version, context=context,
            )
            field_candidate_ids.append(candidate_id)
            field_candidates_inserted += int(candidate_inserted)
        private_image_path = None
        if args.preserve_image:
            frame_size = document.get("frame_size") or []
            if len(frame_size) != 2:
                raise ValueError("OCR document is missing its frame dimensions")
            captured_at = args.captured_at or datetime.fromtimestamp(
                args.image.stat().st_mtime, timezone.utc,
            ).isoformat()
            metadata = PrivateFixtureMetadata(
                captured_at=captured_at,
                window_size=(int(frame_size[0]), int(frame_size[1])),
                screen_state=classification.state,
                ocr_engine_version=document.get("ocr_engine_version", "Vision-VNRecognizeTextRequestRevision3"),
                roi=(tuple(document["extraction_panel"]) if document.get("extraction_panel")
                     else tuple(document["active_panel"]) if document.get("active_panel") else None),
                ocr_document=document,
            )
            private_image_path, _ = PrivateFixtureStore(
                store, REPO_ROOT / "data" / "private-fixtures",
            ).save(evidence_id=evidence_id, image_bytes=image_bytes, metadata=metadata)
    document["persistence"] = {
        "status": "EXEC_PASS",
        "capture_evidence_id": evidence_id,
        "capture_inserted": evidence_inserted,
        "observation_ids": observation_ids,
        "observations_inserted": inserted_count,
        "observations_duplicated": len(observations) - inserted_count,
        "screen_observation_id": screen_id,
        "screen_observation_inserted": screen_inserted,
        "screen_state": classification.state.value,
        "screen_state_status": classification.status.value,
        "screen_profile_match": screen_profile_match,
        "field_candidate_ids": field_candidate_ids,
        "field_candidates_inserted": field_candidates_inserted,
        "player_snapshots_created": 0,
        "source": args.evidence_source,
        "private_image_path": str(private_image_path) if private_image_path else None,
    }
    _print_json(document)
    return 0


def _analyze_saved_ocr(database: Path) -> int:
    """Append versioned parser and screen-state evidence without emitting OCR text."""
    evidence_count = 0
    observation_count = 0
    screen_inserted = 0
    field_inserted = 0
    field_totals: dict[str, dict[str, int]] = {}
    screen_totals: dict[str, int] = {}
    with _database(database) as store:
        evidence_rows = store.connection.execute("SELECT id FROM capture_evidence ORDER BY id").fetchall()
        evidence_count = len(evidence_rows)
        for evidence in evidence_rows:
            evidence_id = int(evidence["id"])
            rows = store.connection.execute(
                "SELECT id,text,confidence,bbox_json,source_type,schema_version,field FROM ocr_observations WHERE evidence_id=? ORDER BY id",
                (evidence_id,),
            ).fetchall()
            observation_count += len(rows)
            observations = tuple(
                OCRObservation(
                    text=row["text"], confidence=row["confidence"],
                    bbox=tuple(json.loads(row["bbox_json"])),
                    source=EvidenceSource(row["source_type"]), schema_version=int(row["schema_version"]),
                    field=row["field"],
                )
                for row in rows
            )
            classification = recognize_screen(observations)
            _, inserted = store.save_screen_observation(
                evidence_id=evidence_id, screen_state=classification.state.value,
                status=classification.status.value, confidence=classification.confidence,
                profile_version=classification.profile_version,
                anchor_indices=list(classification.anchor_indices), panel_layout=None,
            )
            screen_inserted += int(inserted)
            screen_key = f"{classification.state.value}:{classification.status.value}"
            screen_totals[screen_key] = screen_totals.get(screen_key, 0) + 1

            by_field_ids: dict[int, int] = {}
            for row in rows:
                by_field_ids[int(row["id"])] = int(row["id"])
            for candidate in parse_ocr_fields(observations):
                if not candidate.observation_indices:
                    continue
                primary_index = candidate.observation_indices[0]
                if primary_index >= len(rows):
                    continue
                observation_id = by_field_ids[int(rows[primary_index]["id"])]
                context = candidate.context_dict()
                context.update({
                    "screen_state": classification.state.value,
                    "screen_status": classification.status.value,
                    "screen_profile_version": classification.profile_version,
                    "player_identity": "UNRESOLVED",
                    "page_identity": "UNRESOLVED",
                    "player_snapshot_eligible": False,
                })
                _, inserted = store.save_ocr_field_candidate(
                    observation_id=observation_id, field_key=candidate.field_key, value=candidate.value,
                    status=candidate.status.value, confidence=candidate.confidence, source_type=candidate.source,
                    derivation_version=candidate.derivation_version, context=context,
                )
                field_inserted += int(inserted)
                field_key = f"{candidate.field_key}:{candidate.status.value}"
                field_totals[field_key] = field_totals.get(field_key, 0) + 1

    _print_json({
        "status": "EXEC_PASS",
        "database": str(database),
        "evidence_frames_analyzed": evidence_count,
        "ocr_observations_analyzed": observation_count,
        "screen_classifications_inserted": screen_inserted,
        "screen_classifications_by_state": screen_totals,
        "field_candidates_inserted": field_inserted,
        "field_candidates_by_key_and_status": field_totals,
        "player_snapshots_created": 0,
        "raw_ocr_text_emitted": False,
        "note": "Player/card identity and page context remain unresolved unless separately verified.",
    })
    return 0


def _swift_source_digest() -> str:
    package = REPO_ROOT / "apps" / "mac-capture"
    files = [package / "Package.swift", *sorted((package / "Sources").rglob("*.swift"))]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(package).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _swift_manifest_path(binary: Path) -> Path:
    return binary.with_name(binary.name + ".build.json")


def _valid_swift_binary(binary: Path, source_digest: str) -> bool:
    manifest_path = _swift_manifest_path(binary)
    if not binary.is_file() or not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return (manifest.get("source_sha256") == source_digest
                and manifest.get("binary_sha256") == hashlib.sha256(binary.read_bytes()).hexdigest())
    except (OSError, json.JSONDecodeError, TypeError):
        return False


def _write_swift_manifest(binary: Path, source_digest: str, mode: str) -> None:
    version = subprocess.run(["swiftc", "--version"], check=False, capture_output=True, text=True).stdout.strip()
    manifest = {
        "schema_version": 1,
        "source_sha256": source_digest,
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "compiler": version,
        "build_mode": mode,
    }
    destination = _swift_manifest_path(binary)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _swift_binary_candidates(source_digest: str) -> list[Path]:
    package = REPO_ROOT / "apps" / "mac-capture"
    roots = (package / ".build" / "swiftpm", package / ".build" / "manual-localfix")
    binaries: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir() or not child.name.startswith(source_digest):
                continue
            binaries.extend((child / "arm64-apple-macosx" / "release" / "mac-capture",
                             child / "x86_64-apple-macosx" / "release" / "mac-capture",
                             child / "release" / "mac-capture", child / "mac-capture"))
    configured_binary = os.environ.get("COMTUS_AI_SWIFT_BIN")
    if configured_binary:
        binaries.insert(0, Path(configured_binary).expanduser())
    return [binary for binary in binaries if _valid_swift_binary(binary, source_digest)]


def _fresh_build_directory(parent: Path, source_digest: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=source_digest + "-", dir=parent))


def _find_built_swift_cli(build_root: Path) -> Path | None:
    package = REPO_ROOT / "apps" / "mac-capture"
    candidates = (
        build_root / "arm64-apple-macosx" / "release" / "mac-capture",
        build_root / "x86_64-apple-macosx" / "release" / "mac-capture",
        build_root / "release" / "mac-capture",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _compile_swift_direct(build_root: Path) -> Path | None:
    if platform.system() != "Darwin" or shutil.which("swiftc") is None:
        return None
    package = REPO_ROOT / "apps" / "mac-capture"
    sources = sorted((package / "Sources" / "MacCaptureCore").glob("*.swift"))
    cli = package / "Sources" / "MacCaptureCLI" / "main.swift"
    if not sources or not cli.is_file():
        return None
    build_root.mkdir(parents=True, exist_ok=True)
    library = build_root / "libMacCaptureCore.dylib"
    module = build_root / "MacCaptureCore.swiftmodule"
    binary = build_root / "mac-capture"
    frameworks = ["-framework", "AppKit", "-framework", "CoreGraphics", "-framework", "ScreenCaptureKit", "-framework", "Vision"]
    library_command = ["swiftc", "-O", "-whole-module-optimization", "-emit-library", "-emit-module",
                      "-module-name", "MacCaptureCore", "-emit-module-path", str(module),
                      *map(str, sources), *frameworks, "-o", str(library)]
    library_result = subprocess.run(library_command, cwd=REPO_ROOT, check=False, capture_output=True, text=True)
    if library_result.returncode != 0:
        print(library_result.stderr or library_result.stdout, file=sys.stderr)
        return None
    cli_command = ["swiftc", "-O", "-parse-as-library", "-I", str(build_root), "-L", str(build_root),
                   "-lMacCaptureCore", "-Xlinker", "-rpath", "-Xlinker", "@executable_path",
                   *frameworks, "-o", str(binary), str(cli)]
    cli_result = subprocess.run(cli_command, cwd=REPO_ROOT, check=False, capture_output=True, text=True)
    if cli_result.returncode != 0:
        print(cli_result.stderr or cli_result.stdout, file=sys.stderr)
        return None
    return binary


def _ensure_swift_binary() -> Path | None:
    package = REPO_ROOT / "apps" / "mac-capture"
    source_digest = _swift_source_digest()
    candidates = _swift_binary_candidates(source_digest)
    if candidates:
        return candidates[0]
    if shutil.which("swift") is None:
        return None

    swiftpm_root = _fresh_build_directory(package / ".build" / "swiftpm", source_digest)
    swiftpm = subprocess.run(
        ["swift", "build", "--package-path", str(package), "--build-path", str(swiftpm_root), "-c", "release"],
        cwd=REPO_ROOT, check=False, capture_output=True, text=True,
    )
    if swiftpm.returncode == 0:
        binary = _find_built_swift_cli(swiftpm_root)
        if binary:
            _write_swift_manifest(binary, source_digest, "swiftpm")
            return binary
    if swiftpm.stderr:
        print("SwiftPM build unavailable; trying the source-matched direct compiler fallback.", file=sys.stderr)
        print(swiftpm.stderr.strip(), file=sys.stderr)

    manual_root = _fresh_build_directory(package / ".build" / "manual-localfix", source_digest)
    binary = _compile_swift_direct(manual_root)
    if binary:
        _write_swift_manifest(binary, source_digest, "swiftc-direct")
        return binary
    return None


def _swift_command(arguments: list[str]) -> list[str] | None:
    source_digest = _swift_source_digest()
    candidates = _swift_binary_candidates(source_digest)
    return [str(candidates[0]), *arguments] if candidates else None


def _prepare_swift_command(arguments: list[str]) -> list[str] | None:
    binary = _ensure_swift_binary()
    return [str(binary), *arguments] if binary else None


def _optimize_file(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    pitchers = [Pitcher(str(row["card_id"]), str(row["display_name"])) for row in document["pitchers"]]
    opponents = [Opponent(str(row["opponent_id"]), str(row["display_name"])) for row in document["opponents"]]
    scores = {
        (str(pitcher_id), str(opponent_id)): value
        for pitcher_id, row in document.get("scores", {}).items()
        for opponent_id, value in row.items()
    }
    result = optimize_rotation(pitchers, opponents, scores, document.get("baseline"), document.get("source_type", "UNKNOWN"))
    return result.to_dict(pitchers, opponents)


def _seed_reference() -> tuple[int, bool]:
    reference = json.loads((REPO_ROOT / "configs" / "samsung-reference-snapshot.json").read_text(encoding="utf-8"))
    with _database() as store:
        account_id = store.ensure_account("reference:samsung-lions", "Samsung Lions")
        position = reference["position_training"]
        return store.save_team_snapshot(
            account_id=account_id,
            snapshot_kind="USER_REFERENCE",
            payload=reference,
            source_type=EvidenceSource.USER_PROVIDED_REFERENCE,
            team_ovr=reference.get("team_ovr"),
            set_deck_points=reference.get("set_deck_points"),
            position_training_total=position.get("total_level"),
            position_training_ovr_contribution=position.get("displayed_team_ovr_contribution"),
            observed_at=reference.get("observed_at"),
            mode=reference.get("mode"),
        )


def _roster_show(account_key: str | None) -> int:
    with _database() as store:
        query = """SELECT a.account_key, a.team_name, t.id, t.snapshot_kind, t.observed_at,
        t.source_type, t.team_ovr, t.set_deck_points, t.position_training_total,
        t.position_training_ovr_contribution, t.payload_json FROM team_snapshots t
        JOIN accounts a ON a.id=t.account_id"""
        parameters: tuple[object, ...] = ()
        if account_key:
            query += " WHERE a.account_key=?"
            parameters = (account_key,)
        query += " ORDER BY a.account_key, t.id"
        rows = store.connection.execute(query, parameters).fetchall()
        _print_json([
            {"account_key": row["account_key"], "team_name": row["team_name"], "snapshot_id": row["id"],
             "snapshot_kind": row["snapshot_kind"], "observed_at": row["observed_at"], "source": row["source_type"],
             "team_ovr": row["team_ovr"], "set_deck_points": row["set_deck_points"],
             "position_training_total": row["position_training_total"],
             "position_training_ovr_contribution": row["position_training_ovr_contribution"],
             "payload": json.loads(row["payload_json"])} for row in rows
        ])
    return 0


def _roster_diff(account_key: str) -> int:
    with _database() as store:
        rows = store.connection.execute(
            """SELECT t.id,t.roster_fingerprint,t.payload_json,t.observed_at,t.source_type
            FROM team_snapshots t JOIN accounts a ON a.id=t.account_id
            WHERE a.account_key=? ORDER BY t.id DESC LIMIT 2""", (account_key,)
        ).fetchall()
        if not rows:
            _print_json({"account_key": account_key, "status": "NO_SNAPSHOT"})
            return 0
        current = dict(rows[0])
        previous = dict(rows[1]) if len(rows) > 1 else None
        payload = json.loads(current["payload_json"])
        previous_payload = json.loads(previous["payload_json"]) if previous else None
        _print_json({
            "account_key": account_key,
            "status": "FIRST_SNAPSHOT" if previous is None else "UNCHANGED" if current["roster_fingerprint"] == previous["roster_fingerprint"] else "CHANGED",
            "current_snapshot_id": current["id"],
            "previous_snapshot_id": previous["id"] if previous else None,
            "current_fingerprint": current["roster_fingerprint"],
            "changed_fields": [] if previous_payload is None else sorted(key for key in set(payload) | set(previous_payload) if payload.get(key) != previous_payload.get(key)),
        })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comtus-ai", description="Local read-only roster and matchup analysis")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report Python, SQLite, Swift and capture permission status")
    db = sub.add_parser("db", help="Manage the local SQLite database").add_subparsers(dest="db_command", required=True)
    db.add_parser("init", help="Initialize or migrate the local schema")
    db.add_parser("seed-reference", help="Store the clearly labeled user-provided Samsung reference snapshot")
    analyze_ocr = db.add_parser("analyze-ocr", help="Analyze saved local OCR evidence without printing OCR text")
    analyze_ocr.add_argument("--database", type=Path, default=DATABASE_PATH)
    capture = sub.add_parser("capture", help="Read-only macOS window and OCR operations").add_subparsers(dest="capture_command", required=True)
    capture.add_parser("list", help="List candidate windows when capture permission is available")
    once = capture.add_parser("once", help="Capture one frame from a selected window")
    once.add_argument("--window-id", required=True, type=int)
    once.add_argument("--output", type=Path, default=REPO_ROOT / "data" / "captures" / "frame.png")
    session = capture.add_parser("session", help="Watch V26 frames and collect changed stable screens without input")
    session.add_argument("--interval", type=float, default=0.5, help="Seconds between read-only window captures")
    session.add_argument("--stable-samples", type=int, default=2, help="Identical consecutive frames before OCR")
    session.add_argument("--max-polls", type=int, help="Optional poll limit; otherwise wait until interrupted")
    session.add_argument("--preserve-images", action="store_true", help="Keep images locally under the bounded private fixture store")
    session.add_argument("--database", type=Path, default=DATABASE_PATH)
    ocr = capture.add_parser("ocr", help="Run Vision OCR on a local image")
    ocr.add_argument("image", type=Path)
    ocr.add_argument("--active-panel", nargs=4, type=float, metavar=("X", "Y", "W", "H"), help="Normalized active-panel ROI")
    ocr.add_argument("--field-panel", nargs=4, type=float, metavar=("X", "Y", "W", "H"),
                     help="Normalized card region used for field extraction while Vision reads the full frame")
    ocr.add_argument("--screen-state", choices=("HOME", "RANKING_LOBBY", "PITCHER_ORDER", "OPPONENT_LINEUP", "OPPONENT_STARTING_PITCHER_DETAIL", "PLAYER_DETAIL_BATTER", "PLAYER_DETAIL_PITCHER", "TEAM_ROSTER", "SYNERGY", "POSITION_TRAINING", "MATCH_RESULT", "UNKNOWN"), default="UNKNOWN")
    ocr.add_argument("--store", action="store_true", help="Store capture hash and OCR observations in SQLite")
    ocr.add_argument("--preserve-image", action="store_true",
                     help="Optionally retain this original image locally under data/private-fixtures (requires --store)")
    ocr.add_argument("--captured-at", help="ISO-8601 capture time; defaults to the source image file modification time")
    ocr.add_argument("--evidence-source", choices=tuple(source.value for source in EvidenceSource), default=EvidenceSource.UNKNOWN.value,
                     help="Provenance label for a stored capture; defaults to UNKNOWN")
    ocr.add_argument("--database", type=Path, default=DATABASE_PATH, help="SQLite path used with --store")
    navigate = sub.add_parser("navigate", help="Plan or request a safety-gated player navigation session")
    navigate_sub = navigate.add_subparsers(dest="navigate_command", required=True)
    collect = navigate_sub.add_parser("collect", help="Inspect the first-starter player-detail collection path")
    collection_mode = collect.add_mutually_exclusive_group(required=True)
    collection_mode.add_argument("--dry-run", action="store_true", help="Inspect and report a plan without sending UI input")
    collection_mode.add_argument("--allow-ui-input", action="store_true", help="Request live UI input behind all safety gates")
    collect.add_argument("--idle-only", action="store_true", help="Require an idle user before any live input")
    roster = sub.add_parser("roster", help="Show saved team snapshots").add_subparsers(dest="roster_command", required=True)
    show = roster.add_parser("show")
    show.add_argument("--account")
    diff = roster.add_parser("diff")
    diff.add_argument("--account", required=True)
    matchup = sub.add_parser("matchup", help="Analyze a specific Ranking Challenge matchup input")
    matchup_sub = matchup.add_subparsers(dest="matchup_command", required=True)
    analyze = matchup_sub.add_parser("analyze")
    analyze.add_argument("--input", required=True, type=Path)
    for name in ("matchup-analyze", "optimize"):
        item = sub.add_parser(name, help="Rank all 120 one-to-one rotations from explicit heuristic inputs")
        item.add_argument("--input", required=True, type=Path)
    sub.add_parser("report", help="Summarize local evidence and data readiness")
    sub.add_parser("test", help="Run the project Python unit and integration tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            swift_args = _prepare_swift_command(["doctor"])
            swift_status: dict[str, object] = {"available": swift_args is not None, "capture_permission": "NOT_CHECKED"}
            if swift_args:
                environment = _swift_environment(swift_args)
                result = subprocess.run(
                    swift_args, cwd=REPO_ROOT, env=environment, check=False, capture_output=True, text=True,
                )
                try:
                    swift_status = json.loads(result.stdout)
                except json.JSONDecodeError:
                    swift_status["diagnostic"] = result.stderr.strip() or result.stdout.strip()
                    swift_status["exit_code"] = result.returncode
            _print_json({"package_version": __version__, "python": platform.python_version(), "platform": platform.platform(),
                         "sqlite": sqlite3.sqlite_version, "database_path": str(DATABASE_PATH), "swift": swift_status})
            return 0
        if args.command == "db" and args.db_command == "init":
            with _database() as store:
                _print_json({"status": "EXEC_PASS", "schema_version": store.schema_version(), "path": str(DATABASE_PATH), "counts": store.counts()})
            return 0
        if args.command == "db" and args.db_command == "analyze-ocr":
            return _analyze_saved_ocr(args.database)
        if args.command == "db" and args.db_command == "seed-reference":
            snapshot_id, inserted = _seed_reference()
            _print_json({"status": "EXEC_PASS", "snapshot_id": snapshot_id, "inserted": inserted, "source": "USER_PROVIDED_REFERENCE", "screenshots_verified": False})
            return 0
        if args.command == "capture":
            if args.capture_command == "list":
                return _run_swift(["windows"])
            if args.capture_command == "once":
                data_root = (REPO_ROOT / "data").resolve()
                output_parent = args.output.parent.resolve()
                if output_parent == data_root or data_root in output_parent.parents:
                    output_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    os.chmod(output_parent, 0o700)
                return _run_swift(["capture", "--window-id", str(args.window_id), "--output", str(args.output)])
            if args.capture_command == "session":
                return _run_capture_session(args)
            if args.capture_command == "ocr":
                return _run_swift_ocr(args)
        if args.command == "navigate" and args.navigate_command == "collect":
            if args.allow_ui_input and not args.idle_only:
                print("--allow-ui-input requires --idle-only.", file=sys.stderr)
                return 2
            command = ["navigate", "collect", "--dry-run" if args.dry_run else "--allow-ui-input"]
            if args.idle_only:
                command.append("--idle-only")
            return _run_swift(command)
        if args.command == "roster" and args.roster_command == "show":
            return _roster_show(args.account)
        if args.command == "roster" and args.roster_command == "diff":
            return _roster_diff(args.account)
        if args.command == "matchup" and args.matchup_command == "analyze":
            _print_json(_optimize_file(args.input))
            return 0
        if args.command in ("matchup-analyze", "optimize"):
            _print_json(_optimize_file(args.input))
            return 0
        if args.command == "report":
            with _database() as store:
                counts = store.counts()
            _print_json({"counts": counts, "actual_match_results": counts["validated_match_results"],
                         "training_data_status": "NO_REAL_MATCH_RESULTS" if counts["validated_match_results"] == 0 else "AVAILABLE_REQUIRES_VALIDATION",
                         "win_probability_model": "NOT_CALIBRATED", "score_type": "HEURISTIC_SCORE_ONLY"})
            return 0
        if args.command == "test":
            env = os.environ.copy()
            current = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(PYTHON_SRC) + (os.pathsep + current if current else "")
            return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(REPO_ROOT / "packages" / "python" / "tests"), "-v"], cwd=REPO_ROOT, env=env, check=False).returncode
    except (OSError, ValueError, KeyError, json.JSONDecodeError, sqlite3.Error, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
