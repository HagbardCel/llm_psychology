"""Helper classes for TrioAgentOrchestrator responsibilities."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import Message, Session, TherapyPlan
from psychoanalyst_app.models.structured_output_models import (
    StructuredTherapyPlanOutput,
    StructuredUserProfileOutput,
)
from psychoanalyst_app.orchestration.agent_output_validators import is_profile_complete
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    SessionInfo,
    WorkflowEvent,
    WorkflowState,
)
from psychoanalyst_app.orchestration.profile_helpers import merge_user_profile
from psychoanalyst_app.orchestration.trio_conversation_manager import TrioConversationManager
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine

logger = logging.getLogger(__name__)

ProcessMessageFn = Callable[[str, str, str | None], AsyncIterator[str]]
GetAgentFn = Callable[[str, str], Awaitable[Any]]
RunReflectionFn = Callable[[str, str], Awaitable[None]]
CreateSessionFn = Callable[[str], Awaitable[str]]
EndSessionFn = Callable[[str, str, str | None], Awaitable[None]]
EmitNextActionFn = Callable[[str, str | None], Awaitable[None]]


class ActiveSessionRegistry:
    """Track active sessions per user (single concurrent session)."""

    def __init__(self) -> None:
        self._active_sessions: dict[str, str] = {}

    def get_active_session_id(self, user_id: str) -> str | None:
        return self._active_sessions.get(user_id)

    def set_active_session_id(self, user_id: str, session_id: str) -> None:
        self._active_sessions[user_id] = session_id

    def clear_active_session(self, user_id: str, session_id: str | None = None) -> None:
        if session_id is None:
            self._active_sessions.pop(user_id, None)
            return
        if self._active_sessions.get(user_id) == session_id:
            self._active_sessions.pop(user_id, None)

    def is_session_active(self, user_id: str, session_id: str) -> bool:
        return self._active_sessions.get(user_id) == session_id


def session_type_for_workflow_state(state: WorkflowState) -> str:
    """Map workflow state to the session type to resume next."""
    state_map = {
        WorkflowState.NEW: "intake",
        WorkflowState.INTAKE_IN_PROGRESS: "intake",
        WorkflowState.INTAKE_COMPLETE: "assessment",
        WorkflowState.ASSESSMENT_IN_PROGRESS: "assessment",
        WorkflowState.ASSESSMENT_COMPLETE: "therapy",
        WorkflowState.THERAPY_IN_PROGRESS: "therapy",
        WorkflowState.REFLECTION_IN_PROGRESS: "therapy",
        WorkflowState.PLAN_COMPLETE: "therapy",
    }
    return state_map.get(state, "therapy")


async def persist_therapy_plan_from_output(
    *,
    trio_db_service,
    user_id: str,
    plan_output: StructuredTherapyPlanOutput,
    session_briefing: dict[str, Any] | None = None,
) -> TherapyPlan:
    """Persist a therapy plan from structured output data."""
    latest_plan = await trio_db_service.get_latest_therapy_plan(user_id)
    selected_style = plan_output.selected_therapy_style
    if not selected_style and latest_plan:
        selected_style = latest_plan.selected_therapy_style

    plan = TherapyPlan(
        plan_id=str(uuid.uuid4()),
        user_id=user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        version=(latest_plan.version + 1) if latest_plan else 1,
        selected_therapy_style=selected_style,
        plan_details=plan_output.plan_details,
        initial_goals=plan_output.initial_goals,
        current_progress=plan_output.current_progress,
        planned_interventions=plan_output.planned_interventions,
        status=plan_output.status,
        session_briefing=session_briefing,
    )

    success = await trio_db_service.save_therapy_plan(plan)
    if not success:
        raise ValueError("Failed to save therapy plan to database")
    return plan


def _session_has_agent(session: Session, agent_name: str) -> bool:
    needle = agent_name.upper()
    for message in session.transcript:
        if message.agent and message.agent.upper() == needle:
            return True
    return False


async def persist_tier3_update(
    *,
    trio_db_service,
    user_id: str,
    session_id: str,
    tier3_update: dict[str, Any],
) -> bool:
    """Persist a Tier 3 update payload as a new analysis version."""
    analysis_data = tier3_update.get("analysis_data")
    supersede_analysis_id = tier3_update.get("supersede_analysis_id")
    change_summary = tier3_update.get("change_summary")
    if not analysis_data or not supersede_analysis_id:
        return False
    try:
        saved = await trio_db_service.save_patient_analysis_next_version_and_supersede(
            analysis_id=f"analysis_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            analysis_data=analysis_data,
            created_at=datetime.now(),
            created_by_session=session_id,
            change_summary=change_summary,
            supersede_analysis_id=supersede_analysis_id,
        )
        if not saved:
            logger.error("Failed to persist Tier 3 update for user %s", user_id)
            return False
        return True
    except Exception:
        logger.error(
            "Failed to persist Tier 3 update for user %s", user_id, exc_info=True
        )
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
        emit_next_action: EmitNextActionFn | None = None,
    ) -> None:
        self.service_container = service_container
        self.workflow_engine = workflow_engine
        self.conversation_manager = conversation_manager
        self.nursery = nursery
        self._get_agent = get_agent
        self._create_session = create_session
        self._end_session = end_session
        self._emit_next_action = emit_next_action
        self._assessment_recommendations: dict[str, list[dict[str, Any]]] = {}
        self._assessment_jobs: set[str] = set()
        self._reflection_jobs: set[str] = set()

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
        if agent_response.workflow_event:
            workflow_event = agent_response.workflow_event
            current_state = await self.workflow_engine.get_user_state(user_id)
            if workflow_event == WorkflowEvent.START_INTAKE:
                trio_db_service = self.service_container.get("trio_db_service")
                profile = await trio_db_service.get_user_profile(user_id)
                if not profile or not is_profile_complete(profile):
                    logger.info(
                        "Profile incomplete for user %s; skipping intake transition",
                        user_id,
                    )
                else:
                    next_state = self.workflow_engine.get_next_state(
                        current_state, workflow_event
                    )
                    await self.workflow_engine.transition(
                        user_id, next_state, event=workflow_event
                    )
            elif workflow_event == WorkflowEvent.COMPLETE_INTAKE:
                if not (agent_response.metadata or {}).get("intake_complete"):
                    logger.info(
                        "Intake completion not confirmed for user %s; skipping transition",
                        user_id,
                    )
                else:
                    next_state = self.workflow_engine.get_next_state(
                        current_state, workflow_event
                    )
                    await self.workflow_engine.transition(
                        user_id, next_state, event=workflow_event
                    )
                    self.conversation_manager.clear_context(session_id)
                    await self.ensure_assessment_job(user_id, session_id)
            else:
                next_state = self.workflow_engine.get_next_state(
                    current_state, workflow_event
                )
                await self.workflow_engine.transition(
                    user_id, next_state, event=workflow_event
                )
                self.conversation_manager.clear_context(session_id)

                if (
                    current_state == WorkflowState.THERAPY_IN_PROGRESS
                    and next_state == WorkflowState.REFLECTION_IN_PROGRESS
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
                    await self.ensure_reflection_job(user_id, session_id)

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
                    self._assessment_recommendations[user_id] = recommendations
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
            try:
                current_state = await self.workflow_engine.get_user_state(user_id)
                next_state = self.workflow_engine.get_next_state(
                    current_state, WorkflowEvent.START_THERAPY
                )
                trio_db_service = self.service_container.get("trio_db_service")
                plan = await trio_db_service.get_latest_therapy_plan(user_id)
                if not plan or not plan.selected_therapy_style:
                    logger.info(
                        "Skipping therapy transition for user %s; plan not selected",
                        user_id,
                    )
                else:
                    await self.workflow_engine.transition(
                        user_id, next_state, event=WorkflowEvent.START_THERAPY
                    )
            except Exception:
                logger.warning(
                    "Could not transition user %s into therapy before session start",
                    user_id,
                    exc_info=True,
                )
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

            metadata = agent_response.metadata or {}
            plan_output = metadata.get("therapy_plan_output")
            if isinstance(plan_output, dict):
                plan_output = StructuredTherapyPlanOutput.model_validate(plan_output)
            session_briefing = metadata.get("session_briefing")
            plan_update_applied = metadata.get("plan_update_applied", True)
            if isinstance(plan_output, StructuredTherapyPlanOutput) and plan_update_applied:
                try:
                    await persist_therapy_plan_from_output(
                        trio_db_service=trio_db_service,
                        user_id=user_id,
                        plan_output=plan_output,
                        session_briefing=session_briefing,
                    )
                except Exception:
                    logger.error(
                        "Failed to persist therapy plan after reflection for user %s",
                        user_id,
                        exc_info=True,
                    )

            user_profile_output = metadata.get("user_profile")
            if isinstance(user_profile_output, dict):
                user_profile_output = StructuredUserProfileOutput.model_validate(
                    user_profile_output
                )
            if isinstance(user_profile_output, StructuredUserProfileOutput):
                updates = user_profile_output.model_dump(
                    exclude_none=True, exclude_unset=True
                )
                existing = await trio_db_service.get_user_profile(user_id)
                merged = merge_user_profile(
                    existing_profile=existing,
                    user_id=user_id,
                    updates=updates,
                )
                success = await trio_db_service.update_user_profile(
                    merged,
                    change_summary="Reflection profile update",
                    created_by_session=session_id,
                )
                if not success:
                    logger.error(
                        "Failed to persist reflection profile update for user %s",
                        user_id,
                    )

            tier2_enrichment = metadata.get("tier2_enrichment")
            if isinstance(tier2_enrichment, dict):
                try:
                    success = await trio_db_service.update_session_tier2(
                        session_id, tier2_enrichment
                    )
                    if not success:
                        logger.error(
                            "Failed to persist Tier 2 enrichment for session %s",
                            session_id,
                        )
                except Exception:
                    logger.error(
                        "Failed to persist Tier 2 enrichment for session %s",
                        session_id,
                        exc_info=True,
                    )

            tier3_update = metadata.get("tier3_update")
            if isinstance(tier3_update, dict):
                await persist_tier3_update(
                    trio_db_service=trio_db_service,
                    user_id=user_id,
                    session_id=session_id,
                    tier3_update=tier3_update,
                )

            if agent_response.workflow_event:
                next_state = self.workflow_engine.get_next_state(
                    state, agent_response.workflow_event
                )
                await self.workflow_engine.transition(
                    user_id,
                    next_state,
                    event=agent_response.workflow_event,
                )
                self.conversation_manager.clear_context(session_id)

            logger.info("Auto reflection complete for session %s", session_id)
        except Exception as exc:
            logger.error(
                "Auto reflection failed for session %s",
                session_id,
                exc_info=True,
            )
            await self._surface_reflection_failure(user_id, session_id, exc)

    async def _surface_reflection_failure(
        self, user_id: str, session_id: str, exc: Exception
    ) -> None:
        """Send a user-visible error and advance workflow after reflection failure."""
        error_text = str(exc)
        error_code = _extract_error_code(error_text)
        if isinstance(exc, trio.TooSlowError):
            detail = "error code: timeout"
        elif error_code:
            detail = f"error code: {error_code}"
        else:
            detail = f"error type: {type(exc).__name__}"
        await self.conversation_manager.send_json_message(
            session_id,
            "error",
            {
                "message": (
                    f"Reflection failed due to a backend error ({detail}). "
                    "You can continue your session while we investigate."
                )
            },
        )
        try:
            await self.workflow_engine.transition(
                user_id,
                WorkflowState.PLAN_COMPLETE,
                event=WorkflowEvent.COMPLETE_REFLECTION,
            )
            self.conversation_manager.clear_context(session_id)
            logger.info(
                "Advanced workflow to PLAN_COMPLETE after reflection failure "
                "for session %s",
                session_id,
            )
        except Exception:
            logger.warning(
                "Failed to advance workflow after reflection failure "
                "(session=%s, user=%s)",
                session_id,
                user_id,
                exc_info=True,
            )

    async def _run_reflection_job(
        self, user_id: str, session_id: str, emit_session_id: str | None = None
    ) -> None:
        """Run a reflection job and emit next action when done."""
        timeout_seconds = self.service_container.config.REFLECTION_TIMEOUT_SECONDS
        try:
            with trio.fail_after(timeout_seconds):
                await self.run_reflection(user_id, session_id)
            if self._emit_next_action:
                await self._emit_next_action(user_id, emit_session_id or session_id)
        except trio.TooSlowError as exc:
            logger.error(
                "Reflection job timed out after %s seconds for session %s",
                timeout_seconds,
                session_id,
                exc_info=True,
            )
            await self._surface_reflection_failure(user_id, session_id, exc)
            if self._emit_next_action:
                await self._emit_next_action(user_id, emit_session_id or session_id)
        except Exception:
            logger.error(
                "Reflection job failed for session %s (user=%s)",
                session_id,
                user_id,
                exc_info=True,
            )
        finally:
            self._reflection_jobs.discard(session_id)

    async def _run_assessment_job(
        self, user_id: str, intake_session_id: str, emit_session_id: str | None = None
    ) -> None:
        """Run backend assessment and emit recommendations + next actions."""
        try:
            current_state = await self.workflow_engine.get_user_state(user_id)
            if current_state not in (
                WorkflowState.INTAKE_COMPLETE,
                WorkflowState.ASSESSMENT_IN_PROGRESS,
            ):
                logger.info(
                    "Skipping assessment job for user %s (state=%s)",
                    user_id,
                    current_state,
                )
                return
            target_session_id = emit_session_id or intake_session_id
            if current_state == WorkflowState.INTAKE_COMPLETE:
                await self.workflow_engine.transition(
                    user_id,
                    WorkflowState.ASSESSMENT_IN_PROGRESS,
                    event=WorkflowEvent.START_ASSESSMENT,
                )
                if self._emit_next_action:
                    await self._emit_next_action(user_id, target_session_id)
            elif self._emit_next_action:
                await self._emit_next_action(user_id, target_session_id)

            context = await self.conversation_manager.get_context(intake_session_id)
            assessment_agent = self.service_container.create_agent(
                "ASSESSMENT",
                UserContext(user_id=user_id),
            )
            agent_response = await assessment_agent.process_assessment(context)
            recommendations = (agent_response.metadata or {}).get("recommendations")
            if recommendations:
                self._assessment_recommendations[user_id] = recommendations
                await self.conversation_manager.send_json_message(
                    target_session_id,
                    "assessment_recommendations",
                    {
                        "session_id": target_session_id,
                        "user_id": user_id,
                        "recommendations": recommendations,
                    },
                )

            await self.workflow_engine.transition(
                user_id,
                WorkflowState.ASSESSMENT_COMPLETE,
                event=WorkflowEvent.COMPLETE_ASSESSMENT,
            )
            if self._emit_next_action:
                await self._emit_next_action(user_id, target_session_id)
        except Exception:
            logger.error(
                "Assessment job failed for user %s (session=%s)",
                user_id,
                intake_session_id,
                exc_info=True,
            )
        finally:
            self._assessment_jobs.discard(user_id)

    async def ensure_assessment_job(self, user_id: str, session_id: str) -> None:
        """Ensure a single assessment job is running for the user."""
        if user_id in self._assessment_jobs:
            return
        self._assessment_jobs.add(user_id)
        self.nursery.start_soon(
            self._run_assessment_job,
            user_id,
            session_id,
            session_id,
        )

    async def ensure_reflection_job(self, user_id: str, session_id: str) -> None:
        """Ensure a single reflection job is running for the session."""
        if session_id in self._reflection_jobs:
            return
        self._reflection_jobs.add(session_id)
        self.nursery.start_soon(
            self._run_reflection_job,
            user_id,
            session_id,
            session_id,
        )

    async def emit_assessment_recommendations(
        self, session_id: str, user_id: str
    ) -> None:
        """Re-emit cached assessment recommendations if available."""
        recommendations = self._assessment_recommendations.get(user_id)
        if not recommendations:
            return
        await self._send_assessment_recommendations(
            session_id, user_id, recommendations
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
def _extract_error_code(message: str) -> str | None:
    """Extract an HTTP-like status code from an error message."""
    for pattern in (
        r"(?:HTTP|status)\D{0,10}(4\d{2}|5\d{2})",
        r"\b(4\d{2}|5\d{2})\b",
    ):
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
