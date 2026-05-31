"""Session lifecycle operations used by the Trio agent orchestrator."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime

import trio

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.models.data_models import Message, Session
from psychoanalyst_app.orchestration.models import (
    SessionInfo,
    WorkflowState,
)
from psychoanalyst_app.orchestration.trio_conversation_manager import (
    TrioConversationManager,
)
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine
from psychoanalyst_app.utils.ws_protocol import ServerMessageTypes

from .active_sessions import ActiveSessionRegistry
from .initial_greeting import send_initial_greeting
from .session_transition_policy import (
    advance_workflow_on_session_end,
    maybe_transition_for_session_start,
)
from .session_rollover import start_therapy_session as rollover_to_therapy_session
from .session_follow_up import run_session_end_follow_up

logger = logging.getLogger(__name__)

ProcessMessageFn = Callable[[str, str, str | None], AsyncIterator[str]]
RunReflectionFn = Callable[[str, str], Awaitable[None]]
EmitNextActionFn = Callable[[str, str | None], Awaitable[None]]


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

    def bind_session(self, user_id: str, session_id: str) -> None:
        """Bind an existing persisted session for workflow control operations."""
        self.active_sessions.set_active_session_id(user_id, session_id)

    async def find_intake_sessions(
        self, user_id: str, *, limit: int = 1000
    ) -> list[Session]:
        """Return intake sessions for a user (should be at most one)."""
        trio_db_service = self.service_container.get("trio_db_service")
        sessions = await trio_db_service.get_user_sessions(user_id, limit=limit)
        intake_sessions = [session for session in sessions if session.session_type == "intake"]
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

    async def get_latest_therapy_session(self, user_id: str) -> Session | None:
        """Return the most recent persisted therapy session for workflow recovery."""
        trio_db_service = self.service_container.get("trio_db_service")
        sessions = await trio_db_service.get_user_sessions(user_id, limit=1000)
        therapy_sessions = [
            session for session in sessions if session.session_type == "therapy"
        ]
        return therapy_sessions[0] if therapy_sessions else None

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
            state = await self.workflow_engine.get_user_state(user_id)
            if (
                normalized_session_type == "therapy"
                and state
                in (
                    WorkflowState.PLAN_UPDATE_IN_PROGRESS,
                    WorkflowState.REFLECTION_IN_PROGRESS,
                    WorkflowState.PLAN_UPDATE_FAILED,
                )
            ):
                existing_therapy = await self.get_latest_therapy_session(user_id)
                if existing_therapy:
                    self.bind_session(user_id, existing_therapy.session_id)
                    return await self._build_session_info(
                        user_id,
                        existing_therapy.session_id,
                    )
            logger.info(
                "Starting session for user %s, type: %s",
                user_id,
                normalized_session_type,
            )

            # Get current workflow state and adjust if session type demands it.
            state = await maybe_transition_for_session_start(
                user_id=user_id,
                normalized_session_type=normalized_session_type,
                state=state,
                workflow_engine=self.workflow_engine,
                service_container=self.service_container,
            )

            agent_type = self.workflow_engine.get_current_agent(state)
            session_id = await self.create_session(
                user_id, session_type=normalized_session_type
            )

            if send_initial_message:
                # Trigger the agent's normal message processing with an empty message.
                # This avoids introducing a separate "greeting" code path per agent.
                self.send_initial_greeting(user_id, session_id)

            session_info = await self._build_session_info(user_id, session_id)

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

    def send_initial_greeting(self, user_id: str, session_id: str) -> bool:
        """Schedule the initial greeting for a session once."""
        if not self.conversation_manager.claim_initial_greeting(session_id):
            logger.info(
                "Suppressed duplicate initial greeting for session %s",
                session_id,
            )
            return False
        self.nursery.start_soon(self._send_initial_greeting, user_id, session_id)
        logger.info("Scheduled initial greeting for session %s", session_id)
        return True

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
        follow_up_args = ()
        emit_session_id = self.get_active_session_id(user_id) or session_id
        if emit_session_id and not self.get_active_session_id(user_id):
            self.active_sessions.set_active_session_id(user_id, emit_session_id)

        final_state, follow_up, follow_up_args = await advance_workflow_on_session_end(
            user_id=user_id,
            session_id=session_id,
            state=state,
            workflow_engine=self.workflow_engine,
            conversation_manager=self.conversation_manager,
            service_container=self.service_container,
            run_reflection=self._run_reflection,
        )

        if self._emit_next_action:
            try:
                await self._emit_next_action(user_id, emit_session_id)
            except Exception:
                logger.warning(
                    "Could not emit workflow next action after ending session %s "
                    "for user %s",
                    session_id,
                    user_id,
                    exc_info=True,
                )

        await self.conversation_manager.send_json_message(
            session_id,
            ServerMessageTypes.SESSION_ENDED,
            {
                "reason": reason or "Session ended",
                "workflow_state": final_state.value,
            },
        )
        self.active_sessions.clear_active_session(user_id, session_id)
        if follow_up:
            self.nursery.start_soon(
                run_session_end_follow_up,
                user_id,
                session_id,
                follow_up,
                follow_up_args,
                self.workflow_engine,
                self._emit_next_action,
            )

    async def create_session(self, user_id: str, session_type: str = "therapy") -> str:
        """Create a new session in the database and return the ID."""
        try:
            state = await self.workflow_engine.get_user_state(user_id)
            if session_type == "intake":
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
            latest_plan = await trio_db_service.get_current_therapy_plan(user_id)
            plan_id = latest_plan.plan_id if session_type == "therapy" and latest_plan else None

            session = Session(
                session_id=session_id,
                user_id=user_id,
                session_type=session_type,
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

    async def start_therapy_session(
        self, user_id: str, current_session_id: str
    ) -> SessionInfo:
        """Replace the intake control session with a plan-linked therapy session."""
        return await rollover_to_therapy_session(self, user_id, current_session_id)

    async def _build_session_info(self, user_id: str, session_id: str) -> SessionInfo:
        trio_db_service = self.service_container.get("trio_db_service")
        session = await trio_db_service.get_session(session_id)
        created_at = session.timestamp if session else datetime.now()
        state = await self.workflow_engine.get_user_state(user_id)
        agent_type = self.workflow_engine.get_current_agent(state)
        plan = (
            await trio_db_service.get_therapy_plan(session.plan_id)
            if session and session.session_type == "therapy" and session.plan_id
            else None
        )
        return SessionInfo(
            session_id=session_id,
            user_id=user_id,
            agent_type=agent_type,
            workflow_state=state,
            created_at=created_at,
            session_type=session.session_type if session else "intake",
            selected_therapy_style=plan.selected_therapy_style if plan else None,
        )

    async def _send_initial_greeting(self, user_id: str, session_id: str) -> None:
        await send_initial_greeting(
            user_id=user_id,
            session_id=session_id,
            conversation_manager=self.conversation_manager,
            process_message=self._process_message,
        )
