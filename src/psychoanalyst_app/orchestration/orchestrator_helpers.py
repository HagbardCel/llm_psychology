"""Helper classes for TrioAgentOrchestrator responsibilities."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.models.data_models import Message, Session
from psychoanalyst_app.orchestration.models import AgentResponse, SessionInfo, WorkflowEvent, WorkflowState
from psychoanalyst_app.orchestration.trio_conversation_manager import TrioConversationManager
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine

logger = logging.getLogger(__name__)

ProcessMessageFn = Callable[[str, str, str | None], AsyncIterator[str]]
GetAgentFn = Callable[[str, str], Awaitable[Any]]
RunReflectionFn = Callable[[str, str], Awaitable[None]]
CreateSessionFn = Callable[[str], Awaitable[str]]
EndSessionFn = Callable[[str, str, str | None], Awaitable[None]]


class SessionLifecycleManager:
    """Manage session lifecycle operations for the orchestrator."""

    def __init__(
        self,
        service_container: ServiceContainer,
        workflow_engine: TrioWorkflowEngine,
        conversation_manager: TrioConversationManager,
        nursery: trio.Nursery,
        process_message: ProcessMessageFn,
        run_reflection: RunReflectionFn,
    ) -> None:
        self.service_container = service_container
        self.workflow_engine = workflow_engine
        self.conversation_manager = conversation_manager
        self.nursery = nursery
        self._process_message = process_message
        self._run_reflection = run_reflection

    async def start_session(
        self,
        user_id: str,
        session_type: str = "therapy",
        *,
        send_initial_message: bool = False,
    ) -> SessionInfo:
        """Start a new therapy session and optionally send an initial greeting."""
        try:
            normalized_session_type = (session_type or "therapy").lower()
            logger.info(
                "Starting session for user %s, type: %s",
                user_id,
                normalized_session_type,
            )
            has_initial_message = bool(send_initial_message)

            session_state_map = {
                "intake": WorkflowState.INTAKE_IN_PROGRESS,
                "assessment": WorkflowState.ASSESSMENT_IN_PROGRESS,
                "therapy": WorkflowState.THERAPY_IN_PROGRESS,
            }
            session_event_map = {
                "intake": WorkflowEvent.START_INTAKE,
                "assessment": WorkflowEvent.START_ASSESSMENT,
                "therapy": WorkflowEvent.START_THERAPY,
            }

            # Get current workflow state and adjust if session type demands it.
            state = await self.workflow_engine.get_user_state(user_id)
            desired_state = session_state_map.get(normalized_session_type)
            if desired_state and desired_state != state:
                event = session_event_map.get(normalized_session_type)
                try:
                    await self.workflow_engine.transition(
                        user_id, desired_state, event=event
                    )
                    state = desired_state
                    logger.info(
                        "Transitioned user %s to %s for %s session",
                        user_id,
                        desired_state,
                        normalized_session_type,
                    )
                except Exception as exc:  # Transition failures should not block session
                    logger.warning(
                        "Could not transition user %s to %s for %s session: %s",
                        user_id,
                        desired_state,
                        normalized_session_type,
                        exc,
                    )

            agent_type = self.workflow_engine.get_current_agent(state)
            session_id = await self.create_session(user_id)

            if send_initial_message:
                # Trigger the agent's normal message processing with an empty message.
                # This avoids introducing a separate "greeting" code path per agent.
                self.nursery.start_soon(self._send_initial_greeting, user_id, session_id)
                logger.info(
                    "Scheduled initial greeting for session %s (state=%s, agent=%s)",
                    session_id,
                    state,
                    agent_type,
                )

            session_info = SessionInfo(
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
                workflow_state=state,
                created_at=datetime.now(),
                has_initial_message=has_initial_message,
            )

            logger.info(
                "Started session %s for user %s with agent %s in state %s. "
                "Initial message sent: %s",
                session_id,
                user_id,
                agent_type,
                state,
                has_initial_message,
            )
            return session_info

        except Exception as exc:
            logger.error("Error starting session: %s", exc, exc_info=True)
            raise

    async def end_session(
        self, user_id: str, session_id: str, reason: str | None = None
    ) -> None:
        """End the active session and advance workflow if needed."""
        try:
            state = await self.workflow_engine.get_user_state(user_id)
        except Exception:
            logger.error(
                "Failed to load workflow state for session end (user=%s, session=%s)",
                user_id,
                session_id,
                exc_info=True,
            )
            return

        final_state = state
        try:
            if state == WorkflowState.THERAPY_IN_PROGRESS:
                await self.workflow_engine.transition(
                    user_id,
                    WorkflowState.REFLECTION_IN_PROGRESS,
                    event=WorkflowEvent.COMPLETE_SESSION,
                )
                final_state = WorkflowState.REFLECTION_IN_PROGRESS
                self.conversation_manager.clear_context(session_id)
                try:
                    trio_db_service = self.service_container.get("trio_db_service")
                    await trio_db_service.enqueue_session_enrichment_job(
                        session_id, user_id
                    )
                except Exception:
                    logger.warning(
                        "Failed to enqueue Tier 2 enrichment job for session %s",
                        session_id,
                        exc_info=True,
                    )
                if self.nursery:
                    self.nursery.start_soon(
                        self._run_reflection, user_id, session_id
                    )
            elif state == WorkflowState.ASSESSMENT_IN_PROGRESS:
                await self.workflow_engine.transition(
                    user_id,
                    WorkflowState.ASSESSMENT_COMPLETE,
                    event=WorkflowEvent.COMPLETE_ASSESSMENT,
                )
                final_state = WorkflowState.ASSESSMENT_COMPLETE
                self.conversation_manager.clear_context(session_id)
            elif state == WorkflowState.INTAKE_IN_PROGRESS:
                await self.workflow_engine.transition(
                    user_id,
                    WorkflowState.INTAKE_COMPLETE,
                    event=WorkflowEvent.COMPLETE_INTAKE,
                )
                final_state = WorkflowState.INTAKE_COMPLETE
                self.conversation_manager.clear_context(session_id)
        except Exception:
            logger.error(
                "Failed to advance workflow on session end (user=%s, session=%s, state=%s)",
                user_id,
                session_id,
                state,
                exc_info=True,
            )

        await self.conversation_manager.send_json_message(
            session_id,
            "session_ended",
            {
                "reason": reason or "Session ended",
                "workflow_state": final_state.value,
            },
        )

    async def create_session(self, user_id: str) -> str:
        """Create a new session in the database and return the ID."""
        try:
            session_id = str(uuid.uuid4())

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

            trio_db_service = self.service_container.get("trio_db_service")
            success = await trio_db_service.save_session(session)

            if not success:
                raise ValueError("Failed to save session to database")

            logger.info("Created session %s for user %s", session_id, user_id)
            return session_id

        except Exception as exc:
            logger.error("Error creating session: %s", exc, exc_info=True)
            raise

    async def _send_initial_greeting(self, user_id: str, session_id: str) -> None:
        """
        Send initial greeting by processing an empty message through the agent.

        This triggers the agent's normal message processing flow, which will
        generate an appropriate initial greeting based on the conversation context.
        """
        typing_started = False
        try:
            ws_ready = await self.conversation_manager.wait_for_websocket(
                session_id, timeout_seconds=5.0
            )
            if not ws_ready:
                logger.warning(
                    "Skipping initial greeting for session %s: websocket never registered",
                    session_id,
                )
                return

            await self.conversation_manager.send_typing_indicator(session_id, True)
            typing_started = True

            async for chunk in self._process_message(user_id, "", session_id):
                await self.conversation_manager.send_stream_chunk(
                    session_id, chunk, is_complete=False
                )

            await self.conversation_manager.send_stream_chunk(
                session_id, "", is_complete=True
            )

            logger.info("Initial greeting sent for session %s", session_id)

        except Exception as exc:
            logger.error(
                "Initial greeting failed for session %s: %s",
                session_id,
                exc,
                exc_info=True,
            )
            try:
                await self.conversation_manager.send_stream_chunk(
                    session_id,
                    f"\nERROR: Initial greeting failed: {type(exc).__name__}: {exc}\n",
                    is_complete=False,
                )
                await self.conversation_manager.send_stream_chunk(
                    session_id, "", is_complete=True
                )
            except Exception:
                logger.warning(
                    "Failed to send initial-greeting error chunk for session %s",
                    session_id,
                    exc_info=True,
                )
        finally:
            try:
                if typing_started:
                    await self.conversation_manager.send_typing_indicator(
                        session_id, False
                    )
            except Exception:
                logger.debug(
                    "Failed to send typing_stop for session %s (likely disconnected)",
                    session_id,
                    exc_info=True,
                )


class AgentResponseHandler:
    """Handle AgentResponse transitions and follow-up actions."""

    def __init__(
        self,
        service_container: ServiceContainer,
        workflow_engine: TrioWorkflowEngine,
        conversation_manager: TrioConversationManager,
        nursery: trio.Nursery,
        get_agent: GetAgentFn,
        create_session: CreateSessionFn | None = None,
        end_session: EndSessionFn | None = None,
    ) -> None:
        self.service_container = service_container
        self.workflow_engine = workflow_engine
        self.conversation_manager = conversation_manager
        self.nursery = nursery
        self._get_agent = get_agent
        self._create_session = create_session
        self._end_session = end_session

    def attach_session_callbacks(
        self,
        *,
        create_session: CreateSessionFn,
        end_session: EndSessionFn,
    ) -> None:
        """Attach session lifecycle callbacks after initialization."""
        self._create_session = create_session
        self._end_session = end_session

    async def handle(
        self, user_id: str, session_id: str, agent_response: AgentResponse
    ) -> None:
        """Handle the agent's response and manage state transitions."""
        if agent_response.next_state:
            prior_state = await self.workflow_engine.get_user_state(user_id)
            logger.info(
                "Transitioning user %s to state: %s",
                user_id,
                agent_response.next_state,
            )
            await self.workflow_engine.transition(user_id, agent_response.next_state)

            self.conversation_manager.clear_context(session_id)

            if (
                prior_state == WorkflowState.THERAPY_IN_PROGRESS
                and agent_response.next_state == WorkflowState.REFLECTION_IN_PROGRESS
            ):
                try:
                    trio_db_service = self.service_container.get("trio_db_service")
                    await trio_db_service.enqueue_session_enrichment_job(
                        session_id, user_id
                    )
                except Exception:
                    logger.warning(
                        "Failed to enqueue Tier 2 enrichment job for session %s",
                        session_id,
                        exc_info=True,
                    )
                self.nursery.start_soon(self.run_reflection, user_id, session_id)

        action = agent_response.next_action
        logger.info("Handling agent response for user %s: action=%s", user_id, action)

        if action == "transition":
            return

        if action == "complete":
            if agent_response.metadata:
                logger.debug("Completion metadata: %s", agent_response.metadata)
            return

        if action == "continue":
            logger.debug("Continuing in current state for user %s", user_id)
            return

        if action == "await_selection":
            logger.info("Agent is waiting for selection from user %s", user_id)
            if agent_response.metadata:
                logger.debug("Selection metadata: %s", agent_response.metadata)
                recommendations = agent_response.metadata.get("recommendations")
                if recommendations:
                    await self._send_assessment_recommendations(
                        session_id, user_id, recommendations
                    )
            return

        if action == "await_continuation_choice":
            logger.info(
                "Agent is waiting for continuation choice from user %s", user_id
            )
            if agent_response.metadata:
                logger.debug("Continuation metadata: %s", agent_response.metadata)
            return

        if action == "end_session":
            logger.info("User %s chose to end session %s", user_id, session_id)
            if not self._end_session:
                logger.error("End session callback not configured")
                return
            await self._end_session(user_id, session_id, reason="User ended session")
            return

        if action == "start_therapy":
            logger.info(
                "User %s chose to start therapy session immediately", user_id
            )
            if not self._create_session:
                logger.error("Create session callback not configured")
                return
            new_session_id = await self._create_session(user_id)
            logger.info(
                "Created new therapy session %s for user %s",
                new_session_id,
                user_id,
            )

            ws = self.conversation_manager.websockets.get(session_id)
            if ws:
                self.conversation_manager.unregister_websocket(session_id)
                self.conversation_manager.register_websocket(new_session_id, ws)
                logger.info(
                    "Switched websocket from session %s to %s",
                    session_id,
                    new_session_id,
                )
            return

        logger.warning("Unknown agent action '%s' for user %s", action, user_id)

    async def run_reflection(self, user_id: str, session_id: str) -> None:
        """Run reflection automatically after a therapy session completes."""
        try:
            state = await self.workflow_engine.get_user_state(user_id)
            if state != WorkflowState.REFLECTION_IN_PROGRESS:
                logger.info(
                    "Skipping auto reflection for session %s (state=%s)",
                    session_id,
                    state,
                )
                return

            trio_db_service = self.service_container.get("trio_db_service")
            session = await trio_db_service.get_session(session_id)
            if not session:
                logger.error(
                    "Auto reflection skipped: session not found for %s", session_id
                )
                return

            context = await self.conversation_manager.get_context(session_id)
            reflection_agent = await self._get_agent("REFLECTION", user_id)
            agent_response = await reflection_agent.process_reflection(
                session, context
            )

            if agent_response.next_state:
                await self.workflow_engine.transition(
                    user_id,
                    agent_response.next_state,
                    event=WorkflowEvent.COMPLETE_REFLECTION,
                )
                self.conversation_manager.clear_context(session_id)

            logger.info("Auto reflection complete for session %s", session_id)
        except Exception:
            logger.error(
                "Auto reflection failed for session %s",
                session_id,
                exc_info=True,
            )

    async def _send_assessment_recommendations(
        self, session_id: str, user_id: str, recommendations: list[dict[str, Any]]
    ) -> None:
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "recommendations": recommendations,
        }
        await self.conversation_manager.send_json_message(
            session_id, "assessment_recommendations", payload
        )
