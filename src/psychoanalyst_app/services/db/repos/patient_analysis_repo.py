"""Patient analysis (Tier 3) repository helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

import sqlite3

from psychoanalyst_app.models.data_models import PatientAnalysisVersion
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.db.sqlite_config import reraise_locked_database_error
from psychoanalyst_app.services.db_serialization import (
    PATIENT_ANALYSIS_COLUMNS,
    analysis_version_from_row,
)

logger = logging.getLogger(__name__)


async def get_latest_analysis(
    executor: TrioSQLiteExecutor,
    user_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> PatientAnalysisVersion | None:
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_latest_analysis, conn, user_id, iso_to_datetime
        )


def _sync_get_latest_analysis(
    conn: sqlite3.Connection,
    user_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> PatientAnalysisVersion | None:
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT {PATIENT_ANALYSIS_COLUMNS}
        FROM patient_analysis
        WHERE user_id = ?
        ORDER BY version DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    return analysis_version_from_row(row, iso_to_datetime)


async def get_analysis_version(
    executor: TrioSQLiteExecutor,
    user_id: str,
    version: int,
    iso_to_datetime: Callable[[str], datetime],
) -> PatientAnalysisVersion | None:
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_analysis_version, conn, user_id, version, iso_to_datetime
        )


def _sync_get_analysis_version(
    conn: sqlite3.Connection,
    user_id: str,
    version: int,
    iso_to_datetime: Callable[[str], datetime],
) -> PatientAnalysisVersion | None:
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT {PATIENT_ANALYSIS_COLUMNS}
        FROM patient_analysis
        WHERE user_id = ? AND version = ?
        """,
        (user_id, version),
    )
    row = cursor.fetchone()
    if not row:
        return None

    return analysis_version_from_row(row, iso_to_datetime)


async def get_analysis_history(
    executor: TrioSQLiteExecutor,
    user_id: str,
) -> list[PatientAnalysisVersion]:
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_analysis_history, conn, user_id
        )


def _sync_get_analysis_history(
    conn: sqlite3.Connection, user_id: str
) -> list[PatientAnalysisVersion]:
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT {PATIENT_ANALYSIS_COLUMNS}
        FROM patient_analysis
        WHERE user_id = ?
        ORDER BY version DESC
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    return [
        analysis_version_from_row(row, datetime.fromisoformat) for row in rows
    ]


async def save_analysis_version(
    executor: TrioSQLiteExecutor,
    analysis: PatientAnalysisVersion,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_save_analysis_version, conn, analysis, datetime_to_iso
        )


def _sync_save_analysis_version(
    conn: sqlite3.Connection,
    analysis: PatientAnalysisVersion,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO patient_analysis
            (analysis_id, user_id, version, analysis_data, created_at,
             created_by_session, change_summary, superseded_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis.analysis_id,
                analysis.user_id,
                analysis.version,
                analysis.analysis_data.model_dump_json(),
                datetime_to_iso(analysis.created_at),
                analysis.created_by_session,
                analysis.change_summary,
                analysis.superseded_by,
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError as exc:  # pragma: no cover
        logger.error("Analysis version conflict: %s", exc)
        conn.rollback()
        return False
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error saving analysis: %s", exc, exc_info=True)
        conn.rollback()
        return False


async def save_analysis_version_and_supersede(
    executor: TrioSQLiteExecutor,
    analysis: PatientAnalysisVersion,
    superseded_analysis_id: str | None,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_save_analysis_version_and_supersede,
            conn,
            analysis,
            superseded_version,
            datetime_to_iso,
        )


def _sync_save_analysis_version_and_supersede(
    conn: sqlite3.Connection,
    analysis: PatientAnalysisVersion,
    superseded_analysis_id: str | None,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            """
            INSERT INTO patient_analysis
            (analysis_id, user_id, version, analysis_data, created_at,
             created_by_session, change_summary, superseded_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis.analysis_id,
                analysis.user_id,
                analysis.version,
                analysis.analysis_data.model_dump_json(),
                datetime_to_iso(analysis.created_at),
                analysis.created_by_session,
                analysis.change_summary,
                analysis.superseded_by,
            ),
        )

        if superseded_analysis_id:
            cursor.execute(
                """
                UPDATE patient_analysis
                SET superseded_by = ?
                WHERE analysis_id = ?
                """,
                (analysis.analysis_id, superseded_analysis_id),
            )

        conn.commit()
        return True
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error superseding analysis: %s", exc, exc_info=True)
        conn.rollback()
        return False


async def save_next_analysis_version(
    executor: TrioSQLiteExecutor,
    analysis: PatientAnalysisVersion,
    superseded_analysis_id: str | None,
    datetime_to_iso: Callable[[datetime], str],
) -> PatientAnalysisVersion | None:
    """Create the next version number and optionally supersede a previous analysis."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_save_next_analysis_version,
            conn,
            analysis,
            superseded_analysis_id,
            datetime_to_iso,
        )


def _sync_save_next_analysis_version(
    conn: sqlite3.Connection,
    analysis: PatientAnalysisVersion,
    superseded_analysis_id: str | None,
    datetime_to_iso: Callable[[datetime], str],
) -> PatientAnalysisVersion | None:
    cursor = conn.cursor()
    cursor.execute("BEGIN IMMEDIATE")
    cursor.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM patient_analysis WHERE user_id = ?",
        (analysis.user_id,),
    )
    row = cursor.fetchone()
    next_version = int(row[0]) if row and row[0] else 1
    analysis.version = next_version
    saved = _sync_save_analysis_version(conn, analysis, datetime_to_iso)
    if not saved:
        conn.rollback()
        return None
    if superseded_analysis_id:
        cursor.execute(
            """
            UPDATE patient_analysis
            SET superseded_by = ?
            WHERE analysis_id = ?
            """,
            (analysis.analysis_id, superseded_analysis_id),
        )
    conn.commit()
    return analysis


async def mark_analysis_superseded(
    executor: TrioSQLiteExecutor,
    old_analysis_id: str,
    new_analysis_id: str,
) -> bool:
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_mark_analysis_superseded, conn, old_analysis_id, new_analysis_id
        )


def _sync_mark_analysis_superseded(
    conn: sqlite3.Connection, old_analysis_id: str, new_analysis_id: str
) -> bool:
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE patient_analysis
            SET superseded_by = ?
            WHERE analysis_id = ?
            """,
            (new_analysis_id, old_analysis_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error marking analysis superseded: %s", exc, exc_info=True)
        conn.rollback()
        return False
