"""
Trio-native agent orchestrator for coordinating therapy workflow.

This module provides the main entry point for all user interactions,
routing requests to appropriate agents and managing the overall workflow
using Trio's structured concurrency.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import trio

from container.service_container import ServiceContainer
from context.user_context import UserContext
from models.data_models import Message, Session, UserProfile, UserStatus
from orchestration.models import AgentResponse, SessionInfo, WorkflowState
from orchestration.trio_conversation_manager import TrioConversationManager
from orchestration.trio_workflow_engine import TrioWorkflowEngine

# Agent imports moved to factory methods to avoid circular dependency

logger = logging.getLogger(__name__)


class TrioAgentOrchestrator:
    """
    Trio-native orchestrator for agent execution and workflow management.

    This is the main entry point for all user interactions. It:
    - Routes requests to appropriate agents based on workflow state
    - Manages agent lifecycle with Trio nurseries
    - Coordinates with TrioWorkflowEngine and TrioConversationManager
    - Handles state transitions
    """

    def __init__(
        self,
        service_container: ServiceContainer,
        workflow_engine: TrioWorkflowEngine,
        conversation_manager: TrioConversationManager,
        nursery: trio.Nursery,
    ):
        """
        Initialize the Trio agent orchestrator.

        Args:
            service_container: Container providing access to services and agents
            workflow_engine: Engine for workflow state management
            conversation_manager: Manager for conversation and streaming
            nursery: Trio nursery for background tasks
        """
        self.service_container = service_container
        self.workflow_engine = workflow_engine
        self.conversation_manager = conversation_manager
        self.nursery = nursery
        self.agents: dict[str, Any] = {}  # Cache of agent instances

    async def process_message(
        self, user_id: str, message: str, session_id: str | None = None
    ) -> AsyncIterator[str]:
        """
        Process user message and stream response using Trio.

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

            # Add user message to history (skip empty messages used for
            # initial greetings)
            if message.strip():
                await self.conversation_manager.add_message(session_id, "user", message)

            # Get workflow state
            state = await self.workflow_engine.get_user_state(user_id)
            logger.info(f"User {user_id} workflow state: {state}")

            # Special handling for NEW state: create placeholder user profile
            if state == WorkflowState.NEW:
                logger.info(f"Processing NEW user state for {user_id}")

                # Check if profile exists, if not create guest profile
                try:
                    user_profile = await self.service_container.get(
                        "trio_db_service"
                    ).get_user_profile(user_id)
                    if not user_profile:
                        logger.info(f"Creating guest profile for {user_id}")
                        await self.create_user_profile(
                            user_id=user_id, name="Guest", birthdate="", profession=""
                        )
                except Exception as e:
                    logger.error(
                        f"Error checking/creating guest profile: {e}", exc_info=True
                    )

            # Get appropriate agent
            agent_type = self.workflow_engine.get_current_agent(state)
            logger.info(f"Routing to agent: {agent_type}")

            # Get conversation context
            context = await self.conversation_manager.get_context(session_id)

            # Get or create agent instance
            agent = await self._get_or_create_agent(agent_type, user_id)

            # Call agent to process message and get response
            agent_response = await agent.process_message(message, context)
            logger.info(
                f"Agent {agent_type} returned action: {agent_response.next_action}"
            )

            # Stream the agent's content through LLM
            async for chunk in self.conversation_manager.stream_response(
                agent_response.content, context
            ):
                yield chunk

            # Handle state transitions based on agent response
            await self._handle_agent_response(user_id, agent_response)

        except Exception as e:
            import traceback

            # Get full stacktrace
            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))

            # Log the error
            logger.error(
                f"CRITICAL ERROR processing message for user {user_id}: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            logger.error(
                f"Error occurred at session_id: "
                f"{session_id if 'session_id' in locals() else 'NOT_SET'}"
            )
            logger.error(
                f"User state: {state if 'state' in locals() else 'NOT_RETRIEVED'}"
            )

            # Return detailed error with stacktrace for debugging
            error_msg = f"""
ERROR: {type(e).__name__}: {str(e)}

Session ID: {session_id if "session_id" in locals() else "NOT_SET"}
User State: {state if "state" in locals() else "NOT_RETRIEVED"}

STACKTRACE:
{tb_str}
"""
            yield error_msg

    async def start_session(
        self, user_id: str, session_type: str = "THERAPY"
    ) -> SessionInfo:
        """
        Start a new therapy session and send an initial greeting if appropriate.

        Args:
            user_id: User identifier
            session_type: Type of session to start

        Returns:
            Session information, including whether an initial message is being sent.

        Raises:
            ValueError: If user not found or invalid state
        """
        try:
            logger.info(f"Starting session for user {user_id}, type: {session_type}")
            has_initial_message = False

            # Get current workflow state
            state = await self.workflow_engine.get_user_state(user_id)
            agent_type = self.workflow_engine.get_current_agent(state)
            session_id = await self._create_session(user_id)

            # Proactively send an initial message for certain states
            if state in [
                WorkflowState.NEW,
                WorkflowState.INTAKE_IN_PROGRESS,
                WorkflowState.THERAPY_IN_PROGRESS,
            ]:
                logger.info(
                    f"State {state} qualifies for a proactive initial greeting."
                )
                has_initial_message = True

                # Trigger the agent's normal message processing with an empty message
                # This will cause the agent to generate its initial greeting
                self.nursery.start_soon(
                    self._send_initial_greeting, user_id, session_id
                )
                logger.info(f"Scheduled initial greeting for session {session_id}")

            # Build session info
            session_info = SessionInfo(
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
                workflow_state=state,
                created_at=datetime.now(),
                has_initial_message=has_initial_message,
            )

            logger.info(
                f"Started session {session_id} for user {user_id} "
                f"with agent {agent_type} in state {state}. "
                f"Initial message sent: {has_initial_message}"
            )
            return session_info

        except Exception as e:
            logger.error(f"Error starting session: {e}", exc_info=True)
            raise

    async def get_user_state(self, user_id: str) -> WorkflowState:
        """
        Get current workflow state for a user.

        Args:
            user_id: User identifier

        Returns:
            Current workflow state
        """
        return await self.workflow_engine.get_user_state(user_id)

    async def create_user_profile(
        self, user_id: str, name: str, birthdate: str, profession: str
    ) -> UserProfile:
        """
        Create a new user profile.

        Args:
            user_id: User identifier
            name: User's name
            birthdate: User's birthdate (ISO format string)
            profession: User's profession

        Returns:
            Created user profile
        """
        try:
            # Parse birthdate if provided
            birthdate_dt = None
            if birthdate:
                try:
                    birthdate_dt = datetime.fromisoformat(birthdate)
                except ValueError:
                    logger.warning(f"Invalid birthdate format: {birthdate}")

            # Create user profile
            user_profile = UserProfile(
                user_id=user_id,
                name=name,
                birthdate=birthdate_dt,
                profession=profession,
                status=UserStatus.PROFILE_ONLY,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            # Save to database
            trio_db_service = self.service_container.get("trio_db_service")
            success = await trio_db_service.save_user_profile(user_profile)

            if not success:
                raise ValueError("Failed to save user profile to database")

            logger.info(f"Created user profile for {user_id}: {name}")
            return user_profile

        except Exception as e:
            logger.error(f"Error creating user profile: {e}", exc_info=True)
            raise

    async def _create_session(self, user_id: str) -> str:
        """
        Create a new session in the database.

        Args:
            user_id: User identifier

        Returns:
            Session ID

        Raises:
            ValueError: If session creation fails
        """
        try:
            session_id = str(uuid.uuid4())

            # Create session object
            session = Session(
                session_id=session_id,
                user_id=user_id,
                timestamp=datetime.now(),
                transcript=[
                    Message(
                        role="system",
                        content="Session started",
                        timestamp=datetime.now(),
                    )
                ],
                topics=[],
            )

            # Save to database
            trio_db_service = self.service_container.get("trio_db_service")
            success = await trio_db_service.save_session(session)

            if not success:
                raise ValueError("Failed to save session to database")

            logger.info(f"Created session {session_id} for user {user_id}")
            return session_id

        except Exception as e:
            logger.error(f"Error creating session: {e}", exc_info=True)
            raise

    # ===== Agent Factory Methods =====

    async def _create_intake_agent(self, user_id: str):
        """
        Create a TrioIntakeAgent instance for the user.

        Args:
            user_id: User identifier

        Returns:
            TrioIntakeAgent instance
        """
        from agents.trio_intake_agent import TrioIntakeAgent

        llm_service = self.service_container.get("llm_service")
        db_service = self.service_container.get("trio_db_service")
        user_context = UserContext(user_id=user_id)

        logger.info(f"Creating TrioIntakeAgent for user {user_id}")
        return TrioIntakeAgent(llm_service, db_service, user_context)

    async def _create_assessment_agent(self, user_id: str):
        """
        Create a TrioAssessmentAgent instance for the user.

        Args:
            user_id: User identifier

        Returns:
            TrioAssessmentAgent instance
        """
        from agents.trio_assessment_agent import TrioAssessmentAgent

        llm_service = self.service_container.get("llm_service")
        db_service = self.service_container.get("trio_db_service")
        rag_service = self.service_container.get("rag_service")
        user_context = UserContext(user_id=user_id)

        logger.info(f"Creating TrioAssessmentAgent for user {user_id}")
        return TrioAssessmentAgent(llm_service, db_service, rag_service, user_context)

    async def _create_psychoanalyst_agent(self, user_id: str):
        """
        Create a TrioPsychoanalystAgent instance for the user.

        Args:
            user_id: User identifier

        Returns:
            TrioPsychoanalystAgent instance
        """
        from agents.trio_psychoanalyst_agent import TrioPsychoanalystAgent

        llm_service = self.service_container.get("llm_service")
        db_service = self.service_container.get("trio_db_service")
        rag_service = self.service_container.get("rag_service")
        user_context = UserContext(user_id=user_id)

        logger.info(f"Creating TrioPsychoanalystAgent for user {user_id}")
        return TrioPsychoanalystAgent(
            llm_service, db_service, rag_service, user_context
        )

    async def _create_reflection_agent(self, user_id: str):
        """
        Create a TrioReflectionAgent instance for the user.

        Args:
            user_id: User identifier

        Returns:
            TrioReflectionAgent instance
        """
        from agents.trio_memory_agent import TrioMemoryAgent
        from agents.trio_planning_agent import TrioPlanningAgent
        from agents.trio_reflection_agent import TrioReflectionAgent

        llm_service = self.service_container.get("llm_service")
        db_service = self.service_container.get("trio_db_service")
        rag_service = self.service_container.get("rag_service")
        user_context = UserContext(user_id=user_id)

        # Reflection agent needs memory and planning agents
        memory_agent = TrioMemoryAgent(
            llm_service, db_service, rag_service, user_context
        )
        planning_agent = TrioPlanningAgent(
            llm_service, db_service, rag_service, user_context, memory_agent
        )

        logger.info(f"Creating TrioReflectionAgent for user {user_id}")
        return TrioReflectionAgent(
            llm_service,
            db_service,
            rag_service,
            user_context,
            memory_agent,
            planning_agent,
        )

    async def _get_or_create_agent(self, agent_type: str, user_id: str):
        """
        Get or create an agent instance.

        Args:
            agent_type: Type of agent to get
            user_id: User identifier

        Returns:
            Agent instance

        Raises:
            ValueError: If agent_type is unknown
        """
        cache_key = f"{agent_type}_{user_id}"

        if cache_key in self.agents:
            logger.debug(f"Retrieved cached agent: {cache_key}")
            return self.agents[cache_key]

        # Create agent instance based on type
        logger.info(f"Creating agent: {agent_type} for user {user_id}")

        if agent_type == "INTAKE":
            agent = await self._create_intake_agent(user_id)
        elif agent_type == "ASSESSMENT":
            agent = await self._create_assessment_agent(user_id)
        elif agent_type == "PSYCHOANALYST":
            agent = await self._create_psychoanalyst_agent(user_id)
        elif agent_type == "REFLECTION":
            agent = await self._create_reflection_agent(user_id)
        else:
            logger.error(f"Unknown agent type: {agent_type}")
            raise ValueError(f"Unknown agent type: {agent_type}")

        # Cache the agent instance
        self.agents[cache_key] = agent
        logger.info(f"Cached agent: {cache_key}")

        return agent

    async def _send_initial_greeting(self, user_id: str, session_id: str):
        """
        Send initial greeting by processing an empty message through the agent.

        This triggers the agent's normal message processing flow, which will
        generate an appropriate initial greeting based on the conversation context.

        Args:
            user_id: User identifier
            session_id: Session identifier
        """
        try:
            # Small delay to ensure session is fully initialized
            await trio.sleep(0.1)

            # Send typing start
            await self.conversation_manager.send_typing_indicator(session_id, True)

            # Process empty message to trigger initial greeting
            async for chunk in self.process_message(user_id, "", session_id):
                await self.conversation_manager.send_stream_chunk(
                    session_id, chunk, is_complete=False
                )

            # Send completion
            await self.conversation_manager.send_stream_chunk(
                session_id, "", is_complete=True
            )

            # Send typing stop
            await self.conversation_manager.send_typing_indicator(session_id, False)

            logger.info(f"Initial greeting sent for session {session_id}")
        except Exception as e:
            logger.error(f"Error sending initial greeting: {e}", exc_info=True)

    async def _handle_agent_response(self, user_id: str, agent_response: AgentResponse):
        """
        Handle agent response and execute state transitions.

        Args:
            user_id: User identifier
            agent_response: Response from the agent

        This method processes the agent's next_action and performs
        the appropriate state transition or completion logic.
        """
        action = agent_response.next_action
        logger.info(f"Handling agent response for user {user_id}: action={action}")

        if action == "transition" and agent_response.next_state:
            # Agent wants to transition to a new state
            logger.info(
                f"Transitioning user {user_id} to state: {agent_response.next_state}"
            )
            await self.workflow_engine.transition(user_id, agent_response.next_state)

        elif action == "complete":
            # Agent indicates task completion (e.g., intake finished)
            logger.info(f"Agent completed task for user {user_id}")
            # Metadata might contain completion information
            if agent_response.metadata:
                logger.debug(f"Completion metadata: {agent_response.metadata}")

        elif action == "continue":
            # Agent wants to continue in current state
            logger.debug(f"Continuing in current state for user {user_id}")

        elif action == "await_selection":
            # Agent is waiting for user selection
            logger.info(f"Agent is waiting for selection from user {user_id}")
            if agent_response.metadata:
                logger.debug(f"Selection metadata: {agent_response.metadata}")

        else:
            logger.warning(f"Unknown agent action '{action}' for user {user_id}")
