import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime

import trio

logger = logging.getLogger(__name__)


class MigrationService:
    """
    Service for handling database migrations.
    """

    def __init__(self, db_path: str):
        """
        Initialize the migration service.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._is_uri = db_path.startswith("file:")

    def _get_connection(self) -> sqlite3.Connection:
        """Create a database connection."""
        if self._is_uri:
            conn = sqlite3.connect(
                self.db_path, timeout=30.0, uri=True, check_same_thread=False
            )
        else:
            conn = sqlite3.connect(self.db_path, timeout=30.0)

        # Ensure FK constraints behave as expected in SQLite.
        conn.execute("PRAGMA foreign_keys = ON")
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

        finally:
            conn.close()

    def _get_migrations(self) -> list[tuple[int, Callable[[sqlite3.Connection], None]]]:
        """
        Get list of migrations to apply.
        Returns a list of (version, function) tuples.
        """
        return [
            (1, self._migration_001_initial_schema),
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
                status TEXT DEFAULT 'active',
                version INTEGER NOT NULL,
                selected_therapy_style TEXT,
                session_briefing TEXT
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
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                FOREIGN KEY (created_by_session) REFERENCES sessions(session_id) ON DELETE SET NULL,
                FOREIGN KEY (superseded_by) REFERENCES patient_analysis(analysis_id) ON DELETE SET NULL,
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
                status TEXT NOT NULL CHECK(status IN ('queued', 'processing', 'complete', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
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
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                FOREIGN KEY (created_by_session) REFERENCES sessions(session_id) ON DELETE SET NULL
            )
            """
        )

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
