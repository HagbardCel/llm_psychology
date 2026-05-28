"""Trio database service built on top of a shared SQLite executor."""

import logging
from datetime import datetime
from typing import Any

from psychoanalyst_app.models.data_models import (
    DetailedSession,
    PatientAnalysisVersion,
    Session,
    TherapyPlan,
    UserProfile,
    UserProfileSummary,
)
from psychoanalyst_app.services.db.codecs import datetime_to_iso, iso_to_datetime
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.db.repos import (
    assessment_recommendations_repo,
    enrichment_jobs_repo,
    llm_cache_repo,
    patient_analysis_repo,
    sessions_repo,
    therapy_plans_repo,
    users_repo,
)
from psychoanalyst_app.services.db.sqlite_config import reraise_locked_database_error
from psychoanalyst_app.services.migration_service import MigrationService

logger = logging.getLogger(__name__)


class TrioDatabaseService:
    """SQLite-backed database service executed through TrioSQLiteExecutor."""

    def __init__(
        self,
        db_path: str,
        migration_service: MigrationService | None = None,
        executor: TrioSQLiteExecutor | None = None,
    ):
        """
        Initialize the Trio database service.

        Args:
            db_path (str): Path to the SQLite database file or URI.
            migration_service: Optional migration service for schema updates.
        """
        self.migration_service = migration_service
        self.db_path = db_path
        self.executor = executor or TrioSQLiteExecutor(db_path)
        self._initialized = False

        logger.info(f"TrioDatabaseService created for {db_path}")

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

        await self.executor.initialize()

        self._initialized = True
        logger.info("TrioDatabaseService initialized")

    def close(self):
        """Close all open database connections and release pool resources."""
        self.executor.close()

    def _create_connection(self, row_factory=None):
        """Backward-compatible helper for tests that need raw connections."""
        return self.executor.create_connection(row_factory=row_factory)

    async def save_session(self, session: Session) -> bool:
        """Save a session record."""
        return await sessions_repo.save_session(self.executor, session, datetime_to_iso)

    async def get_session(self, session_id: str) -> Session | None:
        """
        Retrieve a session from the database.

        Args:
            session_id (str): The ID of the session to retrieve.

        Returns:
            Optional[Session]: The session if found, None otherwise.
        """
        return await sessions_repo.get_session(
            self.executor, session_id, iso_to_datetime
        )

    async def get_session_details(self, session_id: str) -> DetailedSession | None:
        """
        Retrieve a session with Tier 2 enrichment fields.

        Args:
            session_id: Session identifier

        Returns:
            DetailedSession if found, None otherwise
        """
        return await sessions_repo.get_session_details(
            self.executor, session_id, iso_to_datetime
        )

    async def get_user_sessions(self, user_id: str, limit: int = 10) -> list[Session]:
        """
        Retrieve sessions for a user, ordered by timestamp (most recent first).

        Args:
            user_id (str): The ID of the user.
            limit (int): Maximum number of sessions to retrieve.

        Returns:
            List[Session]: List of sessions for the user.
        """
        return await sessions_repo.get_user_sessions(
            self.executor, user_id, limit, iso_to_datetime
        )

    async def save_therapy_plan(self, plan: TherapyPlan) -> bool:
        """Save a therapy plan record."""
        return await therapy_plans_repo.save_therapy_plan(
            self.executor, plan, datetime_to_iso
        )

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
        return await therapy_plans_repo.get_latest_therapy_plan(
            self.executor, user_id, iso_to_datetime
        )

    async def get_therapy_plan(self, plan_id: str) -> TherapyPlan | None:
        """
        Retrieve a specific therapy plan by ID.

        Args:
            plan_id (str): The ID of the therapy plan.

        Returns:
            Optional[TherapyPlan]: The therapy plan if found, None otherwise.
        """
        return await therapy_plans_repo.get_therapy_plan(
            self.executor, plan_id, iso_to_datetime
        )

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
        return await sessions_repo.get_all_sessions_for_user(
            self.executor, user_id, iso_to_datetime
        )

    async def save_user_profile(self, profile: UserProfile) -> bool:
        """
        Save a user profile to the database.

        Args:
            profile (UserProfile): The user profile to save.

        Returns:
            bool: True if successful, False otherwise.
        """
        return await users_repo.save_user_profile(
            self.executor, profile, datetime_to_iso
        )

    async def update_user_status(self, user_id: str, status: str) -> bool:
        """
        Update the status field of a user profile.

        Args:
            user_id (str): The ID of the user.
            status (str): The new status value.

        Returns:
            bool: True if successful, False otherwise.
        """
        return await users_repo.update_user_status(
            self.executor, user_id, status, datetime_to_iso
        )

    async def update_user_profile(
        self,
        profile: UserProfile,
        *,
        change_summary: str | None = None,
        created_by_session: str | None = None,
    ) -> bool:
        """
        Update the user profile and write a history entry if prior data exists.
        """
        return await users_repo.update_user_profile(
            self.executor,
            profile,
            datetime_to_iso,
            iso_to_datetime,
            change_summary=change_summary,
            created_by_session=created_by_session,
        )


    async def get_user_profile(self, user_id: str) -> UserProfile | None:
        """
        Retrieve a user profile from the database.

        Args:
            user_id (str): The ID of the user.

        Returns:
            Optional[UserProfile]: The user profile if found, None otherwise.
        """
        return await users_repo.get_user_profile(
            self.executor, user_id, iso_to_datetime
        )

    async def list_user_profiles(self) -> list[UserProfileSummary]:
        """List user profile summaries ordered by most recent update."""
        return await users_repo.list_user_profiles(self.executor, iso_to_datetime)

    async def clear_all_data(self) -> bool:
        """
        Clear all data from all tables in the database.

        Returns:
            bool: True if successful, False otherwise.
        """
        async with self.executor.connection() as conn:
            return await self.executor.run_sync(self._sync_clear_all_data, conn)

    def _sync_clear_all_data(self, conn) -> bool:
        """Synchronous clear all data (runs in worker thread)."""
        try:
            cursor = conn.cursor()

            # Clear all tables (order matters with foreign keys).
            cursor.execute("DELETE FROM assessment_recommendations")
            cursor.execute("DELETE FROM session_enrichment_jobs")
            cursor.execute("DELETE FROM user_profile_history")
            cursor.execute("DELETE FROM patient_analysis")
            cursor.execute("DELETE FROM sessions")
            cursor.execute("DELETE FROM therapy_plans")
            cursor.execute("DELETE FROM user_profiles")

            conn.commit()
            return True

        except Exception as e:
            reraise_locked_database_error(e)
            logger.error(f"Error clearing database: {e}", exc_info=True)
            return False

    async def health_check(self) -> bool:
        """
        Perform health check on database connection.

        Returns:
            bool: True if database is healthy, False otherwise.
        """
        try:
            async with self.executor.connection() as conn:
                return await self.executor.run_sync(self._sync_health_check, conn)
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

    # ========================================================================
    # Assessment Recommendation Methods
    # ========================================================================

    async def save_assessment_recommendations(
        self,
        *,
        user_id: str,
        intake_session_block_id: str,
        recommendations: list[dict[str, Any]],
    ) -> bool:
        """Persist generated assessment recommendations for recovery."""
        return await assessment_recommendations_repo.save_assessment_recommendations(
            self.executor,
            user_id=user_id,
            intake_session_block_id=intake_session_block_id,
            recommendations=recommendations,
            datetime_to_iso=datetime_to_iso,
        )

    async def get_latest_assessment_recommendations(
        self, user_id: str
    ) -> list[dict[str, Any]] | None:
        """Fetch latest persisted assessment recommendations for a user."""
        return await assessment_recommendations_repo.get_latest_assessment_recommendations(
            self.executor, user_id
        )

    # ========================================================================
    # LLM Cache Methods
    # ========================================================================

    async def get_llm_cache_entry(self, cache_key: str) -> dict[str, Any] | None:
        """Fetch a cached LLM response by key."""
        return await llm_cache_repo.get_llm_cache_entry(self.executor, cache_key)

    async def upsert_llm_cache_entry(
        self,
        *,
        cache_key: str,
        call_type: str,
        model_name: str,
        prompt: str,
        context_json: str,
        schema_hash: str | None,
        response_json: str,
        created_at: str,
        user_id: str | None,
        session_block_id: str | None,
        source: str | None,
    ) -> None:
        """Insert or update a cached LLM response."""
        await llm_cache_repo.upsert_llm_cache_entry(
            self.executor,
            cache_key=cache_key,
            call_type=call_type,
            model_name=model_name,
            prompt=prompt,
            context_json=context_json,
            schema_hash=schema_hash,
            response_json=response_json,
            created_at=created_at,
            user_id=user_id,
            session_block_id=session_block_id,
            source=source,
        )

    async def delete_llm_cache_entry(self, cache_key: str) -> int:
        """Delete a cached LLM response by key."""
        return await llm_cache_repo.delete_llm_cache_entry(self.executor, cache_key)

    async def prune_llm_cache_before(self, cutoff_iso: str) -> int:
        """Delete cache entries older than the cutoff timestamp."""
        return await llm_cache_repo.prune_llm_cache_before(self.executor, cutoff_iso)

    async def prune_llm_cache_to_max_rows(self, max_rows: int) -> int:
        """Ensure cache contains at most max_rows entries."""
        return await llm_cache_repo.prune_llm_cache_to_max_rows(
            self.executor, max_rows
        )

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
        return await sessions_repo.get_recent_sessions(
            self.executor, user_id, limit, enriched_only, iso_to_datetime
        )

    async def update_session_reflection(
        self,
        session_id: str,
        session_summary: str | None,
        session_briefing: dict[str, Any] | None,
    ) -> bool:
        """Persist reflection summary/briefing for a session."""
        return await sessions_repo.update_session_reflection(
            self.executor,
            session_id,
            session_summary,
            session_briefing,
        )

    async def update_session_tier2(self, session_id: str, tier2_data: dict) -> bool:
        """
        Add Tier 2 enrichment to session (one-time operation).

        Args:
            session_id: Session ID to enrich
            tier2_data: Dictionary with Tier 2 fields

        Returns:
            True if successful, False otherwise
        """
        return await sessions_repo.update_session_tier2(
            self.executor, session_id, tier2_data
        )

    # ========================================================================
    # SESSION ENRICHMENT JOB QUEUE (Tier 2 async enrichment)
    # ========================================================================

    async def enqueue_session_enrichment_job(
        self, session_id: str, user_id: str
    ) -> bool:
        """Enqueue (or re-enqueue) a session for Tier 2 enrichment."""
        return await enrichment_jobs_repo.enqueue_job(
            self.executor, session_id, user_id
        )

    async def claim_next_session_enrichment_job(
        self, *, max_attempts: int = 3
    ) -> dict[str, Any] | None:
        """
        Atomically claim the next queued enrichment job.

        Returns a dict with session_id, user_id, attempts, status, or None if no job.
        """
        return await enrichment_jobs_repo.claim_next_job(
            self.executor, max_attempts
        )

    async def mark_session_enrichment_job_complete(self, session_id: str) -> bool:
        return await enrichment_jobs_repo.mark_job_complete(
            self.executor, session_id
        )

    async def mark_session_enrichment_job_failed(
        self, session_id: str, error: str
    ) -> bool:
        return await enrichment_jobs_repo.mark_job_failed(
            self.executor, session_id, error
        )

    async def get_session_count(self, user_id: str) -> int:
        """
        Get total session count for user (for milestone tracking).

        Args:
            user_id: User ID to count sessions for

        Returns:
            Number of sessions
        """
        return await sessions_repo.get_session_count(self.executor, user_id)

    # ========================================================================
    # TIER 3: Patient Analysis Methods
    # ========================================================================

    async def get_latest_patient_analysis(
        self, user_id: str
    ) -> PatientAnalysisVersion | None:
        return await patient_analysis_repo.get_latest_analysis(
            self.executor, user_id, iso_to_datetime
        )

    async def get_patient_analysis_version(
        self, user_id: str, version: int
    ) -> PatientAnalysisVersion | None:
        return await patient_analysis_repo.get_analysis_version(
            self.executor, user_id, version, iso_to_datetime
        )

    async def get_analysis_history(
        self, user_id: str
    ) -> list[PatientAnalysisVersion]:
        return await patient_analysis_repo.get_analysis_history(
            self.executor, user_id
        )

    async def save_patient_analysis_version(
        self, analysis: PatientAnalysisVersion
    ) -> bool:
        return await patient_analysis_repo.save_analysis_version(
            self.executor, analysis, datetime_to_iso
        )

    async def save_patient_analysis_version_and_supersede(
        self, analysis: PatientAnalysisVersion, supersede_analysis_id: str
    ) -> bool:
        return await patient_analysis_repo.save_analysis_version_and_supersede(
            self.executor,
            analysis,
            supersede_analysis_id,
            datetime_to_iso,
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
        analysis = PatientAnalysisVersion(
            analysis_id=analysis_id,
            user_id=user_id,
            version=1,
            analysis_data=analysis_data,
            created_at=created_at,
            created_by_session=created_by_session,
            change_summary=change_summary,
        )
        result = await patient_analysis_repo.save_next_analysis_version(
            self.executor, analysis, supersede_analysis_id, datetime_to_iso
        )
        return result

    async def mark_analysis_superseded(
        self, old_analysis_id: str, new_analysis_id: str
    ) -> bool:
        return await patient_analysis_repo.mark_analysis_superseded(
            self.executor, old_analysis_id, new_analysis_id
        )
