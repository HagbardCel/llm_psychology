"""Session lifecycle operations used by the Trio agent orchestrator."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.models.data_models import Message, Session
from psychoanalyst_app.orchestration.agent_output_validators import is_profile_complete
from psychoanalyst_app.orchestration.models import (
    SessionInfo,
    WorkflowEvent,
    WorkflowState,
)
from psychoanalyst_app.orchestration.trio_conversation_manager import (
    TrioConversationManager,
)
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine

from .active_sessions import ActiveSessionRegistry

logger = logging.getLogger(__name__)

ProcessMessageFn = Callable[[str, str, str | None], AsyncIterator[str]]
RunReflectionFn = Callable[[str, str], Awaitable[None]]
EmitNextActionFn = Callable[[str, str | None], Awaitable[None]]


def _session_has_agent(session: Session, agent_name: str) -> bool:
    needle = agent_name.upper()
    for message in session.transcript:
        if message.agent and message.agent.upper() == needle:
            return True
    return False


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
        emit_next_action: EmitNextActionFn | None = None,
        active_sessions: ActiveSessionRegistry | None = None,
    ) -> None:
        self.service_container = service_container
        self.workflow_engine = workflow_engine
        self.conversation_manager = conversation_manager
        self.nursery = nursery
        self._process_message = process_message
        self._run_reflection = run_reflection
        self._emit_next_action = emit_next_action
        self.active_sessions = active_sessions or ActiveSessionRegistry()

    def get_active_session_id(self, user_id: str) -> str | None:
        return self.active_sessions.get_active_session_id(user_id)

    def is_session_active(self, user_id: str, session_id: str) -> bool:
        return self.active_sessions.is_session_active(user_id, session_id)

    async def find_intake_sessions(
        self, user_id: str, *, limit: int = 1000
    ) -> list[Session]:
        """Return intake sessions for a user (should be at most one)."""
        trio_db_service = self.service_container.get("trio_db_service")
        sessions = await trio_db_service.get_user_sessions(user_id, limit=limit)
        intake_sessions = [
            session for session in sessions if _session_has_agent(session, "INTAKE")
        ]
        if len(intake_sessions) > 1:
            logger.error(
                "Expected a single intake session for user %s; found %s",
                user_id,
                len(intake_sessions),
            )
        return intake_sessions

    async def get_single_intake_session(self, user_id: str) -> Session | None:
        """Return the sole intake session for a user when present."""
        intake_sessions = await self.find_intake_sessions(user_id)
        if not intake_sessions:
            return None
        return intake_sessions[0]

    async def ensure_session_id(
        self, user_id: str, session_id: str | None = None
    ) -> str:
        """Return an active session ID for a user, creating one if needed."""
        if session_id:
            active_session_id = self.get_active_session_id(user_id)
            if active_session_id and active_session_id != session_id:
                raise ValueError(
                    f"Session {session_id} is not active for user {user_id}"
                )
            if not active_session_id:
                self.active_sessions.set_active_session_id(user_id, session_id)
            return session_id

        active_session_id = self.get_active_session_id(user_id)
        if active_session_id:
            return active_session_id
        return await self.create_session(user_id)

    async def ensure_session(
        self,
        user_id: str,
        session_type: str,
        *,
        send_initial_message: bool = False,
    ) -> SessionInfo:
        """Ensure a session exists for the user, creating one if needed."""
        active_session_id = self.get_active_session_id(user_id)
        if active_session_id:
            return await self._build_session_info(
                user_id,
                active_session_id,
            )
        return await self.start_session(
            user_id,
            session_type=session_type,
            send_initial_message=send_initial_message,
        )

    async def get_session_info(
        self, user_id: str, session_id: str | None = None
    ) -> SessionInfo | None:
        """Build session info for an active session if available."""
        resolved_session_id = session_id or self.get_active_session_id(user_id)
        if not resolved_session_id:
            return None
        return await self._build_session_info(
            user_id,
            resolved_session_id,
        )

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
            if normalized_session_type == "intake":
                existing_intake = await self.get_single_intake_session(user_id)
                if existing_intake:
                    self.active_sessions.set_active_session_id(
                        user_id, existing_intake.session_id
                    )
                    logger.info(
                        "Reusing intake session %s for user %s",
                        existing_intake.session_id,
                        user_id,
                    )
                    return await self._build_session_info(
                        user_id,
                        existing_intake.session_id,
                    )
            logger.info(
                "Starting session for user %s, type: %s",
                user_id,
                normalized_session_type,
            )

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
            if desired_state == WorkflowState.INTAKE_IN_PROGRESS:
                trio_db_service = self.service_container.get("trio_db_service")
                profile = await trio_db_service.get_user_profile(user_id)
                if not profile or not is_profile_complete(profile):
                    desired_state = None
                    logger.info(
                        "Skipping intake transition for user %s until profile is complete",
                        user_id,
                    )
            if desired_state and desired_state != state:
                if (
                    desired_state == WorkflowState.THERAPY_IN_PROGRESS
                    and state == WorkflowState.ASSESSMENT_COMPLETE
                ):
                    trio_db_service = self.service_container.get("trio_db_service")
                    plan = await trio_db_service.get_latest_therapy_plan(user_id)
                    if not plan or not plan.selected_therapy_style:
                        desired_state = None
                        logger.info(
                            "Skipping therapy transition for user %s until therapy style is selected",
                            user_id,
                        )

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
                self.nursery.start_soon(
                    self._send_initial_greeting, user_id, session_id
                )
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
            )

            logger.info(
                "Started session %s for user %s with agent %s in state %s. "
                "Initial message sent: %s",
                session_id,
                user_id,
                agent_type,
                state,
                bool(send_initial_message),
            )
            return session_info

        except Exception as exc:
            logger.error("Error starting session: %s", exc, exc_info=True)
            raise

    def send_initial_greeting(self, user_id: str, session_id: str) -> None:
        """Schedule the initial greeting for a session."""
        self.nursery.start_soon(self._send_initial_greeting, user_id, session_id)

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
            self.active_sessions.clear_active_session(user_id, session_id)
            return

        final_state = state
        follow_up = None
        follow_up_args: tuple[Any, ...] = ()
        emit_session_id = self.get_active_session_id(user_id) or session_id
        if emit_session_id and not self.get_active_session_id(user_id):
            self.active_sessions.set_active_session_id(user_id, emit_session_id)

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
                follow_up = self._run_reflection
                follow_up_args = (user_id, session_id)
            elif state == WorkflowState.ASSESSMENT_IN_PROGRESS:
                await self.workflow_engine.transition(
                    user_id,
                    WorkflowState.ASSESSMENT_COMPLETE,
                    event=WorkflowEvent.COMPLETE_ASSESSMENT,
                )
                final_state = WorkflowState.ASSESSMENT_COMPLETE
                self.conversation_manager.clear_context(session_id)
        except Exception:
            logger.error(
                "Failed to advance workflow on session end (user=%s, session=%s, state=%s)",
                user_id,
                session_id,
                state,
                exc_info=True,
            )

        if self._emit_next_action:
            try:
                await self._emit_next_action(user_id, emit_session_id)
            except Exception:
                logger.warning(
                    "Could not emit workflow next action after ending session %s for user %s",
                    session_id,
                    user_id,
                    exc_info=True,
                )

        if follow_up:
            try:
                await follow_up(*follow_up_args)
            except Exception:
                logger.error(
                    "Follow-up job failed for session %s (user=%s)",
                    session_id,
                    user_id,
                    exc_info=True,
                )

        try:
            final_state = await self.workflow_engine.get_user_state(user_id)
        except Exception:
            logger.warning(
                "Failed to refresh workflow state after session end (user=%s, session=%s)",
                user_id,
                session_id,
                exc_info=True,
            )

        if self._emit_next_action:
            try:
                await self._emit_next_action(user_id, emit_session_id)
            except Exception:
                logger.warning(
                    "Could not emit workflow next action after follow-up for session %s",
                    session_id,
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
        self.active_sessions.clear_active_session(user_id, session_id)

    async def create_session(self, user_id: str) -> str:
        """Create a new session in the database and return the ID."""
        try:
            state = await self.workflow_engine.get_user_state(user_id)
            if state in (WorkflowState.NEW, WorkflowState.INTAKE_IN_PROGRESS):
                existing_intake = await self.get_single_intake_session(user_id)
                if existing_intake:
                    self.active_sessions.set_active_session_id(
                        user_id, existing_intake.session_id
                    )
                    logger.info(
                        "Reusing intake session %s for user %s",
                        existing_intake.session_id,
                        user_id,
                    )
                    return existing_intake.session_id

            existing_session_id = self.get_active_session_id(user_id)
            if existing_session_id:
                logger.info(
                    "Ending active session %s for user %s before creating new session",
                    existing_session_id,
                    user_id,
                )
                await self.end_session(
                    user_id,
                    existing_session_id,
                    reason="Replaced by new session",
                )

            session_id = str(uuid.uuid4())

            trio_db_service = self.service_container.get("trio_db_service")
            latest_plan = await trio_db_service.get_latest_therapy_plan(user_id)
            plan_id = latest_plan.plan_id if latest_plan else None

            session = Session(
                session_id=session_id,
                user_id=user_id,
                plan_id=plan_id,
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
            success = await trio_db_service.save_session(session)

            if not success:
                raise ValueError("Failed to save session to database")

            self.active_sessions.set_active_session_id(user_id, session_id)
            logger.info("Created session %s for user %s", session_id, user_id)
            return session_id

        except Exception as exc:
            logger.error("Error creating session: %s", exc, exc_info=True)
            raise

    async def _build_session_info(self, user_id: str, session_id: str) -> SessionInfo:
        trio_db_service = self.service_container.get("trio_db_service")
        session = await trio_db_service.get_session(session_id)
        created_at = session.timestamp if session else datetime.now()
        state = await self.workflow_engine.get_user_state(user_id)
        agent_type = self.workflow_engine.get_current_agent(state)
        return SessionInfo(
            session_id=session_id,
            user_id=user_id,
            agent_type=agent_type,
            workflow_state=state,
            created_at=created_at,
        )

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

            self.conversation_manager.mark_initial_greeting_sent(session_id)
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
