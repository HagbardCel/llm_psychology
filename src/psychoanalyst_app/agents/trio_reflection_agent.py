"""
TrioReflectionAgent: Trio-native agent for analyzing therapy sessions and updating plans.

This agent coordinates memory and planning functionality to provide
comprehensive therapy session analysis and plan management.

Pure Trio implementation using structured concurrency.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.agents.reflection.helpers import (
    maybe_update_tier1_profile,
)
from psychoanalyst_app.agents.reflection.session_summary_pipeline import (
    generate_session_briefing,
    generate_session_summary_payload,
)
from psychoanalyst_app.agents.reflection.tier2_pipeline import (
    apply_tier2_enrichment,
    enrich_session_tier2,
    ensure_recent_sessions_enriched,
    load_or_enrich_session_record,
)
from psychoanalyst_app.agents.reflection.tier3_pipeline import (
    evaluate_tier3_update_necessity,
    generate_updated_tier3_analysis,
    prepare_tier3_update_payload,
)
from psychoanalyst_app.agents.reflection.tier4_pipeline import (
    apply_tier4_updates,
    generate_combined_recommendations,
)
from psychoanalyst_app.agents.trio_memory_agent import TrioMemoryAgent
from psychoanalyst_app.agents.trio_planning_agent import TrioPlanningAgent
from psychoanalyst_app.config import Settings
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.exceptions import ReflectionError
from psychoanalyst_app.models.data_models import (
    AnalyticOrientation,
    CurrentFocus,
    DefensiveOrganization,
    DetailedSession,
    PatientAnalysis,
    PatientAnalysisVersion,
    RecurringNarrative,
    Session,
    TherapyPlan,
    TransferenceImpressions,
)
from psychoanalyst_app.models.structured_output_models import (
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
from psychoanalyst_app.services.rag_service import RAGService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioReflectionAgent:
    """
    Trio-native coordination agent for therapeutic reflection and planning.

    This agent has two modes:
    1. Legacy mode: Direct method calls (for backward compatibility)
    2. Orchestrator mode: Returns AgentResponse for orchestration layer

    Uses Trio's structured concurrency for all async operations.
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGService,
        user_context: UserContext,
        memory_agent: TrioMemoryAgent,
        planning_agent: TrioPlanningAgent,
        config: Settings,
    ):
        """
        Initialize the Trio Reflection Agent.

        Args:
            llm_service: The LLM service for generating responses (synchronous)
            db_service: The Trio database service for storing plans
            rag_service: The RAG service for retrieving domain knowledge (synchronous)
            user_context: User context for this reflection session
            memory_agent: Trio memory agent for session context analysis
            planning_agent: Trio planning agent for therapy plan management
            config: Application settings
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.memory_agent = memory_agent
        self.planning_agent = planning_agent
        self.config = config

        logger.info(f"TrioReflectionAgent initialized for user {user_context.user_id}")

    # ===== NEW ORCHESTRATOR INTERFACE =====

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """
        Process a message during the reflection phase.

        In the reflection phase, we typically ignore the user's message
        and instead process the completed session to generate a summary.

        Args:
            message: User's message (ignored)
            context: Conversation context

        Returns:
            AgentResponse with reflection summary
        """
        # Reconstruct session from context
        session = Session(
            session_id=context.session_id,
            user_id=context.user_profile.user_id,
            plan_id=context.therapy_plan.plan_id if context.therapy_plan else None,
            timestamp=context.session_start_time,
            transcript=context.message_history,
            topics=[],  # Topics are tracked in context but Session expects list[Topic]
        )

        # Delegate to process_reflection
        return await self.process_reflection(session, context)

    async def process_reflection(
        self, session: Session, context: ConversationContext
    ) -> AgentResponse:
        """
        Process reflection on completed therapy session using Trio (orchestrator interface).

        This is the interface for use with the orchestration layer.
        It produces updated plan output and returns summary information.

        Args:
            session: Completed therapy session
            context: Conversation context

        Returns:
            AgentResponse with reflection summary

        Raises:
            Exception: Any errors during reflection processing (fail-fast behavior)
        """
        logger.info(f"Processing reflection for session {session.session_id}")

        # Update therapy plan (structured output only)
        current_plan = context.therapy_plan
        plan_output = await self.update_plan(session, current_plan)
        is_noop_update = self._is_noop_plan_update(current_plan, plan_output)
        updated_plan = self._build_plan_snapshot(current_plan, plan_output)

        # Generate comprehensive reflection (includes memory and planning analysis)
        (
            reflection,
            tier1_profile_output,
            tier2_enrichment,
            tier3_update,
        ) = await self.generate_comprehensive_reflection(session, updated_plan)

        # Generate session briefing for next session resumption
        # This is critical for session resumption feature
        session_briefing = await self._generate_session_briefing(
            session_context=reflection["session_context"],
            therapeutic_memory=reflection["therapeutic_memory"],
            plan_assessment=reflection.get("plan_assessment"),
            session=session,
            therapy_plan=updated_plan,
        )

        if session_briefing:
            # Update therapy plan with the new briefing
            updated_plan.session_briefing = session_briefing

            # Optional: Apply Tier 4 updates from the same structured LLM output
            tier4_update = (
                session_briefing.get("tier4_update")
                if isinstance(session_briefing, dict)
                else None
            )
            if isinstance(tier4_update, dict) and updated_plan:
                should_update = bool(tier4_update.get("should_update", False))
                if should_update:
                    if "current_progress" in tier4_update and isinstance(
                        tier4_update["current_progress"], str
                    ):
                        updated_plan.current_progress = tier4_update["current_progress"]
                    if "planned_interventions" in tier4_update and isinstance(
                        tier4_update["planned_interventions"], list
                    ):
                        updated_plan.planned_interventions = tier4_update[
                            "planned_interventions"
                        ]
                    if "status" in tier4_update and isinstance(
                        tier4_update["status"], str
                    ):
                        updated_plan.status = tier4_update["status"]
                    updated_plan.updated_at = datetime.now()

            logger.info(
                "Successfully generated session briefing for session %s",
                session.session_id,
            )
        else:
            logger.warning(
                f"Session briefing generation returned None for session {session.session_id}"
            )

        therapy_plan_payload = build_therapy_plan_output(
            {
                "selected_therapy_style": updated_plan.selected_therapy_style,
                "plan_details": updated_plan.plan_details,
                "initial_goals": updated_plan.initial_goals,
                "current_progress": updated_plan.current_progress,
                "planned_interventions": updated_plan.planned_interventions,
                "status": updated_plan.status,
            }
        )
        should_persist_plan = (not is_noop_update) or (session_briefing is not None)

        # Build response content
        content = self._format_reflection_summary(reflection)

        return AgentResponse(
            content=content,
            next_action="transition",
            workflow_event=WorkflowEvent.COMPLETE_REFLECTION,
            metadata={
                "plan_id": updated_plan.plan_id,
                "plan_version": updated_plan.version,
                "session_id": session.session_id,
                "reflection": reflection,
                "has_briefing": updated_plan.session_briefing is not None,
                "therapy_plan_output": therapy_plan_payload,
                "session_briefing": session_briefing,
                "plan_update_applied": should_persist_plan,
                "user_profile": tier1_profile_output,
                "tier2_enrichment": tier2_enrichment,
                "tier3_update": tier3_update,
            },
        )

    def _build_plan_snapshot(
        self,
        current_plan: TherapyPlan | None,
        plan_output: StructuredTherapyPlanOutput,
    ) -> TherapyPlan:
        """Build an in-memory plan snapshot from structured output."""
        if current_plan:
            is_noop_update = self._is_noop_plan_update(current_plan, plan_output)
            plan_id = current_plan.plan_id
            created_at = current_plan.created_at
            version = (
                current_plan.version if is_noop_update else current_plan.version + 1
            )
            session_briefing = current_plan.session_briefing
            selected_style = (
                plan_output.selected_therapy_style
                or current_plan.selected_therapy_style
            )
        else:
            plan_id = f"pending_{uuid.uuid4().hex[:12]}"
            created_at = datetime.now()
            version = 1
            session_briefing = None
            selected_style = plan_output.selected_therapy_style

        return TherapyPlan(
            plan_id=plan_id,
            user_id=self.user_context.user_id,
            created_at=created_at,
            updated_at=datetime.now(),
            version=version,
            selected_therapy_style=selected_style,
            plan_details=plan_output.plan_details,
            initial_goals=plan_output.initial_goals,
            current_progress=plan_output.current_progress,
            planned_interventions=plan_output.planned_interventions,
            status=plan_output.status,
            session_briefing=session_briefing,
        )

    @staticmethod
    def _is_noop_plan_update(
        current_plan: TherapyPlan | None,
        plan_output: StructuredTherapyPlanOutput,
    ) -> bool:
        if not current_plan:
            return False
        return (
            plan_output.selected_therapy_style == current_plan.selected_therapy_style
            and plan_output.plan_details == current_plan.plan_details
            and plan_output.initial_goals == current_plan.initial_goals
            and plan_output.current_progress == current_plan.current_progress
            and plan_output.planned_interventions == current_plan.planned_interventions
            and plan_output.status == current_plan.status
        )

    def _format_reflection_summary(self, reflection: dict[str, Any]) -> str:
        """
        Format reflection data into a readable summary.

        Args:
            reflection: Reflection data dictionary

        Returns:
            Formatted summary string
        """
        summary_parts = []

        # Session context
        if "session_context" in reflection:
            ctx = reflection["session_context"]
            summary_parts.append("## Session Reflection\n")
            summary_parts.append(f"Key themes: {', '.join(ctx.get('key_themes', []))}")
            summary_parts.append(
                f"Emotional state: {ctx.get('emotional_state', 'N/A')}"
            )

        # Memory insights
        if "therapeutic_memory" in reflection:
            mem = reflection["therapeutic_memory"]
            summary_parts.append("\n## Progress Overview")
            summary_parts.append(f"Total sessions: {mem.get('total_sessions', 0)}")
            summary_parts.append(
                f"Relationship quality: {mem.get('relationship_quality', 'developing')}"
            )

        # Plan recommendations
        if "plan_recommendations" in reflection and reflection["plan_recommendations"]:
            summary_parts.append("\n## Recommendations")
            for rec in reflection["plan_recommendations"][:3]:
                summary_parts.append(f"- {rec.get('description', '')}")

        return "\n".join(summary_parts)

    # ===== LEGACY INTERFACE (for backward compatibility) =====

    async def create_initial_plan(
        self, intake_session: Session, selected_style: str | None = None
    ) -> StructuredTherapyPlanOutput:
        """
        Coordinate initial therapy plan creation using specialized agents with Trio.

        Args:
            intake_session: The completed intake session
            selected_style: Optional therapy style preference

        Returns:
            StructuredTherapyPlanOutput: The structured plan payload (no persistence)

        Raises:
            ReflectionError: If plan creation fails
        """
        logger.info(
            f"TrioReflectionAgent: Coordinating initial plan creation for user {self.user_context.user_id}"
        )

        try:
            # Use planning agent to create comprehensive initial plan
            plan_output = await self.planning_agent.create_initial_plan(
                intake_session, selected_style
            )

            logger.info(
                "Initial therapy plan output created for %s",
                self.user_context.user_id,
            )
            return plan_output

        except Exception as e:
            logger.error(
                f"Failed to coordinate initial plan creation: {e}", exc_info=True
            )
            raise ReflectionError(f"Initial plan creation failed: {e}")

    async def create_initial_plan_with_style(
        self, intake_session: Session, selected_style: str
    ) -> StructuredTherapyPlanOutput:
        """
        Create initial therapy plan with specific style using Trio (delegates to create_initial_plan).

        Args:
            intake_session: The completed intake session
            selected_style: The selected therapy style

        Returns:
            StructuredTherapyPlanOutput: The structured plan payload (no persistence)
        """
        logger.info(
            f"TrioReflectionAgent: Creating initial {selected_style.upper()} therapy plan"
        )
        return await self.create_initial_plan(intake_session, selected_style)

    async def update_plan(
        self, session: Session, current_plan: TherapyPlan | None = None
    ) -> StructuredTherapyPlanOutput:
        """
        Coordinate therapy plan updates using specialized agents with Trio.

        Args:
            session: The completed therapy session
            current_plan: The current therapy plan (if None, retrieves latest)

        Returns:
            StructuredTherapyPlanOutput: Updated plan payload (no persistence)

        Raises:
            ReflectionError: If plan update fails
        """
        logger.info(
            f"TrioReflectionAgent: Coordinating plan update for user {self.user_context.user_id}"
        )

        try:
            # Get current plan if not provided
            if current_plan is None:
                current_plan = await self.db_service.get_latest_therapy_plan(
                    self.user_context.user_id
                )

                if current_plan is None:
                    logger.warning(
                        "No existing plan found. Creating initial plan based on session."
                    )
                    return await self.planning_agent.create_initial_plan(session)

            # Use planning agent to update plan
            updated_plan_output = await self.planning_agent.update_plan(
                session, current_plan
            )

            logger.info(
                "Therapy plan update prepared for %s", self.user_context.user_id
            )
            return updated_plan_output

        except Exception as e:
            logger.error(f"Failed to coordinate plan update: {e}", exc_info=True)
            raise ReflectionError(f"Plan update failed: {e}")

    async def generate_comprehensive_reflection(
        self, session: Session, current_plan: TherapyPlan | None = None
    ) -> tuple[
        dict[str, Any],
        StructuredUserProfileOutput | None,
        dict[str, Any] | None,
        dict[str, Any] | None,
    ]:
        """
        Generate comprehensive reflection combining memory analysis and planning insights using Trio.

        Args:
            session: The session to reflect on
            current_plan: Optional current therapy plan

        Returns:
            Tuple containing reflection analysis, Tier 1 profile updates, Tier 2 enrichment,
            and Tier 3 update payloads.

        Raises:
            ReflectionError: If reflection generation fails
        """
        logger.info(
            f"TrioReflectionAgent: Generating comprehensive reflection for session {session.session_id}"
        )

        try:
            # Analyze session context using memory agent (FIXED: added await)
            session_context = await self.memory_agent.analyze_session_context(session)

            # Get therapeutic memory and patterns (FIXED: added await)
            memory = await self.memory_agent.get_therapeutic_memory()
            patterns = await self.memory_agent.identify_patterns()

            # Get continuity context (FIXED: added await)
            continuity_context = await self.memory_agent.get_continuity_context(
                [topic.name for topic in session.topics]
            )

            session_record, tier2_enrichment = await load_or_enrich_session_record(
                self.db_service,
                self.llm_service,
                session,
            )

            # Tier 1: rare background updates (LLM-gated)
            tier1_profile_output = None
            current_profile = await self.db_service.get_user_profile(
                self.user_context.user_id
            )
            if current_profile:
                tier1_profile_output = await maybe_update_tier1_profile(
                    self.llm_service, current_profile, session_record
                )

            (
                tier3_updated,
                tier3_version,
                tier3_update,
                tier3_change_summary,
            ) = await prepare_tier3_update_payload(
                self.db_service,
                self.llm_service,
                self.user_context.user_id,
                session_record,
            )

            # Assess plan effectiveness if plan exists (FIXED: added await)
            plan_assessment = None
            plan_recommendations = []

            if current_plan:
                plan_assessment = await self.planning_agent.assess_plan_effectiveness(
                    current_plan
                )
                plan_recommendations = (
                    await self.planning_agent.recommend_plan_adjustments(current_plan)
                )
            tier4_updated = False
            session_summary_payload = await generate_session_summary_payload(
                self.llm_service, session_record
            )
            session_summary = session_summary_payload["summary"]
            if current_plan:
                tier4_updated = await apply_tier4_updates(
                    self.db_service,
                    self.planning_agent,
                    self.user_context.user_id,
                    current_plan,
                    session_context,
                    plan_assessment,
                    plan_recommendations,
                    session_summary,
                    tier3_updated,
                )

            # Compile comprehensive reflection
            reflection = {
                "session_id": session.session_id,
                "timestamp": session.timestamp.isoformat(),
                "user_id": self.user_context.user_id,
                # Memory analysis
                "session_context": {
                    "key_themes": session_context.key_themes,
                    "emotional_state": session_context.emotional_state,
                    "insights": session_context.insights,
                    "progress_indicators": session_context.progress_indicators,
                },
                "therapeutic_memory": {
                    "total_sessions": len(memory.session_contexts),
                    "relationship_quality": memory.relationship_quality,
                    "dominant_themes": list(memory.recurring_themes.keys())[:5],
                    "emotional_progression": (
                        memory.emotional_patterns[-5:]
                        if memory.emotional_patterns
                        else []
                    ),
                },
                "patterns": patterns,
                "continuity_context": continuity_context,
                # Planning analysis
                "plan_assessment": plan_assessment,
                "plan_recommendations": plan_recommendations,
                # Traditional summary
                "session_summary": session_summary,
                # Metadata
                "reflection_generated_at": datetime.now().isoformat(),
                "agents_used": [
                    "TrioMemoryAgent",
                    "TrioPlanningAgent",
                    "TrioReflectionAgent",
                ],
                # Tier updates (Phase 3-5)
                "tier3_updated": tier3_updated,
                "tier3_version": tier3_version,
                "tier3_change_summary": tier3_change_summary,
                "tier4_updated": tier4_updated,
                "tier1_updated": bool(tier1_profile_output),
            }

            logger.info(
                f"Comprehensive reflection generated for session {session.session_id}"
            )
            return (
                reflection,
                tier1_profile_output,
                tier2_enrichment,
                tier3_update,
            )

        except Exception as e:
            logger.error(
                f"Failed to generate comprehensive reflection: {e}", exc_info=True
            )
            raise ReflectionError(f"Reflection generation failed: {e}")

    async def generate_session_summary(self, session: Session) -> dict[str, Any]:
        """
        Generate a simple session summary using Trio (backwards compatibility).

        Args:
            session: The session to summarize

        Returns:
            Dict containing session summary
        """
        return await generate_session_summary_payload(self.llm_service, session)

    async def _enrich_session(self, session: Session) -> dict[str, Any] | None:
        """
        Enrich session with Tier 2 psychological data using LLM.

        Extracts psychological summary, dominant affects, key themes,
        notable interactions, interpretations, and patient reactions
        from the session transcript.

        Args:
            session: The session to enrich

        Returns:
            Tier 2 enrichment payload, or None when enrichment fails
        """
        return await enrich_session_tier2(self.llm_service, session)

    def _apply_tier2_enrichment(
        self, session: Session, tier2_data: dict[str, Any]
    ) -> Session:
        """Apply Tier 2 enrichment to a session object without persistence."""
        return apply_tier2_enrichment(session, tier2_data)

    async def _generate_session_briefing(
        self,
        session_context: dict[str, Any],
        therapeutic_memory: dict[str, Any],
        plan_assessment: dict[str, Any] | None,
        session: Session,
        therapy_plan: TherapyPlan | None,
    ) -> dict[str, Any] | None:
        """
        Generate a comprehensive session briefing for the next therapy session.

        This performs a deep analysis of the completed session and generates a rich
        briefing object that will be used by the Psychoanalyst Agent when starting
        the next session.

        Args:
            session_context: Key themes, emotional state, and insights from the session
            therapeutic_memory: Aggregated memory across all sessions
            plan_assessment: Assessment of therapy plan effectiveness
            session: The completed session
            therapy_plan: Current therapy plan

        Returns:
            Dict containing validated session briefing, or None if generation fails

        Raises:
            Exception: Propagates LLM and validation errors (fail-fast)
        """
        return await generate_session_briefing(
            self.llm_service,
            self.config,
            session_context,
            therapeutic_memory,
            plan_assessment,
            session,
            therapy_plan,
        )

    async def get_therapeutic_insights(self) -> dict[str, Any]:
        """
        Get comprehensive therapeutic insights across all sessions using Trio.

        Returns:
            Dict containing therapeutic insights
        """
        logger.info(
            f"TrioReflectionAgent: Gathering therapeutic insights for user {self.user_context.user_id}"
        )

        try:
            # Get memory insights (FIXED: added await)
            memory = await self.memory_agent.get_therapeutic_memory()
            patterns = await self.memory_agent.identify_patterns()
            recent_context = await self.memory_agent.get_recent_context(num_sessions=5)

            # Get planning insights
            current_plan = await self.db_service.get_latest_therapy_plan(
                self.user_context.user_id
            )
            plan_evolution = self.planning_agent.get_plan_evolution_summary()

            plan_assessment = None
            if current_plan:
                # FIXED: added await
                plan_assessment = await self.planning_agent.assess_plan_effectiveness(
                    current_plan
                )

            # FIXED: added await to _generate_combined_recommendations
            recommendations = await self._generate_combined_recommendations(
                memory, patterns, current_plan
            )

            return {
                "user_id": self.user_context.user_id,
                "insights_generated_at": datetime.now().isoformat(),
                # Memory insights
                "memory_insights": {
                    "total_sessions": len(memory.session_contexts),
                    "relationship_quality": memory.relationship_quality,
                    "recurring_themes": dict(memory.recurring_themes),
                    "emotional_patterns": memory.emotional_patterns,
                    "recent_progress": recent_context.get("insights", []),
                    "patterns": patterns,
                },
                # Planning insights
                "planning_insights": {
                    "current_plan_id": current_plan.plan_id if current_plan else None,
                    "current_plan_version": (
                        current_plan.version if current_plan else None
                    ),
                    "plan_effectiveness": plan_assessment,
                    "plan_evolution": plan_evolution,
                },
                # Combined recommendations
                "recommendations": recommendations,
            }

        except Exception as e:
            logger.error(f"Failed to gather therapeutic insights: {e}", exc_info=True)
            return {
                "user_id": self.user_context.user_id,
                "error": str(e),
                "insights_generated_at": datetime.now().isoformat(),
            }

    async def ensure_recent_sessions_enriched(
        self, user_id: str, *, limit: int = 5, scan_limit: int | None = None
    ) -> list[DetailedSession]:
        """
        Ensure recent sessions have Tier 2 enrichment, enriching on-demand when missing.

        This is a fallback mechanism used when other agents need enriched session
        context but some recent sessions haven't been enriched yet.
        """
        return await ensure_recent_sessions_enriched(
            self.db_service,
            self.llm_service,
            user_id,
            limit=limit,
            scan_limit=scan_limit,
        )

    async def _generate_combined_recommendations(
        self, memory, patterns: dict[str, Any], current_plan: TherapyPlan | None
    ) -> list[dict[str, Any]]:
        """
        Generate combined recommendations based on memory and planning insights using Trio.

        Args:
            memory: Therapeutic memory object
            patterns: Identified patterns
            current_plan: Current therapy plan

        Returns:
            List of combined recommendations
        """
        return await generate_combined_recommendations(
            self.planning_agent,
            memory,
            patterns,
            current_plan,
        )

    async def health_check(self) -> bool:
        """
        Perform health check on the reflection agent and its dependencies using Trio.

        Returns:
            bool: True if healthy, False otherwise
        """
        try:
            # Check memory agent health
            if not await self.memory_agent.health_check():
                logger.error("TrioMemoryAgent health check failed")
                return False

            # Check planning agent health
            if not await self.planning_agent.health_check():
                logger.error("TrioPlanningAgent health check failed")
                return False

            # Check LLM service (run in thread)
            test_prompt = "Respond with 'OK' if you can process this request."
            response = await trio.to_thread.run_sync(
                self.llm_service.generate_response, test_prompt
            )
            if "OK" not in response and "ok" not in response.lower():
                logger.error("LLM service health check failed")
                return False

            return True

        except Exception as e:
            logger.error(f"TrioReflectionAgent health check failed: {e}")
            return False

    async def _evaluate_tier3_update_necessity(
        self, current_analysis: PatientAnalysisVersion, session: Session
    ) -> tuple[bool, str | None]:
        """
        Evaluate if Tier 3 (clinical formulation) should be updated.

        Uses LLM to determine if the session contains new information
        that meaningfully changes the clinical formulation.

        Args:
            current_analysis: Current PatientAnalysisVersion
            session: Latest therapy session

        Returns:
            Tuple of (update_needed: bool, change_summary: str | None)
        """
        return await evaluate_tier3_update_necessity(
            self.llm_service,
            current_analysis,
            session,
        )

    async def _generate_updated_tier3_analysis(
        self,
        current_analysis: PatientAnalysisVersion,
        session: Session,
        change_summary: str,
    ) -> PatientAnalysis | None:
        """
        Generate updated Tier 3 clinical formulation.

        Creates a new version of PatientAnalysis incorporating insights
        from the latest session.

        Args:
            current_analysis: Current PatientAnalysisVersion
            session: Latest therapy session
            change_summary: Summary of what changed

        Returns:
            Updated PatientAnalysis, or None if failed
        """
        return await generate_updated_tier3_analysis(
            self.llm_service,
            current_analysis,
            session,
            change_summary,
        )

    def __str__(self) -> str:
        """String representation of reflection agent."""
        return f"TrioReflectionAgent(user={self.user_context.user_id}, coordinator)"

    def __repr__(self) -> str:
        """Detailed representation of reflection agent."""
        return f"TrioReflectionAgent(user='{self.user_context.user_id}', memory_agent={type(self.memory_agent).__name__}, planning_agent={type(self.planning_agent).__name__})"
