"""Session-related database operations."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from psychoanalyst_app.models.domain import Session
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.db.sqlite_config import reraise_locked_database_error
from psychoanalyst_app.services.db_serialization import (
    SESSION_COLUMNS,
    dump_intake_note_tracking_diagnostics,
    dump_intake_record,
    dump_json,
    dump_messages,
    dump_topics,
    session_from_row,
)

logger = logging.getLogger(__name__)

_CORRUPT_SESSION_DATA_ERRORS = (json.JSONDecodeError, TypeError, ValidationError)


def _reraise_if_corrupt_session_data(exc: Exception, log_context: str) -> None:
    if isinstance(exc, _CORRUPT_SESSION_DATA_ERRORS):
        logger.error(
            "Invalid persisted session data (%s)",
            log_context,
            exc_info=True,
        )
        raise


async def save_session(
    executor: TrioSQLiteExecutor,
    session: Session,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    """Persist a session record."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_save_session, conn, session, datetime_to_iso
        )


def _sync_save_session(conn, session: Session, datetime_to_iso) -> bool:
    try:
        cursor = conn.cursor()
        transcript_json = dump_messages(session.transcript)
        topics_json = dump_topics(session.topics)
        session_briefing_json = (
            dump_json(session.session_briefing) if session.session_briefing else None
        )
        intake_record_json = dump_intake_record(session.intake_record)
        intake_record_updated_at = (
            datetime_to_iso(session.intake_record_updated_at)
            if session.intake_record_updated_at
            else None
        )
        intake_diagnostics_json = dump_intake_note_tracking_diagnostics(
            session.intake_note_tracking_diagnostics
        )

        cursor.execute(
            """
            INSERT INTO sessions
            (session_id, user_id, session_type, plan_id, timestamp, transcript, topics,
             session_summary, session_briefing, intake_record, intake_record_updated_at,
             intake_note_tracking_diagnostics)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                user_id = excluded.user_id,
                timestamp = excluded.timestamp,
                transcript = excluded.transcript,
                topics = excluded.topics,
                session_summary = excluded.session_summary,
                session_briefing = excluded.session_briefing,
                intake_record = excluded.intake_record,
                intake_record_updated_at = excluded.intake_record_updated_at,
                intake_note_tracking_diagnostics = (
                    excluded.intake_note_tracking_diagnostics
                )
            WHERE sessions.enriched = 0
        """,
            (
                session.session_id,
                session.user_id,
                session.session_type,
                session.plan_id,
                datetime_to_iso(session.timestamp),
                transcript_json,
                topics_json,
                session.session_summary,
                session_briefing_json,
                intake_record_json,
                intake_record_updated_at,
                intake_diagnostics_json,
            ),
        )

        conn.commit()
        if cursor.rowcount > 0:
            logger.info("Session %s saved successfully", session.session_id)
            return True

        logger.warning(
            "Session %s not saved because it is already enriched (immutable)",
            session.session_id,
        )
        return False
    except Exception as exc:  # pragma: no cover - defensive logging
        reraise_locked_database_error(exc)
        logger.error("Error saving session %s: %s", session.session_id, exc)
        return False


async def get_session(
    executor: TrioSQLiteExecutor,
    session_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> Session | None:
    """Fetch a single session by ID."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_session, conn, session_id, iso_to_datetime
        )


def _sync_get_session(conn, session_id: str, iso_to_datetime) -> Session | None:
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT {SESSION_COLUMNS}
            FROM sessions
            WHERE session_id = ?
        """,
            (session_id,),
        )

        row = cursor.fetchone()
        if not row:
            return None

        conn.commit()
        return session_from_row(row, iso_to_datetime)
    except Exception as exc:  # pragma: no cover - defensive logging
        _reraise_if_corrupt_session_data(exc, f"session_id={session_id}")
        reraise_locked_database_error(exc)
        logger.error("Error retrieving session %s: %s", session_id, exc, exc_info=True)
        return None


async def get_user_sessions(
    executor: TrioSQLiteExecutor,
    user_id: str,
    limit: int,
    iso_to_datetime: Callable[[str], datetime],
) -> list[Session]:
    """Return a list of recent sessions for a user."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_user_sessions, conn, user_id, limit, iso_to_datetime
        )


def _sync_get_user_sessions(
    conn, user_id: str, limit: int, iso_to_datetime
) -> list[Session]:
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT {SESSION_COLUMNS}
            FROM sessions
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (user_id, limit),
        )

        rows = cursor.fetchall()
        sessions = [session_from_row(row, iso_to_datetime) for row in rows]

        conn.commit()
        return sessions
    except Exception as exc:  # pragma: no cover
        _reraise_if_corrupt_session_data(exc, f"user_id={user_id} list-read")
        reraise_locked_database_error(exc)
        logger.error("Error retrieving sessions for user %s: %s", user_id, exc)
        return []


async def get_all_sessions_for_user(
    executor: TrioSQLiteExecutor,
    user_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> list[Session]:
    """Fetch all sessions for a user."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_all_sessions, conn, user_id, iso_to_datetime
        )


def _sync_get_all_sessions(conn, user_id: str, iso_to_datetime) -> list[Session]:
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT {SESSION_COLUMNS}
            FROM sessions
            WHERE user_id = ?
            ORDER BY timestamp DESC
        """,
            (user_id,),
        )

        rows = cursor.fetchall()
        sessions = [session_from_row(row, iso_to_datetime) for row in rows]

        conn.commit()
        return sessions
    except Exception as exc:  # pragma: no cover
        _reraise_if_corrupt_session_data(exc, f"user_id={user_id} all-sessions-read")
        reraise_locked_database_error(exc)
        logger.error("Error retrieving all sessions for %s: %s", user_id, exc)
        return []


async def get_recent_sessions(
    executor: TrioSQLiteExecutor,
    user_id: str,
    limit: int,
    enriched_only: bool,
    iso_to_datetime: Callable[[str], datetime],
) -> list[Session]:
    """Fetch recent sessions with optional enrichment filter."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_recent_sessions,
            conn,
            user_id,
            limit,
            enriched_only,
            iso_to_datetime,
        )


def _sync_get_recent_sessions(
    conn,
    user_id: str,
    limit: int,
    enriched_only: bool,
    iso_to_datetime,
) -> list[Session]:
    try:
        cursor = conn.cursor()
        where_clause = "WHERE user_id = ?"
        if enriched_only:
            where_clause += " AND enriched = 1"
        cursor.execute(
            f"""
            SELECT {SESSION_COLUMNS}
            FROM sessions
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        sessions = [session_from_row(row, iso_to_datetime) for row in rows]
        conn.commit()
        return sessions
    except Exception as exc:  # pragma: no cover
        _reraise_if_corrupt_session_data(exc, f"user_id={user_id} recent-sessions-read")
        reraise_locked_database_error(exc)
        logger.error("Error retrieving recent sessions for %s: %s", user_id, exc)
        return []


async def get_session_count(executor: TrioSQLiteExecutor, user_id: str) -> int:
    """Count number of sessions for a user."""
    async with executor.connection() as conn:
        return await executor.run_sync(_sync_get_session_count, conn, user_id)


def _sync_get_session_count(conn, user_id: str) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,))
    (count,) = cursor.fetchone() or (0,)
    conn.commit()
    return int(count)


async def update_session_tier2(
    executor: TrioSQLiteExecutor, session_id: str, tier2_data: dict
) -> bool:
    """Update Tier 2 enrichment data for a session."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_update_session_tier2, conn, session_id, tier2_data
        )


def _sync_update_session_tier2(conn, session_id: str, tier2_data: dict) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sessions
        SET psychological_summary = ?, dominant_affects = ?, key_themes = ?,
            notable_interactions = ?, interpretations = ?, patient_reactions = ?,
            enriched = 1
        WHERE session_id = ?
        """,
        (
            tier2_data.get("psychological_summary", ""),
            dump_json(tier2_data.get("dominant_affects", [])),
            dump_json(tier2_data.get("key_themes", [])),
            tier2_data.get("notable_interactions", ""),
            tier2_data.get("interpretations", ""),
            tier2_data.get("patient_reactions", ""),
            session_id,
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


async def update_session_reflection(
    executor: TrioSQLiteExecutor,
    session_id: str,
    session_summary: str | None,
    session_briefing: dict | None,
) -> bool:
    """Persist reflection summary/briefing for a session."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_update_session_reflection,
            conn,
            session_id,
            session_summary,
            session_briefing,
        )


def _sync_update_session_reflection(
    conn,
    session_id: str,
    session_summary: str | None,
    session_briefing: dict | None,
) -> bool:
    cursor = conn.cursor()
    session_briefing_json = dump_json(session_briefing) if session_briefing else None
    cursor.execute(
        """
        UPDATE sessions
        SET session_summary = ?, session_briefing = ?
        WHERE session_id = ?
        """,
        (
            session_summary,
            session_briefing_json,
            session_id,
        ),
    )
    conn.commit()
    return cursor.rowcount > 0
