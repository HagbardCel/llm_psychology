"""
TrioPsychoanalystAgent: Trio-native agent for conducting therapy sessions.

This agent conducts the main therapeutic conversations based on the
established therapy plan and selected therapy style.

Pure Trio implementation using structured concurrency.
"""

import logging
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.briefing_models import BriefingStatus
from psychoanalyst_app.models.data_models import TherapyPlan, UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
    WorkflowEvent,
)
from psychoanalyst_app.prompts.psychoanalyst_prompt_builder import (
    build_continuation_prompt,
    build_initial_prompt,
    build_resumption_prompt,
)
from psychoanalyst_app.prompts.psychoanalyst_prompts import CLOSING_SESSION_PROMPT
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag_service import RAGService
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioPsychoanalystAgent:
    """
    Trio-native agent responsible for conducting therapy sessions.

    Uses Trio's structured concurrency for all async operations.
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGService,
        reflection_agent: Any | None = None,
        style_service: StyleService | None = None,
        config: Settings | None = None,
    ):
        """
        Initialize the Trio Psychoanalyst Agent.

        Args:
            llm_service: The LLM service for generating responses (synchronous)
            db_service: The Trio database service for storing sessions
            rag_service: The RAG service for retrieving domain knowledge (synchronous)
            reflection_agent: Reflection agent (optional; used for on-demand Tier 2 enrichment)
            config: Application settings
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.reflection_agent = reflection_agent
        if config is None:
            raise ValueError("config is required")
        self.config = config
        if style_service is None:
            raise ValueError("style_service is required")
        self.style_service = style_service

    # ===== SESSION RESUMPTION SUPPORT =====

    def get_briefing_status(self, briefing: dict[str, Any]) -> BriefingStatus:
        """
        Determines the status of a briefing based on its age.

        Args:
            briefing: Session briefing dict

        Returns:
            BriefingStatus enum value
        """
        try:
            generated_at_str = briefing.get("generated_at")
            if not generated_at_str:
                return BriefingStatus.INVALID

            generated_at = datetime.fromisoformat(generated_at_str)
            age_days = (datetime.now() - generated_at).days

            if age_days <= self.config.BRIEFING_VALIDITY_DAYS:
                return BriefingStatus.FRESH
            elif age_days <= self.config.STALE_BRIEFING_DAYS:
                return BriefingStatus.STALE
            else:
                return BriefingStatus.VERY_STALE

        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing briefing timestamp: {e}")
            return BriefingStatus.INVALID

    async def _build_resumption_prompt(
        self,
        user_profile: UserProfile,
        therapy_plan: TherapyPlan,
        briefing: dict[str, Any],
        status: BriefingStatus,
    ) -> str:
        """
        Build prompt for resuming therapy session using the enhanced briefing.

        Args:
            user_profile: User's profile
            therapy_plan: Therapy plan
            briefing: Session briefing dict
            status: Briefing status (FRESH, STALE, etc.)

        Returns:
            System prompt that will generate the opening greeting
        """
        return build_resumption_prompt(user_profile, therapy_plan, briefing, status)

    # ===== NEW ORCHESTRATOR INTERFACE =====

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """
        Process user message during therapy session using Trio (orchestrator interface).

        This is the interface for use with the orchestration layer.
        It builds prompts with RAG context without UI interaction.

        Args:
            message: User's message
            context: Conversation context

        Returns:
            AgentResponse with prompt for LLM
        """
        try:
            # Get therapy plan
            therapy_plan = context.therapy_plan
            if not therapy_plan:
                return AgentResponse(
                    content="I apologize, but I don't have your therapy plan loaded. Please contact support.",
                    next_action="continue",
                    workflow_event=None,
                    metadata={"error": "No therapy plan"},
                )

            selected_style = therapy_plan.selected_therapy_style

            # Check if this is the first message (initial greeting)
            # This path is now less likely to be used for initial greetings
            # due to the proactive prompt in start_session.
            if not context.message_history or len(context.message_history) <= 1:
                prompt = await self._build_initial_session_prompt(
                    context.user_profile,
                    therapy_plan,
                    active_session_id=context.session_id,
                )
            else:
                # Build continuation prompt with RAG context
                prompt = await self._build_continuation_prompt(
                    message, context, therapy_plan, selected_style
                )

            # Check if session should end
            if context.user_profile.status == UserStatus.ASSESSMENT_COMPLETE:
                # First message in therapy - request transition to IN_PROGRESS
                next_action = "transition"
                workflow_event = WorkflowEvent.START_THERAPY
            elif context.user_profile.status == UserStatus.PLAN_COMPLETE:
                # Starting new session after plan update - request transition to IN_PROGRESS
                next_action = "transition"
                workflow_event = WorkflowEvent.START_THERAPY
            elif context.is_time_up:
                next_action = "transition"
                workflow_event = WorkflowEvent.COMPLETE_SESSION
            elif self._should_offer_extension(context):
                next_action = "offer_extension"
                workflow_event = None
            else:
                next_action = "continue"
                workflow_event = None

            return AgentResponse(
                content=prompt,
                next_action=next_action,
                workflow_event=workflow_event,
                metadata={
                    "therapy_style": selected_style,
                    "time_remaining": context.time_remaining_minutes,
                    "can_extend": context.can_extend,
                    "extensions_used": context.extensions_used,
                },
            )

        except Exception as e:
            return AgentResponse(
                content="I apologize, but I encountered an error. Could you please repeat that?",
                next_action="continue",
                workflow_event=None,
                metadata={"error": str(e)},
            )

    async def _build_initial_session_prompt(
        self,
        user_profile: UserProfile,
        therapy_plan: TherapyPlan,
        *,
        active_session_id: str | None = None,
    ) -> str:
        """
        Build initial greeting prompt for therapy session using Trio.

        Checks for session briefing and uses resumption prompt if available.
        Falls back to standard initial prompt for first-time sessions.

        Args:
            user_profile: User's profile
            therapy_plan: Therapy plan

        Returns:
            Initial prompt for LLM
        """
        # Check if there's a session briefing for resumption
        if therapy_plan.session_briefing:
            briefing = therapy_plan.session_briefing
            status = self.get_briefing_status(briefing)

            # Use resumption prompt for FRESH and STALE briefings
            if status in [BriefingStatus.FRESH, BriefingStatus.STALE]:
                logger.info(
                    f"Using session briefing (status: {status.value}) for user {user_profile.user_id}"
                )
                return await self._build_resumption_prompt(
                    user_profile, therapy_plan, briefing, status
                )
            else:
                logger.warning(
                    f"Briefing is {status.value} for user {user_profile.user_id}; "
                    "falling back to standard initial prompt"
                )

        # Fall back to standard initial prompt (first session or no valid briefing)
        selected_style = therapy_plan.selected_therapy_style
        user_name = user_profile.name
        plan_context = await self._build_plan_context(therapy_plan)
        exclude = {active_session_id} if active_session_id else None
        patient_context = await self._load_patient_context(
            user_profile.user_id,
            exclude_session_ids=exclude,
        )
        if patient_context:
            plan_context = f"{patient_context}\n\n{plan_context}"

        style_instructions = "Conduct a general psychoanalytic session."
        if selected_style and self.style_service.get_style_pack(selected_style):
            style_instructions = self.style_service.get_psychoanalyst_prompt(selected_style)

        return build_initial_prompt(
            user_name=user_name,
            plan_context=plan_context,
            style_instructions=style_instructions,
        )

    async def _build_continuation_prompt(
        self,
        message: str,
        context: ConversationContext,
        therapy_plan: TherapyPlan,
        selected_style: str,
    ) -> str:
        """
        Build continuation prompt with RAG context using Trio.

        Args:
            message: Current user message
            context: Conversation context
            therapy_plan: Therapy plan
            selected_style: Selected therapy style

        Returns:
            Continuation prompt for LLM
        """
        # Get RAG context from recent conversation
        recent_messages = context.message_history[-3:]
        recent_context = " ".join([msg.content for msg in recent_messages] + [message])

        # Retrieve relevant knowledge (run in thread)
        if selected_style:
            knowledge_source = self.style_service.get_knowledge_source(selected_style)
            context_knowledge = await trio.to_thread.run_sync(
                self.rag_service.retrieve_relevant_knowledge,
                recent_context,
                1,  # n_results
                knowledge_source,  # filter_source
            )
        else:
            context_knowledge = await trio.to_thread.run_sync(
                self.rag_service.retrieve_relevant_knowledge,
                recent_context,
                1,  # n_results
            )

        # Build plan context
        plan_context = await self._build_plan_context(therapy_plan)
        patient_context = await self._load_patient_context(
            context.user_profile.user_id,
            exclude_session_ids={context.session_id},
        )
        if patient_context:
            plan_context = f"{patient_context}\n\n{plan_context}"

        # Get style instructions
        style_instructions = "Conduct a general psychoanalytic session."
        if selected_style and self.style_service.get_style_pack(selected_style):
            style_instructions = self.style_service.get_psychoanalyst_prompt(selected_style)

        knowledge_text = (
            context_knowledge[0]["content"] if context_knowledge else "None"
        )

        return build_continuation_prompt(
            plan_context=plan_context,
            additional_knowledge=knowledge_text,
            time_prompt="",
            style_instructions=style_instructions,
        )

    def _should_offer_extension(self, context: ConversationContext) -> bool:
        """
        Check if session extension should be offered.

        Args:
            context: Conversation context

        Returns:
            True if extension should be offered
        """
        # Offer extension if:
        # - Time remaining is low (5 minutes or less)
        # - Can still extend
        # - Not in the middle of a deep topic (TODO: implement topic detection)
        return (
            context.time_remaining_minutes <= 5
            and context.can_extend
            and context.time_remaining_minutes > 0
        )

    async def _build_plan_context(self, therapy_plan: TherapyPlan) -> str:
        """
        Build the therapy plan context string using Trio.

        Args:
            therapy_plan: Therapy plan

        Returns:
            Formatted plan context
        """
        selected_style = therapy_plan.selected_therapy_style
        plan_focus = therapy_plan.plan_details.get("focus", "")

        # Get relevant knowledge (run in thread)
        if selected_style:
            knowledge_source = self.style_service.get_knowledge_source(selected_style)
            relevant_knowledge = await trio.to_thread.run_sync(
                self.rag_service.retrieve_relevant_knowledge,
                plan_focus,
                2,  # n_results
                knowledge_source,  # filter_source
            )
        else:
            relevant_knowledge = await trio.to_thread.run_sync(
                self.rag_service.retrieve_relevant_knowledge,
                plan_focus,
                2,  # n_results
            )

        # Build context
        context = f"""
        Therapy Plan (Version {therapy_plan.version}):
        Focus: {therapy_plan.plan_details.get("focus", "General exploration")}
        Goals: {therapy_plan.plan_details.get("goals", "Explore thoughts and feelings")}
        Techniques: {therapy_plan.plan_details.get("techniques", "Active listening and reflection")}

        Relevant Psychological Knowledge:
        """

        for i, knowledge in enumerate(relevant_knowledge, 1):
            context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"

        return context

    async def _load_patient_context(
        self, user_id: str, *, exclude_session_ids: set[str] | None = None
    ) -> str | None:
        """
        Load comprehensive patient context from all 4 tiers.

        Loads current/latest data only (no version history) to keep
        context focused and token count manageable.

        Args:
            user_id: User ID to load context for

        Returns:
            Formatted patient context string or None if no data available
        """
        exclude_session_ids = exclude_session_ids or set()
        try:
            # Load all 4 tiers concurrently
            async with trio.open_nursery() as nursery:
                tier1_result = {"data": None}
                tier2_result = {"data": None}
                tier3_result = {"data": None}
                tier4_result = {"data": None}

                async def load_tier1():
                    tier1_result["data"] = (
                        await self.db_service.get_user_profile(user_id)
                    )

                async def load_tier2():
                    # Read-only: do not trigger LLM calls during context loading.
                    limit = 5
                    enriched = await self.db_service.get_recent_sessions(
                        user_id, limit=limit, enriched_only=True
                    )
                    tier2_result["data"] = enriched

                    # Opportunistically enqueue missing enrichments for future sessions.
                    if len(enriched) < limit:
                        recent_any = await self.db_service.get_recent_sessions(
                            user_id, limit=max(limit * 3, 10), enriched_only=False
                        )
                        for session in recent_any:
                            if session.session_id in exclude_session_ids:
                                continue
                            if getattr(session, "enriched", False):
                                continue
                            await self.db_service.enqueue_session_enrichment_job(
                                session.session_id, user_id
                            )

                async def load_tier3():
                    tier3_result["data"] = (
                        await self.db_service.get_latest_patient_analysis(user_id)
                    )

                async def load_tier4():
                    tier4_result["data"] = (
                        await self.db_service.get_latest_therapy_plan(user_id)
                    )

                nursery.start_soon(load_tier1)
                nursery.start_soon(load_tier2)
                nursery.start_soon(load_tier3)
                nursery.start_soon(load_tier4)

            # Extract results
            user_profile = tier1_result["data"]
            recent_sessions = tier2_result["data"]
            current_analysis = tier3_result["data"]
            treatment_plan = tier4_result["data"]

            # If no data at all, return None
            has_data = any(
                [user_profile, recent_sessions, current_analysis, treatment_plan]
            )
            if not has_data:
                logger.info(f"No patient context data for user {user_id}")
                return None

            # Build formatted context
            context_parts = []

            # Tier 1: Patient Background
            if user_profile:
                context_parts.append("=== PATIENT BACKGROUND ===")
                context_parts.append(
                    f"Patient: {user_profile.alias or user_profile.name}"
                )

                if user_profile.cultural_background:
                    context_parts.append(
                        f"Cultural Background: "
                        f"{user_profile.cultural_background}"
                    )

                if user_profile.family_atmosphere:
                    context_parts.append(
                        f"Family: {user_profile.family_atmosphere}"
                    )

                if user_profile.relationship_to_work:
                    context_parts.append(
                        f"Work: {user_profile.relationship_to_work}"
                    )

                if user_profile.current_situation:
                    context_parts.append(
                        f"Current Situation: "
                        f"{user_profile.current_situation}"
                    )

                context_parts.append("")  # Blank line

            # Tier 3: Clinical Formulation (most important for therapist)
            if current_analysis:
                analysis = current_analysis.analysis_data
                context_parts.append("=== CLINICAL FORMULATION ===")
                context_parts.append(f"(Version {current_analysis.version})")
                context_parts.append(
                    f"Current Focus: {analysis.current_focus.theme}"
                )
                context_parts.append(f"  {analysis.current_focus.salience}")

                if analysis.transference.other_patterns:
                    context_parts.append(
                        f"Transference: {analysis.transference.other_patterns}"
                    )

                if analysis.narratives:
                    context_parts.append("Recurring Narratives:")
                    for narrative in analysis.narratives[:3]:  # Max 3
                        context_parts.append(f"  - {narrative.title}: {narrative.description}")

                if analysis.defenses.primary_defenses:
                    context_parts.append(
                        f"Primary Defenses: "
                        f"{', '.join(analysis.defenses.primary_defenses[:3])}"
                    )

                if analysis.orientation.pacing:
                    context_parts.append(
                        f"Therapeutic Pacing: {analysis.orientation.pacing}"
                    )

                if analysis.orientation.risk_areas:
                    context_parts.append(
                        f"Risk Areas: "
                        f"{', '.join(analysis.orientation.risk_areas[:3])}"
                    )

                context_parts.append("")  # Blank line

            # Tier 4: Treatment Goals
            if treatment_plan:
                context_parts.append("=== TREATMENT GOALS ===")
                for i, goal in enumerate(treatment_plan.initial_goals[:3], 1):
                    context_parts.append(f"{i}. {goal}")

                if treatment_plan.current_progress:
                    # Truncate to first 200 chars for conciseness
                    progress = treatment_plan.current_progress[:200]
                    if len(treatment_plan.current_progress) > 200:
                        progress += "..."
                    context_parts.append(f"Progress: {progress}")

                context_parts.append("")  # Blank line

            # Tier 2: Recent Session Highlights (brief summaries only)
            if recent_sessions and len(recent_sessions) > 0:
                context_parts.append(
                    f"=== RECENT SESSIONS (Last {len(recent_sessions)}) ==="
                )
                for session in recent_sessions:
                    if session.enriched and session.psychological_summary:
                        # Take first sentence or 100 chars
                        summary = session.psychological_summary.split(".")[0]
                        if len(summary) > 100:
                            summary = summary[:100] + "..."
                        date = session.timestamp.strftime("%Y-%m-%d")
                        context_parts.append(f"[{date}] {summary}")

                        # Add key themes if available
                        if session.key_themes:
                            themes = ", ".join(session.key_themes[:3])
                            context_parts.append(f"  Themes: {themes}")
                    else:
                        # Session not enriched yet - just note it exists
                        date = session.timestamp.strftime("%Y-%m-%d")
                        context_parts.append(f"[{date}] Session recorded")

            return "\n".join(context_parts)

        except Exception as e:
            logger.error(
                f"Error loading patient context for user {user_id}: {e}",
                exc_info=True,
            )
            return None


    async def get_closing_response(self, therapy_plan: TherapyPlan) -> str:
        """
        Generate a closing response for the therapy session using Trio.

        Args:
            therapy_plan: Therapy plan

        Returns:
            Closing response string
        """
        selected_style = therapy_plan.selected_therapy_style if therapy_plan else None
        plan_context = await self._build_plan_context(therapy_plan)

        # Get style instructions
        style_instructions = "Conduct a general psychoanalytic session."
        if selected_style and self.style_service.get_style_pack(selected_style):
            style_instructions = self.style_service.get_psychoanalyst_prompt(selected_style)

        closing_prompt = CLOSING_SESSION_PROMPT.format(
            plan_context=plan_context, style_instructions=style_instructions
        )

        # Generate response (run in thread)
        return await trio.to_thread.run_sync(
            self.llm_service.generate_response, closing_prompt
        )

    def _get_agent_display_name(self) -> str:
        """Get the display name for the agent in UI."""
        return "therapist"
