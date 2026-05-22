"""Session enrichment job queue repository."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import sqlite3

from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.db.sqlite_config import reraise_locked_database_error

logger = logging.getLogger(__name__)


async def enqueue_job(
    executor: TrioSQLiteExecutor, session_id: str, user_id: str
) -> bool:
    """Enqueue or requeue a session for enrichment."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_enqueue_job, conn, session_id, user_id
        )


def _sync_enqueue_job(
    conn: sqlite3.Connection, session_id: str, user_id: str
) -> bool:
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO session_enrichment_jobs
            (session_id, user_id, status, attempts, last_error, created_at, updated_at)
            VALUES (?, ?, 'queued', 0, NULL, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                status = CASE
                    WHEN session_enrichment_jobs.status = 'complete' THEN 'complete'
                    ELSE 'queued'
                END,
                updated_at = excluded.updated_at
            """,
            (session_id, user_id, now, now),
        )
        conn.commit()
        return True
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error enqueuing enrichment job: %s", exc, exc_info=True)
        conn.rollback()
        return False


async def claim_next_job(
    executor: TrioSQLiteExecutor, max_attempts: int
) -> dict[str, Any] | None:
    """Atomically claim the next queued enrichment job."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_claim_next_job, conn, max_attempts
        )


def _sync_claim_next_job(
    conn: sqlite3.Connection, max_attempts: int
) -> dict[str, Any] | None:
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            SELECT session_id, user_id, attempts
            FROM session_enrichment_jobs
            WHERE status = 'queued' AND attempts < ?
            ORDER BY updated_at ASC
            LIMIT 1
            """,
            (max_attempts,),
        )
        row = cursor.fetchone()
        if not row:
            conn.commit()
            return None

        session_id, user_id, attempts = row
        cursor.execute(
            """
            UPDATE session_enrichment_jobs
            SET status = 'processing',
                attempts = attempts + 1,
                updated_at = ?
            WHERE session_id = ?
            """,
            (datetime.now().isoformat(), session_id),
        )
        conn.commit()
        return {
            "session_id": session_id,
            "user_id": user_id,
            "attempts": attempts + 1,
            "status": "processing",
        }
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error claiming enrichment job: %s", exc, exc_info=True)
        conn.rollback()
        return None


async def mark_job_complete(executor: TrioSQLiteExecutor, session_id: str) -> bool:
    """Mark an enrichment job as complete."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_mark_job_complete, conn, session_id
        )


def _sync_mark_job_complete(
    conn: sqlite3.Connection, session_id: str
) -> bool:
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE session_enrichment_jobs
            SET status = 'complete',
                last_error = NULL,
                updated_at = ?
            WHERE session_id = ?
            """,
            (datetime.now().isoformat(), session_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error marking job complete: %s", exc, exc_info=True)
        conn.rollback()
        return False


async def mark_job_failed(
    executor: TrioSQLiteExecutor, session_id: str, error: str
) -> bool:
    """Mark an enrichment job as failed with error text."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_mark_job_failed, conn, session_id, error
        )


def _sync_mark_job_failed(
    conn: sqlite3.Connection, session_id: str, error: str
) -> bool:
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE session_enrichment_jobs
            SET status = 'failed',
                last_error = ?,
                updated_at = ?
            WHERE session_id = ?
            """,
            (error[:2000], datetime.now().isoformat(), session_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error marking job failed: %s", exc, exc_info=True)
        conn.rollback()
        return False
