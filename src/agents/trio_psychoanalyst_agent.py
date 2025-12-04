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

from config import settings
from context.user_context import UserContext
from models.briefing_models import BriefingStatus
from models.data_models import Session, TherapyPlan, UserProfile, UserStatus
from orchestration.models import AgentResponse, ConversationContext, WorkflowState
from prompts.psychoanalyst_prompts import (
    CLOSING_SESSION_PROMPT,
    CONTINUE_SESSION_PROMPT,
    INITIAL_SESSION_PROMPT,
)
from services.llm_service import LLMService
from services.rag_service import RAGService
from services.style_service import style_service
from services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioPsychoanalystAgent:
    """
    Trio-native agent responsible for conducting therapy sessions.

    This agent has two modes:
    1. Legacy mode: Full session management (limited support in Trio version)
    2. Orchestrator mode: Pure business logic, returns prompts

    Uses Trio's structured concurrency for all async operations.
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGService,
        user_context: UserContext | None = None,
        conversation_manager: Any | None = None,
    ):
        """
        Initialize the Trio Psychoanalyst Agent.

        Args:
            llm_service: The LLM service for generating responses (synchronous)
            db_service: The Trio database service for storing sessions
            rag_service: The RAG service for retrieving domain knowledge (synchronous)
            user_context: User context (optional, for legacy mode)
            conversation_manager: Conversation manager for streaming (optional)
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.conversation_manager = conversation_manager

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

            if age_days <= settings.BRIEFING_VALIDITY_DAYS:
                return BriefingStatus.FRESH
            elif age_days <= settings.STALE_BRIEFING_DAYS:
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
        # Extract briefing components
        narrative = briefing.get("narrative_handoff", "")
        observations = briefing.get("patient_observations", "")
        plan_notes = briefing.get("plan_progression_notes", "")
        relationship = briefing.get("relationship_quality", "building")
        session_number = briefing.get("session_count", 0) + 1
        recommended = briefing.get("recommended_approach", {})

        # Format continuity points
        continuity_points = briefing.get("continuity_points", [])
        continuity_text = "\n".join([f"  - {point}" for point in continuity_points[:3]])

        # Format key themes with priority
        key_themes = briefing.get("key_themes", [])
        high_priority_themes = [t for t in key_themes if t.get("priority") == "high"]
        themes_text = ", ".join([t.get("theme", "") for t in high_priority_themes[:3]])

        # Format suggested questions
        suggested_questions = recommended.get("suggested_questions", [])
        questions_text = "\n".join(
            [f"  {i + 1}. {q}" for i, q in enumerate(suggested_questions)]
        )

        prompt = f"""You are conducting a {therapy_plan.selected_therapy_style} therapy session. This is session #{session_number} with {user_profile.name}.

THERAPEUTIC CONTEXT:
Relationship Stage: {relationship.capitalize()}
Last Session Date: {briefing.get("last_session_date", "Recent")}

SUPERVISOR'S BRIEFING:
{narrative}

CLINICAL OBSERVATIONS FROM PREVIOUS SESSION:
{observations}

TREATMENT PLAN PROGRESSION:
{plan_notes}

EMOTIONAL STATE:
- Current: {briefing.get("emotional_summary", {}).get("last_session", "Not specified")}
- Trend: {briefing.get("emotional_summary", {}).get("trend", "Not specified")}
- Note: {briefing.get("emotional_summary", {}).get("note", "")}

CONTINUITY POINTS TO FOLLOW UP ON:
{continuity_text}

CURRENT HIGH-PRIORITY THEMES:
{themes_text if themes_text else "No specific themes identified"}

PROGRESS HIGHLIGHTS:
{chr(10).join([f"  ✓ {h}" for h in briefing.get("progress_highlights", [])[:3]])}

UNRESOLVED ISSUES REQUIRING ATTENTION:
{chr(10).join([f"  • {issue}" for issue in briefing.get("unresolved_issues", [])[:3]])}

RECOMMENDED APPROACH FOR THIS SESSION:
Tone: {recommended.get("opening_tone", "Warm and welcoming")}
Focus: {recommended.get("opening_focus", "General check-in")}
Avoid: {recommended.get("things_to_avoid", "Pushing too hard")}

Suggested Opening Questions (choose one or synthesize your own based on the above):
{questions_text}

Session Goals:
{chr(10).join([f"  {i + 1}. {g}" for i, g in enumerate(recommended.get("therapeutic_goals_for_session", []))])}

YOUR TASK:
The patient has just entered the session. They have not spoken yet. Based on the comprehensive briefing above, generate a natural, conversational opening greeting that:

1. Welcomes them back warmly and authentically
2. Demonstrates continuity by referencing something specific from your last session together
3. Acknowledges their emotional state or progress if appropriate
4. Invites them to begin speaking in an open-ended way
5. Maintains the recommended tone and focus

IMPORTANT CONSTRAINTS:
- Keep your greeting to 2-4 sentences
- Be specific and personal - reference actual themes or topics from the briefing
- Sound natural and conversational, not scripted or formulaic
- Don't overwhelm them with everything from the briefing - choose what feels most relevant
- Match the therapeutic style ({therapy_plan.selected_therapy_style}) in your language and approach

Generate your opening greeting now:"""

        # Add specific guidance for STALE briefings
        if status == BriefingStatus.STALE:
            days_since = (
                datetime.now()
                - datetime.fromisoformat(
                    briefing.get("generated_at", datetime.now().isoformat())
                )
            ).days
            prompt += f"""

IMPORTANT - STALE BRIEFING NOTICE:
It has been approximately {days_since} days since the last session. The briefing above may not reflect the patient's current state. When generating your greeting:

1. Acknowledge the time gap explicitly but gently
2. Don't assume they're in the same emotional place as the briefing suggests
3. Be more open-ended and exploratory rather than assuming continuity
4. Focus on "what's been on your mind recently" rather than specific past themes
5. Use the briefing as background context, not as current truth

Example approach: "Welcome back, {user_profile.name}. It's been a while since we last spoke. I'm curious to hear what's been on your mind recently."
"""

        return prompt

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
                    next_state=None,
                    metadata={"error": "No therapy plan"},
                )

            selected_style = therapy_plan.selected_therapy_style

            # Check if this is the first message (initial greeting)
            # This path is now less likely to be used for initial greetings
            # due to the proactive prompt in start_session.
            if not context.message_history or len(context.message_history) <= 1:
                prompt = await self._build_initial_session_prompt(
                    context.user_profile, therapy_plan
                )
            else:
                # Build continuation prompt with RAG context
                prompt = await self._build_continuation_prompt(
                    message, context, therapy_plan, selected_style
                )

            # Check if session should end
            if context.user_profile.status == UserStatus.ASSESSMENT_COMPLETE:
                # First message in therapy - transition to IN_PROGRESS
                next_action = "transition"
                next_state = WorkflowState.THERAPY_IN_PROGRESS
            elif context.user_profile.status == UserStatus.PLAN_COMPLETE:
                # Starting new session after plan update - transition to IN_PROGRESS
                next_action = "transition"
                next_state = WorkflowState.THERAPY_IN_PROGRESS
            elif context.is_time_up:
                next_action = "transition"
                next_state = WorkflowState.REFLECTION_IN_PROGRESS
            elif self._should_offer_extension(context):
                next_action = "offer_extension"
                next_state = None
            else:
                next_action = "continue"
                next_state = None

            return AgentResponse(
                content=prompt,
                next_action=next_action,
                next_state=next_state,
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
                next_state=None,
                metadata={"error": str(e)},
            )

    async def _build_initial_session_prompt(
        self, user_profile: UserProfile, therapy_plan: TherapyPlan
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

        # Get style instructions
        style_instructions = "Conduct a general psychoanalytic session."
        if selected_style and style_service.get_style_pack(selected_style):
            style_instructions = style_service.get_psychoanalyst_prompt(selected_style)

        return INITIAL_SESSION_PROMPT.format(
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
            knowledge_source = style_service.get_knowledge_source(selected_style)
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

        # Get style instructions
        style_instructions = "Conduct a general psychoanalytic session."
        if selected_style and style_service.get_style_pack(selected_style):
            style_instructions = style_service.get_psychoanalyst_prompt(selected_style)

        knowledge_text = (
            context_knowledge[0]["content"] if context_knowledge else "None"
        )

        return CONTINUE_SESSION_PROMPT.format(
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
            knowledge_source = style_service.get_knowledge_source(selected_style)
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

    # ===== LEGACY INTERFACE (limited support) =====

    async def get_initial_prompt_legacy(self, therapy_plan: TherapyPlan) -> str:
        """
        Get the initial prompt for the therapy session using Trio.

        Args:
            therapy_plan: Therapy plan

        Returns:
            Initial prompt string
        """
        selected_style = therapy_plan.selected_therapy_style

        # Get user profile for personalization
        user_profile = await self.db_service.get_user_profile(self.user_context.user_id)
        user_name = user_profile.name if user_profile else "Client"

        # Get plan context
        plan_context = await self._build_plan_context(therapy_plan)

        # Get style instructions
        style_instructions = "Conduct a general psychoanalytic session."
        if selected_style and style_service.get_style_pack(selected_style):
            style_instructions = style_service.get_psychoanalyst_prompt(selected_style)

        return INITIAL_SESSION_PROMPT.format(
            user_name=user_name,
            plan_context=plan_context,
            style_instructions=style_instructions,
        )

    async def handle_user_message(
        self, message: str, session: Session, therapy_plan: TherapyPlan
    ) -> str:
        """
        Handle a user message and generate a therapy response using Trio.

        Args:
            message: User's message
            session: Current session
            therapy_plan: Therapy plan

        Returns:
            LLM response string
        """
        selected_style = therapy_plan.selected_therapy_style if therapy_plan else None

        # Get relevant RAG knowledge
        recent_context = " ".join([msg.content for msg in session.transcript[-3:]])

        # Retrieve knowledge (run in thread)
        if selected_style:
            knowledge_source = style_service.get_knowledge_source(selected_style)
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

        # Build response prompt
        plan_context = await self._build_plan_context(therapy_plan)
        context_messages = [
            {"role": msg.role, "content": msg.content} for msg in session.transcript
        ]

        # Get style instructions
        style_instructions = "Conduct a general psychoanalytic session."
        if selected_style and style_service.get_style_pack(selected_style):
            style_instructions = style_service.get_psychoanalyst_prompt(selected_style)

        knowledge_text = (
            context_knowledge[0]["content"] if context_knowledge else "None"
        )

        response_prompt = CONTINUE_SESSION_PROMPT.format(
            plan_context=plan_context,
            additional_knowledge=knowledge_text,
            time_prompt="",
            style_instructions=style_instructions,
        )

        # Generate response (run in thread)
        return await trio.to_thread.run_sync(
            self.llm_service.generate_response, response_prompt, context_messages
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
        style_instructions = "Conduct a general psychoanalytic session."
        if selected_style and style_service.get_style_pack(selected_style):
            style_instructions = style_service.get_psychoanalyst_prompt(selected_style)

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
