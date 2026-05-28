"""Unit tests for the local SQLite backup utility."""

import json
import sqlite3
from pathlib import Path

import pytest

from psychoanalyst_app.tools.db_backup import (
    BackupError,
    RestoreError,
    VerificationError,
    backup_database,
    calculate_sha256,
    manifest_for_backup,
    restore_backup,
    verify_backup,
)

pytestmark = pytest.mark.unit


def test_backup_creates_verified_sqlite_copy_and_manifest(tmp_path):
    db_path = tmp_path / "psychoanalyst.db"
    backup_dir = tmp_path / "backups"
    _create_database(db_path, [("u1", "first"), ("u2", "second")])

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("INSERT INTO notes VALUES (?, ?)", ("u3", "third"))
        conn.commit()

    result = backup_database(db_path, backup_dir)

    assert result.backup_path.exists()
    assert result.manifest_path.exists()
    assert result.integrity_check == "ok"
    assert result.sha256 == calculate_sha256(result.backup_path)

    manifest = verify_backup(result.backup_path)
    assert manifest["backup_file"] == result.backup_path.name
    assert manifest["source_db_path"] == str(db_path)
    assert manifest["actual_integrity_check"] == "ok"

    with sqlite3.connect(result.backup_path) as conn:
        rows = conn.execute(
            "SELECT user_id, body FROM notes ORDER BY user_id"
        ).fetchall()

    assert rows == [("u1", "first"), ("u2", "second"), ("u3", "third")]


def test_backup_requires_existing_database(tmp_path):
    with pytest.raises(BackupError, match="Database does not exist"):
        backup_database(tmp_path / "missing.db", tmp_path / "backups")


def test_verify_fails_when_manifest_hash_does_not_match(tmp_path):
    db_path = tmp_path / "source.db"
    _create_database(db_path, [("u1", "first")])
    result = backup_database(db_path, tmp_path / "backups")

    manifest_path = manifest_for_backup(result.backup_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = "not-the-real-hash"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(VerificationError, match="Backup hash mismatch"):
        verify_backup(result.backup_path)


def test_verify_fails_for_corrupted_sqlite_backup(tmp_path):
    backup_path = tmp_path / "corrupt.db"
    backup_path.write_bytes(b"this is not sqlite")
    manifest_for_backup(backup_path).write_text(
        json.dumps(
            {
                "backup_file": backup_path.name,
                "file_size_bytes": backup_path.stat().st_size,
                "sha256": calculate_sha256(backup_path),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(VerificationError, match="integrity check could not open"):
        verify_backup(backup_path)


def test_restore_refuses_to_replace_existing_target_without_flag(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _create_database(source_path, [("u1", "from backup")])
    _create_database(target_path, [("old", "keep me")])
    result = backup_database(source_path, tmp_path / "backups")

    with pytest.raises(RestoreError, match="Pass --replace"):
        restore_backup(result.backup_path, target_path)

    assert _read_notes(target_path) == [("old", "keep me")]


def test_restore_refuses_same_backup_and_target_path(tmp_path):
    db_path = tmp_path / "target.db"
    _create_database(db_path, [("u1", "same path")])

    with pytest.raises(RestoreError, match="must be different paths"):
        restore_backup(db_path, db_path, replace=True)


def test_restore_replaces_target_creates_safety_backup_and_removes_stale_wal(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    backup_dir = tmp_path / "backups"
    safety_dir = tmp_path / "safety"
    _create_database(source_path, [("new", "restored")])
    _create_database(target_path, [("old", "safety copy")])
    Path(f"{target_path}-wal").write_text("stale wal", encoding="utf-8")
    Path(f"{target_path}-shm").write_text("stale shm", encoding="utf-8")
    backup = backup_database(source_path, backup_dir)

    result = restore_backup(
        backup.backup_path,
        target_path,
        replace=True,
        safety_backup_dir=safety_dir,
    )

    assert result.restored_path == target_path
    assert result.safety_backup_path is not None
    assert result.safety_backup_path.exists()
    assert _read_notes(target_path) == [("new", "restored")]
    assert _read_notes(result.safety_backup_path) == [("old", "safety copy")]
    assert not Path(f"{target_path}-wal").exists()
    assert not Path(f"{target_path}-shm").exists()


def _create_database(path, rows):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE notes (user_id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        conn.executemany("INSERT INTO notes VALUES (?, ?)", rows)
        conn.commit()


def _read_notes(path):
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT user_id, body FROM notes ORDER BY user_id"
        ).fetchall()
