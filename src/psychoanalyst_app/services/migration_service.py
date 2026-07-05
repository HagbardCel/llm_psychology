"""SQLite schema initialization for the therapist app.

This module previously chained numbered migrations 001-004; clean databases
always ended up with the same shape regardless. We now declare a single
"current schema" and apply it idempotently. Legacy databases that pre-date
the immutable therapy plan revisions are rejected so users reset them via
``make reset-foundation-db``.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

import trio

from psychoanalyst_app.services.db.sqlite_config import configure_connection

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 3

_FOUNDATION_PLAN_COLUMNS = {
    "supersedes_plan_id",
    "superseded_by_plan_id",
    "revision_recommendations",
    "focus",
    "themes",
    "timeline",
}

_SESSION_ADDITIVE_COLUMNS = {
    "intake_record": "TEXT",
    "intake_record_updated_at": "TEXT",
    "intake_note_tracking_diagnostics": "TEXT",
}

_PLAN_UPDATE_JOBS_ADDITIVE_COLUMNS = {
    "briefing_validation_metadata": "TEXT",
}

_TABLE_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        alias TEXT,
        date_of_birth TEXT,
        gender TEXT,
        cultural_background TEXT,
        primary_language TEXT NOT NULL DEFAULT 'English',
        profession TEXT,
        status TEXT NOT NULL,
        plan_id TEXT,
        parents TEXT,
        siblings TEXT,
        family_atmosphere TEXT,
        significant_events TEXT,
        education TEXT,
        work_history TEXT,
        relationship_to_work TEXT,
        relationships TEXT,
        social_context TEXT,
        current_situation TEXT,
        preferred_school TEXT,
        boundary_notes TEXT,
        frame_notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        session_type TEXT NOT NULL DEFAULT 'intake'
            CHECK(session_type IN ('intake', 'therapy')),
        plan_id TEXT,
        timestamp TEXT NOT NULL,
        transcript TEXT NOT NULL,
        topics TEXT,
        session_summary TEXT,
        session_briefing TEXT,
        intake_record TEXT,
        intake_record_updated_at TEXT,
        intake_note_tracking_diagnostics TEXT,
        psychological_summary TEXT,
        dominant_affects TEXT,
        key_themes TEXT,
        notable_interactions TEXT,
        interpretations TEXT,
        patient_reactions TEXT,
        enriched INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS therapy_plans (
        plan_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        focus TEXT NOT NULL,
        themes TEXT NOT NULL DEFAULT '[]',
        timeline TEXT,
        initial_goals TEXT,
        current_progress TEXT,
        planned_interventions TEXT,
        revision_recommendations TEXT NOT NULL DEFAULT '[]',
        status TEXT DEFAULT 'active'
            CHECK(status IN ('active', 'paused', 'completed', 'superseded')),
        version INTEGER NOT NULL,
        selected_therapy_style TEXT,
        session_briefing TEXT,
        supersedes_plan_id TEXT,
        superseded_by_plan_id TEXT,
        FOREIGN KEY (supersedes_plan_id)
            REFERENCES therapy_plans(plan_id) ON DELETE SET NULL,
        FOREIGN KEY (superseded_by_plan_id)
            REFERENCES therapy_plans(plan_id) ON DELETE SET NULL,
        UNIQUE(user_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS patient_analysis (
        analysis_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        analysis_data TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by_session TEXT,
        change_summary TEXT,
        superseded_by TEXT,
        FOREIGN KEY (user_id)
            REFERENCES user_profiles(user_id) ON DELETE CASCADE,
        FOREIGN KEY (created_by_session)
            REFERENCES sessions(session_id) ON DELETE SET NULL,
        FOREIGN KEY (superseded_by)
            REFERENCES patient_analysis(analysis_id) ON DELETE SET NULL,
        UNIQUE(user_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_enrichment_jobs (
        session_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(
            status IN ('queued', 'processing', 'complete', 'failed')
        ),
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (session_id)
            REFERENCES sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (user_id)
            REFERENCES user_profiles(user_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS plan_update_jobs (
        session_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(
            status IN ('queued', 'processing', 'complete', 'failed')
        ),
        attempts INTEGER NOT NULL DEFAULT 0,
        current_step TEXT,
        last_error TEXT,
        error_type TEXT,
        error_code TEXT,
        error_stage TEXT,
        artifact_path TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (session_id)
            REFERENCES sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (user_id)
            REFERENCES user_profiles(user_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_profile_history (
        history_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        previous_profile_data TEXT NOT NULL,
        new_profile_data TEXT NOT NULL,
        change_summary TEXT,
        created_at TEXT NOT NULL,
        created_by_session TEXT,
        FOREIGN KEY (user_id)
            REFERENCES user_profiles(user_id) ON DELETE CASCADE,
        FOREIGN KEY (created_by_session)
            REFERENCES sessions(session_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assessment_recommendations (
        user_id TEXT NOT NULL,
        intake_session_block_id TEXT NOT NULL,
        recommendations TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, intake_session_block_id),
        FOREIGN KEY (user_id)
            REFERENCES user_profiles(user_id) ON DELETE CASCADE
    )
    """,
]

_INDEX_DDL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_user_profiles_status ON user_profiles(status)",
    "CREATE INDEX IF NOT EXISTS idx_user_profiles_plan_id ON user_profiles(plan_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)",
    (
        "CREATE INDEX IF NOT EXISTS idx_sessions_user_timestamp "
        "ON sessions(user_id, timestamp DESC)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_sessions_plan_id ON sessions(plan_id)",
    "CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_id ON therapy_plans(user_id)",
    (
        "CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_created "
        "ON therapy_plans(user_id, created_at DESC)"
    ),
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_therapy_plans_current_user
    ON therapy_plans(user_id)
    WHERE superseded_by_plan_id IS NULL
    """,
    (
        "CREATE INDEX IF NOT EXISTS idx_analysis_user_version "
        "ON patient_analysis(user_id, version DESC)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_analysis_created ON patient_analysis(created_at)",
    (
        "CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_user_status "
        "ON session_enrichment_jobs(user_id, status, updated_at DESC)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status_updated "
        "ON session_enrichment_jobs(status, updated_at ASC)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_plan_update_jobs_user_status "
        "ON plan_update_jobs(user_id, status, updated_at DESC)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_plan_update_jobs_status_updated "
        "ON plan_update_jobs(status, updated_at ASC)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_user_profile_history_user_created "
        "ON user_profile_history(user_id, created_at DESC)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_assessment_recommendations_user_created "
        "ON assessment_recommendations(user_id, created_at DESC)"
    ),
]


class MigrationService:
    """Initialize and validate the SQLite schema for clean and legacy DBs."""

    def __init__(self, db_path: str, *, busy_timeout_seconds: float = 30.0):
        self.db_path = db_path
        self.busy_timeout_seconds = busy_timeout_seconds
        self.busy_timeout_ms = int(busy_timeout_seconds * 1000)
        self._is_uri = db_path.startswith("file:")

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_uri:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.busy_timeout_seconds,
                uri=True,
                check_same_thread=False,
            )
        else:
            conn = sqlite3.connect(self.db_path, timeout=self.busy_timeout_seconds)

        configure_connection(
            conn,
            db_path=self.db_path,
            busy_timeout_ms=self.busy_timeout_ms,
        )
        return conn

    async def run_migrations(self) -> None:
        """Apply the current schema (idempotent)."""
        await trio.to_thread.run_sync(self._sync_run_migrations)

    def _sync_run_migrations(self) -> None:
        conn = self._get_connection()
        try:
            self._ensure_schema_version_table(conn)
            self._validate_foundation_schema(conn)
            self._create_current_schema(conn)
            self._ensure_sessions_additive_columns(conn)
            self._ensure_plan_update_jobs_additive_columns(conn)
            self._record_schema_version(conn)
        finally:
            conn.close()

    @staticmethod
    def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    @staticmethod
    def _validate_foundation_schema(conn: sqlite3.Connection) -> None:
        """Reject legacy DBs that lack immutable therapy plan revisions."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='therapy_plans'"
        )
        if cursor.fetchone() is None:
            return

        cursor = conn.execute("PRAGMA table_info(therapy_plans)")
        columns = {row[1] for row in cursor.fetchall()}
        if not _FOUNDATION_PLAN_COLUMNS.issubset(columns):
            raise RuntimeError(
                "Database schema is incompatible with immutable therapy plan "
                "revisions. Run `make reset-foundation-db` before startup."
            )

    @staticmethod
    def _create_current_schema(conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        for statement in _TABLE_DDL:
            cursor.execute(statement)
        for statement in _INDEX_DDL:
            cursor.execute(statement)
        conn.commit()

    @staticmethod
    def _ensure_sessions_additive_columns(conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(sessions)")
        existing = {row[1] for row in cursor.fetchall()}
        for column, ddl_type in _SESSION_ADDITIVE_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {ddl_type}")
        conn.commit()

    @staticmethod
    def _ensure_plan_update_jobs_additive_columns(conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(plan_update_jobs)")
        existing = {row[1] for row in cursor.fetchall()}
        for column, ddl_type in _PLAN_UPDATE_JOBS_ADDITIVE_COLUMNS.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE plan_update_jobs ADD COLUMN {column} {ddl_type}"
                )
        conn.commit()

    @staticmethod
    def _record_schema_version(conn: sqlite3.Connection) -> None:
        cursor = conn.execute("SELECT MAX(version) FROM schema_migrations")
        row = cursor.fetchone()
        current_version = row[0] if row and row[0] is not None else 0
        if current_version >= CURRENT_SCHEMA_VERSION:
            return
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (CURRENT_SCHEMA_VERSION, datetime.now().isoformat()),
        )
        conn.commit()
        logger.info("Recorded schema version %s", CURRENT_SCHEMA_VERSION)
