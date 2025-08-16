"""
Database migration service for schema evolution.

This module provides a robust migration system that can safely apply
database schema changes, track migration history, and rollback changes
when necessary.
"""

import logging
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from exceptions import DatabaseError

logger = logging.getLogger(__name__)


class MigrationError(DatabaseError):
    """Raised when migration operations fail."""
    pass


class Migration:
    """Represents a single database migration."""
    
    def __init__(self, version: int, name: str, file_path: Path):
        """
        Initialize a migration.
        
        Args:
            version: Migration version number
            name: Human-readable migration name
            file_path: Path to the SQL migration file
        """
        self.version = version
        self.name = name
        self.file_path = file_path
        self.content = self._load_content()
    
    def _load_content(self) -> str:
        """Load migration SQL content from file."""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise MigrationError(f"Failed to load migration {self.version}: {e}")
    
    def __str__(self) -> str:
        return f"Migration {self.version}: {self.name}"
    
    def __repr__(self) -> str:
        return f"Migration(version={self.version}, name='{self.name}', file='{self.file_path.name}')"


class MigrationService:
    """
    Service for managing database migrations.
    
    Features:
    - Automatic migration discovery
    - Migration dependency tracking
    - Safe rollback capabilities
    - Migration history logging
    - Transaction-based application
    """
    
    def __init__(self, db_service, migrations_dir: Optional[str] = None):
        """
        Initialize the migration service.
        
        Args:
            db_service: DatabaseService instance for database operations
            migrations_dir: Directory containing migration files (defaults to migrations/)
        """
        self.db_service = db_service
        self.migrations_dir = Path(migrations_dir or "migrations")
        
        logger.info(f"MigrationService initialized with directory: {self.migrations_dir}")
        
        # Ensure migrations directory exists
        self.migrations_dir.mkdir(exist_ok=True)
    
    def _ensure_migration_table(self, conn: sqlite3.Connection) -> None:
        """
        Create the schema_migrations table if it doesn't exist.
        
        Args:
            conn: Database connection
        """
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                execution_time_ms INTEGER,
                checksum TEXT
            )
        """)
        conn.commit()
        logger.debug("Migration tracking table ensured")
    
    def _get_applied_migrations(self, conn: sqlite3.Connection) -> Dict[int, Dict]:
        """
        Get list of applied migrations from database.
        
        Args:
            conn: Database connection
            
        Returns:
            Dictionary mapping version numbers to migration info
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT version, name, applied_at, execution_time_ms, checksum
            FROM schema_migrations 
            ORDER BY version
        """)
        
        applied = {}
        for row in cursor.fetchall():
            applied[row[0]] = {
                'version': row[0],
                'name': row[1],
                'applied_at': row[2],
                'execution_time_ms': row[3],
                'checksum': row[4]
            }
        
        logger.debug(f"Found {len(applied)} applied migrations")
        return applied
    
    def _discover_migrations(self) -> List[Migration]:
        """
        Discover migration files in the migrations directory.
        
        Returns:
            List of Migration objects sorted by version
        """
        migrations = []
        
        for migration_file in self.migrations_dir.glob("*.sql"):
            try:
                # Parse version from filename (e.g., "001_initial_schema.sql")
                filename_parts = migration_file.stem.split('_', 1)
                if len(filename_parts) < 2:
                    logger.warning(f"Skipping migration file with invalid name: {migration_file.name}")
                    continue
                
                version = int(filename_parts[0])
                name = filename_parts[1].replace('_', ' ').title()
                
                migration = Migration(version, name, migration_file)
                migrations.append(migration)
                
            except ValueError as e:
                logger.warning(f"Skipping migration file {migration_file.name}: {e}")
                continue
        
        # Sort by version number
        migrations.sort(key=lambda m: m.version)
        
        logger.info(f"Discovered {len(migrations)} migration files")
        return migrations
    
    def _calculate_checksum(self, content: str) -> str:
        """
        Calculate checksum for migration content.
        
        Args:
            content: Migration SQL content
            
        Returns:
            Hexadecimal checksum string
        """
        import hashlib
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _apply_migration(self, conn: sqlite3.Connection, migration: Migration) -> None:
        """
        Apply a single migration to the database.
        
        Args:
            conn: Database connection
            migration: Migration to apply
            
        Raises:
            MigrationError: If migration application fails
        """
        logger.info(f"Applying {migration}")
        
        start_time = datetime.now()
        checksum = self._calculate_checksum(migration.content)
        
        try:
            # Execute migration in a transaction
            cursor = conn.cursor()
            
            # Split content by semicolons and execute each statement
            statements = [stmt.strip() for stmt in migration.content.split(';') if stmt.strip()]
            
            for statement in statements:
                if statement:
                    logger.debug(f"Executing: {statement[:100]}...")
                    cursor.execute(statement)
            
            # Record migration as applied
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            cursor.execute("""
                INSERT INTO schema_migrations (version, name, applied_at, execution_time_ms, checksum)
                VALUES (?, ?, ?, ?, ?)
            """, (migration.version, migration.name, datetime.now().isoformat(), 
                  execution_time, checksum))
            
            conn.commit()
            
            logger.info(f"Successfully applied {migration} in {execution_time}ms")
            
        except Exception as e:
            conn.rollback()
            error_msg = f"Failed to apply {migration}: {e}"
            logger.error(error_msg)
            raise MigrationError(error_msg)
    
    def run_migrations(self) -> List[Migration]:
        """
        Run all pending migrations.
        
        Returns:
            List of migrations that were applied
            
        Raises:
            MigrationError: If any migration fails
        """
        logger.info("Starting migration run")
        
        applied_migrations = []
        
        try:
            with self.db_service.get_connection() as conn:
                # Ensure migration tracking table exists
                self._ensure_migration_table(conn)
                
                # Get currently applied migrations
                applied = self._get_applied_migrations(conn)
                
                # Discover available migrations
                available_migrations = self._discover_migrations()
                
                # Find pending migrations
                pending_migrations = [
                    migration for migration in available_migrations
                    if migration.version not in applied
                ]
                
                if not pending_migrations:
                    logger.info("No pending migrations found")
                    return []
                
                logger.info(f"Found {len(pending_migrations)} pending migrations")
                
                # Apply each pending migration
                for migration in pending_migrations:
                    self._apply_migration(conn, migration)
                    applied_migrations.append(migration)
                
                logger.info(f"Successfully applied {len(applied_migrations)} migrations")
                
        except Exception as e:
            logger.error(f"Migration run failed: {e}")
            raise MigrationError(f"Migration run failed: {e}")
        
        return applied_migrations
    
    def get_migration_status(self) -> Dict:
        """
        Get current migration status.
        
        Returns:
            Dictionary with migration status information
        """
        try:
            with self.db_service.get_connection() as conn:
                self._ensure_migration_table(conn)
                
                applied = self._get_applied_migrations(conn)
                available = self._discover_migrations()
                
                pending = [m for m in available if m.version not in applied]
                
                return {
                    'total_migrations': len(available),
                    'applied_count': len(applied),
                    'pending_count': len(pending),
                    'applied_migrations': list(applied.values()),
                    'pending_migrations': [
                        {'version': m.version, 'name': m.name, 'file': m.file_path.name}
                        for m in pending
                    ],
                    'last_migration': max(applied.values(), key=lambda x: x['version']) if applied else None
                }
                
        except Exception as e:
            logger.error(f"Failed to get migration status: {e}")
            raise MigrationError(f"Failed to get migration status: {e}")
    
    def validate_migrations(self) -> List[str]:
        """
        Validate migration files and check for issues.
        
        Returns:
            List of validation warning/error messages
        """
        issues = []
        
        try:
            available_migrations = self._discover_migrations()
            
            # Check for version gaps
            versions = [m.version for m in available_migrations]
            if versions:
                expected_versions = list(range(1, max(versions) + 1))
                missing_versions = set(expected_versions) - set(versions)
                if missing_versions:
                    issues.append(f"Missing migration versions: {sorted(missing_versions)}")
            
            # Check for duplicate versions
            version_counts = {}
            for migration in available_migrations:
                version_counts[migration.version] = version_counts.get(migration.version, 0) + 1
            
            duplicates = [v for v, count in version_counts.items() if count > 1]
            if duplicates:
                issues.append(f"Duplicate migration versions: {duplicates}")
            
            # Validate migration content
            for migration in available_migrations:
                if not migration.content.strip():
                    issues.append(f"Migration {migration.version} is empty")
                
                # Check for dangerous operations (optional warnings)
                dangerous_keywords = ['DROP TABLE', 'DELETE FROM', 'TRUNCATE']
                for keyword in dangerous_keywords:
                    if keyword in migration.content.upper():
                        issues.append(f"Migration {migration.version} contains potentially dangerous operation: {keyword}")
        
        except Exception as e:
            issues.append(f"Migration validation failed: {e}")
        
        return issues
    
    def create_migration_template(self, name: str) -> Path:
        """
        Create a new migration file template.
        
        Args:
            name: Migration name (will be formatted)
            
        Returns:
            Path to the created migration file
        """
        try:
            # Get next version number
            available_migrations = self._discover_migrations()
            next_version = max([m.version for m in available_migrations], default=0) + 1
            
            # Format filename
            formatted_name = name.lower().replace(' ', '_')
            filename = f"{next_version:03d}_{formatted_name}.sql"
            file_path = self.migrations_dir / filename
            
            # Create template content
            template = f"""-- Migration {next_version:03d}: {name.title()}
-- Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Purpose: [Describe what this migration does]

-- Add your migration SQL here
-- Example:
-- CREATE TABLE IF NOT EXISTS new_table (
--     id INTEGER PRIMARY KEY,
--     name TEXT NOT NULL
-- );

-- CREATE INDEX IF NOT EXISTS idx_new_table_name ON new_table(name);

-- Log successful completion
SELECT 'Migration {next_version:03d} completed successfully' as result;
"""
            
            # Write template to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(template)
            
            logger.info(f"Created migration template: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Failed to create migration template: {e}")
            raise MigrationError(f"Failed to create migration template: {e}")
    
    def __str__(self) -> str:
        """String representation of migration service."""
        return f"MigrationService(migrations_dir={self.migrations_dir})"
    
    def __repr__(self) -> str:
        """Detailed representation of migration service."""
        return f"MigrationService(migrations_dir='{self.migrations_dir}', db_service={type(self.db_service).__name__})"