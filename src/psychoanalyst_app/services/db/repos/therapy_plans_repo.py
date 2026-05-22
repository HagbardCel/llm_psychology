"""Therapy plan-related database operations."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Callable

from psychoanalyst_app.models.data_models import TherapyPlan
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.db.sqlite_config import reraise_locked_database_error
from psychoanalyst_app.services.db_serialization import (
    THERAPY_PLAN_COLUMNS,
    dump_json,
    therapy_plan_from_row,
)

logger = logging.getLogger(__name__)


async def save_therapy_plan(
    executor: TrioSQLiteExecutor,
    plan: TherapyPlan,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    """Persist a therapy plan record."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_save_therapy_plan, conn, plan, datetime_to_iso
        )


def _sync_save_therapy_plan(conn, plan: TherapyPlan, datetime_to_iso) -> bool:
    try:
        cursor = conn.cursor()
        plan_details_json = dump_json(plan.plan_details)
        initial_goals_json = dump_json(plan.initial_goals)
        planned_interventions_json = dump_json(plan.planned_interventions)
        session_briefing_json = (
            dump_json(plan.session_briefing) if plan.session_briefing else None
        )

        cursor.execute(
            """
            INSERT OR REPLACE INTO therapy_plans
            (plan_id, user_id, created_at, updated_at, plan_details,
             initial_goals, current_progress, planned_interventions, status,
             version, selected_therapy_style, session_briefing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                plan.plan_id,
                plan.user_id,
                datetime_to_iso(plan.created_at),
                datetime_to_iso(plan.updated_at),
                plan_details_json,
                initial_goals_json,
                plan.current_progress,
                planned_interventions_json,
                plan.status,
                plan.version,
                plan.selected_therapy_style,
                session_briefing_json,
            ),
        )

        conn.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        reraise_locked_database_error(exc)
        logger.error("Error saving therapy plan %s: %s", plan.plan_id, exc, exc_info=True)
        return False


async def get_latest_therapy_plan(
    executor: TrioSQLiteExecutor,
    user_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> TherapyPlan | None:
    """Fetch the newest therapy plan for a user."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_latest_therapy_plan, conn, user_id, iso_to_datetime
        )


def _sync_get_latest_therapy_plan(
    conn, user_id: str, iso_to_datetime
) -> TherapyPlan | None:
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT {THERAPY_PLAN_COLUMNS}
        FROM therapy_plans
        WHERE user_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
    """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    conn.commit()
    return therapy_plan_from_row(row, iso_to_datetime)


async def get_therapy_plan(
    executor: TrioSQLiteExecutor,
    plan_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> TherapyPlan | None:
    """Fetch a therapy plan by identifier."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_therapy_plan, conn, plan_id, iso_to_datetime
        )


def _sync_get_therapy_plan(conn, plan_id: str, iso_to_datetime) -> TherapyPlan | None:
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT {THERAPY_PLAN_COLUMNS}
        FROM therapy_plans
        WHERE plan_id = ?
    """,
        (plan_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    conn.commit()
    return therapy_plan_from_row(row, iso_to_datetime)
