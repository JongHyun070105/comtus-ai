from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
from typing import Any

from . import __version__
from .database import SQLiteStore
from .database.store import default_database_path
from .models import EvidenceSource
from .observations import load_ocr_document
from .optimizer import Opponent, Pitcher, optimize_rotation


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
    command = _swift_command(arguments)
    if command is None:
        print("BLOCKED: Swift toolchain was not found.", file=sys.stderr)
        return 2
    result = subprocess.run(command, cwd=REPO_ROOT, env=_swift_environment(command), check=False)
    return result.returncode


def _swift_environment(command: list[str]) -> dict[str, str]:
    environment = os.environ.copy()
    binary_directory = Path(command[0]).parent
    if any(binary_directory.glob("*.dylib")):
        environment["DYLD_LIBRARY_PATH"] = str(binary_directory) + (os.pathsep + environment["DYLD_LIBRARY_PATH"] if environment.get("DYLD_LIBRARY_PATH") else "")
    return environment


def _run_swift_ocr(args: argparse.Namespace) -> int:
    command = ["ocr", "--image", str(args.image), "--screen-state", args.screen_state]
    if args.active_panel:
        command += ["--active-panel", *(str(value) for value in args.active_panel)]
    if not args.store:
        return _run_swift(command)

    swift_command = _swift_command(command)
    if swift_command is None:
        print("BLOCKED: Swift toolchain was not found.", file=sys.stderr)
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
    observations = load_ocr_document(result.stdout)
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
    document["persistence"] = {
        "status": "EXEC_PASS",
        "capture_evidence_id": evidence_id,
        "capture_inserted": evidence_inserted,
        "observation_ids": observation_ids,
        "observations_inserted": inserted_count,
        "observations_duplicated": len(observations) - inserted_count,
        "source": args.evidence_source,
    }
    _print_json(document)
    return 0


def _swift_command(arguments: list[str]) -> list[str] | None:
    package = REPO_ROOT / "apps" / "mac-capture"
    configured_binary = os.environ.get("COMTUS_AI_SWIFT_BIN")
    if configured_binary:
        binary = Path(configured_binary).expanduser()
        return [str(binary), *arguments] if binary.is_file() else None
    binaries = (
        package / ".build" / "release" / "mac-capture",
        package / ".build" / "arm64-apple-macosx" / "release" / "mac-capture",
        package / ".build" / "manual-release" / "mac-capture",
        package / ".build" / "out" / "Products" / "Release" / "mac-capture",
        package / ".build" / "manual" / "mac-capture",
    )
    source_files = tuple((package / "Sources").rglob("*.swift"))
    newest_source = max((source.stat().st_mtime_ns for source in source_files), default=0)
    available = [binary for binary in binaries if binary.is_file() and binary.stat().st_mtime_ns >= newest_source]
    if available:
        binary = max(available, key=lambda candidate: candidate.stat().st_mtime_ns)
        return [str(binary), *arguments]
    if shutil.which("swift") is None:
        return None
    return ["swift", "run", "--package-path", str(package), "mac-capture", *arguments]


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
    capture = sub.add_parser("capture", help="Read-only macOS window and OCR operations").add_subparsers(dest="capture_command", required=True)
    capture.add_parser("list", help="List candidate windows when capture permission is available")
    once = capture.add_parser("once", help="Capture one frame from a selected window")
    once.add_argument("--window-id", required=True, type=int)
    once.add_argument("--output", type=Path, default=REPO_ROOT / "data" / "captures" / "frame.png")
    ocr = capture.add_parser("ocr", help="Run Vision OCR on a local image")
    ocr.add_argument("image", type=Path)
    ocr.add_argument("--active-panel", nargs=4, type=float, metavar=("X", "Y", "W", "H"), help="Normalized active-panel ROI")
    ocr.add_argument("--screen-state", choices=("HOME", "RANKING_LOBBY", "PITCHER_ORDER", "OPPONENT_LINEUP", "PLAYER_DETAIL_BATTER", "PLAYER_DETAIL_PITCHER", "TEAM_ROSTER", "SYNERGY", "POSITION_TRAINING", "MATCH_RESULT", "UNKNOWN"), default="UNKNOWN")
    ocr.add_argument("--store", action="store_true", help="Store capture hash and OCR observations in SQLite")
    ocr.add_argument("--evidence-source", choices=tuple(source.value for source in EvidenceSource), default=EvidenceSource.UNKNOWN.value,
                     help="Provenance label for a stored capture; defaults to UNKNOWN")
    ocr.add_argument("--database", type=Path, default=DATABASE_PATH, help="SQLite path used with --store")
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
            swift_args = _swift_command(["doctor"])
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
        if args.command == "db" and args.db_command == "seed-reference":
            snapshot_id, inserted = _seed_reference()
            _print_json({"status": "EXEC_PASS", "snapshot_id": snapshot_id, "inserted": inserted, "source": "USER_PROVIDED_REFERENCE", "screenshots_verified": False})
            return 0
        if args.command == "capture":
            if args.capture_command == "list":
                return _run_swift(["windows"])
            if args.capture_command == "once":
                args.output.parent.mkdir(parents=True, exist_ok=True)
                return _run_swift(["capture", "--window-id", str(args.window_id), "--output", str(args.output)])
            if args.capture_command == "ocr":
                return _run_swift_ocr(args)
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
