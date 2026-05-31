"""
TrioTherapistAgent: Trio-native agent for conducting therapy sessions.

This agent conducts the main therapeutic conversations based on the
established therapy plan and selected therapy style.

Pure Trio implementation using structured concurrency.
"""

import logging
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.agents.therapist.prompt_context import (
    build_continuation_prompt_with_context,
    build_plan_context,
    default_style_instructions,
    load_patient_context,
)
from psychoanalyst_app.agents.therapist.response_mode import (
    resolve_response_mode,
)
from psychoanalyst_app.agents.therapist.time_policy import should_offer_extension
from psychoanalyst_app.agents.therapist.topic_detection import is_in_deep_topic
from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.briefing_models import BriefingStatus
from psychoanalyst_app.models.data_models import TherapyPlan, UserProfile
from psychoanalyst_app.models.structured_output_models import DeepTopicSignalOutput
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
)
from psychoanalyst_app.prompts.therapist_prompt_builder import (
    build_initial_prompt,
    build_resumption_prompt,
)
from psychoanalyst_app.prompts.therapist_prompts import CLOSING_SESSION_PROMPT
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag_service import RAGService
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioTherapistAgent:
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
                therapy_plan = await self.db_service.get_current_therapy_plan(
                    context.user_profile.user_id
                )
                context.therapy_plan = therapy_plan

            if not therapy_plan:
                logger.error(
                    "Therapy context recovery found no plan for user %s "
                    "(session=%s)",
                    context.user_profile.user_id,
                    context.session_id,
                )
                return AgentResponse(
                    content=(
                        "Let's stay with what feels most urgent right now. "
                        "Tell me one recent moment when the worry became strongest, "
                        "and we can work from there."
                    ),
                    next_action="continue",
                    workflow_event=None,
                    metadata={"error": "No therapy plan"},
                )

            selected_style = therapy_plan.selected_therapy_style

            # Only an explicit empty turn can produce a session opening. A
            # patient disclosure must never be treated as an initial greeting.
            has_patient_history = any(
                item.role == "user" for item in context.message_history
            )
            if not message.strip() and not has_patient_history:
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
            next_action, workflow_event = resolve_response_mode(
                context,
                should_offer_extension=await self._should_offer_extension(context),
            )

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

        style_instructions = default_style_instructions(
            selected_style, self.style_service
        )

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
        return await build_continuation_prompt_with_context(
            message=message,
            context=context,
            therapy_plan=therapy_plan,
            selected_style=selected_style,
            rag_service=self.rag_service,
            style_service=self.style_service,
            db_service=self.db_service,
        )

    async def _should_offer_extension(self, context: ConversationContext) -> bool:
        """
        Check if session extension should be offered.

        Args:
            context: Conversation context

        Returns:
            True if extension should be offered
        """
        if not should_offer_extension(context, in_deep_topic=False):
            return False
        return should_offer_extension(
            context,
            in_deep_topic=await self._is_in_deep_topic(context),
        )

    async def _is_in_deep_topic(self, context: ConversationContext) -> bool:
        """Return whether the current exchange appears to be in a deep topic."""
        try:
            recent_messages = context.message_history[-6:]
            if not recent_messages:
                return is_in_deep_topic(context)

            transcript_lines: list[str] = []
            for message in recent_messages:
                role = "Therapist" if message.role == "assistant" else "Patient"
                transcript_lines.append(f"{role}: {message.content}")

            prompt = (
                "Assess whether the conversation below is currently in a deep "
                "emotionally sensitive topic where ending now would feel abrupt.\n\n"
                "Return JSON with:\n"
                '- in_deep_topic: boolean\n'
                '- confidence: "high" | "medium" | "low"\n'
                "- rationale: short explanation\n\n"
                "Mark in_deep_topic=true only when there is active emotionally "
                "intense disclosure, unresolved vulnerability, or a critical "
                "breakthrough still unfolding.\n\n"
                "Recent Transcript:\n"
                f"{chr(10).join(transcript_lines)}"
            )
            signal_output = await self.llm_service.generate_structured_output_async(
                prompt,
                DeepTopicSignalOutput,
                method="json_schema",
            )
            if not isinstance(signal_output, DeepTopicSignalOutput):
                signal_output = DeepTopicSignalOutput.model_validate(signal_output)
            return signal_output.in_deep_topic
        except Exception:
            logger.debug(
                "Deep topic signal detection failed; using conservative fallback",
                exc_info=True,
            )
            return is_in_deep_topic(context)

    async def _build_plan_context(self, therapy_plan: TherapyPlan) -> str:
        """
        Build the therapy plan context string using Trio.

        Args:
            therapy_plan: Therapy plan

        Returns:
            Formatted plan context
        """
        return await build_plan_context(
            therapy_plan,
            self.rag_service,
            self.style_service,
        )

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
        return await load_patient_context(
            self.db_service,
            user_id,
            exclude_session_ids=exclude_session_ids,
        )


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
        style_instructions = default_style_instructions(
            selected_style, self.style_service
        )

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
