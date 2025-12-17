"""
TrioReflectionAgent: Trio-native agent for analyzing therapy sessions and updating plans.

This agent coordinates memory and planning functionality to provide
comprehensive therapy session analysis and plan management.

Pure Trio implementation using structured concurrency.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

import trio
from pydantic import ValidationError

from agents.trio_memory_agent import TrioMemoryAgent
from agents.trio_planning_agent import TrioPlanningAgent
from config import settings
from context.user_context import UserContext
from exceptions import ReflectionError
from models.briefing_models import SessionBriefing
from models.data_models import (
    AnalyticOrientation,
    CurrentFocus,
    DefensiveOrganization,
    DetailedSession,
    PatientAnalysis,
    PatientAnalysisVersion,
    PatientProfile,
    RecurringNarrative,
    Session,
    TherapyPlan,
    TransferenceImpressions,
)
from models.structured_output_models import (
    ChangeDetectionDecision,
    Tier1ProfilePatch,
    Tier2Enrichment,
)
from orchestration.models import AgentResponse, ConversationContext, WorkflowState
from prompts.reflection_prompts import (
    SESSION_BRIEFING_PROMPT,
    SESSION_SUMMARY_PROMPT,
    TIER1_CHANGE_DETECTION_PROMPT,
    TIER1_UPDATE_GENERATION_PROMPT,
    TIER2_ENRICHMENT_PROMPT,
    TIER3_CHANGE_DETECTION_PROMPT,
    TIER3_UPDATE_GENERATION_PROMPT,
)
from services.llm_service import LLMService
from services.rag_service import RAGService
from services.trio_db_service import TrioDatabaseService

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
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.memory_agent = memory_agent
        self.planning_agent = planning_agent

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
        It updates the therapy plan and returns summary information.

        Args:
            session: Completed therapy session
            context: Conversation context

        Returns:
            AgentResponse with reflection summary

        Raises:
            Exception: Any errors during reflection processing (fail-fast behavior)
        """
        logger.info(f"Processing reflection for session {session.session_id}")

        # Update therapy plan
        current_plan = context.therapy_plan
        updated_plan = await self.update_plan(session, current_plan)

        # Generate comprehensive reflection (includes memory and planning analysis)
        reflection = await self.generate_comprehensive_reflection(session, updated_plan)

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
            tier4_update = session_briefing.get("tier4_update") if isinstance(session_briefing, dict) else None
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

            # Save updated plan with briefing
            await self.db_service.save_therapy_plan(updated_plan)
            logger.info(
                f"Successfully generated and saved session briefing for session {session.session_id}"
            )
        else:
            logger.warning(
                f"Session briefing generation returned None for session {session.session_id}"
            )

        # Build response content
        content = self._format_reflection_summary(reflection)

        return AgentResponse(
            content=content,
            next_action="transition",
            next_state=WorkflowState.PLAN_COMPLETE,
            metadata={
                "plan_id": updated_plan.plan_id,
                "plan_version": updated_plan.version,
                "session_id": session.session_id,
                "reflection": reflection,
                "has_briefing": updated_plan.session_briefing is not None,
            },
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
    ) -> TherapyPlan:
        """
        Coordinate initial therapy plan creation using specialized agents with Trio.

        Args:
            intake_session: The completed intake session
            selected_style: Optional therapy style preference

        Returns:
            TherapyPlan: The initial therapy plan

        Raises:
            ReflectionError: If plan creation fails
        """
        logger.info(
            f"TrioReflectionAgent: Coordinating initial plan creation for user {self.user_context.user_id}"
        )

        try:
            # Use planning agent to create comprehensive initial plan
            therapy_plan = await self.planning_agent.create_initial_plan(
                intake_session, selected_style
            )

            logger.info(f"Initial therapy plan created with ID: {therapy_plan.plan_id}")
            return therapy_plan

        except Exception as e:
            logger.error(
                f"Failed to coordinate initial plan creation: {e}", exc_info=True
            )
            raise ReflectionError(f"Initial plan creation failed: {e}")

    async def create_initial_plan_with_style(
        self, intake_session: Session, selected_style: str
    ) -> TherapyPlan:
        """
        Create initial therapy plan with specific style using Trio (delegates to create_initial_plan).

        Args:
            intake_session: The completed intake session
            selected_style: The selected therapy style

        Returns:
            TherapyPlan: The initial therapy plan with selected style
        """
        logger.info(
            f"TrioReflectionAgent: Creating initial {selected_style.upper()} therapy plan"
        )
        return await self.create_initial_plan(intake_session, selected_style)

    async def update_plan(
        self, session: Session, current_plan: TherapyPlan | None = None
    ) -> TherapyPlan:
        """
        Coordinate therapy plan updates using specialized agents with Trio.

        Args:
            session: The completed therapy session
            current_plan: The current therapy plan (if None, retrieves latest)

        Returns:
            TherapyPlan: The updated therapy plan

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
            updated_plan = await self.planning_agent.update_plan(session, current_plan)

            logger.info(f"Therapy plan updated to version {updated_plan.version}")
            return updated_plan

        except Exception as e:
            logger.error(f"Failed to coordinate plan update: {e}", exc_info=True)
            raise ReflectionError(f"Plan update failed: {e}")

    async def generate_comprehensive_reflection(
        self, session: Session, current_plan: TherapyPlan | None = None
    ) -> dict[str, Any]:
        """
        Generate comprehensive reflection combining memory analysis and planning insights using Trio.

        Args:
            session: The session to reflect on
            current_plan: Optional current therapy plan

        Returns:
            Dict containing comprehensive reflection analysis

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

            # Enrich session with Tier 2 psychological data
            # This is a one-time operation - check if already enriched
            enrichment_success = False
            session_record = session
            if not getattr(session, "enriched", False):
                logger.info(
                    f"Session {session.session_id} not yet enriched - "
                    f"extracting Tier 2 data..."
                )
                enrichment_success = await self._enrich_session(session)
                if enrichment_success:
                    logger.info(
                        f"Successfully enriched session {session.session_id} "
                        f"with Tier 2 data"
                    )
                else:
                    logger.warning(
                        f"Failed to enrich session {session.session_id} - "
                        f"continuing without enrichment"
                    )
            else:
                logger.info(
                    f"Session {session.session_id} already enriched - skipping"
                )

            # Load enriched view of the session for downstream analysis
            session_record = await self.db_service.get_session(session.session_id)
            if session_record:
                logger.debug("Loaded enriched session record for %s", session.session_id)
            else:
                session_record = session

            # Tier 1: rare background updates (LLM-gated)
            tier1_updated = False
            current_profile = await self.db_service.get_patient_profile(
                self.user_context.user_id
            )
            if current_profile:
                tier1_updated = await self._maybe_update_tier1_profile(
                    current_profile, session_record
                )

            # Phase 5: Check Tier 3 (clinical formulation) for updates
            tier3_updated = False
            tier3_version = None

            # Load current Tier 3 analysis
            current_tier3 = await self.db_service.get_latest_patient_analysis(
                self.user_context.user_id
            )

            if current_tier3:
                # Evaluate if update is needed
                update_needed, change_summary = (
                    await self._evaluate_tier3_update_necessity(
                        current_tier3, session_record
                    )
                )

                if update_needed and change_summary:
                    logger.info(
                        f"Tier 3 update needed: {change_summary}"
                    )

                    # Generate updated formulation
                    updated_analysis = await self._generate_updated_tier3_analysis(
                        current_tier3, session_record, change_summary
                    )

                    if updated_analysis:
                        saved = await self.db_service.save_patient_analysis_next_version_and_supersede(
                            analysis_id=f"analysis_{uuid.uuid4().hex[:12]}",
                            user_id=current_tier3.user_id,
                            analysis_data=updated_analysis,
                            created_at=datetime.now(),
                            created_by_session=session_record.session_id,
                            change_summary=change_summary,
                            supersede_analysis_id=current_tier3.analysis_id,
                        )

                        if saved:
                            logger.info(
                                "Created Tier 3 v%s for user %s: %s",
                                saved.version,
                                self.user_context.user_id,
                                change_summary,
                            )
                            tier3_updated = True
                            tier3_version = saved.version
                        else:
                            logger.warning(
                                "Failed to save Tier 3 update"
                            )
                    else:
                        logger.warning(
                            "Failed to generate Tier 3 update"
                        )
                else:
                    logger.info(
                        "Tier 3 update not needed - formulation remains stable"
                    )
            else:
                logger.info(
                    "No Tier 3 analysis exists yet (created during assessment)"
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
            # Generate traditional session summary
            session_summary = await self._generate_session_summary(session_record)

            if current_plan:
                session_count = await self.db_service.get_session_count(
                    self.user_context.user_id
                )
                if self._should_update_tier4(
                    session_count, tier3_updated, plan_recommendations
                ):
                    tier4_updated = self._update_tier4_fields(
                        current_plan,
                        session_context,
                        plan_assessment,
                        plan_recommendations,
                        session_summary,
                    )
                    if tier4_updated:
                        current_plan.updated_at = datetime.now()
                        await self.db_service.save_therapy_plan(current_plan)

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
                "tier4_updated": tier4_updated,
                "tier1_updated": tier1_updated,
            }

            logger.info(
                f"Comprehensive reflection generated for session {session.session_id}"
            )
            return reflection

        except Exception as e:
            logger.error(
                f"Failed to generate comprehensive reflection: {e}", exc_info=True
            )
            raise ReflectionError(f"Reflection generation failed: {e}")

    async def _generate_session_summary(self, session: Session) -> str:
        """
        Generate traditional session summary using LLM with Trio.

        Args:
            session: The session to summarize

        Returns:
            String summary of the session
        """
        session_text = "\n".join(
            [f"{msg.role}: {msg.content}" for msg in session.transcript]
        )
        summary_prompt = SESSION_SUMMARY_PROMPT.format(session_text=session_text)

        # Run synchronous LLM call in thread
        return await trio.to_thread.run_sync(
            self.llm_service.generate_response, summary_prompt
        )

    def _update_tier4_fields(
        self,
        plan: TherapyPlan | None,
        session_context,
        plan_assessment: dict[str, Any] | None,
        plan_recommendations: list[dict[str, Any]],
        session_summary: str,
    ) -> bool:
        """
        Refresh Tier 4 fields (progress/interventions) based on newest session.
        """
        if not plan:
            return False

        updated = False

        indicators = getattr(session_context, "progress_indicators", []) or []
        progress_parts = []
        if indicators:
            progress_parts.append(
                "Progress indicators: " + "; ".join(indicators[:3])
            )
        if plan_assessment:
            strengths = plan_assessment.get("strengths") or []
            if strengths:
                progress_parts.append(
                    "Strengths noted: " + "; ".join(strengths[:2])
                )

        if not progress_parts and session_summary:
            progress_parts.append(session_summary[:300])

        new_progress = " ".join(progress_parts)[:2000]
        if new_progress and new_progress != plan.current_progress:
            plan.current_progress = new_progress
            updated = True

        rec_descriptions = []
        for rec in plan_recommendations or []:
            description = rec.get("description")
            if description:
                rec_descriptions.append(description)
            if len(rec_descriptions) == 3:
                break

        if rec_descriptions:
            if plan.planned_interventions[: len(rec_descriptions)] != rec_descriptions:
                plan.planned_interventions = rec_descriptions
                updated = True

        return updated

    def _should_update_tier4(
        self,
        session_count: int,
        tier3_updated: bool,
        plan_recommendations: list[dict[str, Any]],
    ) -> bool:
        if tier3_updated:
            return True
        if session_count > 0 and session_count % 5 == 0:
            return True
        for rec in plan_recommendations or []:
            if rec.get("priority") == "high":
                return True
        return False

    async def _maybe_update_tier1_profile(
        self, profile: PatientProfile, session: Session
    ) -> bool:
        try:
            if getattr(session, "enriched", False) and getattr(
                session, "psychological_summary", None
            ):
                session_summary = session.psychological_summary or ""
            else:
                session_summary = f"Session {session.session_id} with {len(session.transcript)} messages"

            detection_prompt = TIER1_CHANGE_DETECTION_PROMPT.format(
                current_profile_json=profile.model_dump_json(),
                session_summary=session_summary,
            )
            decision = await self.llm_service.generate_structured_output_async(
                detection_prompt,
                ChangeDetectionDecision,
                method="json_schema",
            )
            if not isinstance(decision, ChangeDetectionDecision):
                return False
            if not decision.update_needed:
                return False

            change_summary = decision.change_summary or ""
            update_prompt = TIER1_UPDATE_GENERATION_PROMPT.format(
                current_profile_json=profile.model_dump_json(),
                session_summary=session_summary,
                change_summary=change_summary,
            )
            patch = await self.llm_service.generate_structured_output_async(
                update_prompt,
                Tier1ProfilePatch,
                method="json_schema",
            )
            if not isinstance(patch, Tier1ProfilePatch):
                return False
            merged = profile.model_dump()
            for section in ["basic_info", "family", "history", "context", "frame"]:
                section_patch = getattr(patch, section, None)
                if not section_patch:
                    continue
                for key, value in section_patch.model_dump().items():
                    if value is None:
                        continue
                    if isinstance(value, str) and not value.strip():
                        continue
                    merged[section][key] = value

            merged["updated_at"] = datetime.now()
            updated_profile = PatientProfile.model_validate(merged)
            return bool(
                await self.db_service.update_patient_profile(
                    updated_profile,
                    change_summary=change_summary or None,
                    created_by_session=session.session_id,
                )
            )

        except Exception as e:
            logger.error(f"Error updating Tier 1 profile: {e}", exc_info=True)
            return False

    async def generate_session_summary(self, session: Session) -> dict[str, Any]:
        """
        Generate a simple session summary using Trio (backwards compatibility).

        Args:
            session: The session to summarize

        Returns:
            Dict containing session summary
        """
        summary = await self._generate_session_summary(session)

        return {
            "session_id": session.session_id,
            "summary": summary,
            "timestamp": session.timestamp.isoformat(),
        }

    async def _enrich_session(self, session: Session) -> bool:
        """
        Enrich session with Tier 2 psychological data using LLM.

        Extracts psychological summary, dominant affects, key themes,
        notable interactions, interpretations, and patient reactions
        from the session transcript.

        Args:
            session: The session to enrich

        Returns:
            bool: True if enrichment successful, False otherwise
        """
        try:
            # Format session transcript
            transcript_lines = []
            for msg in session.transcript:
                role = "Therapist" if msg.role == "assistant" else "Patient"
                transcript_lines.append(f"{role}: {msg.content}")

            transcript = "\n".join(transcript_lines)

            # Format the enrichment prompt
            enrichment_prompt = TIER2_ENRICHMENT_PROMPT.format(
                session_transcript=transcript
            )

            logger.info(
                f"Extracting Tier 2 enrichment for session {session.session_id}..."
            )

            tier2 = await self.llm_service.generate_structured_output_async(
                enrichment_prompt,
                Tier2Enrichment,
                method="json_schema",
            )
            if not isinstance(tier2, Tier2Enrichment):
                logger.error("Tier 2 enrichment returned unexpected type")
                return False
            tier2_data = tier2.model_dump()

            logger.info(
                f"Extracted Tier 2 data keys: {tier2_data.keys()}"
            )

            # Save to database
            success = await self.db_service.update_session_tier2(
                session.session_id, tier2_data
            )

            if success:
                session.psychological_summary = tier2_data.get(
                    "psychological_summary"
                )
                session.dominant_affects = tier2_data.get("dominant_affects", [])
                session.key_themes = tier2_data.get("key_themes", [])
                session.notable_interactions = tier2_data.get(
                    "notable_interactions"
                )
                session.interpretations = tier2_data.get("interpretations")
                session.patient_reactions = tier2_data.get("patient_reactions")
                session.enriched = True
                logger.info(
                    f"Successfully enriched session {session.session_id} "
                    f"with Tier 2 data"
                )
            else:
                logger.warning(
                    f"Failed to save Tier 2 enrichment for session "
                    f"{session.session_id}"
                )

            return success

        except Exception as e:
            logger.error(
                f"Error enriching session {session.session_id}: {e}",
                exc_info=True,
            )
            return False

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
        logger.info(f"Generating session briefing for session {session.session_id}")

        # Get session transcript as string
        session_transcript = "\n".join(
            [f"{msg.role}: {msg.content}" for msg in session.transcript]
        )

        # Construct comprehensive analysis prompt
        # Construct comprehensive analysis prompt
        analysis_prompt = SESSION_BRIEFING_PROMPT.format(
            total_sessions=therapeutic_memory.get("total_sessions", 0),
            relationship_quality=therapeutic_memory.get(
                "relationship_quality", "building"
            ),
            therapy_style=(
                therapy_plan.selected_therapy_style if therapy_plan else "Not specified"
            ),
            session_transcript=session_transcript,
            key_themes=json.dumps(session_context.get("key_themes", []), indent=2),
            emotional_state=session_context.get("emotional_state", "Not assessed"),
            insights=json.dumps(session_context.get("insights", []), indent=2),
            progress_indicators=json.dumps(
                session_context.get("progress_indicators", []), indent=2
            ),
            therapeutic_memory=json.dumps(therapeutic_memory, indent=2),
            plan_assessment=json.dumps(
                plan_assessment if plan_assessment else {}, indent=2
            ),
            tier4_initial_goals=json.dumps(
                (therapy_plan.initial_goals if therapy_plan else []), indent=2
            ),
            tier4_current_progress=(
                therapy_plan.current_progress if therapy_plan else ""
            ),
            tier4_planned_interventions=json.dumps(
                (therapy_plan.planned_interventions if therapy_plan else []), indent=2
            ),
            tier4_status=(therapy_plan.status if therapy_plan else "active"),
            generated_at=datetime.now().isoformat(),
            last_session_id=session.session_id,
            last_session_date=session.timestamp.date().isoformat(),
            max_continuity_points=settings.MAX_CONTINUITY_POINTS,
            max_key_themes=settings.MAX_KEY_THEMES,
            max_progress_highlights=settings.MAX_PROGRESS_HIGHLIGHTS,
            max_unresolved_issues=settings.MAX_UNRESOLVED_ISSUES,
            max_suggested_questions=settings.MAX_SUGGESTED_QUESTIONS,
            max_session_goals=settings.MAX_SESSION_GOALS,
            min_narrative_length=settings.MIN_NARRATIVE_LENGTH,
            max_narrative_length=settings.MAX_NARRATIVE_LENGTH,
            max_observations_length=settings.MAX_OBSERVATIONS_LENGTH,
            max_plan_notes_length=settings.MAX_PLAN_NOTES_LENGTH,
        )

        # Generate structured briefing using Gemini structured outputs.
        try:
            briefing = await self.llm_service.generate_structured_output_async(
                analysis_prompt,
                SessionBriefing,
                method="json_schema",
            )
            if not isinstance(briefing, SessionBriefing):
                raise TypeError("Unexpected SessionBriefing type")

            # Ensure key metadata matches ground truth.
            now = datetime.now().isoformat()
            if hasattr(briefing, "model_copy"):
                briefing = briefing.model_copy(
                    update={
                        "generated_at": now,
                        "session_count": therapeutic_memory.get("total_sessions", 0),
                        "last_session_id": session.session_id,
                    }
                )
            else:
                briefing.generated_at = now
                briefing.session_count = therapeutic_memory.get("total_sessions", 0)
                briefing.last_session_id = session.session_id

            logger.info(
                "Successfully generated session briefing for session %s",
                session.session_id,
            )
            return briefing.model_dump() if hasattr(briefing, "model_dump") else briefing.dict()

        except ValidationError as e:
            logger.error(f"Session briefing failed validation: {e}")
            raise

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
        scan_limit = scan_limit or max(limit * 3, 10)

        # First try: return already-enriched sessions
        enriched = await self.db_service.get_recent_sessions(
            user_id, limit=limit, enriched_only=True
        )
        if len(enriched) >= limit:
            return enriched

        # Attempt to enrich recent sessions until we have enough
        recent_any = await self.db_service.get_recent_sessions(
            user_id, limit=scan_limit, enriched_only=False
        )
        for session in recent_any:
            if getattr(session, "enriched", False):
                continue
            try:
                await self._enrich_session(session)
            except Exception:
                logger.warning(
                    "On-demand Tier 2 enrichment failed for session %s",
                    session.session_id,
                    exc_info=True,
                )

            enriched = await self.db_service.get_recent_sessions(
                user_id, limit=limit, enriched_only=True
            )
            if len(enriched) >= limit:
                break

        return enriched

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
        recommendations = []

        # Memory-based recommendations
        if memory.relationship_quality in ["established", "strong"]:
            recommendations.append(
                {
                    "type": "relationship",
                    "description": "Strong therapeutic relationship established - consider deeper therapeutic work",
                    "source": "memory_analysis",
                    "priority": "medium",
                }
            )

        # Pattern-based recommendations
        emotional_trend = patterns.get("emotional_patterns", {}).get(
            "recent_trend", "stable"
        )
        if emotional_trend == "improving":
            recommendations.append(
                {
                    "type": "progress",
                    "description": "Positive emotional trend - maintain current approach and build on progress",
                    "source": "pattern_analysis",
                    "priority": "high",
                }
            )
        elif emotional_trend == "declining":
            recommendations.append(
                {
                    "type": "intervention",
                    "description": "Declining emotional trend - consider plan adjustment or additional support",
                    "source": "pattern_analysis",
                    "priority": "high",
                }
            )

        # Planning-based recommendations (FIXED: added await)
        if current_plan:
            plan_recommendations = await self.planning_agent.recommend_plan_adjustments(
                current_plan
            )
            for rec in plan_recommendations[:3]:  # Top 3 recommendations
                rec["source"] = "planning_analysis"
                recommendations.append(rec)

        return recommendations

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
        try:
            # Format current analysis for prompt
            analysis_data = current_analysis.analysis_data
            current_formulation = (
                f"Theme: {analysis_data.current_focus.theme}\n"
                f"Salience: {analysis_data.current_focus.salience}\n"
                f"Primary Defenses: "
                f"{', '.join(analysis_data.defenses.primary_defenses)}\n"
                f"Narratives: "
                f"{', '.join([n.title for n in analysis_data.narratives])}\n"
                f"Risk Areas: "
                f"{', '.join(analysis_data.orientation.risk_areas)}"
            )

            # Format session summary (use Tier 2 enrichment if available)
            if getattr(session, "enriched", False) and getattr(
                session, "psychological_summary", None
            ):
                session_summary = (
                    f"Summary: {session.psychological_summary}\n"
                    f"Affects: {', '.join(getattr(session, 'dominant_affects', []))}\n"
                    f"Themes: {', '.join(getattr(session, 'key_themes', []))}"
                )
            else:
                # Fallback to basic transcript summary
                session_summary = (
                    f"Session {session.session_id} with "
                    f"{len(session.transcript)} messages"
                )

            # Format detection prompt
            detection_prompt = TIER3_CHANGE_DETECTION_PROMPT.format(
                current_version=current_analysis.version,
                current_analysis=current_formulation,
                session_summary=session_summary,
            )

            logger.info(
                f"Evaluating Tier 3 update necessity for session "
                f"{session.session_id}"
            )

            decision = await self.llm_service.generate_structured_output_async(
                detection_prompt,
                ChangeDetectionDecision,
                method="json_schema",
            )
            if not isinstance(decision, ChangeDetectionDecision):
                return (False, None)
            update_needed = decision.update_needed
            change_summary = decision.change_summary

            logger.info(
                f"Tier 3 update decision: update_needed={update_needed}, "
                f"summary={change_summary}"
            )

            return (update_needed, change_summary)

        except Exception as e:
            logger.error(
                f"Error evaluating Tier 3 update necessity: {e}",
                exc_info=True,
            )
            return (False, None)

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
        try:
            # Format current analysis
            analysis_data = current_analysis.analysis_data
            current_formulation = json.dumps(
                {
                    "current_focus": {
                        "theme": analysis_data.current_focus.theme,
                        "salience": analysis_data.current_focus.salience,
                    },
                    "transference": {
                        "idealization": analysis_data.transference.idealization,
                        "devaluation": analysis_data.transference.devaluation,
                        "boundaries": analysis_data.transference.boundaries,
                        "other_patterns": (
                            analysis_data.transference.other_patterns
                        ),
                    },
                    "narratives": [
                        {
                            "title": n.title,
                            "description": n.description,
                            "first_appeared": n.first_appeared,
                        }
                        for n in analysis_data.narratives
                    ],
                    "defenses": {
                        "primary_defenses": (
                            analysis_data.defenses.primary_defenses
                        ),
                        "defensive_style": (
                            analysis_data.defenses.defensive_style
                        ),
                        "flexibility": analysis_data.defenses.flexibility,
                    },
                    "orientation": {
                        "pacing": analysis_data.orientation.pacing,
                        "risk_areas": analysis_data.orientation.risk_areas,
                        "key_questions": (
                            analysis_data.orientation.key_questions
                        ),
                    },
                },
                indent=2,
            )

            # Format session summary
            if getattr(session, "enriched", False) and getattr(
                session, "psychological_summary", None
            ):
                session_summary = (
                    f"Summary: {session.psychological_summary}\n"
                    f"Affects: {', '.join(getattr(session, 'dominant_affects', []))}\n"
                    f"Themes: {', '.join(getattr(session, 'key_themes', []))}"
                )
            else:
                session_summary = f"Session {session.session_id}"

            # Format update generation prompt
            update_prompt = TIER3_UPDATE_GENERATION_PROMPT.format(
                current_version=current_analysis.version,
                current_analysis=current_formulation,
                session_summary=session_summary,
                change_summary=change_summary,
            )

            logger.info(
                "Generating updated Tier 3 analysis for session %s",
                session.session_id,
            )

            updated_analysis = await self.llm_service.generate_structured_output_async(
                update_prompt,
                PatientAnalysis,
                method="json_schema",
            )
            if not isinstance(updated_analysis, PatientAnalysis):
                logger.error("Tier 3 update generation returned unexpected type")
                return None

            logger.info(
                "Successfully generated updated Tier 3 analysis for user %s",
                current_analysis.user_id,
            )

            return updated_analysis

        except Exception as e:
            logger.error(
                f"Error generating updated Tier 3 analysis: {e}",
                exc_info=True,
            )
            return None

    def __str__(self) -> str:
        """String representation of reflection agent."""
        return f"TrioReflectionAgent(user={self.user_context.user_id}, coordinator)"

    def __repr__(self) -> str:
        """Detailed representation of reflection agent."""
        return f"TrioReflectionAgent(user='{self.user_context.user_id}', memory_agent={type(self.memory_agent).__name__}, planning_agent={type(self.planning_agent).__name__})"
