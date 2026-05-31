"""Therapy plan-related database operations."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Callable

from psychoanalyst_app.models.domain import TherapyPlan
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
    """Persist a new immutable therapy plan revision."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_save_therapy_plan, conn, plan, datetime_to_iso
        )


def _sync_save_therapy_plan(conn, plan: TherapyPlan, datetime_to_iso) -> bool:
    try:
        cursor = conn.cursor()
        plan_details_json = dump_json(plan.plan_details)
        initial_goals_json = dump_json(plan.initial_goals)
        planned_interventions_json = dump_json(plan.planned_interventions)
        revision_recommendations_json = dump_json(plan.revision_recommendations)
        session_briefing_json = (
            dump_json(plan.session_briefing) if plan.session_briefing else None
        )

        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("PRAGMA defer_foreign_keys = ON")
        cursor.execute(
            """
            SELECT plan_id, version
            FROM therapy_plans
            WHERE user_id = ? AND superseded_by_plan_id IS NULL
            """,
            (plan.user_id,),
        )
        current = cursor.fetchone()
        if current:
            if current["plan_id"] == plan.plan_id:
                raise ValueError("Therapy plan revisions are immutable")
            plan.supersedes_plan_id = current["plan_id"]
            plan.version = current["version"] + 1
            cursor.execute(
                """
                UPDATE therapy_plans
                SET status = 'superseded', superseded_by_plan_id = ?, updated_at = ?
                WHERE plan_id = ? AND superseded_by_plan_id IS NULL
                """,
                (
                    plan.plan_id,
                    datetime_to_iso(plan.updated_at),
                    current["plan_id"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Current therapy plan changed during revision write")
        else:
            plan.supersedes_plan_id = None
            plan.version = 1

        cursor.execute(
            """
            INSERT INTO therapy_plans
            (plan_id, user_id, created_at, updated_at, plan_details,
             initial_goals, current_progress, planned_interventions, status,
             version, selected_therapy_style, session_briefing, supersedes_plan_id,
             superseded_by_plan_id, revision_recommendations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                plan.supersedes_plan_id,
                None,
                revision_recommendations_json,
            ),
        )
        cursor.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?",
            (plan.user_id,),
        )
        profile = cursor.fetchone()
        if not profile:
            raise ValueError(f"User profile not found: {plan.user_id}")
        previous_profile_data = dump_json(dict(profile))
        cursor.execute(
            """
            UPDATE user_profiles
            SET plan_id = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (plan.plan_id, datetime_to_iso(plan.updated_at), plan.user_id),
        )
        cursor.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?",
            (plan.user_id,),
        )
        new_profile_data = dump_json(dict(cursor.fetchone()))
        cursor.execute(
            """
            INSERT INTO user_profile_history
            (history_id, user_id, previous_profile_data, new_profile_data,
             change_summary, created_at, created_by_session)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                f"uph_{uuid.uuid4().hex[:12]}",
                plan.user_id,
                previous_profile_data,
                new_profile_data,
                f"Linked therapy plan revision {plan.version}",
                datetime_to_iso(plan.updated_at),
            ),
        )

        conn.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        reraise_locked_database_error(exc)
        logger.error("Error saving therapy plan %s: %s", plan.plan_id, exc, exc_info=True)
        conn.rollback()
        return False


async def get_current_therapy_plan(
    executor: TrioSQLiteExecutor,
    user_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> TherapyPlan | None:
    """Fetch the single current therapy plan revision for a user."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_current_therapy_plan, conn, user_id, iso_to_datetime
        )


def _sync_get_current_therapy_plan(
    conn, user_id: str, iso_to_datetime
) -> TherapyPlan | None:
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT {THERAPY_PLAN_COLUMNS}
        FROM therapy_plans
        WHERE user_id = ? AND superseded_by_plan_id IS NULL
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
