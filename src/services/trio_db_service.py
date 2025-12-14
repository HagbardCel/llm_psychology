"""
Pure Trio database service using synchronous sqlite3.

This service uses Python's built-in synchronous sqlite3 module with
trio.to_thread.run_sync to execute database operations without blocking
the Trio event loop. This is the recommended approach for Trio applications
that need database access.
"""

import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

import trio

from models.auth_models import UserCredentials
from models.data_models import (
    Message,
    Session,
    TherapyPlan,
    Topic,
    UserProfile,
    UserStatus,
)
from services.migration_service import MigrationService

logger = logging.getLogger(__name__)


class TrioDatabaseService:
    """
    Pure Trio database service using synchronous SQLite operations.

    All database operations are executed in worker threads via trio.to_thread.run_sync
    to avoid blocking the Trio event loop.
    """

    def __init__(self, db_path: str, migration_service: MigrationService | None = None):
        """
        Initialize the Trio database service.

        Args:
            db_path (str): Path to the SQLite database file or URI.
            migration_service: Optional migration service for schema updates.
        """
        self.db_path = db_path
        self.migration_service = migration_service
        # Check if db_path is a URI (for shared memory databases)
        self._is_uri = db_path.startswith("file:")
        self._initialized = False

        # Connection pool
        self._pool_size = 5
        self._pool_send, self._pool_recv = trio.open_memory_channel(self._pool_size)
        self._pool_created = False

        logger.info(f"TrioDatabaseService created for {db_path}")

    def _create_connection(self, row_factory=None):
        """
        Create a new database connection.

        Args:
            row_factory: Optional row factory for the connection.

        Returns:
            sqlite3.Connection: Database connection.
        """
        if self._is_uri:
            conn = sqlite3.connect(
                self.db_path, timeout=30.0, uri=True, check_same_thread=False
            )
        else:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)

        if row_factory:
            conn.row_factory = row_factory
        else:
            # Enable foreign keys by default
            conn.execute("PRAGMA foreign_keys = ON")

        return conn

    async def _init_pool(self):
        """Initialize the connection pool."""
        if self._pool_created:
            return

        logger.info(
            f"Initializing database connection pool with {self._pool_size} connections"
        )
        for _ in range(self._pool_size):
            conn = await trio.to_thread.run_sync(self._create_connection)
            await self._pool_send.send(conn)
        self._pool_created = True

    @asynccontextmanager
    async def _acquire_connection(self, row_factory=None):
        """
        Acquire a connection from the pool.

        Args:
            row_factory: Optional row factory to set on the connection.
        """
        conn = await self._pool_recv.receive()
        try:
            if row_factory:
                conn.row_factory = row_factory
            yield conn
        finally:
            # Reset row factory if needed, or just return it
            # Ideally we should reset state, but for sqlite3 it's mostly fine
            await self._pool_send.send(conn)

    async def initialize(self):
        """Initialize the database schema and connection pool."""
        if self._initialized:
            return

        # Run migrations if service is available
        # Run migrations
        if not self.migration_service:
            raise RuntimeError(
                "MigrationService is required for database initialization"
            )

        await self.migration_service.run_migrations()

        # Initialize connection pool
        await self._init_pool()

        self._initialized = True
        logger.info("TrioDatabaseService initialized")

    def _datetime_to_iso(self, dt: datetime) -> str:
        """Convert datetime to ISO format string."""
        return dt.isoformat()

    def _iso_to_datetime(self, iso_str: str) -> datetime:
        """Convert ISO format string to datetime."""
        return datetime.fromisoformat(iso_str)

    async def save_session(self, session: Session) -> bool:
        """
        Save a session to the database.

        Args:
            session (Session): The session to save.

        Returns:
            bool: True if successful, False otherwise.
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(self._sync_save_session, conn, session)

    def _sync_save_session(self, conn, session: Session) -> bool:
        """Synchronous session save (runs in worker thread)."""
        try:
            cursor = conn.cursor()

            # Convert transcript to JSON string
            transcript_data = []
            for msg in session.transcript:
                transcript_data.append(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": self._datetime_to_iso(msg.timestamp),
                        "agent": msg.agent,
                    }
                )
            transcript_json = json.dumps(transcript_data)

            # Convert topics to JSON string
            topics_data = []
            for topic in session.topics:
                topics_data.append({"name": topic.name, "status": topic.status})
            topics_json = json.dumps(topics_data)

            cursor.execute(
                """
                INSERT OR REPLACE INTO sessions
                (session_id, user_id, timestamp, transcript, topics)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    session.session_id,
                    session.user_id,
                    self._datetime_to_iso(session.timestamp),
                    transcript_json,
                    topics_json,
                ),
            )

            conn.commit()
            logger.info(f"Session {session.session_id} saved successfully")
            return True

        except Exception as e:
            logger.error(f"Error saving session {session.session_id}: {e}")
            return False

    async def get_session(self, session_id: str) -> Session | None:
        """
        Retrieve a session from the database.

        Args:
            session_id (str): The ID of the session to retrieve.

        Returns:
            Optional[Session]: The session if found, None otherwise.
        """
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_session, conn, session_id
            )

    def _sync_get_session(self, conn, session_id: str) -> Session | None:
        """Synchronous session retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, user_id, timestamp, transcript, topics
                FROM sessions
                WHERE session_id = ?
            """,
                (session_id,),
            )

            row = cursor.fetchone()

            if row:
                # Parse transcript JSON
                transcript_data = json.loads(row["transcript"])
                transcript = []
                for msg_data in transcript_data:
                    transcript.append(
                        Message(
                            role=msg_data["role"],
                            content=msg_data["content"],
                            timestamp=self._iso_to_datetime(msg_data["timestamp"]),
                            agent=msg_data.get("agent"),
                        )
                    )

                # Parse topics JSON if available
                topics = []
                if row["topics"]:
                    try:
                        topics_data = json.loads(row["topics"])
                        topics = [
                            Topic(name=topic_data["name"], status=topic_data["status"])
                            for topic_data in topics_data
                        ]
                    except (json.JSONDecodeError, KeyError):
                        topics = []

                conn.commit()
                return Session(
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    timestamp=self._iso_to_datetime(row["timestamp"]),
                    transcript=transcript,
                    topics=topics,
                )
            return None

        except Exception as e:
            logger.error(f"Error retrieving session: {e}", exc_info=True)
            return None

    async def get_user_sessions(self, user_id: str, limit: int = 10) -> list[Session]:
        """
        Retrieve sessions for a user, ordered by timestamp (most recent first).

        Args:
            user_id (str): The ID of the user.
            limit (int): Maximum number of sessions to retrieve.

        Returns:
            List[Session]: List of sessions for the user.
        """
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_user_sessions, conn, user_id, limit
            )

    def _sync_get_user_sessions(self, conn, user_id: str, limit: int) -> list[Session]:
        """Synchronous user sessions retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, user_id, timestamp, transcript, topics
                FROM sessions
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (user_id, limit),
            )

            rows = cursor.fetchall()
            sessions = []

            for row in rows:
                # Parse transcript JSON
                transcript_data = json.loads(row["transcript"])
                transcript = []
                for msg_data in transcript_data:
                    transcript.append(
                        Message(
                            role=msg_data["role"],
                            content=msg_data["content"],
                            timestamp=self._iso_to_datetime(msg_data["timestamp"]),
                            agent=msg_data.get("agent"),
                        )
                    )

                # Parse topics JSON if available
                topics = []
                if row["topics"]:
                    try:
                        topics_data = json.loads(row["topics"])
                        topics = [
                            Topic(name=topic_data["name"], status=topic_data["status"])
                            for topic_data in topics_data
                        ]
                    except (json.JSONDecodeError, KeyError):
                        topics = []

                sessions.append(
                    Session(
                        session_id=row["session_id"],
                        user_id=row["user_id"],
                        timestamp=self._iso_to_datetime(row["timestamp"]),
                        transcript=transcript,
                        topics=topics,
                    )
                )

            conn.commit()
            return sessions

        except Exception as e:
            logger.error(f"Error retrieving user sessions: {e}", exc_info=True)
            return []

    async def save_therapy_plan(self, plan: TherapyPlan) -> bool:
        """
        Save a therapy plan to the database.

        Args:
            plan (TherapyPlan): The therapy plan to save.

        Returns:
            bool: True if successful, False otherwise.
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_save_therapy_plan, conn, plan
            )

    def _sync_save_therapy_plan(self, conn, plan: TherapyPlan) -> bool:
        """Synchronous therapy plan save (runs in worker thread)."""
        try:
            cursor = conn.cursor()

            # Convert plan_details to JSON string
            plan_details_json = json.dumps(plan.plan_details)

            # Convert session_briefing to JSON string if present
            session_briefing_json = None
            if plan.session_briefing:
                session_briefing_json = json.dumps(plan.session_briefing)

            cursor.execute(
                """
                INSERT OR REPLACE INTO therapy_plans
                (plan_id, user_id, created_at, updated_at, plan_details,
                 version, selected_therapy_style, session_briefing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    plan.plan_id,
                    plan.user_id,
                    self._datetime_to_iso(plan.created_at),
                    self._datetime_to_iso(plan.updated_at),
                    plan_details_json,
                    plan.version,
                    plan.selected_therapy_style,
                    session_briefing_json,
                ),
            )

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving therapy plan: {e}", exc_info=True)
            return False

    async def get_latest_therapy_plan(
        self, user_id: str = "default_user"
    ) -> TherapyPlan | None:
        """
        Retrieve the latest therapy plan for a user.

        Args:
            user_id (str): The ID of the user.

        Returns:
            Optional[TherapyPlan]: The latest therapy plan if found, None otherwise.
        """
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_latest_therapy_plan, conn, user_id
            )

    def _sync_get_latest_therapy_plan(self, conn, user_id: str) -> TherapyPlan | None:
        """Synchronous therapy plan retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                    SELECT plan_id, user_id, created_at, updated_at,
                           plan_details, version, selected_therapy_style,
                           session_briefing
                    FROM therapy_plans
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                """,
                (user_id,),
            )

            row = cursor.fetchone()

            if row:
                plan_details_data = json.loads(row["plan_details"])

                # Deserialize session_briefing if present
                session_briefing = None
                if row["session_briefing"]:
                    try:
                        session_briefing = json.loads(row["session_briefing"])
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Failed to parse session_briefing for user {user_id}"
                        )

                conn.commit()
                return TherapyPlan(
                    plan_id=row["plan_id"],
                    user_id=row["user_id"],
                    created_at=self._iso_to_datetime(row["created_at"]),
                    updated_at=self._iso_to_datetime(row["updated_at"]),
                    plan_details=plan_details_data,
                    version=row["version"],
                    selected_therapy_style=row["selected_therapy_style"],
                    session_briefing=session_briefing,
                )
            return None

        except Exception as e:
            logger.error(f"Error retrieving therapy plan: {e}", exc_info=True)
            return None

    async def get_therapy_plan(self, plan_id: str) -> TherapyPlan | None:
        """
        Retrieve a specific therapy plan by ID.

        Args:
            plan_id (str): The ID of the therapy plan.

        Returns:
            Optional[TherapyPlan]: The therapy plan if found, None otherwise.
        """
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_therapy_plan, conn, plan_id
            )

    def _sync_get_therapy_plan(self, conn, plan_id: str) -> TherapyPlan | None:
        """Synchronous therapy plan retrieval by ID (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                    SELECT plan_id, user_id, created_at, updated_at,
                           plan_details, version, selected_therapy_style,
                           session_briefing
                    FROM therapy_plans
                    WHERE plan_id = ?
                """,
                (plan_id,),
            )

            row = cursor.fetchone()

            if row:
                plan_details_data = json.loads(row["plan_details"])

                # Deserialize session_briefing if present
                session_briefing = None
                if row["session_briefing"]:
                    try:
                        session_briefing = json.loads(row["session_briefing"])
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Failed to parse session_briefing for plan {plan_id}"
                        )

                conn.commit()
                return TherapyPlan(
                    plan_id=row["plan_id"],
                    user_id=row["user_id"],
                    created_at=self._iso_to_datetime(row["created_at"]),
                    updated_at=self._iso_to_datetime(row["updated_at"]),
                    plan_details=plan_details_data,
                    version=row["version"],
                    selected_therapy_style=row["selected_therapy_style"],
                    session_briefing=session_briefing,
                )
            return None

        except Exception as e:
            logger.error(f"Error retrieving therapy plan by ID: {e}", exc_info=True)
            return None

    async def get_all_sessions_for_user(
        self, user_id: str = "default_user"
    ) -> list[Session]:
        """
        Retrieve all sessions for a user.

        Args:
            user_id (str): The ID of the user.

        Returns:
            List[Session]: List of all sessions for the user.
        """
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_all_sessions, conn, user_id
            )

    def _sync_get_all_sessions(self, conn, user_id: str) -> list[Session]:
        """Synchronous all sessions retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                    SELECT session_id, user_id, timestamp, transcript, topics
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY timestamp ASC
                """,
                (user_id,),
            )

            rows = cursor.fetchall()
            sessions = []

            for row in rows:
                # Parse transcript JSON
                transcript_data = json.loads(row["transcript"])
                transcript = []
                for msg_data in transcript_data:
                    transcript.append(
                        Message(
                            role=msg_data["role"],
                            content=msg_data["content"],
                            timestamp=self._iso_to_datetime(msg_data["timestamp"]),
                            agent=msg_data.get("agent"),
                        )
                    )

                # Parse topics JSON if available
                topics = []
                if row["topics"]:
                    try:
                        topics_data = json.loads(row["topics"])
                        topics = [
                            Topic(name=topic_data["name"], status=topic_data["status"])
                            for topic_data in topics_data
                        ]
                    except (json.JSONDecodeError, KeyError):
                        topics = []

                sessions.append(
                    Session(
                        session_id=row["session_id"],
                        user_id=row["user_id"],
                        timestamp=self._iso_to_datetime(row["timestamp"]),
                        transcript=transcript,
                        topics=topics,
                    )
                )

            conn.commit()
            return sessions

        except Exception as e:
            logger.error(f"Error retrieving sessions: {e}", exc_info=True)
            return []

    async def save_user_profile(self, profile: UserProfile) -> bool:
        """
        Save a user profile to the database.

        Args:
            profile (UserProfile): The user profile to save.

        Returns:
            bool: True if successful, False otherwise.
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_save_user_profile, conn, profile
            )

    def _sync_save_user_profile(self, conn, profile: UserProfile) -> bool:
        """Synchronous user profile save (runs in worker thread)."""
        try:
            cursor = conn.cursor()

            cursor.execute(
                """
                    INSERT OR REPLACE INTO user_profiles
                    (user_id, name, birthdate, profession, status,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.user_id,
                    profile.name,
                    (
                        self._datetime_to_iso(profile.birthdate)
                        if profile.birthdate
                        else None
                    ),
                    profile.profession,
                    (
                        profile.status.value
                        if hasattr(profile.status, "value")
                        else profile.status
                    ),
                    self._datetime_to_iso(profile.created_at),
                    self._datetime_to_iso(profile.updated_at),
                ),
            )

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error saving user profile: {e}", exc_info=True)
            return False

    async def update_user_status(self, user_id: str, status: str) -> bool:
        """
        Update the status field of a user profile.

        Args:
            user_id (str): The ID of the user.
            status (str): The new status value.

        Returns:
            bool: True if successful, False otherwise.
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_update_user_status, conn, user_id, status
            )

    def _sync_update_user_status(self, conn, user_id: str, status: str) -> bool:
        """Synchronous user status update (runs in worker thread)."""
        try:
            cursor = conn.cursor()

            cursor.execute(
                """
                    UPDATE user_profiles
                    SET status = ?, updated_at = ?
                    WHERE user_id = ?
                """,
                (status, self._datetime_to_iso(datetime.now()), user_id),
            )

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error updating user status: {e}", exc_info=True)
            return False

    async def get_user_profile(self, user_id: str) -> UserProfile | None:
        """
        Retrieve a user profile from the database.

        Args:
            user_id (str): The ID of the user.

        Returns:
            Optional[UserProfile]: The user profile if found, None otherwise.
        """
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_user_profile, conn, user_id
            )

    def _sync_get_user_profile(self, conn, user_id: str) -> UserProfile | None:
        """Synchronous user profile retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                    SELECT user_id, name, birthdate, profession, status,
                           created_at, updated_at
                    FROM user_profiles
                    WHERE user_id = ?
                """,
                (user_id,),
            )

            row = cursor.fetchone()

            if row:
                conn.commit()
                return UserProfile(
                    user_id=row["user_id"],
                    name=row["name"],
                    birthdate=(
                        self._iso_to_datetime(row["birthdate"])
                        if row["birthdate"]
                        else None
                    ),
                    profession=row["profession"],
                    status=(
                        UserStatus(row["status"])
                        if row["status"]
                        else UserStatus.PROFILE_ONLY
                    ),
                    created_at=self._iso_to_datetime(row["created_at"]),
                    updated_at=self._iso_to_datetime(row["updated_at"]),
                )
            return None

        except Exception as e:
            logger.error(f"Error retrieving user profile: {e}", exc_info=True)
            return None

    async def clear_all_data(self) -> bool:
        """
        Clear all data from all tables in the database.

        Returns:
            bool: True if successful, False otherwise.
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(self._sync_clear_all_data, conn)

    def _sync_clear_all_data(self, conn) -> bool:
        """Synchronous clear all data (runs in worker thread)."""
        try:
            cursor = conn.cursor()

            # Clear all tables
            cursor.execute("DELETE FROM sessions")
            cursor.execute("DELETE FROM therapy_plans")
            cursor.execute("DELETE FROM user_profiles")

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error clearing database: {e}", exc_info=True)
            return False

    async def health_check(self) -> bool:
        """
        Perform health check on database connection.

        Returns:
            bool: True if database is healthy, False otherwise.
        """
        try:
            async with self._acquire_connection() as conn:
                return await trio.to_thread.run_sync(self._sync_health_check, conn)
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def _sync_health_check(self, conn) -> bool:
        """Synchronous health check (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            conn.commit()
            return result is not None

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    # Authentication methods

    async def create_user_credentials(self, credentials: UserCredentials) -> bool:
        """
        Create user credentials in the database.

        Args:
            credentials: UserCredentials object with username and password hash

        Returns:
            bool: True if successful, False otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_create_user_credentials, conn, credentials
            )

    def _sync_create_user_credentials(self, conn, credentials: UserCredentials) -> bool:
        """Synchronous user credentials creation (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_credentials
                (user_id, username, password_hash, created_at, last_login)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    credentials.user_id,
                    credentials.username,
                    credentials.password_hash,
                    self._datetime_to_iso(credentials.created_at),
                    (
                        self._datetime_to_iso(credentials.last_login)
                        if credentials.last_login
                        else None
                    ),
                ),
            )
            conn.commit()
            return True

        except sqlite3.IntegrityError as e:
            logger.error(f"Duplicate username or user_id: {e}")
            return False
        except Exception as e:
            logger.error(f"Error creating user credentials: {e}", exc_info=True)
            return False

    async def get_user_credentials(self, username: str) -> UserCredentials | None:
        """
        Retrieve user credentials by username.

        Args:
            username: Username to look up

        Returns:
            UserCredentials if found, None otherwise
        """
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_user_credentials, conn, username
            )

    def _sync_get_user_credentials(self, conn, username: str) -> UserCredentials | None:
        """Synchronous user credentials retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_id, username, password_hash, created_at, last_login
                FROM user_credentials
                WHERE username = ?
                """,
                (username,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return UserCredentials(
                user_id=row["user_id"],
                username=row["username"],
                password_hash=row["password_hash"],
                created_at=self._iso_to_datetime(row["created_at"]),
                last_login=(
                    self._iso_to_datetime(row["last_login"])
                    if row["last_login"]
                    else None
                ),
            )

        except Exception as e:
            logger.error(f"Error retrieving user credentials: {e}", exc_info=True)
            return None

    async def update_last_login(self, user_id: str, login_time: datetime) -> bool:
        """
        Update the last login time for a user.

        Args:
            user_id: User ID
            login_time: Datetime of login

        Returns:
            bool: True if successful, False otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_update_last_login, conn, user_id, login_time
            )

    def _sync_update_last_login(self, conn, user_id: str, login_time: datetime) -> bool:
        """Synchronous last login update (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE user_credentials
                SET last_login = ?
                WHERE user_id = ?
                """,
                (self._datetime_to_iso(login_time), user_id),
            )
            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error updating last login: {e}", exc_info=True)
            return False

    async def get_user_by_username(self, username: str) -> UserProfile | None:
        """
        Get user profile by username (convenience method).

        Args:
            username: Username to look up

        Returns:
            UserProfile if found, None otherwise
        """
        credentials = await self.get_user_credentials(username)
        if not credentials:
            return None

        return await self.get_user_profile(credentials.user_id)
