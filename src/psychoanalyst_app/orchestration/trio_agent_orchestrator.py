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

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import TherapyPlan, UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import (
    SessionInfo,
    WorkflowEvent,
    WorkflowState,
)
from psychoanalyst_app.orchestration.orchestrator_helpers import (
    AgentResponseHandler,
    SessionLifecycleManager,
)
from psychoanalyst_app.orchestration.agent_output_validators import is_profile_complete
from psychoanalyst_app.orchestration.process_messages import (
    ensure_profile_for_new_state,
    ensure_session,
    finalize_agent_response,
    record_user_message,
    resolve_agent_and_context,
    stream_agent_response,
)
from psychoanalyst_app.orchestration.profile_helpers import ensure_user_profile
from psychoanalyst_app.orchestration.trio_conversation_manager import TrioConversationManager
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine

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
        self.response_handler = AgentResponseHandler(
            service_container=self.service_container,
            workflow_engine=self.workflow_engine,
            conversation_manager=self.conversation_manager,
            nursery=self.nursery,
            get_agent=self._get_or_create_agent,
        )
        self.session_lifecycle = SessionLifecycleManager(
            service_container=self.service_container,
            workflow_engine=self.workflow_engine,
            conversation_manager=self.conversation_manager,
            nursery=self.nursery,
            process_message=self.process_message,
            run_reflection=self.response_handler.run_reflection,
        )
        self.response_handler.attach_session_callbacks(
            create_session=self.session_lifecycle.create_session,
            end_session=self.session_lifecycle.end_session,
        )

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
        state = None
        try:
            logger.info("Processing message for user %s", user_id)

            session_id = await ensure_session(
                self.session_lifecycle, user_id, session_id
            )

            await record_user_message(
                self.conversation_manager, session_id, message
            )

            state = await self.workflow_engine.get_user_state(user_id)
            logger.info("User %s workflow state: %s", user_id, state)

            await ensure_profile_for_new_state(
                self.service_container, user_id, state
            )

            agent_type, agent, context = await resolve_agent_and_context(
                self.workflow_engine,
                self.conversation_manager,
                self._get_or_create_agent,
                user_id,
                session_id,
                state,
            )
            logger.info("Routing to agent: %s", agent_type)

            agent_response = await agent.process_message(message, context)
            logger.info(
                "Agent %s returned action: %s",
                agent_type,
                agent_response.next_action,
            )
            logger.debug(
                "Agent response: action=%s state=%s direct=%s",
                agent_response.next_action,
                agent_response.next_state,
                (agent_response.metadata or {}).get("is_direct_response"),
            )

            async for chunk in stream_agent_response(
                self.conversation_manager,
                self.service_container,
                agent_type,
                agent,
                agent_response,
                context,
            ):
                yield chunk

            await finalize_agent_response(
                self.service_container,
                self.response_handler,
                user_id,
                session_id,
                agent_response,
            )

        except Exception:
            logger.error(
                "Error processing message (user=%s, session=%s, state=%s)",
                user_id,
                session_id,
                state,
                exc_info=True,
            )
            raise

    async def start_session(
        self,
        user_id: str,
        session_type: str = "therapy",
        *,
        send_initial_message: bool = False,
    ) -> SessionInfo:
        """
        Start a new therapy session and optionally send an initial greeting.

        Args:
            user_id: User identifier
            session_type: Type of session to start
            send_initial_message: If True, schedule an initial therapist message
                (via the current agent) to be streamed over WebSocket.

        Returns:
            Session information, including whether an initial message is being sent.

        Raises:
            ValueError: If user not found or invalid state
        """
        return await self.session_lifecycle.start_session(
            user_id,
            session_type=session_type,
            send_initial_message=send_initial_message,
        )

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
        self, profile_data: dict[str, Any]
    ) -> UserProfile:
        """
        Create a new user profile.

        Args:
            profile_data: Incoming profile data
        Returns:
            Created user profile
        """
        try:
            user_id = profile_data.get("user_id")
            if not user_id:
                raise ValueError("user_id is required for profile creation")

            trio_db_service = self.service_container.get("trio_db_service")
            existing_profile = await trio_db_service.get_user_profile(user_id)
            prior_status = (
                existing_profile.status if existing_profile else UserStatus.PROFILE_ONLY
            )

            user_profile = await ensure_user_profile(
                trio_db_service, user_id, profile_data
            )

            if (
                prior_status == UserStatus.PROFILE_ONLY
                and is_profile_complete(user_profile)
            ):
                await self.workflow_engine.transition(
                    user_id,
                    WorkflowState.INTAKE_IN_PROGRESS,
                    event=WorkflowEvent.START_INTAKE,
                )
                updated = await trio_db_service.get_user_profile(user_id)
                if updated:
                    logger.info(
                        "Created user profile for %s: %s",
                        user_id,
                        updated.name,
                    )
                    return updated

            logger.info("Updated user profile for %s: %s", user_id, user_profile.name)
            return user_profile

        except Exception:
            logger.error("Error creating user profile", exc_info=True)
            raise

    async def create_therapy_plan(
        self, user_id: str, therapy_style: str
    ) -> TherapyPlan:
        """
        Create therapy plan with selected therapy style.

        This encapsulates business logic for plan creation,
        callable from both HTTP and WebSocket interfaces.

        Args:
            user_id: User identifier
            therapy_style: Selected therapy style ("freud", "jung", "cbt")

        Returns:
            Created TherapyPlan

        Raises:
            ValueError: If validation fails
        """
        try:
            # Validate therapy style
            style_service = self.service_container.get("style_service")
            available_styles = style_service.get_available_styles()

            if therapy_style not in available_styles:
                raise ValueError(f"Invalid therapy style: {therapy_style}")

            # Get user profile
            trio_db_service = self.service_container.get("trio_db_service")
            profile = await trio_db_service.get_user_profile(user_id)
            if not profile:
                raise ValueError(f"User profile not found: {user_id}")

            # Check if plan already exists
            existing_plan = await trio_db_service.get_latest_therapy_plan(user_id)
            if existing_plan and existing_plan.version == 1:
                logger.info(
                    f"Therapy plan already exists for {user_id}, returning existing"
                )
                return existing_plan

            # Create minimal therapy plan (version 1).
            # Tier 4 fields must always be present.
            plan = TherapyPlan(
                plan_id=str(uuid.uuid4()),
                user_id=user_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                plan_details={
                    "focus": "To be refined in early sessions",
                    "goals": "Stabilize presenting concerns",
                    "techniques": "Supportive listening; clarification",
                    "themes": "Presenting concerns; therapeutic alliance",
                    "timeline": "Ongoing assessment with regular reviews",
                },
                initial_goals=["Stabilize presenting concerns"],
                current_progress="Baseline established",
                planned_interventions=["Supportive listening", "Clarification"],
                status="active",
                version=1,
                selected_therapy_style=therapy_style,
            )

            # Save plan
            success = await trio_db_service.save_therapy_plan(plan)
            if not success:
                raise RuntimeError("Failed to save therapy plan to database")

            # Update user status to PLAN_COMPLETE
            profile.status = UserStatus.PLAN_COMPLETE
            profile.updated_at = datetime.now()
            await trio_db_service.save_user_profile(profile)

            logger.info(
                f"Created therapy plan for {user_id} with style {therapy_style}"
            )
            return plan

        except Exception as e:
            logger.error(f"Error creating therapy plan: {e}", exc_info=True)
            raise

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

        # Create agent instance based on type via the container
        logger.info(f"Creating agent: {agent_type} for user {user_id}")
        user_context = UserContext(user_id=user_id)
        try:
            agent = self.service_container.create_agent(agent_type, user_context)
        except ValueError as exc:
            logger.error(f"Unknown agent type requested: {agent_type}")
            raise

        # Cache the agent instance
        self.agents[cache_key] = agent
        logger.info(f"Cached agent: {cache_key}")

        return agent

    async def end_session(
        self, user_id: str, session_id: str, reason: str | None = None
    ) -> None:
        """End the active session and advance workflow if needed."""
        await self.session_lifecycle.end_session(
            user_id,
            session_id,
            reason=reason,
        )
