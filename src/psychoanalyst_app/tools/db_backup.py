"""Local SQLite backup, verification, and restore utility."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psychoanalyst_app.config import Settings

MANIFEST_SUFFIX = ".manifest.json"


@dataclass(frozen=True)
class BackupResult:
    backup_path: Path
    manifest_path: Path
    sha256: str
    size_bytes: int
    integrity_check: str


@dataclass(frozen=True)
class RestoreResult:
    restored_path: Path
    safety_backup_path: Path | None


class BackupError(RuntimeError):
    """Raised when a backup operation cannot be completed safely."""


class VerificationError(RuntimeError):
    """Raised when a backup fails verification."""


class RestoreError(RuntimeError):
    """Raised when a restore operation cannot be completed safely."""


def backup_database(
    db_path: str | Path,
    backup_dir: str | Path,
    *,
    prefix: str = "psychoanalyst_backup",
) -> BackupResult:
    """Create a consistent SQLite backup and manifest."""
    source_path = Path(db_path)
    if not source_path.exists():
        raise BackupError(f"Database does not exist: {source_path}")
    if not source_path.is_file():
        raise BackupError(f"Database path is not a file: {source_path}")

    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    backup_path = _next_backup_path(destination_dir, prefix)
    _copy_sqlite_database(source_path, backup_path)

    integrity_check = check_integrity(backup_path)
    sha256 = calculate_sha256(backup_path)
    size_bytes = backup_path.stat().st_size
    manifest_path = manifest_for_backup(backup_path)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_db_path": str(source_path),
        "backup_file": backup_path.name,
        "file_size_bytes": size_bytes,
        "sha256": sha256,
        "sqlite_version": sqlite3.sqlite_version,
        "integrity_check": integrity_check,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return BackupResult(
        backup_path=backup_path,
        manifest_path=manifest_path,
        sha256=sha256,
        size_bytes=size_bytes,
        integrity_check=integrity_check,
    )


def verify_backup(backup_file: str | Path) -> dict[str, Any]:
    """Verify a backup file against its manifest and SQLite integrity check."""
    backup_path = Path(backup_file)
    if not backup_path.exists():
        raise VerificationError(f"Backup file does not exist: {backup_path}")
    if not backup_path.is_file():
        raise VerificationError(f"Backup path is not a file: {backup_path}")

    manifest_path = manifest_for_backup(backup_path)
    if not manifest_path.exists():
        raise VerificationError(f"Manifest file does not exist: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VerificationError(f"Manifest is not valid JSON: {manifest_path}") from exc

    expected_hash = manifest.get("sha256")
    actual_hash = calculate_sha256(backup_path)
    if expected_hash != actual_hash:
        raise VerificationError(
            f"Backup hash mismatch: expected {expected_hash}, got {actual_hash}"
        )

    expected_size = manifest.get("file_size_bytes")
    actual_size = backup_path.stat().st_size
    if expected_size != actual_size:
        raise VerificationError(
            f"Backup size mismatch: expected {expected_size}, got {actual_size}"
        )

    integrity_check = check_integrity(backup_path)
    if integrity_check.lower() != "ok":
        raise VerificationError(f"SQLite integrity check failed: {integrity_check}")

    manifest["verified_at"] = datetime.now(UTC).isoformat()
    manifest["actual_sha256"] = actual_hash
    manifest["actual_file_size_bytes"] = actual_size
    manifest["actual_integrity_check"] = integrity_check
    return manifest


def restore_backup(
    backup_file: str | Path,
    db_path: str | Path,
    *,
    replace: bool = False,
    safety_backup_dir: str | Path | None = None,
) -> RestoreResult:
    """Restore a verified backup to the target database path."""
    backup_path = Path(backup_file)
    target_path = Path(db_path)
    if backup_path.resolve(strict=False) == target_path.resolve(strict=False):
        raise RestoreError("Backup file and target database must be different paths.")
    verify_backup(backup_path)

    if target_path.exists() and not replace:
        raise RestoreError(
            f"Target database already exists: {target_path}. Pass --replace to restore."
        )

    safety_backup_path = None
    if target_path.exists():
        backup_dir = (
            Path(safety_backup_dir)
            if safety_backup_dir is not None
            else target_path.parent / "backups"
        )
        safety_result = backup_database(
            target_path,
            backup_dir,
            prefix="pre_restore_backup",
        )
        safety_backup_path = safety_result.backup_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    _delete_sqlite_artifacts(target_path)
    shutil.copy2(backup_path, target_path)

    restored_integrity = check_integrity(target_path)
    if restored_integrity.lower() != "ok":
        raise RestoreError(
            f"Restored database failed integrity check: {restored_integrity}"
        )

    return RestoreResult(
        restored_path=target_path,
        safety_backup_path=safety_backup_path,
    )


def check_integrity(db_path: str | Path) -> str:
    """Run SQLite integrity_check for a database file."""
    path = Path(db_path)
    try:
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise VerificationError(
            f"SQLite integrity check could not open {path}"
        ) from exc
    return str(row[0]) if row else "missing integrity_check result"


def calculate_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_for_backup(backup_file: str | Path) -> Path:
    path = Path(backup_file)
    return path.with_name(path.name + MANIFEST_SUFFIX)


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = _build_parser(settings)
    args = parser.parse_args(argv)

    try:
        if args.command == "backup":
            result = backup_database(args.db_path, args.backup_dir)
            print(f"Backup created: {result.backup_path}")
            print(f"Manifest: {result.manifest_path}")
            print(f"SHA-256: {result.sha256}")
            print(f"Integrity: {result.integrity_check}")
            return 0

        if args.command == "verify":
            manifest = verify_backup(args.backup_file)
            print(f"Backup verified: {args.backup_file}")
            print(f"SHA-256: {manifest['actual_sha256']}")
            print(f"Integrity: {manifest['actual_integrity_check']}")
            return 0

        if args.command == "restore":
            result = restore_backup(
                args.backup_file,
                args.db_path,
                replace=args.replace,
                safety_backup_dir=args.safety_backup_dir,
            )
            print(f"Database restored: {result.restored_path}")
            if result.safety_backup_path is not None:
                print(f"Pre-restore backup: {result.safety_backup_path}")
            return 0

    except (BackupError, VerificationError, RestoreError) as exc:
        print(f"Error: {exc}")
        return 1

    parser.print_help()
    return 2


def _build_parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="psychoanalyst-db",
        description="Back up, verify, and restore the local SQLite database.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="Create a SQLite backup")
    backup_parser.add_argument("--db-path", default=settings.DATABASE_PATH)
    backup_parser.add_argument("--backup-dir", default=settings.DATABASE_BACKUP_DIR)

    verify_parser = subparsers.add_parser("verify", help="Verify a backup file")
    verify_parser.add_argument("backup_file")

    restore_parser = subparsers.add_parser("restore", help="Restore a backup file")
    restore_parser.add_argument("backup_file")
    restore_parser.add_argument("--db-path", default=settings.DATABASE_PATH)
    restore_parser.add_argument(
        "--replace",
        action="store_true",
        help="Required when the target database already exists.",
    )
    restore_parser.add_argument(
        "--safety-backup-dir",
        default=None,
        help="Directory for the pre-restore safety backup.",
    )
    return parser


def _copy_sqlite_database(source_path: Path, backup_path: Path) -> None:
    try:
        with sqlite3.connect(str(source_path)) as source_conn:
            with sqlite3.connect(str(backup_path)) as backup_conn:
                source_conn.backup(backup_conn)
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"SQLite backup failed for {source_path}") from exc


def _next_backup_path(backup_dir: Path, prefix: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    return backup_dir / f"{prefix}_{timestamp}.db"


def _delete_sqlite_artifacts(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            candidate.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
