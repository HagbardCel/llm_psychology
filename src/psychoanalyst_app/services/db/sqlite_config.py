"""Shared SQLite connection configuration and datetime codecs."""

from __future__ import annotations

import sqlite3
from datetime import datetime

LOCKED_DATABASE_MARKERS = (
    "database is locked",
    "database table is locked",
    "database is busy",
)


def is_memory_database(db_path: str) -> bool:
    """Return True for SQLite in-memory database paths/URIs."""
    if db_path == ":memory:":
        return True
    if not db_path.startswith("file:"):
        return False
    return "mode=memory" in db_path or db_path.startswith("file::memory:")


def configure_connection(
    conn: sqlite3.Connection,
    *,
    db_path: str,
    busy_timeout_ms: int,
) -> None:
    """Apply project-standard SQLite pragmas to a connection."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")

    if not is_memory_database(db_path):
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")


def is_locked_database_error(exc: BaseException) -> bool:
    """Return True for transient SQLite lock/busy operational errors."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    message = str(exc).lower()
    return any(marker in message for marker in LOCKED_DATABASE_MARKERS)


def reraise_locked_database_error(exc: BaseException) -> None:
    """Let executor-level retry handle transient SQLite lock failures."""
    if is_locked_database_error(exc):
        raise exc


def datetime_to_iso(value: datetime) -> str:
    """Serialize datetime to ISO string."""
    return value.isoformat()


def iso_to_datetime(value: str) -> datetime:
    """Deserialize ISO string to datetime."""
    return datetime.fromisoformat(value)
