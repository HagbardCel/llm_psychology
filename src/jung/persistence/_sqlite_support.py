"""SQLite connection, codec, mapping, and error helpers for the target store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from jung.domain.errors import Busy, PersistenceFailure
from jung.domain.models import (
    AppState,
    ChatTurn,
    ChatTurnStatus,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    OperationStatus,
    Plan,
    Profile,
    Session,
    SessionKind,
    Stage,
    StoredProfile,
)

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

DANGEROUS_DB_PATHS = {
    Path("data/psychoanalyst.db"),
    Path("data/usertest/psychoanalyst.db"),
}


@contextmanager
def connect(database_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(database_path)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def assert_foreign_keys(conn: sqlite3.Connection) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise PersistenceFailure("foreign key check failed after schema creation")


def seed_initial_state(conn: sqlite3.Connection) -> None:
    now = dt(datetime.now(UTC))
    conn.execute(
        """
        INSERT INTO app_state (singleton_id, stage, revision, created_at, updated_at)
        VALUES (1, ?, 0, ?, ?)
        """,
        (Stage.SETUP.value, now, now),
    )
    conn.execute(
        """
        INSERT INTO profile (
            singleton_id, name, primary_language, date_of_birth, notes,
            derived_profile_json, current_plan_id, created_at, updated_at
        ) VALUES (1, '', 'English', NULL, NULL, NULL, NULL, ?, ?)
        """,
        (now, now),
    )


def has_target_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'app_state'
        """
    ).fetchone()
    return row is not None


def is_busy_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def translate_sqlite_error(exc: BaseException) -> BaseException:
    if isinstance(exc, sqlite3.OperationalError) and is_busy_error(exc):
        return Busy("database is busy")
    if isinstance(exc, sqlite3.IntegrityError):
        return PersistenceFailure("database constraint failed")
    if isinstance(exc, sqlite3.Error):
        return PersistenceFailure("SQLite operation failed")
    return exc


def dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def date_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def row_to_app_state(row: sqlite3.Row | tuple[Any, ...]) -> AppState:
    return AppState(
        stage=Stage(row[0]),
        revision=int(row[1]),
        created_at=parse_dt(row[2]),
        updated_at=parse_dt(row[3]),
    )


def row_to_stored_profile(row: sqlite3.Row | tuple[Any, ...]) -> StoredProfile:
    profile = Profile(
        name=row[0],
        primary_language=row[1],
        date_of_birth=parse_date(row[2]),
        notes=row[3],
    )
    return StoredProfile(
        profile=profile,
        derived_profile=json_loads(row[4]),
        current_plan_id=UUID(row[5]) if row[5] else None,
        created_at=parse_dt(row[6]),
        updated_at=parse_dt(row[7]),
    )


def row_to_session(row: sqlite3.Row | tuple[Any, ...]) -> Session:
    return Session(
        id=UUID(row[0]),
        kind=SessionKind(row[1]),
        plan_id=UUID(row[2]) if row[2] else None,
        started_at=parse_dt(row[3]),
        ended_at=parse_dt(row[4]) if row[4] else None,
        summary=row[5],
        briefing=json_loads(row[6]),
    )


def row_to_message(row: sqlite3.Row | tuple[Any, ...]) -> Message:
    return Message(
        id=UUID(row[0]),
        session_id=UUID(row[1]),
        sequence=int(row[2]),
        role=MessageRole(row[3]),
        content=row[4],
        created_at=parse_dt(row[5]),
        client_message_id=UUID(row[6]) if len(row) > 6 and row[6] else None,
    )


def row_to_plan(row: sqlite3.Row | tuple[Any, ...]) -> Plan:
    return Plan(
        id=UUID(row[0]),
        version=int(row[1]),
        selected_style=row[2],
        focus=row[3],
        themes=json_loads(row[4]),
        goals=json_loads(row[5]),
        current_progress=row[6],
        planned_interventions=json_loads(row[7]),
        revision_recommendations=json_loads(row[8]),
        session_briefing=json_loads(row[9]),
        source_session_id=UUID(row[10]) if row[10] else None,
        supersedes_plan_id=UUID(row[11]) if row[11] else None,
        created_at=parse_dt(row[12]),
    )


def row_to_operation(row: sqlite3.Row | tuple[Any, ...]) -> Operation:
    return Operation(
        id=UUID(row[0]),
        kind=OperationKind(row[1]),
        status=OperationStatus(row[2]),
        source_session_id=UUID(row[3]),
        attempt=int(row[4]),
        result=json_loads(row[5]),
        error_code=row[6],
        error_message=row[7],
        retryable=bool(row[8]),
        created_at=parse_dt(row[9]),
        updated_at=parse_dt(row[10]),
        started_at=parse_dt(row[11]) if row[11] else None,
        completed_at=parse_dt(row[12]) if row[12] else None,
    )


def row_to_chat_turn(row: sqlite3.Row | tuple[Any, ...]) -> ChatTurn:
    return ChatTurn(
        id=UUID(row[0]),
        session_id=UUID(row[1]),
        client_message_id=UUID(row[2]),
        status=ChatTurnStatus(row[3]),
        user_message_id=UUID(row[4]),
        assistant_message_id=UUID(row[5]) if row[5] else None,
        error_code=row[6],
        error_message=row[7],
        retryable=bool(row[8]),
        created_at=parse_dt(row[9]),
        updated_at=parse_dt(row[10]),
        completed_at=parse_dt(row[11]) if row[11] else None,
    )
