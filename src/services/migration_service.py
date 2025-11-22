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
