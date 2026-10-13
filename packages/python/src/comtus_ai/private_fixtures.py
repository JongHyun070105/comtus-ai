from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Any

from .database.store import SQLiteStore, canonical_json, utc_now
from .screens import NormalizedRect, ScreenState


DEFAULT_PRIVATE_FIXTURE_LIMIT_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PrivateFixtureMetadata:
    captured_at: str
    window_size: tuple[int, int]
    screen_state: ScreenState
    ocr_engine_version: str
    roi: tuple[float, float, float, float] | None
    ocr_document: dict[str, Any]

    def __post_init__(self) -> None:
        try:
            datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("captured_at must be an ISO-8601 timestamp") from error
        if len(self.window_size) != 2 or any(value <= 0 for value in self.window_size):
            raise ValueError("window_size must contain positive pixel dimensions")
        if not self.ocr_engine_version.strip():
            raise ValueError("ocr_engine_version is required")
        if self.roi is not None:
            NormalizedRect(*self.roi)


class PrivateFixtureStore:
    """Optional, local-only image retention linked to immutable OCR evidence."""

    def __init__(self, store: SQLiteStore, root: str | Path, *, max_bytes: int = DEFAULT_PRIVATE_FIXTURE_LIMIT_BYTES):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.store = store
        self.root = Path(root).expanduser().absolute()
        self.max_bytes = max_bytes

    def save(self, *, evidence_id: int, image_bytes: bytes, metadata: PrivateFixtureMetadata) -> tuple[Path, bool]:
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("private fixture storage accepts PNG images only")
        digest = hashlib.sha256(image_bytes).hexdigest()
        evidence = self.store.connection.execute(
            "SELECT sha256 FROM capture_evidence WHERE id=?", (evidence_id,)
        ).fetchone()
        if evidence is None or evidence["sha256"] != digest:
            raise ValueError("private image does not match its capture evidence SHA-256")

        self._prepare_root()
        path = self.root / f"{digest}.png"
        row = self.store.connection.execute(
            "SELECT * FROM private_fixture_assets WHERE evidence_id=?", (evidence_id,)
        ).fetchone()
        if row is not None:
            self._assert_metadata_matches(row, metadata, digest, len(image_bytes))
            if row["status"] != "PRESENT" or not path.is_file() or path.is_symlink():
                raise RuntimeError("private image metadata exists but its image is not present")
            self._verify_digest(path, digest)
            os.chmod(path, 0o600)
            return path, False

        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("private fixture path is not a regular file")
            self._verify_digest(path, digest)
            os.chmod(path, 0o600)
            created_file = False
        else:
            if len(image_bytes) + self._stored_bytes() > self.max_bytes:
                raise OSError("private fixture storage limit would be exceeded")
            self._write_private(path, image_bytes)
            created_file = True

        relative_path = path.relative_to(self.root.parent.parent).as_posix()
        try:
            self.store.connection.execute(
                """INSERT INTO private_fixture_assets(evidence_id,relative_path,sha256,byte_size,captured_at,
                window_size_json,screen_state,ocr_engine_version,roi_json,ocr_document_json,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (evidence_id, relative_path, digest, len(image_bytes), metadata.captured_at,
                 canonical_json(metadata.window_size), metadata.screen_state.value,
                 metadata.ocr_engine_version,
                 None if metadata.roi is None else canonical_json(metadata.roi),
                 canonical_json(metadata.ocr_document), "PRESENT", utc_now()),
            )
            self.store.connection.commit()
        except Exception:
            self.store.connection.rollback()
            if created_file:
                path.unlink(missing_ok=True)
            raise
        return path, True

    def delete_image(self, evidence_id: int) -> bool:
        row = self.store.connection.execute(
            "SELECT relative_path,status FROM private_fixture_assets WHERE evidence_id=?", (evidence_id,)
        ).fetchone()
        if row is None or row["status"] == "DELETED":
            return False
        path = self._resolve_recorded_path(row["relative_path"])
        self.store.connection.execute(
            "UPDATE private_fixture_assets SET status='DELETING' WHERE evidence_id=?", (evidence_id,)
        )
        self.store.connection.commit()
        try:
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError("refusing to remove a non-regular private fixture path")
                path.unlink()
            self.store.connection.execute(
                "UPDATE private_fixture_assets SET status='DELETED',deleted_at=? WHERE evidence_id=?",
                (utc_now(), evidence_id),
            )
            self.store.connection.commit()
        except Exception:
            self.store.connection.execute(
                "UPDATE private_fixture_assets SET status=? WHERE evidence_id=?",
                ("PRESENT" if path.exists() else "DELETING", evidence_id),
            )
            self.store.connection.commit()
            raise
        return True

    def reconcile(self) -> dict[str, int]:
        """Reconcile interrupted/missing local image files without deleting metadata."""
        marked_deleted = 0
        verified = 0
        rows = self.store.connection.execute(
            "SELECT evidence_id,relative_path,sha256,status FROM private_fixture_assets ORDER BY evidence_id"
        ).fetchall()
        for row in rows:
            path = self._resolve_recorded_path(row["relative_path"])
            if not path.exists() and row["status"] in ("PRESENT", "DELETING"):
                self.store.connection.execute(
                    "UPDATE private_fixture_assets SET status='DELETED',deleted_at=? WHERE evidence_id=?",
                    (utc_now(), row["evidence_id"]),
                )
                marked_deleted += 1
            elif path.exists():
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError("recorded private fixture is not a regular file")
                self._verify_digest(path, row["sha256"])
                if row["status"] != "PRESENT":
                    self.store.connection.execute(
                        "UPDATE private_fixture_assets SET status='PRESENT',deleted_at=NULL WHERE evidence_id=?",
                        (row["evidence_id"],),
                    )
                os.chmod(path, 0o600)
                verified += 1
        self.store.connection.commit()
        return {"verified_images": verified, "marked_deleted": marked_deleted}

    def _prepare_root(self) -> None:
        if self.root.is_symlink():
            raise RuntimeError("private fixture directory must not be a symlink")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _stored_bytes(self) -> int:
        total = 0
        for path in (*self.root.glob("*.png"), *self.root.glob("*.tmp")):
            if path.is_symlink() or not path.is_file():
                continue
            total += path.stat().st_size
        return total

    def _write_private(self, path: Path, content: bytes) -> None:
        temporary = path.with_suffix(".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _resolve_recorded_path(self, relative_path: str) -> Path:
        path = (self.root.parent.parent / relative_path).absolute()
        if path.parent != self.root or path.name in ("", ".", ".."):
            raise RuntimeError("private fixture path escaped its configured directory")
        return path

    @staticmethod
    def _verify_digest(path: Path, expected: str) -> None:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError("private fixture SHA-256 does not match the evidence record")

    @staticmethod
    def _assert_metadata_matches(row: sqlite3.Row, metadata: PrivateFixtureMetadata,
                                 digest: str, size: int) -> None:
        expected_roi = None if metadata.roi is None else canonical_json(metadata.roi)
        expected = (digest, size, metadata.captured_at, canonical_json(metadata.window_size),
                    metadata.screen_state.value, metadata.ocr_engine_version, expected_roi,
                    canonical_json(metadata.ocr_document))
        actual = tuple(row[key] for key in (
            "sha256", "byte_size", "captured_at", "window_size_json", "screen_state",
            "ocr_engine_version", "roi_json", "ocr_document_json",
        ))
        if actual != expected:
            raise sqlite3.IntegrityError("the same image hash already has different capture metadata")
