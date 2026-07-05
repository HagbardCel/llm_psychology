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
from psychoanalyst_app.models.domain import TherapyPlan, UserProfile, UserStatus
from psychoanalyst_app.models.http import (
    WorkflowNextActionDTO,
)
from psychoanalyst_app.orchestration.agent_output_validators import is_profile_complete
from psychoanalyst_app.orchestration.intake_turn_persistence import (
    extract_intake_turn_persistence_payload,
    mark_intake_record_persisted,
    persist_intake_turn_outputs,
)
from psychoanalyst_app.orchestration.models import (
    SessionInfo,
    WorkflowEvent,
    WorkflowState,
)
from psychoanalyst_app.orchestration.persistence import (
    persist_therapy_plan_from_output,
)
from psychoanalyst_app.orchestration.process_messages import (
    ensure_profile_for_new_state,
    ensure_session,
    finalize_agent_response,
    record_user_message,
    resolve_agent_and_context,
    stream_agent_response,
)
from psychoanalyst_app.orchestration.profile_helpers import ensure_user_profile
from psychoanalyst_app.orchestration.response_handler import AgentResponseHandler
from psychoanalyst_app.orchestration.session_lifecycle import SessionLifecycleManager
from psychoanalyst_app.orchestration.trio_conversation_manager import (
    TrioConversationManager,
)
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine
from psychoanalyst_app.orchestration.workflow_transitions import (
    emit_workflow_next_action as emit_workflow_next_action_runtime,
)
from psychoanalyst_app.orchestration.workflow_transitions import (
    get_workflow_next_action as get_workflow_next_action_runtime,
)

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
        self._emitted_workflow_signatures: dict[str, str] = {}
        self.response_handler = AgentResponseHandler(
            service_container=self.service_container,
            workflow_engine=self.workflow_engine,
            conversation_manager=self.conversation_manager,
            nursery=self.nursery,
            get_agent=self._get_or_create_agent,
            emit_next_action=self.emit_workflow_next_action,
        )
        self.session_lifecycle = SessionLifecycleManager(
            service_container=self.service_container,
            workflow_engine=self.workflow_engine,
            conversation_manager=self.conversation_manager,
            nursery=self.nursery,
            process_message=self.process_message,
            run_reflection=self.response_handler.ensure_reflection_job,
            emit_next_action=self.emit_workflow_next_action,
        )
        self.response_handler.attach_session_callbacks(
            end_session=self.session_lifecycle.end_session,
            start_therapy_session=self.session_lifecycle.start_therapy_session,
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

            await record_user_message(self.conversation_manager, session_id, message)

            state = await self.workflow_engine.get_user_state(user_id)
            logger.info("User %s workflow state: %s", user_id, state)

            await ensure_profile_for_new_state(self.service_container, user_id, state)

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
                "Agent response: action=%s state=%s event=%s direct=%s",
                agent_response.next_action,
                agent_response.next_state,
                agent_response.workflow_event,
                (agent_response.metadata or {}).get("is_direct_response"),
            )

            intake_payload = extract_intake_turn_persistence_payload(agent_response)
            if intake_payload is not None:
                try:
                    persisted = await persist_intake_turn_outputs(
                        self.conversation_manager, session_id, intake_payload
                    )
                    if persisted:
                        mark_intake_record_persisted(
                            agent_response, persisted_stage="pre_stream"
                        )
                except Exception:
                    logger.warning(
                        "Pre-stream intake persistence failed for session %s",
                        session_id,
                        exc_info=True,
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
            try:
                await self.emit_workflow_next_action(
                    user_id,
                    session_id,
                    emission_source="process_message_final_emit",
                )
            except Exception:
                logger.warning(
                    "Failed to emit workflow next action after agent response",
                    exc_info=True,
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

    def send_initial_greeting(self, user_id: str, session_id: str) -> None:
        """Schedule the initial greeting for a session."""
        self.session_lifecycle.send_initial_greeting(user_id, session_id)

    async def start_therapy_session(
        self, user_id: str, current_session_id: str
    ) -> SessionInfo:
        """Start the first plan-linked therapy conversation without a UI break."""
        return await self.session_lifecycle.start_therapy_session(
            user_id, current_session_id
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

    def get_active_session_id(self, user_id: str) -> str | None:
        """Return the active session ID for a user if available."""
        return self.session_lifecycle.get_active_session_id(user_id)

    def is_session_active(self, user_id: str, session_id: str) -> bool:
        """Return whether a session is active for a user."""
        return self.session_lifecycle.is_session_active(user_id, session_id)

    async def ensure_session_for_user(
        self,
        user_id: str,
        session_type: str,
        *,
        send_initial_message: bool = False,
    ) -> SessionInfo:
        """Ensure a session exists for a user, creating one if needed."""
        return await self.session_lifecycle.ensure_session(
            user_id,
            session_type=session_type,
            send_initial_message=send_initial_message,
        )

    async def get_workflow_next_action(
        self,
        user_id: str,
        session_id: str | None = None,
        session: SessionInfo | None = None,
    ) -> WorkflowNextActionDTO:
        """
        Build the next action instruction for a user using the resolver.

        Args:
            user_id: User identifier
            session: Optional active session context

        Returns:
            WorkflowNextActionDTO describing the required action
        """
        return await get_workflow_next_action_runtime(
            service_container=self.service_container,
            workflow_engine=self.workflow_engine,
            session_lifecycle=self.session_lifecycle,
            user_id=user_id,
            session_id=session_id,
            session=session,
        )

    async def emit_workflow_next_action(
        self,
        user_id: str,
        session_id: str | None = None,
        *,
        emission_source: str = "orchestrator_emit",
        include_resume_payloads: bool = False,
        force_emit: bool = False,
    ) -> None:
        """
        Send the workflow next action event to the WebSocket session if available.
        """
        await emit_workflow_next_action_runtime(
            user_id=user_id,
            session_id=session_id,
            session_lifecycle=self.session_lifecycle,
            conversation_manager=self.conversation_manager,
            response_handler=self.response_handler,
            send_initial_greeting=self.send_initial_greeting,
            get_workflow_next_action=self.get_workflow_next_action,
            emitted_signatures=self._emitted_workflow_signatures,
            emission_source=emission_source,
            include_resume_payloads=include_resume_payloads,
            force_emit=force_emit,
        )

    async def emit_assessment_recommendations(
        self, user_id: str, session_id: str
    ) -> None:
        """Send cached assessment recommendations if available."""
        await self.response_handler.emit_assessment_recommendations(session_id, user_id)

    async def ensure_assessment_job(self, user_id: str, session_id: str) -> None:
        """Ensure assessment jobs are running when required."""
        await self.response_handler.ensure_assessment_job(user_id, session_id)

    async def retry_plan_update(self, user_id: str, session_id: str) -> None:
        """Retry reflection for the ended therapy session that failed persistence."""
        state = await self.workflow_engine.get_user_state(user_id)
        if state != WorkflowState.PLAN_UPDATE_FAILED:
            raise ValueError(
                "Plan update retry is only allowed after reflection failure"
            )
        trio_db_service = self.service_container.get("trio_db_service")
        session = await trio_db_service.get_session(session_id)
        if (
            not session
            or session.user_id != user_id
            or session.session_type != "therapy"
        ):
            raise ValueError("Retry requires the failed therapy session")
        self.session_lifecycle.bind_session(user_id, session_id)
        await self.workflow_engine.transition(
            user_id,
            WorkflowState.PLAN_UPDATE_IN_PROGRESS,
            event=WorkflowEvent.RETRY_PLAN_UPDATE,
        )
        await self.response_handler.ensure_reflection_job(user_id, session_id)

    async def create_user_profile(self, profile_data: dict[str, Any]) -> UserProfile:
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

            if prior_status == UserStatus.PROFILE_ONLY and is_profile_complete(
                user_profile
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
            existing_plan = await trio_db_service.get_current_therapy_plan(user_id)
            if existing_plan:
                if (
                    existing_plan.selected_therapy_style
                    and existing_plan.selected_therapy_style != therapy_style
                ):
                    raise ValueError(
                        "Therapy plan already exists with a different style"
                    )
                if not existing_plan.selected_therapy_style:
                    revised_plan = existing_plan.model_copy(
                        update={
                            "plan_id": f"plan_{uuid.uuid4().hex[:12]}",
                            "selected_therapy_style": therapy_style,
                            "created_at": datetime.now(),
                            "updated_at": datetime.now(),
                        }
                    )
                    success = await trio_db_service.save_therapy_plan(revised_plan)
                    if not success:
                        raise RuntimeError(
                            "Failed to update therapy plan with selected style"
                        )
                    return revised_plan
                logger.info(
                    "Therapy plan already exists for %s, returning existing",
                    user_id,
                )
                return existing_plan

            intake_sessions = await self.session_lifecycle.find_intake_sessions(user_id)
            if not intake_sessions:
                raise ValueError(f"Intake session not found for user {user_id}")
            if len(intake_sessions) > 1:
                raise ValueError(f"Multiple intake sessions found for user {user_id}")
            intake_session = intake_sessions[0]

            reflection_agent = await self._get_or_create_agent("REFLECTION", user_id)
            plan_output = await reflection_agent.create_initial_plan_with_style(
                intake_session, therapy_style
            )
            plan = await persist_therapy_plan_from_output(
                trio_db_service=trio_db_service,
                user_id=user_id,
                plan_output=plan_output,
            )

            await self.workflow_engine.transition(
                user_id,
                WorkflowState.INITIAL_PLAN_COMPLETE,
            )

            logger.info(
                f"Created therapy plan for {user_id} with style {therapy_style}"
            )
            return plan

        except Exception as e:
            logger.error(f"Error creating therapy plan: {e}", exc_info=True)
            raise

    async def _get_or_create_agent(self, agent_type: str, user_id: str):
        """Return cached agent instance or create+cache a new one."""
        cache_key = f"{agent_type}_{user_id}"
        if cache_key in self.agents:
            logger.debug("Retrieved cached agent: %s", cache_key)
            return self.agents[cache_key]

        try:
            logger.info("Creating agent: %s for user %s", agent_type, user_id)
            agent = self.service_container.create_agent(
                agent_type, UserContext(user_id=user_id)
            )
        except ValueError:
            logger.error(f"Unknown agent type requested: {agent_type}")
            raise

        self.agents[cache_key] = agent
        logger.info("Cached agent: %s", cache_key)
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
