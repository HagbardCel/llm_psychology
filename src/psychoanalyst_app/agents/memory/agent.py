"""TrioMemoryAgent: Trio-native specialized agent for managing session context."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import trio

from psychoanalyst_app.agents.memory.analysis import (
    analyze_emotional_patterns,
    analyze_progress_patterns,
    analyze_theme_patterns,
    assess_relationship_quality,
    format_knowledge,
    generate_context_summary,
)
from psychoanalyst_app.agents.memory.models import SessionContext, TherapeuticMemory
from psychoanalyst_app.agents.memory.prompts import build_session_context_prompt
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.exceptions import MemoryError
from psychoanalyst_app.models.domain import Session
from psychoanalyst_app.models.llm_outputs import SessionAnalysis
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.llm_phases import MEMORY_ANALYSIS
from psychoanalyst_app.services.rag import RAGServiceProtocol
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioMemoryAgent:
    """Agent for therapeutic memory and session context."""

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGServiceProtocol,
        user_context: UserContext,
    ):
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context

        self._memory_cache: TherapeuticMemory | None = None
        self._cache_timestamp: datetime | None = None
        self._session_context_cache: dict[str, tuple[str, SessionContext]] = {}

        logger.info(f"TrioMemoryAgent initialized for user {user_context.user_id}")

    async def analyze_session_context(self, session: Session) -> SessionContext:
        """Analyze a session to extract key contextual information."""
        logger.debug(f"Analyzing session context for {session.session_id}")

        try:
            session_text = "\n".join(
                [f"{msg.role}: {msg.content}" for msg in session.transcript]
            )

            cached = self._session_context_cache.get(session.session_id)
            if cached and cached[0] == session_text:
                logger.debug(
                    "Returning cached session context for %s", session.session_id
                )
                return cached[1]

            relevant_knowledge = await trio.to_thread.run_sync(
                self.rag_service.retrieve_relevant_knowledge,
                session_text,
                2,
            )

            analysis_prompt = build_session_context_prompt(
                session_text=session_text,
                knowledge_context=format_knowledge(relevant_knowledge),
            )

            analysis = await self.llm_service.generate_structured_output_async(
                analysis_prompt,
                SessionAnalysis,
                method="json_schema",
                phase=MEMORY_ANALYSIS,
            )
            if not isinstance(analysis, SessionAnalysis):
                raise MemoryError("Session analysis returned unexpected type")

            context = SessionContext(
                session_id=session.session_id,
                key_themes=analysis.key_themes,
                emotional_state=analysis.emotional_state,
                insights=analysis.insights,
                progress_indicators=analysis.progress_indicators,
            )
            self._session_context_cache[session.session_id] = (session_text, context)

            logger.info(f"Session context analyzed for {session.session_id}")
            return context

        except Exception as exc:
            logger.error(f"Failed to analyze session context: {exc}", exc_info=True)
            raise MemoryError(f"Session context analysis failed: {exc}") from exc

    async def get_therapeutic_memory(self, refresh: bool = False) -> TherapeuticMemory:
        """Get comprehensive therapeutic memory for the user."""
        cache_valid = (
            self._memory_cache is not None
            and self._cache_timestamp is not None
            and not refresh
            and (datetime.now() - self._cache_timestamp) < timedelta(hours=1)
        )

        if cache_valid:
            logger.debug("Returning cached therapeutic memory")
            return self._memory_cache

        logger.debug("Building therapeutic memory from sessions")

        try:
            sessions = await self.db_service.get_all_sessions_for_user(
                self.user_context.user_id
            )

            memory = TherapeuticMemory(self.user_context.user_id)

            for session in sessions:
                try:
                    context = await self.analyze_session_context(session)
                    memory.add_session_context(context)
                except Exception as exc:
                    logger.warning(
                        f"Failed to analyze session {session.session_id}: {exc}"
                    )
                    continue

            memory.relationship_quality = assess_relationship_quality(sessions)

            self._memory_cache = memory
            self._cache_timestamp = datetime.now()

            logger.info(
                f"Therapeutic memory built with {len(memory.session_contexts)} sessions"
            )
            return memory

        except Exception as exc:
            logger.error(f"Failed to build therapeutic memory: {exc}", exc_info=True)
            raise MemoryError(f"Therapeutic memory building failed: {exc}") from exc

    async def get_recent_context(self, num_sessions: int = 3) -> dict[str, Any]:
        """Get context from recent sessions for immediate therapy planning."""
        logger.debug(f"Getting context from {num_sessions} recent sessions")

        try:
            all_sessions = await self.db_service.get_all_sessions_for_user(
                self.user_context.user_id
            )
            recent_sessions = all_sessions[-num_sessions:] if all_sessions else []

            if not recent_sessions:
                return {
                    "sessions": [],
                    "themes": [],
                    "emotional_progression": [],
                    "insights": [],
                    "context_summary": "No recent sessions available",
                }

            contexts = []
            all_themes: list[str] = []
            emotional_states: list[str] = []
            all_insights: list[str] = []

            for session in recent_sessions:
                try:
                    context = await self.analyze_session_context(session)
                    contexts.append(
                        {
                            "session_id": context.session_id,
                            "themes": context.key_themes,
                            "emotional_state": context.emotional_state,
                            "insights": context.insights,
                        }
                    )
                    all_themes.extend(context.key_themes)
                    emotional_states.append(context.emotional_state)
                    all_insights.extend(context.insights)

                except Exception as exc:
                    logger.warning(
                        f"Failed to analyze recent session {session.session_id}: {exc}"
                    )
                    continue

            summary = generate_context_summary(
                all_themes, emotional_states, all_insights
            )

            return {
                "sessions": contexts,
                "themes": list(set(all_themes)),
                "emotional_progression": emotional_states,
                "insights": all_insights,
                "context_summary": summary,
            }

        except Exception as exc:
            logger.error(f"Failed to get recent context: {exc}", exc_info=True)
            raise MemoryError(f"Recent context retrieval failed: {exc}") from exc

    async def identify_patterns(self) -> dict[str, Any]:
        """Identify patterns and trends across all sessions."""
        logger.debug("Identifying therapeutic patterns")

        try:
            memory = await self.get_therapeutic_memory()

            theme_patterns = analyze_theme_patterns(memory.recurring_themes)
            emotional_patterns = analyze_emotional_patterns(memory.emotional_patterns)
            progress_patterns = analyze_progress_patterns(memory.progress_timeline)

            return {
                "theme_patterns": theme_patterns,
                "emotional_patterns": emotional_patterns,
                "progress_patterns": progress_patterns,
                "relationship_quality": memory.relationship_quality,
                "total_sessions": len(memory.session_contexts),
            }

        except Exception as exc:
            logger.error(f"Failed to identify patterns: {exc}", exc_info=True)
            raise MemoryError(f"Pattern identification failed: {exc}") from exc

    async def get_continuity_context(self, current_session_topics: list[str]) -> str:
        """Get context for maintaining continuity with current session."""
        logger.debug("Getting continuity context")

        try:
            memory = await self.get_therapeutic_memory()
            recent_context = await self.get_recent_context(num_sessions=2)

            related_themes = []
            for topic in current_session_topics:
                for theme, count in memory.recurring_themes.items():
                    if topic.lower() in theme.lower() or theme.lower() in topic.lower():
                        related_themes.append(f"{theme} (mentioned {count} times)")

            context_parts = []

            if related_themes:
                context_parts.append(
                    "Related themes from previous sessions: "
                    + ", ".join(related_themes)
                )

            if recent_context["emotional_progression"]:
                recent_emotions = recent_context["emotional_progression"][-2:]
                context_parts.append(
                    f"Recent emotional states: {' → '.join(recent_emotions)}"
                )

            if recent_context["insights"]:
                recent_insights = recent_context["insights"][-2:]
                context_parts.append(f"Recent insights: {'; '.join(recent_insights)}")

            if memory.relationship_quality:
                context_parts.append(
                    f"Therapeutic relationship: {memory.relationship_quality}"
                )

            return (
                " | ".join(context_parts)
                if context_parts
                else "Starting fresh session context"
            )

        except Exception as exc:
            logger.error(f"Failed to get continuity context: {exc}", exc_info=True)
            return "Context unavailable due to error"

    async def health_check(self) -> bool:
        """Perform health check on the memory agent."""
        try:
            sessions = await self.db_service.get_all_sessions_for_user(
                self.user_context.user_id
            )

            if sessions:
                test_prompt = "Respond with 'OK' if you can process this request."
                response = await trio.to_thread.run_sync(
                    self.llm_service.generate_response, test_prompt
                )
                return "OK" in response or "ok" in response.lower()

            return True

        except Exception as exc:
            logger.error(f"TrioMemoryAgent health check failed: {exc}")
            return False

    def __str__(self) -> str:
        return f"TrioMemoryAgent(user={self.user_context.user_id})"

    def __repr__(self) -> str:
        cache_status = "cached" if self._memory_cache else "not_cached"
        return (
            f"TrioMemoryAgent(user='{self.user_context.user_id}', cache={cache_status})"
        )
