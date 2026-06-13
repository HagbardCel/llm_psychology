"""TrioReflectionAgent for session analysis and plan updates."""

from __future__ import annotations

import logging
from typing import Any

import trio

from psychoanalyst_app.agents.memory.agent import TrioMemoryAgent
from psychoanalyst_app.agents.planning.agent import TrioPlanningAgent
from psychoanalyst_app.agents.reflection.insights_pipeline import (
    gather_therapeutic_insights,
    generate_comprehensive_reflection_data,
)
from psychoanalyst_app.agents.reflection.session_summary import (
    build_plan_snapshot,
    format_reflection_summary,
    generate_session_briefing,
    generate_session_summary_payload,
)
from psychoanalyst_app.agents.reflection.tier2_pipeline import (
    ensure_recent_sessions_enriched,
)
from psychoanalyst_app.config import Settings
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.exceptions import ReflectionError
from psychoanalyst_app.models.domain import (
    Session,
    TherapyPlan,
)
from psychoanalyst_app.models.llm_outputs import (
    StructuredTherapyPlanOutput,
    StructuredUserProfileOutput,
)
from psychoanalyst_app.orchestration.agent_output_validators import (
    build_therapy_plan_output,
)
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
    WorkflowEvent,
)
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag import RAGServiceProtocol
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioReflectionAgent:
    """Trio-native coordination agent for therapeutic reflection and planning."""

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGServiceProtocol,
        user_context: UserContext,
        memory_agent: TrioMemoryAgent,
        planning_agent: TrioPlanningAgent,
        config: Settings,
    ):
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.memory_agent = memory_agent
        self.planning_agent = planning_agent
        self.config = config

        logger.info(f"TrioReflectionAgent initialized for user {user_context.user_id}")

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """Process a message during the reflection phase."""
        session = Session(
            session_id=context.session_id,
            user_id=context.user_profile.user_id,
            plan_id=context.therapy_plan.plan_id if context.therapy_plan else None,
            timestamp=context.session_start_time,
            transcript=context.message_history,
            topics=[],
        )

        return await self.process_reflection(session, context)

    async def process_reflection(
        self, session: Session, context: ConversationContext
    ) -> AgentResponse:
        """Process reflection on completed therapy session (orchestrator interface)."""
        logger.info(f"Processing reflection for session {session.session_id}")

        current_plan = context.therapy_plan
        plan_output = await self.update_plan(session, current_plan)
        updated_plan = build_plan_snapshot(
            current_plan,
            plan_output,
            user_id=self.user_context.user_id,
        )

        (
            reflection,
            tier1_profile_output,
            tier2_enrichment,
            tier3_update,
        ) = await self.generate_comprehensive_reflection(session, updated_plan)

        session_briefing = await generate_session_briefing(
            self.llm_service,
            self.config,
            reflection["session_context"],
            reflection["therapeutic_memory"],
            reflection.get("plan_assessment"),
            session,
            updated_plan,
        )

        if session_briefing:
            updated_plan.session_briefing = session_briefing

            logger.info(
                "Successfully generated session briefing for session %s",
                session.session_id,
            )
        else:
            logger.warning(
                "Session briefing generation returned None for session %s",
                session.session_id,
            )

        therapy_plan_payload = build_therapy_plan_output(
            {
                "selected_therapy_style": updated_plan.selected_therapy_style,
                "focus": updated_plan.focus,
                "themes": updated_plan.themes,
                "timeline": updated_plan.timeline,
                "initial_goals": updated_plan.initial_goals,
                "current_progress": updated_plan.current_progress,
                "planned_interventions": updated_plan.planned_interventions,
                "revision_recommendations": updated_plan.revision_recommendations,
                "status": updated_plan.status,
            }
        )
        plan_revision_required = not _is_noop_plan_snapshot(
            current_plan,
            updated_plan,
        )
        effective_plan_id = (
            current_plan.plan_id
            if current_plan is not None and not plan_revision_required
            else updated_plan.plan_id
        )
        effective_plan_version = (
            current_plan.version
            if current_plan is not None and not plan_revision_required
            else current_plan.version + 1
            if current_plan is not None
            else updated_plan.version
        )

        content = format_reflection_summary(reflection)

        return AgentResponse(
            content=content,
            next_action="transition",
            workflow_event=WorkflowEvent.COMPLETE_REFLECTION,
            metadata={
                "plan_id": effective_plan_id,
                "plan_version": effective_plan_version,
                "session_id": session.session_id,
                "reflection": reflection,
                "has_briefing": updated_plan.session_briefing is not None,
                "therapy_plan_output": therapy_plan_payload,
                "session_briefing": session_briefing,
                "plan_revision_required": plan_revision_required,
                "session_briefing_generated": session_briefing is not None,
                "plan_update_applied": plan_revision_required,
                "user_profile": tier1_profile_output,
                "tier2_enrichment": tier2_enrichment,
                "tier3_update": tier3_update,
            },
        )

    async def create_initial_plan(
        self, intake_session: Session, selected_style: str | None = None
    ) -> StructuredTherapyPlanOutput:
        """Coordinate initial therapy plan creation using specialized agents."""
        logger.info(
            "Coordinating initial plan creation for user %s",
            self.user_context.user_id,
        )

        try:
            plan_output = await self.planning_agent.create_initial_plan(
                intake_session, selected_style
            )

            logger.info(
                "Initial therapy plan output created for %s",
                self.user_context.user_id,
            )
            return plan_output

        except Exception as exc:
            logger.error(
                f"Failed to coordinate initial plan creation: {exc}", exc_info=True
            )
            raise ReflectionError(f"Initial plan creation failed: {exc}") from exc

    async def create_initial_plan_with_style(
        self, intake_session: Session, selected_style: str
    ) -> StructuredTherapyPlanOutput:
        """Create initial therapy plan with specific style."""
        logger.info(
            "Creating initial %s therapy plan",
            selected_style.upper(),
        )
        return await self.create_initial_plan(intake_session, selected_style)

    async def update_plan(
        self, session: Session, current_plan: TherapyPlan | None = None
    ) -> StructuredTherapyPlanOutput:
        """Coordinate therapy plan updates using specialized agents."""
        logger.info(
            "Coordinating plan update for user %s",
            self.user_context.user_id,
        )

        try:
            if current_plan is None:
                current_plan = await self.db_service.get_current_therapy_plan(
                    self.user_context.user_id
                )

                if current_plan is None:
                    logger.warning(
                        "No existing plan found; creating initial plan from session."
                    )
                    return await self.planning_agent.create_initial_plan(session)

            updated_plan_output = await self.planning_agent.update_plan(
                session, current_plan
            )

            logger.info(
                "Therapy plan update prepared for %s", self.user_context.user_id
            )
            return updated_plan_output

        except Exception as exc:
            logger.error(f"Failed to coordinate plan update: {exc}", exc_info=True)
            raise ReflectionError(f"Plan update failed: {exc}") from exc

    async def generate_comprehensive_reflection(
        self, session: Session, current_plan: TherapyPlan | None = None
    ) -> tuple[
        dict[str, Any],
        StructuredUserProfileOutput | None,
        dict[str, Any] | None,
        dict[str, Any] | None,
    ]:
        """Generate reflection from memory analysis and planning insights."""
        logger.info(
            "Generating comprehensive reflection for session %s",
            session.session_id,
        )

        try:
            return await generate_comprehensive_reflection_data(
                db_service=self.db_service,
                llm_service=self.llm_service,
                memory_agent=self.memory_agent,
                planning_agent=self.planning_agent,
                user_id=self.user_context.user_id,
                session=session,
                current_plan=current_plan,
            )

        except Exception as exc:
            logger.error(
                f"Failed to generate comprehensive reflection: {exc}", exc_info=True
            )
            raise ReflectionError(f"Reflection generation failed: {exc}") from exc

    async def generate_session_summary(self, session: Session) -> dict[str, Any]:
        """Generate a simple session summary (backwards compatibility)."""
        return await generate_session_summary_payload(self.llm_service, session)

    async def get_therapeutic_insights(self) -> dict[str, Any]:
        """Get comprehensive therapeutic insights across all sessions."""
        return await gather_therapeutic_insights(
            db_service=self.db_service,
            memory_agent=self.memory_agent,
            planning_agent=self.planning_agent,
            user_id=self.user_context.user_id,
        )

    async def ensure_recent_sessions_enriched(
        self, user_id: str, *, limit: int = 5, scan_limit: int | None = None
    ) -> list[Session]:
        """Ensure recent sessions have Tier 2 enrichment on demand."""
        return await ensure_recent_sessions_enriched(
            self.db_service,
            self.llm_service,
            user_id,
            limit=limit,
            scan_limit=scan_limit,
        )

    async def health_check(self) -> bool:
        """Perform health check on the reflection agent and its dependencies."""
        try:
            if not await self.memory_agent.health_check():
                logger.error("TrioMemoryAgent health check failed")
                return False

            if not await self.planning_agent.health_check():
                logger.error("TrioPlanningAgent health check failed")
                return False

            test_prompt = "Respond with 'OK' if you can process this request."
            response = await trio.to_thread.run_sync(
                self.llm_service.generate_response, test_prompt
            )
            if "OK" not in response and "ok" not in response.lower():
                logger.error("LLM service health check failed")
                return False

            return True

        except Exception as exc:
            logger.error(f"TrioReflectionAgent health check failed: {exc}")
            return False

    def __str__(self) -> str:
        return f"TrioReflectionAgent(user={self.user_context.user_id}, coordinator)"

    def __repr__(self) -> str:
        return (
            f"TrioReflectionAgent(user='{self.user_context.user_id}', "
            f"memory_agent={type(self.memory_agent).__name__}, "
            f"planning_agent={type(self.planning_agent).__name__})"
        )


def _is_noop_plan_snapshot(
    current_plan: TherapyPlan | None,
    updated_plan: TherapyPlan,
) -> bool:
    if current_plan is None:
        return False
    return (
        updated_plan.selected_therapy_style == current_plan.selected_therapy_style
        and updated_plan.focus == current_plan.focus
        and updated_plan.themes == current_plan.themes
        and updated_plan.timeline == current_plan.timeline
        and updated_plan.initial_goals == current_plan.initial_goals
        and updated_plan.current_progress == current_plan.current_progress
        and updated_plan.planned_interventions == current_plan.planned_interventions
        and updated_plan.revision_recommendations
        == current_plan.revision_recommendations
        and updated_plan.status == current_plan.status
    )
