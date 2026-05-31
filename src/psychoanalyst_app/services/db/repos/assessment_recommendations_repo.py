"""Assessment recommendation persistence."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime

from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.db.sqlite_config import reraise_locked_database_error
from psychoanalyst_app.services.db_serialization import dump_json, load_json

logger = logging.getLogger(__name__)


async def save_assessment_recommendations(
    executor: TrioSQLiteExecutor,
    *,
    user_id: str,
    intake_session_block_id: str,
    recommendations: list[dict],
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    """Persist assessment recommendations for a user and intake session block."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_save_assessment_recommendations,
            conn,
            user_id,
            intake_session_block_id,
            recommendations,
            datetime_to_iso,
        )


def _sync_save_assessment_recommendations(
    conn,
    user_id: str,
    intake_session_block_id: str,
    recommendations: list[dict],
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    try:
        cursor = conn.cursor()
        payload = dump_json(recommendations)
        created_at = datetime_to_iso(datetime.now())
        logger.info(
            "Saving assessment recommendations: user_id=%s block_id=%s len=%s",
            user_id,
            intake_session_block_id,
            len(payload),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO assessment_recommendations
            (user_id, intake_session_block_id, recommendations, created_at)
            VALUES (?, ?, ?, ?)
        """,
            (user_id, intake_session_block_id, payload, created_at),
        )
        logger.info(f"Saved assessment recommendations. Row count: {cursor.rowcount}")
        conn.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        reraise_locked_database_error(exc)
        logger.error(
            "Error saving assessment recommendations for user %s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        return False


async def get_latest_assessment_recommendations(
    executor: TrioSQLiteExecutor,
    user_id: str,
) -> list[dict] | None:
    """Fetch the latest assessment recommendations for a user."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_latest_assessment_recommendations, conn, user_id
        )


def _sync_get_latest_assessment_recommendations(
    conn, user_id: str
) -> list[dict] | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT recommendations
        FROM assessment_recommendations
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    conn.commit()
    return load_json(row["recommendations"], default=[])
