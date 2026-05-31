"""User profile repository helpers."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime

from psychoanalyst_app.models.domain import (
    UserProfile,
    UserProfileSummary,
    UserStatus,
)
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.db.sqlite_config import reraise_locked_database_error

logger = logging.getLogger(__name__)

PROFILE_COLUMNS = (
    "user_id, name, alias, date_of_birth, gender, cultural_background, "
    "primary_language, profession, status, plan_id, parents, siblings, "
    "family_atmosphere, "
    "significant_events, education, work_history, relationship_to_work, "
    "relationships, social_context, current_situation, preferred_school, "
    "boundary_notes, frame_notes, created_at, updated_at"
)
PROFILE_SUMMARY_COLUMNS = "user_id, name, status, primary_language, plan_id, updated_at"
PROFILE_UPDATE_ASSIGNMENTS = ", ".join(
    f"{column} = excluded.{column}"
    for column in PROFILE_COLUMNS.replace(",", "").split()
    if column != "user_id"
)


async def save_user_profile(
    executor: TrioSQLiteExecutor,
    profile: UserProfile,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    """Persist a user profile row."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_save_user_profile, conn, profile, datetime_to_iso
        )


def _sync_save_user_profile(
    conn: sqlite3.Connection,
    profile: UserProfile,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO user_profiles
            ({PROFILE_COLUMNS})
            VALUES ({', '.join(['?'] * 25)})
            ON CONFLICT(user_id) DO UPDATE SET
                {PROFILE_UPDATE_ASSIGNMENTS}
            """,
            _profile_values(profile, datetime_to_iso),
        )
        conn.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        reraise_locked_database_error(exc)
        logger.error("Error saving user profile: %s", exc, exc_info=True)
        return False


async def update_user_status(
    executor: TrioSQLiteExecutor,
    user_id: str,
    status: str,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    """Update workflow status for a user."""
    async with executor.connection() as conn:
        return await executor.run_sync(
            _sync_update_user_status, conn, user_id, status, datetime_to_iso
        )


def _sync_update_user_status(
    conn: sqlite3.Connection,
    user_id: str,
    status: str,
    datetime_to_iso: Callable[[datetime], str],
) -> bool:
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE user_profiles
            SET status = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (status, datetime_to_iso(datetime.now()), user_id),
        )
        conn.commit()
        return True
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error updating user status: %s", exc, exc_info=True)
        return False


async def update_user_profile(
    executor: TrioSQLiteExecutor,
    profile: UserProfile,
    datetime_to_iso: Callable[[datetime], str],
    iso_to_datetime: Callable[[str], datetime],
    change_summary: str | None = None,
    created_by_session: str | None = None,
) -> bool:
    """Update user profile and write history when previous data exists."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_update_user_profile,
            conn,
            profile,
            datetime_to_iso,
            iso_to_datetime,
            change_summary,
            created_by_session,
        )


def _sync_update_user_profile(
    conn: sqlite3.Connection,
    profile: UserProfile,
    datetime_to_iso: Callable[[datetime], str],
    iso_to_datetime: Callable[[str], datetime],
    change_summary: str | None,
    created_by_session: str | None,
) -> bool:
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            f"SELECT {PROFILE_COLUMNS} FROM user_profiles WHERE user_id = ?",
            (profile.user_id,),
        )
        row = cursor.fetchone()
        previous_profile = _profile_from_row(row, iso_to_datetime) if row else None

        cursor.execute(
            f"""
            INSERT INTO user_profiles
            ({PROFILE_COLUMNS})
            VALUES ({', '.join(['?'] * 25)})
            ON CONFLICT(user_id) DO UPDATE SET
                {PROFILE_UPDATE_ASSIGNMENTS}
            """,
            _profile_values(profile, datetime_to_iso),
        )

        if previous_profile:
            cursor.execute(
                """
                INSERT INTO user_profile_history
                (history_id, user_id, previous_profile_data, new_profile_data,
                 change_summary, created_at, created_by_session)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"uph_{uuid.uuid4().hex[:12]}",
                    profile.user_id,
                    previous_profile.model_dump_json(),
                    profile.model_dump_json(),
                    (change_summary or "")[:1000] or None,
                    datetime.now().isoformat(),
                    created_by_session,
                ),
            )

        conn.commit()
        return True
    except Exception as exc:  # pragma: no cover
        reraise_locked_database_error(exc)
        logger.error("Error updating user profile: %s", exc, exc_info=True)
        conn.rollback()
        return False


async def get_user_profile(
    executor: TrioSQLiteExecutor,
    user_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> UserProfile | None:
    """Fetch a user profile."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(
            _sync_get_user_profile, conn, user_id, iso_to_datetime
        )


def _sync_get_user_profile(
    conn: sqlite3.Connection,
    user_id: str,
    iso_to_datetime: Callable[[str], datetime],
) -> UserProfile | None:
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {PROFILE_COLUMNS} FROM user_profiles WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        conn.commit()
        return _profile_from_row(row, iso_to_datetime)
    except Exception as exc:  # pragma: no cover
        logger.error("Error retrieving user profile: %s", exc, exc_info=True)
        return None


def _profile_from_row(
    row: sqlite3.Row,
    iso_to_datetime: Callable[[str], datetime],
) -> UserProfile:
    return UserProfile(
        user_id=row["user_id"],
        name=row["name"],
        alias=row["alias"],
        date_of_birth=(
            iso_to_datetime(row["date_of_birth"]) if row["date_of_birth"] else None
        ),
        gender=row["gender"],
        cultural_background=row["cultural_background"],
        primary_language=row["primary_language"] or "English",
        profession=row["profession"],
        status=UserStatus(row["status"]) if row["status"] else UserStatus.PROFILE_ONLY,
        plan_id=row["plan_id"],
        parents=row["parents"],
        siblings=row["siblings"],
        family_atmosphere=row["family_atmosphere"],
        significant_events=row["significant_events"],
        education=row["education"],
        work_history=row["work_history"],
        relationship_to_work=row["relationship_to_work"],
        relationships=row["relationships"],
        social_context=row["social_context"],
        current_situation=row["current_situation"],
        preferred_school=row["preferred_school"],
        boundary_notes=row["boundary_notes"],
        frame_notes=row["frame_notes"],
        created_at=iso_to_datetime(row["created_at"]),
        updated_at=iso_to_datetime(row["updated_at"]),
    )


def _profile_values(
    profile: UserProfile,
    datetime_to_iso: Callable[[datetime], str],
) -> tuple:
    return (
        profile.user_id,
        profile.name,
        profile.alias,
        datetime_to_iso(profile.date_of_birth) if profile.date_of_birth else None,
        profile.gender,
        profile.cultural_background,
        profile.primary_language or "English",
        profile.profession,
        profile.status.value if hasattr(profile.status, "value") else profile.status,
        profile.plan_id,
        profile.parents,
        profile.siblings,
        profile.family_atmosphere,
        profile.significant_events,
        profile.education,
        profile.work_history,
        profile.relationship_to_work,
        profile.relationships,
        profile.social_context,
        profile.current_situation,
        profile.preferred_school,
        profile.boundary_notes,
        profile.frame_notes,
        datetime_to_iso(profile.created_at),
        datetime_to_iso(profile.updated_at),
    )


async def list_user_profiles(
    executor: TrioSQLiteExecutor,
    iso_to_datetime: Callable[[str], datetime],
) -> list[UserProfileSummary]:
    """Fetch profile summaries ordered by most recent update."""
    async with executor.connection(row_factory=sqlite3.Row) as conn:
        return await executor.run_sync(_sync_list_user_profiles, conn, iso_to_datetime)


def _sync_list_user_profiles(
    conn: sqlite3.Connection,
    iso_to_datetime: Callable[[str], datetime],
) -> list[UserProfileSummary]:
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT {PROFILE_SUMMARY_COLUMNS}
            FROM user_profiles
            ORDER BY updated_at DESC
            """
        )
        rows = cursor.fetchall() or []
        conn.commit()
        return [_profile_summary_from_row(row, iso_to_datetime) for row in rows]
    except Exception as exc:  # pragma: no cover
        logger.error("Error listing user profiles: %s", exc, exc_info=True)
        return []


def _profile_summary_from_row(
    row: sqlite3.Row,
    iso_to_datetime: Callable[[str], datetime],
) -> UserProfileSummary:
    return UserProfileSummary(
        user_id=row["user_id"],
        name=row["name"],
        status=UserStatus(row["status"]) if row["status"] else UserStatus.PROFILE_ONLY,
        primary_language=row["primary_language"] or "English",
        plan_id=row["plan_id"],
        updated_at=iso_to_datetime(row["updated_at"]),
    )
