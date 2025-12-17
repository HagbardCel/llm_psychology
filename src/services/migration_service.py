import json
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
            (2, self._migration_002_add_briefing),
            (3, self._migration_003_add_auth_tables),
            (4, self._migration_004_add_performance_indexes),
            (5, self._migration_005_tiered_patient_information),
            (6, self._migration_006_unify_treatment_plans),
            (7, self._migration_007_add_session_enrichment_jobs),
            (8, self._migration_008_add_patient_profile_history),
        ]

    def _migration_001_initial_schema(self, conn: sqlite3.Connection):
        """Initial schema creation."""
        cursor = conn.cursor()

        # Create sessions table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                transcript TEXT NOT NULL,
                topics TEXT
            )
        """
        )

        # Create therapy_plans table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS therapy_plans (
                plan_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                plan_details TEXT NOT NULL,
                version INTEGER NOT NULL,
                selected_therapy_style TEXT
            )
        """
        )

        # Create user_profiles table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                birthdate TEXT,
                profession TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """
        )

    def _migration_002_add_briefing(self, conn: sqlite3.Connection):
        """Add session_briefing column to therapy_plans."""
        cursor = conn.cursor()

        # Check if column exists first (idempotency)
        cursor.execute("PRAGMA table_info(therapy_plans)")
        columns = {col[1] for col in cursor.fetchall()}

        if "session_briefing" not in columns:
            cursor.execute(
                """
                ALTER TABLE therapy_plans
                ADD COLUMN session_briefing TEXT
            """
            )

    def _migration_003_add_auth_tables(self, conn: sqlite3.Connection):
        """Add authentication tables for JWT-based auth."""
        cursor = conn.cursor()

        # Create user_credentials table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT,
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
            )
        """
        )

        # Create index on username for faster lookups
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_credentials_username
            ON user_credentials(username)
        """
        )

    def _migration_004_add_performance_indexes(self, conn: sqlite3.Connection):
        """Add performance indexes for frequently queried columns."""
        cursor = conn.cursor()

        # Index on user_profiles for status lookups
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profiles_status
            ON user_profiles(status)
        """
        )

        # Index on sessions for user_id and timestamp lookups
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user_timestamp
            ON sessions(user_id, timestamp DESC)
        """
        )

        # Index on sessions for session_id lookups (if not already primary key indexed)
        # Note: Primary key already creates an index, but adding explicit index for joins
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id
            ON sessions(user_id)
        """
        )

        # Index on therapy_plans for user_id and created_at lookups
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_created
            ON therapy_plans(user_id, created_at DESC)
        """
        )

        # Index on therapy_plans for user_id alone (for faster user plan lookups)
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_id
            ON therapy_plans(user_id)
        """
        )

        logger.info("Performance indexes created successfully")

    def _migration_005_tiered_patient_information(self, conn: sqlite3.Connection):
        """Add tiered patient information system tables and columns."""
        cursor = conn.cursor()

        # ========================================================================
        # TIER 1: Patient Profiles Table
        # ========================================================================
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS patient_profiles (
                user_id TEXT PRIMARY KEY,
                profile_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
            )
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_patient_profiles_updated
            ON patient_profiles(updated_at)
        """
        )

        # ========================================================================
        # TIER 2: Extend Sessions Table with Enrichment Fields
        # ========================================================================
        # Check which columns already exist
        cursor.execute("PRAGMA table_info(sessions)")
        existing_columns = {col[1] for col in cursor.fetchall()}

        # Add Tier 2 columns if they don't exist
        tier2_columns = [
            ("psychological_summary", "TEXT"),
            ("dominant_affects", "TEXT"),  # JSON array
            ("key_themes", "TEXT"),  # JSON array
            ("notable_interactions", "TEXT"),
            ("interpretations", "TEXT"),
            ("patient_reactions", "TEXT"),
            ("enriched", "INTEGER DEFAULT 0"),  # SQLite doesn't have BOOLEAN
        ]

        for column_name, column_type in tier2_columns:
            if column_name not in existing_columns:
                cursor.execute(
                    f"""
                    ALTER TABLE sessions
                    ADD COLUMN {column_name} {column_type}
                """
                )
                logger.info(f"Added column {column_name} to sessions table")

        # ========================================================================
        # TIER 3: Patient Analysis with Versioning
        # ========================================================================
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

        # Create indexes for Tier 3
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

        # ========================================================================
        # TIER 4: Treatment Plans
        # ========================================================================
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS treatment_plans (
                plan_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                plan_data TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'paused', 'completed')),
                created_at TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
            )
        """
        )

        # Create indexes for Tier 4
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_treatment_plans_user
            ON treatment_plans(user_id)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_treatment_plans_status
            ON treatment_plans(status)
        """
        )

        logger.info("Tiered patient information system tables created successfully")

    def _migration_006_unify_treatment_plans(self, conn: sqlite3.Connection):
        """Unify therapy/treatment plan storage into a single table."""
        cursor = conn.cursor()

        # Add Tier 4 columns to therapy_plans if missing
        cursor.execute("PRAGMA table_info(therapy_plans)")
        columns = {col[1] for col in cursor.fetchall()}

        def add_column(name: str, definition: str):
            if name not in columns:
                cursor.execute(f"ALTER TABLE therapy_plans ADD COLUMN {name} {definition}")
                columns.add(name)

        add_column("initial_goals", "TEXT")
        add_column("current_progress", "TEXT")
        add_column("planned_interventions", "TEXT")
        add_column("status", "TEXT DEFAULT 'active'")

        # Ensure defaults for existing rows
        cursor.execute(
            "UPDATE therapy_plans SET initial_goals = '[\"Stabilize presenting concerns\"]' WHERE initial_goals IS NULL OR initial_goals = ''"
        )
        cursor.execute(
            "UPDATE therapy_plans SET planned_interventions = '[\"Supportive listening\"]' WHERE planned_interventions IS NULL OR planned_interventions = ''"
        )
        cursor.execute(
            "UPDATE therapy_plans SET current_progress = 'Baseline established' WHERE current_progress IS NULL OR current_progress = ''"
        )
        cursor.execute(
            "UPDATE therapy_plans SET status = 'active' WHERE status IS NULL OR status = ''"
        )

        # Migrate any data from treatment_plans table if it exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='treatment_plans'"
        )
        if cursor.fetchone():
            cursor.execute(
                "SELECT plan_data, user_id FROM treatment_plans"
            )
            rows = cursor.fetchall()
            for plan_data, user_id in rows:
                try:
                    data = json.loads(plan_data)
                except json.JSONDecodeError:
                    continue

                initial_goals = json.dumps(data.get("initial_goals", []))
                planned_interventions = json.dumps(data.get("planned_interventions", []))
                current_progress = data.get("current_progress", "")
                status = data.get("status", "active")

                cursor.execute(
                    """
                    UPDATE therapy_plans
                    SET initial_goals = ?,
                        current_progress = ?,
                        planned_interventions = ?,
                        status = ?
                    WHERE user_id = ?
                    """,
                    (initial_goals, current_progress, planned_interventions, status, user_id),
                )

            cursor.execute("DROP TABLE IF EXISTS treatment_plans")

        logger.info("Therapy plan columns unified with Tier 4 data")

    def _migration_007_add_session_enrichment_jobs(self, conn: sqlite3.Connection):
        """Add session enrichment job queue for async Tier 2 enrichment."""
        cursor = conn.cursor()

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

        logger.info("Session enrichment job queue table created successfully")

    def _migration_008_add_patient_profile_history(self, conn: sqlite3.Connection):
        """Add audit trail for Tier 1 patient profile updates."""
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS patient_profile_history (
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

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_profile_history_user_created
            ON patient_profile_history(user_id, created_at DESC)
            """
        )

        logger.info("Patient profile history table created successfully")
