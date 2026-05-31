import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime

import trio

from psychoanalyst_app.services.db.sqlite_config import configure_connection

logger = logging.getLogger(__name__)


class MigrationService:
    """
    Service for handling database migrations.
    """

    def __init__(self, db_path: str, *, busy_timeout_seconds: float = 30.0):
        """
        Initialize the migration service.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self.busy_timeout_seconds = busy_timeout_seconds
        self.busy_timeout_ms = int(busy_timeout_seconds * 1000)
        self._is_uri = db_path.startswith("file:")

    def _get_connection(self) -> sqlite3.Connection:
        """Create a database connection."""
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

    async def run_migrations(self):
        """Run all pending migrations."""
        await trio.to_thread.run_sync(self._sync_run_migrations)

    def _sync_run_migrations(self):
        """Synchronous migration execution."""
        conn = self._get_connection()
        try:
            # Create migrations table if it doesn't exist
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """
            )
            conn.commit()

            # Get current version
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(version) FROM schema_migrations")
            result = cursor.fetchone()
            current_version = result[0] if result and result[0] is not None else 0

            logger.info(f"Current database schema version: {current_version}")

            # Define migrations
            migrations = self._get_migrations()

            # Apply pending migrations
            for version, migration_func in migrations:
                if version > current_version:
                    logger.info(f"Applying migration version {version}...")
                    try:
                        migration_func(conn)
                        cursor.execute(
                            """
                            INSERT INTO schema_migrations
                            (version, applied_at) VALUES (?, ?)
                            """,
                            (version, datetime.now().isoformat()),
                        )
                        conn.commit()
                        logger.info(f"Migration {version} applied successfully.")
                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Migration {version} failed: {e}")
                        raise

            self._validate_foundation_schema(conn)
            self._ensure_current_schema(conn)

        finally:
            conn.close()

    def _ensure_current_schema(self, conn: sqlite3.Connection) -> None:
        """Ensure indexes and additive non-foundation columns are present."""
        cursor = conn.cursor()

        self._ensure_columns(
            cursor,
            "user_profiles",
            {
                "alias": "TEXT",
                "data_of_birth": "TEXT",
                "gender": "TEXT",
                "cultural_background": "TEXT",
                "primary_language": "TEXT NOT NULL DEFAULT 'English'",
                "plan_id": "TEXT",
                "parents": "TEXT",
                "siblings": "TEXT",
                "family_atmosphere": "TEXT",
                "significant_events": "TEXT",
                "education": "TEXT",
                "work_history": "TEXT",
                "relationship_to_work": "TEXT",
                "relationships": "TEXT",
                "social_context": "TEXT",
                "current_situation": "TEXT",
                "preferred_school": "TEXT",
                "boundary_notes": "TEXT",
                "frame_notes": "TEXT",
            },
        )
        self._ensure_columns(
            cursor,
            "sessions",
            {
                "plan_id": "TEXT",
                "topics": "TEXT",
                "session_summary": "TEXT",
                "session_briefing": "TEXT",
                "psychological_summary": "TEXT",
                "dominant_affects": "TEXT",
                "key_themes": "TEXT",
                "notable_interactions": "TEXT",
                "interpretations": "TEXT",
                "patient_reactions": "TEXT",
                "enriched": "INTEGER DEFAULT 0",
            },
        )
        self._ensure_columns(
            cursor,
            "therapy_plans",
            {
                "initial_goals": "TEXT",
                "current_progress": "TEXT",
                "planned_interventions": "TEXT",
                "status": "TEXT DEFAULT 'active'",
                "version": "INTEGER NOT NULL DEFAULT 1",
                "selected_therapy_style": "TEXT",
                "session_briefing": "TEXT",
            },
        )

        self._create_assessment_recommendations_table(cursor)
        self._ensure_current_indexes(cursor)
        conn.commit()

    def _validate_foundation_schema(self, conn: sqlite3.Connection) -> None:
        """Fail closed for databases created before immutable plan revisions."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(therapy_plans)")
        columns = {row[1] for row in cursor.fetchall()}
        required = {
            "supersedes_plan_id",
            "superseded_by_plan_id",
            "revision_recommendations",
        }
        if not required.issubset(columns):
            raise RuntimeError(
                "Database schema is incompatible with immutable therapy plan "
                "revisions. Run `make reset-foundation-db` before startup."
            )

    def _ensure_columns(
        self,
        cursor: sqlite3.Cursor,
        table_name: str,
        column_definitions: dict[str, str],
    ) -> None:
        """Add missing columns to an existing table."""
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        for column_name, column_definition in column_definitions.items():
            if column_name not in existing_columns:
                logger.info("Adding missing column %s.%s", table_name, column_name)
                cursor.execute(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {column_name} {column_definition}"
                )

    def _ensure_current_indexes(self, cursor: sqlite3.Cursor) -> None:
        """Create indexes expected by the current repositories."""
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profiles_status
            ON user_profiles(status)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user_timestamp
            ON sessions(user_id, timestamp DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id
            ON sessions(user_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_plan_id
            ON sessions(plan_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_created
            ON therapy_plans(user_id, created_at DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_id
            ON therapy_plans(user_id)
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_therapy_plans_current_user
            ON therapy_plans(user_id)
            WHERE superseded_by_plan_id IS NULL
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profiles_plan_id
            ON user_profiles(plan_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_user_version
            ON patient_analysis(user_id, version DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_created
            ON patient_analysis(created_at)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_user_status
            ON session_enrichment_jobs(user_id, status, updated_at DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status_updated
            ON session_enrichment_jobs(status, updated_at ASC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profile_history_user_created
            ON user_profile_history(user_id, created_at DESC)
            """
        )

    def _get_migrations(self) -> list[tuple[int, Callable[[sqlite3.Connection], None]]]:
        """
        Get list of migrations to apply.
        Returns a list of (version, function) tuples.
        """
        return [
            (1, self._migration_001_initial_schema),
            (2, self._migration_002_add_llm_cache),
            (3, self._migration_003_add_assessment_recommendations),
            (4, self._migration_004_add_session_type),
        ]

    def _migration_001_initial_schema(self, conn: sqlite3.Connection):
        """Create the full current schema for clean database resets."""
        cursor = conn.cursor()

        # Core user profiles.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                alias TEXT,
                data_of_birth TEXT,
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
        """
        )

        # Sessions (with Tier 2 enrichment fields).
        cursor.execute(
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
                psychological_summary TEXT,
                dominant_affects TEXT,
                key_themes TEXT,
                notable_interactions TEXT,
                interpretations TEXT,
                patient_reactions TEXT,
                enriched INTEGER DEFAULT 0
            )
        """
        )

        # Therapy plans (full unified schema).
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS therapy_plans (
                plan_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                plan_details TEXT NOT NULL,
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
        """
        )

        # Tier 3 analysis with versioning.
        cursor.execute(
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
        """
        )

        # Session enrichment jobs for async Tier 2 processing.
        cursor.execute(
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
            """
        )

        # User profile history for audit trail.
        cursor.execute(
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
            """
        )

        # Assessment recommendations generated after intake.
        self._create_assessment_recommendations_table(cursor)

        # Indexes.
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profiles_status
            ON user_profiles(status)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user_timestamp
            ON sessions(user_id, timestamp DESC)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id
            ON sessions(user_id)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_plan_id
            ON sessions(plan_id)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_created
            ON therapy_plans(user_id, created_at DESC)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_id
            ON therapy_plans(user_id)
        """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_therapy_plans_current_user
            ON therapy_plans(user_id)
            WHERE superseded_by_plan_id IS NULL
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profiles_plan_id
            ON user_profiles(plan_id)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_user_version
            ON patient_analysis(user_id, version DESC)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_created
            ON patient_analysis(created_at)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_user_status
            ON session_enrichment_jobs(user_id, status, updated_at DESC)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status_updated
            ON session_enrichment_jobs(status, updated_at ASC)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profile_history_user_created
            ON user_profile_history(user_id, created_at DESC)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profiles_status
            ON user_profiles(status)
            """
        )
        cursor.execute("PRAGMA foreign_keys=ON")

        logger.info("Removed session_mode from user_profiles")

    def _migration_004_add_session_type(self, conn: sqlite3.Connection):
        """Persist whether a conversation block is intake or therapy."""
        self._ensure_columns(
            conn.cursor(),
            "sessions",
            {"session_type": "TEXT NOT NULL DEFAULT 'intake'"},
        )

    def _migration_002_add_llm_cache(self, conn: sqlite3.Connection):
        """Add LLM response cache table and maintenance indexes."""
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                call_type TEXT NOT NULL,
                model_name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                context_json TEXT NOT NULL,
                schema_hash TEXT,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                user_id TEXT,
                session_block_id TEXT,
                source TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_llm_cache_created_at
            ON llm_cache(created_at DESC)
            """
        )

    def _migration_003_add_assessment_recommendations(
        self, conn: sqlite3.Connection
    ) -> None:
        """Persist assessment recommendations for reconnect/restart recovery."""
        cursor = conn.cursor()
        self._create_assessment_recommendations_table(cursor)

    def _create_assessment_recommendations_table(
        self, cursor: sqlite3.Cursor
    ) -> None:
        """Create assessment recommendation table and lookup indexes."""
        cursor.execute(
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
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assessment_recommendations_user_created
            ON assessment_recommendations(user_id, created_at DESC)
            """
        )
