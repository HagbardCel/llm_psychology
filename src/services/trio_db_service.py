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
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import trio

from models.auth_models import UserCredentials
from models.data_models import (
    DetailedSession,
    Message,
    PatientAnalysisVersion,
    PatientProfile,
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

        # Ensure FK constraints behave as expected in SQLite.
        conn.execute("PRAGMA foreign_keys = ON")

        if row_factory:
            conn.row_factory = row_factory

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
                INSERT INTO sessions
                (session_id, user_id, timestamp, transcript, topics)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    timestamp = excluded.timestamp,
                    transcript = excluded.transcript,
                    topics = excluded.topics
                WHERE sessions.enriched = 0
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
            if cursor.rowcount > 0:
                logger.info(f"Session {session.session_id} saved successfully")
                return True

            logger.warning(
                "Session %s not saved because it is already enriched (immutable)",
                session.session_id,
            )
            return False

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
                SELECT session_id, user_id, timestamp, transcript, topics,
                       psychological_summary, dominant_affects, key_themes,
                       notable_interactions, interpretations, patient_reactions,
                       enriched
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
                    psychological_summary=row["psychological_summary"],
                    dominant_affects=(
                        json.loads(row["dominant_affects"])
                        if row["dominant_affects"]
                        else []
                    ),
                    key_themes=(
                        json.loads(row["key_themes"]) if row["key_themes"] else []
                    ),
                    notable_interactions=row["notable_interactions"],
                    interpretations=row["interpretations"],
                    patient_reactions=row["patient_reactions"],
                    enriched=bool(row["enriched"]),
                )
            return None

        except Exception as e:
            logger.error(f"Error retrieving session: {e}", exc_info=True)
            return None

    async def get_session_details(self, session_id: str) -> DetailedSession | None:
        """
        Retrieve a session with Tier 2 enrichment fields.

        Args:
            session_id: Session identifier

        Returns:
            DetailedSession if found, None otherwise
        """
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_session_details, conn, session_id
            )

    def _sync_get_session_details(
        self, conn: sqlite3.Connection, session_id: str
    ) -> DetailedSession | None:
        """Synchronous detailed session retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, user_id, timestamp, transcript, topics,
                       psychological_summary, dominant_affects, key_themes,
                       notable_interactions, interpretations, patient_reactions,
                       enriched
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            transcript = [Message.model_validate(m) for m in json.loads(row["transcript"])]
            topics = (
                [Topic.model_validate(t) for t in json.loads(row["topics"])]
                if row["topics"]
                else []
            )
            dominant_affects = json.loads(row["dominant_affects"]) if row["dominant_affects"] else []
            key_themes = json.loads(row["key_themes"]) if row["key_themes"] else []

            detailed = DetailedSession(
                session_id=row["session_id"],
                user_id=row["user_id"],
                timestamp=self._iso_to_datetime(row["timestamp"]),
                transcript=transcript,
                topics=topics,
                psychological_summary=row["psychological_summary"],
                dominant_affects=dominant_affects,
                key_themes=key_themes,
                notable_interactions=row["notable_interactions"],
                interpretations=row["interpretations"],
                patient_reactions=row["patient_reactions"],
                enriched=bool(row["enriched"]),
            )
            conn.commit()
            return detailed

        except Exception as e:
            logger.error(f"Error retrieving detailed session: {e}", exc_info=True)
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
                SELECT session_id, user_id, timestamp, transcript, topics,
                       psychological_summary, dominant_affects, key_themes,
                       notable_interactions, interpretations, patient_reactions,
                       enriched
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
                        psychological_summary=row["psychological_summary"],
                        dominant_affects=(
                            json.loads(row["dominant_affects"])
                            if row["dominant_affects"]
                            else []
                        ),
                        key_themes=(
                            json.loads(row["key_themes"])
                            if row["key_themes"]
                            else []
                        ),
                        notable_interactions=row["notable_interactions"],
                        interpretations=row["interpretations"],
                        patient_reactions=row["patient_reactions"],
                        enriched=bool(row["enriched"]),
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

            # Serialize list fields
            initial_goals_json = json.dumps(plan.initial_goals)
            planned_interventions_json = json.dumps(plan.planned_interventions)

            # Convert session_briefing to JSON string if present
            session_briefing_json = None
            if plan.session_briefing:
                session_briefing_json = json.dumps(plan.session_briefing)

            cursor.execute(
                """
                INSERT OR REPLACE INTO therapy_plans
                (plan_id, user_id, created_at, updated_at, plan_details,
                 initial_goals, current_progress, planned_interventions, status,
                 version, selected_therapy_style, session_briefing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    plan.plan_id,
                    plan.user_id,
                    self._datetime_to_iso(plan.created_at),
                    self._datetime_to_iso(plan.updated_at),
                    plan_details_json,
                    initial_goals_json,
                    plan.current_progress,
                    planned_interventions_json,
                    plan.status,
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
                           plan_details, initial_goals, current_progress,
                           planned_interventions, status,
                           version, selected_therapy_style,
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
                plan_details_data = json.loads(row["plan_details"]) if row["plan_details"] else {}
                initial_goals = json.loads(row["initial_goals"]) if row["initial_goals"] else []
                planned_interventions = json.loads(row["planned_interventions"]) if row["planned_interventions"] else []
                status = row["status"] or "active"

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
                    initial_goals=initial_goals,
                    current_progress=row["current_progress"] or "",
                    planned_interventions=planned_interventions,
                    status=status,
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
                           plan_details, initial_goals, current_progress,
                           planned_interventions, status,
                           version, selected_therapy_style,
                           session_briefing
                    FROM therapy_plans
                    WHERE plan_id = ?
                """,
                (plan_id,),
            )

            row = cursor.fetchone()

            if row:
                plan_details_data = json.loads(row["plan_details"]) if row["plan_details"] else {}
                initial_goals = json.loads(row["initial_goals"]) if row["initial_goals"] else []
                planned_interventions = json.loads(row["planned_interventions"]) if row["planned_interventions"] else []
                status = row["status"] or "active"

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
                    initial_goals=initial_goals,
                    current_progress=row["current_progress"] or "",
                    planned_interventions=planned_interventions,
                    status=status,
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
                    SELECT session_id, user_id, timestamp, transcript, topics,
                           psychological_summary, dominant_affects, key_themes,
                           notable_interactions, interpretations, patient_reactions,
                           enriched
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
                        psychological_summary=row["psychological_summary"],
                        dominant_affects=(
                            json.loads(row["dominant_affects"])
                            if row["dominant_affects"]
                            else []
                        ),
                        key_themes=(
                            json.loads(row["key_themes"])
                            if row["key_themes"]
                            else []
                        ),
                        notable_interactions=row["notable_interactions"],
                        interpretations=row["interpretations"],
                        patient_reactions=row["patient_reactions"],
                        enriched=bool(row["enriched"]),
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

            # Clear all tables (order matters with foreign keys).
            cursor.execute("DELETE FROM session_enrichment_jobs")
            cursor.execute("DELETE FROM patient_profile_history")
            cursor.execute("DELETE FROM patient_analysis")
            cursor.execute("DELETE FROM patient_profiles")
            cursor.execute("DELETE FROM sessions")
            cursor.execute("DELETE FROM therapy_plans")
            cursor.execute("DELETE FROM user_credentials")
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

    # ========================================================================
    # TIER 1: Patient Profile Methods
    # ========================================================================

    async def get_patient_profile(self, user_id: str) -> PatientProfile | None:
        """
        Retrieve patient profile (Tier 1) for user.

        Args:
            user_id: User ID to retrieve profile for

        Returns:
            PatientProfile if found, None otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_patient_profile, conn, user_id
            )

    def _sync_get_patient_profile(
        self, conn: sqlite3.Connection, user_id: str
    ) -> PatientProfile | None:
        """Synchronous patient profile retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT profile_data FROM patient_profiles WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Deserialize JSON to PatientProfile
            profile_data = json.loads(row[0])
            return PatientProfile.model_validate(profile_data)

        except Exception as e:
            logger.error(f"Error retrieving patient profile: {e}", exc_info=True)
            return None

    async def save_patient_profile(self, profile: PatientProfile) -> bool:
        """
        Create or replace patient profile.

        Args:
            profile: PatientProfile to save

        Returns:
            True if successful, False otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_save_patient_profile, conn, profile
            )

    def _sync_save_patient_profile(
        self, conn: sqlite3.Connection, profile: PatientProfile
    ) -> bool:
        """Synchronous patient profile save (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO patient_profiles
                (user_id, profile_data, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    profile.user_id,
                    profile.model_dump_json(),
                    self._datetime_to_iso(profile.created_at),
                    self._datetime_to_iso(profile.updated_at),
                ),
            )
            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error saving patient profile: {e}", exc_info=True)
            conn.rollback()
            return False

    async def update_patient_profile(
        self,
        profile: PatientProfile,
        *,
        change_summary: str | None = None,
        created_by_session: str | None = None,
    ) -> bool:
        """
        Update existing patient profile (rare operation).

        Args:
            profile: Updated PatientProfile
            change_summary: Optional reason for audit trail
            created_by_session: Optional session_id that triggered the update

        Returns:
            True if successful, False otherwise
        """
        profile.updated_at = datetime.now()
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_update_patient_profile_with_history,
                conn,
                profile,
                change_summary,
                created_by_session,
            )

    def _sync_update_patient_profile_with_history(
        self,
        conn: sqlite3.Connection,
        profile: PatientProfile,
        change_summary: str | None,
        created_by_session: str | None,
    ) -> bool:
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            cursor.execute(
                "SELECT profile_data FROM patient_profiles WHERE user_id = ?",
                (profile.user_id,),
            )
            row = cursor.fetchone()
            previous_profile_json = row[0] if row else None

            if previous_profile_json:
                cursor.execute(
                    """
                    INSERT INTO patient_profile_history
                    (history_id, user_id, previous_profile_data, new_profile_data,
                     change_summary, created_at, created_by_session)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"pph_{uuid.uuid4().hex[:12]}",
                        profile.user_id,
                        previous_profile_json,
                        profile.model_dump_json(),
                        (change_summary or "")[:1000] or None,
                        datetime.now().isoformat(),
                        created_by_session,
                    ),
                )

            cursor.execute(
                """
                INSERT OR REPLACE INTO patient_profiles
                (user_id, profile_data, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    profile.user_id,
                    profile.model_dump_json(),
                    self._datetime_to_iso(profile.created_at),
                    self._datetime_to_iso(profile.updated_at),
                ),
            )

            conn.commit()
            return True
        except Exception as e:
            logger.error("Error updating patient profile with history: %s", e, exc_info=True)
            conn.rollback()
            return False

    async def get_patient_profile_history(
        self, user_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Retrieve recent Tier 1 profile change history for a user."""
        async with self._acquire_connection(row_factory=sqlite3.Row) as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_patient_profile_history, conn, user_id, limit
            )

    def _sync_get_patient_profile_history(
        self, conn: sqlite3.Connection, user_id: str, limit: int
    ) -> list[dict[str, Any]]:
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT history_id, user_id, previous_profile_data, new_profile_data,
                       change_summary, created_at, created_by_session
                FROM patient_profile_history
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Error retrieving patient profile history: %s", e, exc_info=True)
            return []

    # ========================================================================
    # TIER 2: Session Enrichment Methods
    # ========================================================================

    async def get_recent_sessions(
        self, user_id: str, limit: int = 5, *, enriched_only: bool = True
    ) -> list[DetailedSession]:
        """
        Get recent enriched sessions for context.

        Args:
            user_id: User ID to retrieve sessions for
            limit: Maximum number of sessions to retrieve (default 5)
            enriched_only: When True, returns only enriched (immutable) sessions

        Returns:
            List of DetailedSession objects, ordered by timestamp DESC
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_recent_sessions, conn, user_id, limit, enriched_only
            )

    def _sync_get_recent_sessions(
        self, conn: sqlite3.Connection, user_id: str, limit: int, enriched_only: bool
    ) -> list[DetailedSession]:
        """Synchronous recent sessions retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            where_clause = "WHERE user_id = ?"
            params: tuple[Any, ...]
            if enriched_only:
                where_clause += " AND enriched = 1"
            params = (user_id, limit)
            cursor.execute(
                f"""
                SELECT session_id, user_id, timestamp, transcript, topics,
                       psychological_summary, dominant_affects, key_themes,
                       notable_interactions, interpretations, patient_reactions, enriched
                FROM sessions
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            )

            sessions = []
            for row in cursor.fetchall():
                # Parse transcript and topics
                transcript = [Message.model_validate(m) for m in json.loads(row[3])]
                topics = [Topic.model_validate(t) for t in json.loads(row[4])] if row[4] else []

                # Parse Tier 2 fields
                dominant_affects = json.loads(row[6]) if row[6] else []
                key_themes = json.loads(row[7]) if row[7] else []

                session = DetailedSession(
                    session_id=row[0],
                    user_id=row[1],
                    timestamp=self._iso_to_datetime(row[2]),
                    transcript=transcript,
                    topics=topics,
                    psychological_summary=row[5],
                    dominant_affects=dominant_affects,
                    key_themes=key_themes,
                    notable_interactions=row[8],
                    interpretations=row[9],
                    patient_reactions=row[10],
                    enriched=bool(row[11]),
                )
                sessions.append(session)

            return sessions

        except Exception as e:
            logger.error(f"Error retrieving recent sessions: {e}", exc_info=True)
            return []

    async def update_session_tier2(self, session_id: str, tier2_data: dict) -> bool:
        """
        Add Tier 2 enrichment to session (one-time operation).

        Args:
            session_id: Session ID to enrich
            tier2_data: Dictionary with Tier 2 fields

        Returns:
            True if successful, False otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_update_session_tier2, conn, session_id, tier2_data
            )

    def _sync_update_session_tier2(
        self, conn: sqlite3.Connection, session_id: str, tier2_data: dict
    ) -> bool:
        """Synchronous session Tier 2 update (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sessions
                SET psychological_summary = ?,
                    dominant_affects = ?,
                    key_themes = ?,
                    notable_interactions = ?,
                    interpretations = ?,
                    patient_reactions = ?,
                    enriched = 1
                WHERE session_id = ? AND enriched = 0
                """,
                (
                    tier2_data.get("psychological_summary"),
                    json.dumps(tier2_data.get("dominant_affects", [])),
                    json.dumps(tier2_data.get("key_themes", [])),
                    tier2_data.get("notable_interactions"),
                    tier2_data.get("interpretations"),
                    tier2_data.get("patient_reactions"),
                    session_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

        except Exception as e:
            logger.error(f"Error updating session Tier 2: {e}", exc_info=True)
            conn.rollback()
            return False

    # ========================================================================
    # SESSION ENRICHMENT JOB QUEUE (Tier 2 async enrichment)
    # ========================================================================

    async def enqueue_session_enrichment_job(self, session_id: str, user_id: str) -> bool:
        """Enqueue (or re-enqueue) a session for Tier 2 enrichment."""
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_enqueue_session_enrichment_job, conn, session_id, user_id
            )

    def _sync_enqueue_session_enrichment_job(
        self, conn: sqlite3.Connection, session_id: str, user_id: str
    ) -> bool:
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO session_enrichment_jobs
                (session_id, user_id, status, attempts, last_error, created_at, updated_at)
                VALUES (?, ?, 'queued', 0, NULL, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status = CASE
                        WHEN session_enrichment_jobs.status = 'complete' THEN 'complete'
                        ELSE 'queued'
                    END,
                    updated_at = excluded.updated_at
                """,
                (session_id, user_id, now, now),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Error enqueuing enrichment job: %s", e, exc_info=True)
            conn.rollback()
            return False

    async def claim_next_session_enrichment_job(
        self, *, max_attempts: int = 3
    ) -> dict[str, Any] | None:
        """
        Atomically claim the next queued enrichment job.

        Returns a dict with session_id, user_id, attempts, status, or None if no job.
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_claim_next_session_enrichment_job, conn, max_attempts
            )

    def _sync_claim_next_session_enrichment_job(
        self, conn: sqlite3.Connection, max_attempts: int
    ) -> dict[str, Any] | None:
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT session_id, user_id, attempts
                FROM session_enrichment_jobs
                WHERE status = 'queued' AND attempts < ?
                ORDER BY updated_at ASC
                LIMIT 1
                """,
                (max_attempts,),
            )
            row = cursor.fetchone()
            if not row:
                conn.commit()
                return None

            session_id, user_id, attempts = row
            now = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE session_enrichment_jobs
                SET status = 'processing',
                    attempts = attempts + 1,
                    updated_at = ?,
                    last_error = NULL
                WHERE session_id = ? AND status = 'queued'
                """,
                (now, session_id),
            )
            if cursor.rowcount <= 0:
                conn.commit()
                return None

            conn.commit()
            return {
                "session_id": session_id,
                "user_id": user_id,
                "attempts": attempts + 1,
                "status": "processing",
            }
        except Exception as e:
            logger.error("Error claiming enrichment job: %s", e, exc_info=True)
            conn.rollback()
            return None

    async def mark_session_enrichment_job_complete(self, session_id: str) -> bool:
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_mark_session_enrichment_job_complete, conn, session_id
            )

    def _sync_mark_session_enrichment_job_complete(
        self, conn: sqlite3.Connection, session_id: str
    ) -> bool:
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE session_enrichment_jobs
                SET status = 'complete', updated_at = ?
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("Error marking enrichment job complete: %s", e, exc_info=True)
            conn.rollback()
            return False

    async def mark_session_enrichment_job_failed(self, session_id: str, error: str) -> bool:
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_mark_session_enrichment_job_failed, conn, session_id, error
            )

    def _sync_mark_session_enrichment_job_failed(
        self, conn: sqlite3.Connection, session_id: str, error: str
    ) -> bool:
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE session_enrichment_jobs
                SET status = 'failed',
                    last_error = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (error[:2000], now, session_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("Error marking enrichment job failed: %s", e, exc_info=True)
            conn.rollback()
            return False

    async def get_session_count(self, user_id: str) -> int:
        """
        Get total session count for user (for milestone tracking).

        Args:
            user_id: User ID to count sessions for

        Returns:
            Number of sessions
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_session_count, conn, user_id
            )

    def _sync_get_session_count(
        self, conn: sqlite3.Connection, user_id: str
    ) -> int:
        """Synchronous session count (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else 0

        except Exception as e:
            logger.error(f"Error counting sessions: {e}", exc_info=True)
            return 0

    # ========================================================================
    # TIER 3: Patient Analysis Methods
    # ========================================================================

    async def get_latest_patient_analysis(
        self, user_id: str
    ) -> PatientAnalysisVersion | None:
        """
        Get most recent version of patient analysis.

        Args:
            user_id: User ID to retrieve analysis for

        Returns:
            PatientAnalysisVersion if found, None otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_latest_patient_analysis, conn, user_id
            )

    def _sync_get_latest_patient_analysis(
        self, conn: sqlite3.Connection, user_id: str
    ) -> PatientAnalysisVersion | None:
        """Synchronous latest analysis retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT analysis_id, user_id, version, analysis_data, created_at,
                       created_by_session, change_summary, superseded_by
                FROM patient_analysis
                WHERE user_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            analysis_data = json.loads(row[3])
            return PatientAnalysisVersion(
                analysis_id=row[0],
                user_id=row[1],
                version=row[2],
                analysis_data=analysis_data,
                created_at=self._iso_to_datetime(row[4]),
                created_by_session=row[5],
                change_summary=row[6],
                superseded_by=row[7],
            )

        except Exception as e:
            logger.error(f"Error retrieving latest patient analysis: {e}", exc_info=True)
            return None

    async def get_patient_analysis_version(
        self, user_id: str, version: int
    ) -> PatientAnalysisVersion | None:
        """
        Get specific version of patient analysis.

        Args:
            user_id: User ID
            version: Version number to retrieve

        Returns:
            PatientAnalysisVersion if found, None otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_patient_analysis_version, conn, user_id, version
            )

    def _sync_get_patient_analysis_version(
        self, conn: sqlite3.Connection, user_id: str, version: int
    ) -> PatientAnalysisVersion | None:
        """Synchronous analysis version retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT analysis_id, user_id, version, analysis_data, created_at,
                       created_by_session, change_summary, superseded_by
                FROM patient_analysis
                WHERE user_id = ? AND version = ?
                """,
                (user_id, version),
            )
            row = cursor.fetchone()

            if not row:
                return None

            analysis_data = json.loads(row[3])
            return PatientAnalysisVersion(
                analysis_id=row[0],
                user_id=row[1],
                version=row[2],
                analysis_data=analysis_data,
                created_at=self._iso_to_datetime(row[4]),
                created_by_session=row[5],
                change_summary=row[6],
                superseded_by=row[7],
            )

        except Exception as e:
            logger.error(
                f"Error retrieving patient analysis version: {e}", exc_info=True
            )
            return None

    async def get_analysis_history(
        self, user_id: str
    ) -> list[PatientAnalysisVersion]:
        """
        Get all analysis versions (for review/audit).

        Args:
            user_id: User ID to retrieve history for

        Returns:
            List of PatientAnalysisVersion objects, ordered by version DESC
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_get_analysis_history, conn, user_id
            )

    def _sync_get_analysis_history(
        self, conn: sqlite3.Connection, user_id: str
    ) -> list[PatientAnalysisVersion]:
        """Synchronous analysis history retrieval (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT analysis_id, user_id, version, analysis_data, created_at,
                       created_by_session, change_summary, superseded_by
                FROM patient_analysis
                WHERE user_id = ?
                ORDER BY version DESC
                """,
                (user_id,),
            )

            versions = []
            for row in cursor.fetchall():
                analysis_data = json.loads(row[3])
                version = PatientAnalysisVersion(
                    analysis_id=row[0],
                    user_id=row[1],
                    version=row[2],
                    analysis_data=analysis_data,
                    created_at=self._iso_to_datetime(row[4]),
                    created_by_session=row[5],
                    change_summary=row[6],
                    superseded_by=row[7],
                )
                versions.append(version)

            return versions

        except Exception as e:
            logger.error(f"Error retrieving analysis history: {e}", exc_info=True)
            return []

    async def save_patient_analysis_version(
        self, analysis: PatientAnalysisVersion
    ) -> bool:
        """
        Save new version of patient analysis.

        Args:
            analysis: PatientAnalysisVersion to save

        Returns:
            True if successful, False otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_save_patient_analysis_version, conn, analysis
            )

    async def save_patient_analysis_version_and_supersede(
        self, analysis: PatientAnalysisVersion, supersede_analysis_id: str
    ) -> bool:
        """
        Save a new analysis version and mark a previous version as superseded.

        This is an atomic, transaction-protected operation to avoid creating a
        new version without updating the previous version's `superseded_by`.

        Args:
            analysis: New PatientAnalysisVersion to save
            supersede_analysis_id: Existing analysis_id to mark as superseded

        Returns:
            True if both insert + supersede update succeeded, False otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_save_patient_analysis_version_and_supersede,
                conn,
                analysis,
                supersede_analysis_id,
            )

    async def save_patient_analysis_next_version_and_supersede(
        self,
        *,
        analysis_id: str,
        user_id: str,
        analysis_data: Any,
        created_at: datetime,
        created_by_session: str | None,
        change_summary: str | None,
        supersede_analysis_id: str,
    ) -> PatientAnalysisVersion | None:
        """
        Save a new analysis version with an atomically allocated version number,
        and mark a previous version as superseded.
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_save_patient_analysis_next_version_and_supersede,
                conn,
                analysis_id,
                user_id,
                analysis_data,
                created_at,
                created_by_session,
                change_summary,
                supersede_analysis_id,
            )

    def _sync_save_patient_analysis_next_version_and_supersede(
        self,
        conn: sqlite3.Connection,
        analysis_id: str,
        user_id: str,
        analysis_data: Any,
        created_at: datetime,
        created_by_session: str | None,
        change_summary: str | None,
        supersede_analysis_id: str,
    ) -> PatientAnalysisVersion | None:
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM patient_analysis WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            next_version = int(row[0]) if row else 1

            cursor.execute(
                """
                INSERT INTO patient_analysis
                (analysis_id, user_id, version, analysis_data, created_at,
                 created_by_session, change_summary, superseded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    analysis_id,
                    user_id,
                    next_version,
                    analysis_data.model_dump_json(),
                    self._datetime_to_iso(created_at),
                    created_by_session,
                    change_summary,
                ),
            )

            cursor.execute(
                """
                UPDATE patient_analysis
                SET superseded_by = ?
                WHERE analysis_id = ? AND (superseded_by IS NULL OR superseded_by = '')
                """,
                (analysis_id, supersede_analysis_id),
            )
            if cursor.rowcount <= 0:
                raise RuntimeError(
                    f"Failed to mark analysis {supersede_analysis_id} as superseded"
                )

            conn.commit()
            return PatientAnalysisVersion(
                analysis_id=analysis_id,
                user_id=user_id,
                version=next_version,
                analysis_data=analysis_data,
                created_at=created_at,
                created_by_session=created_by_session,
                change_summary=change_summary,
                superseded_by=None,
            )

        except Exception as e:
            logger.error(
                "Error saving next patient analysis version: %s", e, exc_info=True
            )
            conn.rollback()
            return None

    def _sync_save_patient_analysis_version(
        self, conn: sqlite3.Connection, analysis: PatientAnalysisVersion
    ) -> bool:
        """Synchronous analysis version save (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO patient_analysis
                (analysis_id, user_id, version, analysis_data, created_at,
                 created_by_session, change_summary, superseded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis.analysis_id,
                    analysis.user_id,
                    analysis.version,
                    analysis.analysis_data.model_dump_json(),
                    self._datetime_to_iso(analysis.created_at),
                    analysis.created_by_session,
                    analysis.change_summary,
                    analysis.superseded_by,
                ),
            )
            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error saving patient analysis version: {e}", exc_info=True)
            conn.rollback()
            return False

    def _sync_save_patient_analysis_version_and_supersede(
        self,
        conn: sqlite3.Connection,
        analysis: PatientAnalysisVersion,
        supersede_analysis_id: str,
    ) -> bool:
        """Synchronous atomic analysis save + supersede (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            cursor.execute(
                """
                INSERT INTO patient_analysis
                (analysis_id, user_id, version, analysis_data, created_at,
                 created_by_session, change_summary, superseded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis.analysis_id,
                    analysis.user_id,
                    analysis.version,
                    analysis.analysis_data.model_dump_json(),
                    self._datetime_to_iso(analysis.created_at),
                    analysis.created_by_session,
                    analysis.change_summary,
                    analysis.superseded_by,
                ),
            )

            cursor.execute(
                """
                UPDATE patient_analysis
                SET superseded_by = ?
                WHERE analysis_id = ? AND (superseded_by IS NULL OR superseded_by = '')
                """,
                (analysis.analysis_id, supersede_analysis_id),
            )
            if cursor.rowcount <= 0:
                raise RuntimeError(
                    f"Failed to mark analysis {supersede_analysis_id} as superseded"
                )

            conn.commit()
            return True

        except Exception as e:
            logger.error(
                "Error saving patient analysis version and superseding previous: %s",
                e,
                exc_info=True,
            )
            conn.rollback()
            return False

    async def mark_analysis_superseded(
        self, old_analysis_id: str, new_analysis_id: str
    ) -> bool:
        """
        Mark previous version as superseded by new version.

        Args:
            old_analysis_id: Analysis ID to mark as superseded
            new_analysis_id: Analysis ID that supersedes it

        Returns:
            True if successful, False otherwise
        """
        async with self._acquire_connection() as conn:
            return await trio.to_thread.run_sync(
                self._sync_mark_analysis_superseded, conn, old_analysis_id, new_analysis_id
            )

    def _sync_mark_analysis_superseded(
        self, conn: sqlite3.Connection, old_analysis_id: str, new_analysis_id: str
    ) -> bool:
        """Synchronous analysis superseding (runs in worker thread)."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE patient_analysis
                SET superseded_by = ?
                WHERE analysis_id = ?
                """,
                (new_analysis_id, old_analysis_id),
            )
            conn.commit()
            return cursor.rowcount > 0

        except Exception as e:
            logger.error(f"Error marking analysis as superseded: {e}", exc_info=True)
            conn.rollback()
            return False
