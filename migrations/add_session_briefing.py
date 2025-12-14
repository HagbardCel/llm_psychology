"""
Database migration to add session_briefing column to therapy_plans table.

Usage:
    python migrations/add_session_briefing.py [db_path]

If no db_path is provided, defaults to data/psychoanalyst.db
"""

import sqlite3
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_database(db_path: str) -> bool:
    """
    Add session_briefing column to therapy_plans table.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        bool: True if migration succeeded, False otherwise
    """
    try:
        logger.info(f"Starting migration for database: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if column already exists
        cursor.execute("PRAGMA table_info(therapy_plans)")
        columns = [row[1] for row in cursor.fetchall()]

        if "session_briefing" in columns:
            logger.info("session_briefing column already exists - migration not needed")
            conn.close()
            return True

        # Add column
        logger.info("Adding session_briefing column to therapy_plans table")
        cursor.execute("ALTER TABLE therapy_plans ADD COLUMN session_briefing TEXT")
        conn.commit()
        conn.close()

        logger.info("Successfully added session_briefing column")
        return True

    except sqlite3.Error as e:
        logger.error(f"SQLite error during migration: {e}")
        return False
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


def main():
    """Run the migration."""
    # Determine database path
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # Default to main database
        db_path = "data/psychoanalyst.db"

    # Verify database exists
    if not Path(db_path).exists():
        logger.warning(f"Database does not exist at {db_path}")
        logger.info("This is expected for new installations")
        logger.info("The column will be created when the database is initialized")
        return 0

    # Run migration
    success = migrate_database(db_path)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
