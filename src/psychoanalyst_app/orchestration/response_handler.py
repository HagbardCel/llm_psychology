"""Agent response handling and background orchestration jobs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import trio

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.models.llm_outputs import (
    StructuredTherapyPlanOutput,
    StructuredUserProfileOutput,
)
from psychoanalyst_app.orchestration.agent_output_validators import is_profile_complete
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    WorkflowEvent,
    WorkflowState,
)
from psychoanalyst_app.orchestration.profile_helpers import (
    persist_structured_user_profile_output,
)
from psychoanalyst_app.orchestration.trio_conversation_manager import (
    TrioConversationManager,
)
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine
from psychoanalyst_app.utils.ws_protocol import ServerMessageTypes

from .persistence import persist_therapy_plan_from_output, persist_tier3_update
from .response_jobs import (
    emit_assessment_recommendations,
    extract_error_code,
    persist_assessment_recommendations,
    queue_assessment_job,
    queue_reflection_job,
    run_assessment_job,
    run_reflection_job,
    send_assessment_recommendations,
)

logger = logging.getLogger(__name__)
GetAgentFn = Callable[[str, str], Awaitable[Any]]
EndSessionFn = Callable[[str, str, str | None], Awaitable[None]]
StartTherapySessionFn = Callable[[str, str], Awaitable[Any]]
EmitNextActionFn = Callable[[str, str | None], Awaitable[None]]


class AgentResponseHandler:
    """Handle AgentResponse transitions and follow-up actions."""

    def __init__(
        self,
        service_container: ServiceContainer,
        workflow_engine: TrioWorkflowEngine,
        conversation_manager: TrioConversationManager,
        nursery: trio.Nursery,
        get_agent: GetAgentFn,
        end_session: EndSessionFn | None = None,
        emit_next_action: EmitNextActionFn | None = None,
        start_therapy_session: StartTherapySessionFn | None = None,
    ) -> None:
        self.service_container = service_container
        self.workflow_engine = workflow_engine
        self.conversation_manager = conversation_manager
        self.nursery = nursery
        self._get_agent = get_agent
        self._end_session = end_session
        self._emit_next_action = emit_next_action
        self._start_therapy_session = start_therapy_session
        self._assessment_recommendations: dict[str, list[dict[str, Any]]] = {}
        self._assessment_jobs: set[str] = set()
        self._reflection_jobs: set[str] = set()

    def attach_session_callbacks(
        self,
        *,
        end_session: EndSessionFn,
        start_therapy_session: StartTherapySessionFn,
    ) -> None:
        """Attach session lifecycle callbacks after initialization."""
        self._end_session = end_session
        self._start_therapy_session = start_therapy_session

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
                        "Intake completion not confirmed for user %s; "
                        "skipping transition",
                        user_id,
                    )
                else:
                    next_state = self.workflow_engine.get_next_state(
                        current_state, workflow_event
                    )
                    await self.workflow_engine.transition(
                        user_id, next_state, event=workflow_event
                    )
                    assessment_state = self.workflow_engine.get_next_state(
                        next_state, WorkflowEvent.START_ASSESSMENT
                    )
                    await self.workflow_engine.transition(
                        user_id,
                        assessment_state,
                        event=WorkflowEvent.START_ASSESSMENT,
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
                    and next_state == WorkflowState.PLAN_UPDATE_IN_PROGRESS
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
                    await persist_assessment_recommendations(
                        service_container=self.service_container,
                        user_id=user_id,
                        intake_session_id=session_id,
                        recommendations=recommendations,
                    )
                    await send_assessment_recommendations(
                        conversation_manager=self.conversation_manager,
                        session_id=session_id,
                        user_id=user_id,
                        recommendations=recommendations,
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
            logger.info("User %s chose to start therapy session immediately", user_id)
            if not self._start_therapy_session:
                logger.error("Start therapy session callback not configured")
                return
            session_info = await self._start_therapy_session(user_id, session_id)
            logger.info(
                "Created new therapy session %s for user %s",
                session_info.session_id,
                user_id,
            )
            return

        logger.warning("Unknown agent action '%s' for user %s", action, user_id)

    async def run_reflection(self, user_id: str, session_id: str) -> None:
        """Run reflection automatically after a therapy session completes."""
        try:
            state = await self.workflow_engine.get_user_state(user_id)
            if state not in (
                WorkflowState.PLAN_UPDATE_IN_PROGRESS,
                WorkflowState.REFLECTION_IN_PROGRESS,
            ):
                logger.info(
                    "Skipping auto reflection for session %s (state=%s)",
                    session_id,
                    state,
                )
                return

            logger.info(
                "reflection_started session_id=%s user_id=%s state=%s",
                session_id,
                user_id,
                state.value,
            )
            trio_db_service = self.service_container.get("trio_db_service")
            session = await trio_db_service.get_session(session_id)
            if not session:
                raise RuntimeError(
                    f"Auto reflection failed: session not found for {session_id}"
                )

            context = await self.conversation_manager.get_context(session_id)
            reflection_agent = await self._get_agent("REFLECTION", user_id)
            agent_response = await reflection_agent.process_reflection(session, context)

            metadata = agent_response.metadata or {}
            reflection_payload = metadata.get("reflection")
            session_summary = None
            if isinstance(reflection_payload, dict):
                session_summary = reflection_payload.get("session_summary")
            plan_output = metadata.get("therapy_plan_output")
            if isinstance(plan_output, dict):
                plan_output = StructuredTherapyPlanOutput.model_validate(plan_output)
            session_briefing = metadata.get("session_briefing")
            plan_update_applied = metadata.get("plan_update_applied", True)
            if not isinstance(plan_output, StructuredTherapyPlanOutput):
                raise RuntimeError("Reflection did not produce a therapy plan update")
            if not plan_update_applied:
                raise RuntimeError("Reflection therapy plan update was not applied")
            if not isinstance(session_briefing, dict):
                raise RuntimeError("Reflection did not produce a session briefing")
            previous_plan = await trio_db_service.get_current_therapy_plan(user_id)
            persisted_plan = await persist_therapy_plan_from_output(
                trio_db_service=trio_db_service,
                user_id=user_id,
                plan_output=plan_output,
                session_briefing=session_briefing,
            )
            if previous_plan and persisted_plan.version <= previous_plan.version:
                raise RuntimeError("Reflection did not increment therapy plan version")

            user_profile_output = metadata.get("user_profile")
            if isinstance(user_profile_output, (dict, StructuredUserProfileOutput)):
                await persist_structured_user_profile_output(
                    trio_db_service=trio_db_service,
                    user_id=user_id,
                    session_id=session_id,
                    user_profile_output=user_profile_output,
                    change_summary="Reflection profile update",
                )

            success = await trio_db_service.update_session_reflection(
                session_id,
                session_summary,
                session_briefing,
            )
            if not success:
                raise RuntimeError(
                    "Failed to persist reflection summary/briefing for "
                    f"session {session_id}"
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

            if agent_response.workflow_event != WorkflowEvent.COMPLETE_REFLECTION:
                raise RuntimeError("Reflection did not signal completion")
            next_state = self.workflow_engine.get_next_state(
                state, agent_response.workflow_event
            )
            await self.workflow_engine.transition(
                user_id,
                next_state,
                event=agent_response.workflow_event,
            )
            self.conversation_manager.clear_context(session_id)

            logger.info(
                "reflection_completed session_id=%s user_id=%s final_state=%s",
                session_id,
                user_id,
                (await self.workflow_engine.get_user_state(user_id)).value,
            )
        except Exception as exc:
            logger.error(
                "reflection_failed session_id=%s",
                session_id,
                exc_info=True,
            )
            await self._surface_reflection_failure(user_id, session_id, exc)

    async def _surface_reflection_failure(
        self, user_id: str, session_id: str, exc: Exception
    ) -> None:
        """Send a user-visible error and expose a retryable workflow state."""
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
            ServerMessageTypes.ERROR,
            {
                "message": (
                    "Your session reflection could not be saved. Please retry "
                    "the plan update before starting another therapy session."
                )
            },
        )
        logger.error(
            "Reflection recovery response emitted for session %s (%s)",
            session_id,
            detail,
        )
        try:
            state = await self.workflow_engine.get_user_state(user_id)
            if state != WorkflowState.PLAN_UPDATE_FAILED:
                await self.workflow_engine.transition(
                    user_id,
                    WorkflowState.PLAN_UPDATE_FAILED,
                    event=WorkflowEvent.FAIL_REFLECTION,
                )
            self.conversation_manager.clear_context(session_id)
            logger.info(
                "reflection_transitioned_to_plan_update_failed "
                "session_id=%s user_id=%s reason=%s",
                session_id,
                user_id,
                detail,
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
        await run_reflection_job(
            run_reflection=self.run_reflection,
            emit_next_action=self._emit_next_action,
            surface_reflection_failure=self._surface_reflection_failure,
            reflection_jobs=self._reflection_jobs,
            timeout_seconds=self.service_container.config.REFLECTION_TIMEOUT_SECONDS,
            user_id=user_id,
            session_id=session_id,
            emit_session_id=emit_session_id,
        )

    async def _run_assessment_job(
        self, user_id: str, intake_session_id: str, emit_session_id: str | None = None
    ) -> None:
        """Run backend assessment and emit recommendations + next actions."""
        await run_assessment_job(
            workflow_engine=self.workflow_engine,
            conversation_manager=self.conversation_manager,
            service_container=self.service_container,
            emit_next_action=self._emit_next_action,
            assessment_recommendations=self._assessment_recommendations,
            assessment_jobs=self._assessment_jobs,
            user_id=user_id,
            intake_session_id=intake_session_id,
            emit_session_id=emit_session_id,
        )

    async def ensure_assessment_job(self, user_id: str, session_id: str) -> None:
        """Ensure a single assessment job is running for the user."""
        queue_assessment_job(
            user_id=user_id,
            session_id=session_id,
            assessment_jobs=self._assessment_jobs,
            nursery=self.nursery,
            runner=self._run_assessment_job,
        )

    async def ensure_reflection_job(self, user_id: str, session_id: str) -> None:
        """Ensure a single reflection job is running for the session."""
        queue_reflection_job(
            user_id=user_id,
            session_id=session_id,
            reflection_jobs=self._reflection_jobs,
            nursery=self.nursery,
            runner=self._run_reflection_job,
        )

    async def emit_assessment_recommendations(
        self, session_id: str, user_id: str
    ) -> None:
        """Re-emit cached or persisted assessment recommendations if available."""
        await emit_assessment_recommendations(
            service_container=self.service_container,
            conversation_manager=self.conversation_manager,
            session_id=session_id,
            user_id=user_id,
            cache=self._assessment_recommendations,
        )


_extract_error_code = extract_error_code
