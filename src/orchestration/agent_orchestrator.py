"""
Agent orchestrator for coordinating therapy workflow.

This module provides the main entry point for all user interactions,
routing requests to appropriate agents and managing the overall workflow.
"""

import logging
import uuid
from datetime import datetime
from typing import AsyncIterator, Dict, Optional

from container.service_container import ServiceContainer
from models.data_models import Session, UserProfile
from orchestration.conversation_manager import ConversationManager
from orchestration.models import AgentResponse, SessionInfo, WorkflowState
from orchestration.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """
    Orchestrates agent execution and workflow management.

    This is the main entry point for all user interactions. It:
    - Routes requests to appropriate agents based on workflow state
    - Manages agent lifecycle
    - Coordinates with WorkflowEngine and ConversationManager
    - Handles state transitions
    """

    def __init__(
        self,
        service_container: ServiceContainer,
        workflow_engine: WorkflowEngine,
        conversation_manager: ConversationManager,
    ):
        """
        Initialize the agent orchestrator.

        Args:
            service_container: Container providing access to services and agents
            workflow_engine: Engine for workflow state management
            conversation_manager: Manager for conversation and streaming
        """
        self.service_container = service_container
        self.workflow_engine = workflow_engine
        self.conversation_manager = conversation_manager
        self.agents: Dict[str, any] = {}  # Cache of agent instances

    async def process_message(
        self, user_id: str, message: str, session_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """
        Process user message and stream response.

        This is the main method for handling user interactions. It:
        1. Determines current workflow state
        2. Gets appropriate agent
        3. Processes message through agent
        4. Streams LLM response
        5. Handles state transitions

        Args:
            user_id: User identifier
            message: User's message
            session_id: Optional session ID (creates new if None)

        Yields:
            Response chunks

        Raises:
            ValueError: If user or session not found
        """
        try:
            logger.info(f"Processing message for user {user_id}")

            # Get or create session
            if not session_id:
                session_id = await self._create_session(user_id)
                logger.info(f"Created new session: {session_id}")

            # Add user message to history
            await self.conversation_manager.add_message(
                session_id, "user", message
            )

            # Get workflow state
            state = await self.workflow_engine.get_user_state(user_id)
            logger.info(f"User {user_id} workflow state: {state}")

            # Get appropriate agent
            agent_type = self.workflow_engine.get_current_agent(state)
            agent = await self._get_or_create_agent(agent_type, user_id)

            # Get conversation context
            context = await self.conversation_manager.get_context(session_id)

            # Process message through agent
            # TODO: This will be updated in Phase 3 when agents are refactored
            # For now, we'll use the conversation manager directly
            logger.info(f"Routing to agent: {agent_type}")

            # Build prompt based on agent type
            prompt = self._build_agent_prompt(agent_type, message, context)

            # Stream response
            async for chunk in self.conversation_manager.stream_response(
                prompt, context
            ):
                yield chunk

            # TODO: Handle state transitions based on agent response
            # This will be implemented in Phase 3

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            error_msg = (
                "I apologize, but I encountered an error processing your message."
            )
            yield error_msg

    def _build_agent_prompt(
        self, agent_type: str, message: str, context
    ) -> str:
        """
        Build agent-specific prompt.

        This is a temporary implementation until agents are refactored
        to return prompts themselves.

        Args:
            agent_type: Type of agent
            message: User message
            context: Conversation context

        Returns:
            Prompt for LLM
        """
        # For now, use simple prompts
        # TODO: Replace with agent.process_message() in Phase 3

        if agent_type == "INTAKE":
            return f"""You are conducting an intake session for a therapy client.
Your goal is to gather information about the user's background, current concerns,
and therapy goals in a warm, empathetic manner.

User message: {message}

Respond thoughtfully and ask follow-up questions to understand their needs better."""

        elif agent_type == "ASSESSMENT":
            return f"""You are assessing which therapy approach would best suit the client
based on their intake session. Consider approaches like Freudian psychoanalysis,
Jungian analysis, and Cognitive Behavioral Therapy (CBT).

User message: {message}

Provide thoughtful recommendations based on what you've learned about the client."""

        elif agent_type == "PSYCHOANALYST":
            style = context.therapy_plan.selected_style if context.therapy_plan else "general"
            return f"""You are a {style} therapist conducting a therapy session.
Use the principles and techniques of {style} therapy.

User message: {message}

Respond therapeutically using your chosen approach."""

        elif agent_type == "REFLECTION":
            return f"""You are reflecting on the therapy session to update the treatment plan.

User message: {message}

Provide insights and recommendations for future sessions."""

        else:
            return message

    async def _create_session(self, user_id: str) -> str:
        """
        Create a new therapy session.

        Args:
            user_id: User identifier

        Returns:
            Session ID
        """
        # Get current workflow state
        state = await self.workflow_engine.get_user_state(user_id)
        agent_type = self.workflow_engine.get_current_agent(state)

        # Create session via database service
        session_id = str(uuid.uuid4())
        db_service = self.service_container.get_db_service()

        # Create session record
        # Note: Using simplified session creation - actual implementation may vary
        db_service.create_session(
            session_id=session_id,
            user_id=user_id,
            session_type=agent_type
        )
        logger.info(
            f"Created session {session_id} for user {user_id} "
            f"with agent {agent_type}"
        )

        return session_id

    async def start_session(
        self, user_id: str, session_type: str
    ) -> SessionInfo:
        """
        Start a new therapy session.

        Args:
            user_id: User identifier
            session_type: Type of session/agent

        Returns:
            Session information
        """
        try:
            # Create session
            session_id = await self._create_session(user_id)

            # Get workflow state
            state = await self.workflow_engine.get_user_state(user_id)

            return SessionInfo(
                session_id=session_id,
                agent_type=session_type,
                workflow_state=state,
                created_at=datetime.now(),
                user_id=user_id,
            )

        except Exception as e:
            logger.error(f"Error starting session: {e}", exc_info=True)
            raise

    async def get_user_state(self, user_id: str) -> WorkflowState:
        """
        Get current workflow state for user.

        Args:
            user_id: User identifier

        Returns:
            Current workflow state
        """
        return await self.workflow_engine.get_user_state(user_id)

    async def transition_state(
        self, user_id: str, new_state: WorkflowState
    ) -> None:
        """
        Transition user to new workflow state.

        Args:
            user_id: User identifier
            new_state: Target workflow state
        """
        await self.workflow_engine.transition(user_id, new_state)
        logger.info(f"Transitioned user {user_id} to state {new_state}")

    async def _get_or_create_agent(
        self, agent_type: str, user_id: str
    ) -> any:
        """
        Get or create agent instance.

        Args:
            agent_type: Type of agent to get
            user_id: User identifier

        Returns:
            Agent instance
        """
        # TODO: Implement agent caching and lifecycle management
        # For now, return a placeholder
        cache_key = f"{agent_type}_{user_id}"

        if cache_key not in self.agents:
            # Create agent based on type
            if agent_type == "INTAKE":
                agent = self.service_container.get_intake_agent()
            elif agent_type == "ASSESSMENT":
                agent = self.service_container.get_assessment_agent()
            elif agent_type == "PSYCHOANALYST":
                agent = self.service_container.get_psychoanalyst_agent()
            elif agent_type == "REFLECTION":
                agent = self.service_container.get_reflection_agent()
            else:
                raise ValueError(f"Unknown agent type: {agent_type}")

            self.agents[cache_key] = agent
            logger.info(f"Created agent: {agent_type} for user {user_id}")

        return self.agents[cache_key]

    async def create_user_profile(
        self, name: str, birthdate: str, profession: str
    ) -> UserProfile:
        """
        Create a new user profile.

        Args:
            name: User's name
            birthdate: User's birthdate
            profession: User's profession

        Returns:
            Created user profile
        """
        user_id = str(uuid.uuid4())
        profile = UserProfile(
            id=user_id,
            name=name,
            birthdate=birthdate,
            profession=profession,
        )

        await self.service_container.get_db_service().create_user_profile(profile)
        logger.info(f"Created user profile: {user_id}")

        return profile
