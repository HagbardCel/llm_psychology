"""
Psychoanalyst Agent for conducting therapy sessions.

This agent conducts the main therapeutic conversations based on the
established therapy plan and selected therapy style.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from agents.base_agent import BaseConversationalAgent
from agents.session_manager import ConversationContext
from context.user_context import UserContext
from models.data_models import Message, Session, TherapyPlan, UserProfile
from prompts.psychoanalyst_prompts import (
    CLOSING_SESSION_PROMPT,
    CONTINUE_SESSION_PROMPT,
    INITIAL_SESSION_PROMPT,
)
from services.db_service import DatabaseService
from services.llm_service import LLMService
from services.rag_service import RAGService
from services.style_service import style_service
from src.orchestration.models import AgentResponse, ConversationContext as OrchestratorContext, WorkflowState
from ui.base_ui import BaseUI


class PsychoanalystAgent(BaseConversationalAgent):
    """
    Agent responsible for conducting therapy sessions.

    This agent has two modes:
    1. Legacy mode: Full session management via BaseConversationalAgent
    2. Orchestrator mode: Pure business logic, returns prompts
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: DatabaseService,
        rag_service: RAGService,
        user_context: Optional[UserContext] = None,
    ):
        """
        Initialize the Psychoanalyst Agent.

        Args:
            llm_service: The LLM service for generating responses
            db_service: The database service for storing sessions
            rag_service: The RAG service for retrieving domain knowledge
            user_context: User context (optional, for legacy mode)
        """
        if user_context:
            super().__init__(llm_service, db_service, user_context)
        else:
            # For orchestrator mode without full initialization
            self.llm_service = llm_service
            self.db_service = db_service
            self.user_context = user_context
        self.rag_service = rag_service

    # ===== NEW ORCHESTRATOR INTERFACE =====

    async def process_message(
        self, message: str, context: OrchestratorContext
    ) -> AgentResponse:
        """
        Process user message during therapy session (orchestrator interface).

        This is the new interface for use with the orchestration layer.
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

            selected_style = therapy_plan.selected_style

            # Check if this is the first message (initial greeting)
            if len(context.message_history) == 0:
                prompt = self._build_initial_session_prompt(context.user_profile, therapy_plan)
            else:
                # Build continuation prompt with RAG context
                prompt = await self._build_continuation_prompt(
                    message, context, therapy_plan, selected_style
                )

            # Check if session should end
            if context.is_time_up:
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

    def _build_initial_session_prompt(
        self, user_profile: UserProfile, therapy_plan: TherapyPlan
    ) -> str:
        """
        Build initial greeting prompt for therapy session.

        Args:
            user_profile: User's profile
            therapy_plan: Therapy plan

        Returns:
            Initial prompt for LLM
        """
        selected_style = therapy_plan.selected_style
        user_name = user_profile.name
        plan_context = self._build_plan_context(therapy_plan)

        # Use style-specific prompt if available
        if selected_style and style_service.get_style_pack(selected_style):
            therapist_prompt = style_service.get_psychoanalyst_prompt(selected_style)
            return f"""
{therapist_prompt}

Context for this session:
{plan_context}

User's name: {user_name}

Please provide an appropriate initial greeting for the session.
"""
        else:
            return INITIAL_SESSION_PROMPT.format(
                user_name=user_name, plan_context=plan_context
            )

    async def _build_continuation_prompt(
        self,
        message: str,
        context: OrchestratorContext,
        therapy_plan: TherapyPlan,
        selected_style: str,
    ) -> str:
        """
        Build continuation prompt with RAG context.

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

        # Retrieve relevant knowledge
        if selected_style:
            knowledge_source = style_service.get_knowledge_source(selected_style)
            context_knowledge = self.rag_service.retrieve_relevant_knowledge(
                recent_context, n_results=1, filter_source=knowledge_source
            )
        else:
            context_knowledge = self.rag_service.retrieve_relevant_knowledge(
                recent_context, n_results=1
            )

        # Build plan context
        plan_context = self._build_plan_context(therapy_plan)

        # Use style-specific prompt if available
        if selected_style and style_service.get_style_pack(selected_style):
            therapist_prompt = style_service.get_psychoanalyst_prompt(selected_style)
            knowledge_text = (
                context_knowledge[0]["content"] if context_knowledge else "None"
            )

            return f"""
{therapist_prompt}

Context for this session:
{plan_context}

Additional relevant knowledge:
{knowledge_text}

Please continue the session based on the conversation history and maintain your therapeutic approach.
"""
        else:
            knowledge_text = (
                context_knowledge[0]["content"] if context_knowledge else "None"
            )
            return CONTINUE_SESSION_PROMPT.format(
                plan_context=plan_context,
                additional_knowledge=knowledge_text,
                time_prompt="",
            )

    def _should_offer_extension(self, context: OrchestratorContext) -> bool:
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

    def _build_plan_context(self, therapy_plan: TherapyPlan) -> str:
        """
        Build the therapy plan context string.

        Args:
            therapy_plan: Therapy plan

        Returns:
            Formatted plan context
        """
        selected_style = therapy_plan.selected_style
        plan_focus = therapy_plan.plan_details.get("focus", "")

        # Get relevant knowledge
        if selected_style:
            knowledge_source = style_service.get_knowledge_source(selected_style)
            relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(
                plan_focus, n_results=2, filter_source=knowledge_source
            )
        else:
            relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(
                plan_focus, n_results=2
            )

        # Build context
        context = f"""
        Therapy Plan (Version {therapy_plan.version}):
        Focus: {therapy_plan.plan_details.get('focus', 'General exploration')}
        Goals: {therapy_plan.plan_details.get('goals', 'Explore thoughts and feelings')}
        Techniques: {therapy_plan.plan_details.get('techniques', 'Active listening and reflection')}

        Relevant Psychological Knowledge:
        """

        for i, knowledge in enumerate(relevant_knowledge, 1):
            context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"

        return context

    # ===== LEGACY INTERFACE (BaseConversationalAgent implementation) =====

    async def conduct_session(
        self, therapy_plan: TherapyPlan, session_duration_minutes: int, ui: BaseUI
    ) -> Session:
        """
        Conduct a therapy session based on the provided therapy plan (legacy interface).

        This method uses the base class session management with proper extension handling.

        Args:
            therapy_plan: The therapy plan to follow
            session_duration_minutes: Duration of the session
            ui: The UI interface

        Returns:
            Completed session
        """
        # Validate that therapy_plan is provided
        if therapy_plan is None:
            from exceptions import PsychoanalystAgentError

            raise PsychoanalystAgentError(
                "Therapy plan is required to conduct a session"
            )

        # Delegate to base class with therapy plan as context
        return await super().conduct_session(therapy_plan, session_duration_minutes, ui)

    # Abstract method implementations for BaseConversationalAgent

    async def get_initial_prompt(self, therapy_plan: TherapyPlan) -> str:
        """Get the initial prompt for the therapy session."""
        selected_style = therapy_plan.selected_therapy_style

        # Get user profile for personalization
        user_profile = self.db_service.get_user_profile(self.user_context.user_id)
        user_name = user_profile.name if user_profile else "Client"

        # Get plan context
        plan_context = self._build_plan_context(therapy_plan)

        # Use style-specific prompt if available
        if selected_style and style_service.get_style_pack(selected_style):
            therapist_prompt = style_service.get_psychoanalyst_prompt(selected_style)
            return f"""
{therapist_prompt}

Context for this session:
{plan_context}

User's name: {user_name}

Please provide an appropriate initial greeting for the session.
"""
        else:
            return INITIAL_SESSION_PROMPT.format(
                user_name=user_name, plan_context=plan_context
            )

    async def handle_user_message(
        self, message: str, conv_context: ConversationContext
    ) -> str:
        """Handle a user message and generate a therapy response."""
        therapy_plan = conv_context.get("therapy_plan")
        selected_style = (
            therapy_plan.selected_therapy_style if therapy_plan else None
        )

        # Get relevant RAG knowledge
        recent_context = " ".join(
            [
                msg.content
                for msg in conv_context.session_context.session.transcript[-3:]
            ]
        )

        if selected_style:
            knowledge_source = style_service.get_knowledge_source(selected_style)
            context_knowledge = self.rag_service.retrieve_relevant_knowledge(
                recent_context, n_results=1, filter_source=knowledge_source
            )
        else:
            context_knowledge = self.rag_service.retrieve_relevant_knowledge(
                recent_context, n_results=1
            )

        # Build response prompt
        plan_context = conv_context.get("plan_context", "")
        context_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in conv_context.session_context.session.transcript
        ]

        if selected_style and style_service.get_style_pack(selected_style):
            therapist_prompt = style_service.get_psychoanalyst_prompt(selected_style)
            response_prompt = f"""
{therapist_prompt}

Context for this session:
{plan_context}

Additional relevant knowledge:
{context_knowledge[0]['content'] if context_knowledge else 'None'}

Please continue the session based on the conversation history and maintain your therapeutic approach.
"""
        else:
            response_prompt = CONTINUE_SESSION_PROMPT.format(
                plan_context=plan_context,
                additional_knowledge=context_knowledge[0]["content"]
                if context_knowledge
                else "None",
                time_prompt="",
            )

        return self.llm_service.generate_response(response_prompt, context_messages)

    async def get_initial_conversation_context(
        self, therapy_plan: TherapyPlan
    ) -> Dict[str, Any]:
        """Get initial conversation context data."""
        return {
            "therapy_plan": therapy_plan,
            "plan_context": self._build_plan_context(therapy_plan),
        }

    # Hook method overrides

    async def pre_conversation_setup(
        self, session: Session, therapy_plan: TherapyPlan, ui: BaseUI
    ) -> None:
        """Display therapy session setup information."""
        user_profile = self.db_service.get_user_profile(self.user_context.user_id)
        user_name = user_profile.name if user_profile else "Client"
        selected_style = therapy_plan.selected_therapy_style

        await ui.display_system_status(f"Starting therapy session for {user_name}...")
        if selected_style:
            await ui.display_system_status(
                f"Therapy Style: {selected_style.upper()}"
            )
        await ui.display_system_status(
            f"Session Focus: {therapy_plan.plan_details.get('focus', 'Exploring your thoughts and feelings')}"
        )
        await ui.display_system_status(
            "You can end the session at any time by typing 'quit', 'exit', or 'bye'."
        )
        await ui.display_system_status("Please share what's on your mind today.\n")

    async def get_closing_response(
        self, conv_context: ConversationContext
    ) -> Optional[str]:
        """Generate a closing response for the therapy session."""
        therapy_plan = conv_context.get("therapy_plan")
        selected_style = (
            therapy_plan.selected_therapy_style if therapy_plan else None
        )
        plan_context = conv_context.get("plan_context", "")

        if selected_style and style_service.get_style_pack(selected_style):
            therapist_prompt = style_service.get_psychoanalyst_prompt(selected_style)
            closing_prompt = f"""
{therapist_prompt}

Context for this session:
{plan_context}

Please provide an appropriate closing for the session.
"""
        else:
            closing_prompt = CLOSING_SESSION_PROMPT.format(plan_context=plan_context)

        return self.llm_service.generate_response(closing_prompt)

    def _get_agent_display_name(self) -> str:
        """Get the display name for the agent in UI."""
        return "therapist"
