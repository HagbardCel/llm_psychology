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
            return sqlite3.connect(
                self.db_path, timeout=30.0, uri=True, check_same_thread=False
            )
        return sqlite3.connect(self.db_path, timeout=30.0)

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
