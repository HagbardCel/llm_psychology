"""Workflow transition policy helpers for session lifecycle operations."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.orchestration.agent_output_validators import is_profile_complete
from psychoanalyst_app.orchestration.models import WorkflowEvent, WorkflowState
from psychoanalyst_app.orchestration.trio_conversation_manager import (
    TrioConversationManager,
)
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine

logger = logging.getLogger(__name__)

RunReflectionFn = Callable[[str, str], Awaitable[None]]

SESSION_STATE_MAP: dict[str, WorkflowState] = {
    "intake": WorkflowState.INTAKE_IN_PROGRESS,
    "assessment": WorkflowState.ASSESSMENT_IN_PROGRESS,
    "therapy": WorkflowState.THERAPY_IN_PROGRESS,
}

SESSION_EVENT_MAP: dict[str, WorkflowEvent] = {
    "intake": WorkflowEvent.START_INTAKE,
    "assessment": WorkflowEvent.START_ASSESSMENT,
    "therapy": WorkflowEvent.START_THERAPY,
}


async def maybe_transition_for_session_start(
    *,
    user_id: str,
    normalized_session_type: str,
    state: WorkflowState,
    workflow_engine: TrioWorkflowEngine,
    service_container: ServiceContainer,
) -> WorkflowState:
    """Transition workflow for session start when policy conditions are satisfied."""
    desired_state = await _resolve_desired_start_state(
        user_id=user_id,
        normalized_session_type=normalized_session_type,
        state=state,
        service_container=service_container,
    )
    if not desired_state or desired_state == state:
        return state

    event = SESSION_EVENT_MAP.get(normalized_session_type)
    try:
        await workflow_engine.transition(user_id, desired_state, event=event)
        logger.info(
            "Transitioned user %s to %s for %s session",
            user_id,
            desired_state,
            normalized_session_type,
        )
        return desired_state
    except Exception as exc:
        logger.warning(
            "Could not transition user %s to %s for %s session: %s",
            user_id,
            desired_state,
            normalized_session_type,
            exc,
        )
        return state


async def _resolve_desired_start_state(
    *,
    user_id: str,
    normalized_session_type: str,
    state: WorkflowState,
    service_container: ServiceContainer,
) -> WorkflowState | None:
    desired_state = SESSION_STATE_MAP.get(normalized_session_type)
    if not desired_state or desired_state == state:
        return desired_state

    trio_db_service = service_container.get("trio_db_service")
    if desired_state == WorkflowState.INTAKE_IN_PROGRESS:
        profile = await trio_db_service.get_user_profile(user_id)
        if not profile or not is_profile_complete(profile):
            logger.info(
                "Skipping intake transition for user %s until profile is complete",
                user_id,
            )
            return None

    if (
        desired_state == WorkflowState.THERAPY_IN_PROGRESS
        and state in (
            WorkflowState.ASSESSMENT_COMPLETE,
            WorkflowState.INITIAL_PLAN_COMPLETE,
            WorkflowState.PLAN_UPDATE_COMPLETE,
        )
    ):
        plan = await trio_db_service.get_current_therapy_plan(user_id)
        if not plan or not plan.selected_therapy_style:
            logger.info(
                "Skipping therapy transition for user %s until therapy style "
                "is selected",
                user_id,
            )
            return None

    return desired_state


async def advance_workflow_on_session_end(
    *,
    user_id: str,
    session_id: str,
    state: WorkflowState,
    workflow_engine: TrioWorkflowEngine,
    conversation_manager: TrioConversationManager,
    service_container: ServiceContainer,
    run_reflection: RunReflectionFn,
) -> tuple[WorkflowState, RunReflectionFn | None, tuple[Any, ...]]:
    """Advance workflow state for session end and return follow-up job metadata."""
    final_state = state
    follow_up: RunReflectionFn | None = None
    follow_up_args: tuple[Any, ...] = ()

    try:
        if state == WorkflowState.THERAPY_IN_PROGRESS:
            trio_db_service = service_container.get("trio_db_service")
            session = await trio_db_service.get_session(session_id)
            if not session or session.session_type != "therapy":
                logger.warning(
                    "Skipping reflection for non-therapy session %s", session_id
                )
                return final_state, follow_up, follow_up_args
            await workflow_engine.transition(
                user_id,
                WorkflowState.PLAN_UPDATE_IN_PROGRESS,
                event=WorkflowEvent.COMPLETE_SESSION,
            )
            final_state = WorkflowState.PLAN_UPDATE_IN_PROGRESS
            conversation_manager.clear_context(session_id)
            try:
                await trio_db_service.enqueue_session_enrichment_job(
                    session_id, user_id
                )
            except Exception:
                logger.warning(
                    "Failed to enqueue Tier 2 enrichment job for session %s",
                    session_id,
                    exc_info=True,
                )
            follow_up = run_reflection
            follow_up_args = (user_id, session_id)
        elif state == WorkflowState.ASSESSMENT_IN_PROGRESS:
            await workflow_engine.transition(
                user_id,
                WorkflowState.ASSESSMENT_COMPLETE,
                event=WorkflowEvent.COMPLETE_ASSESSMENT,
            )
            final_state = WorkflowState.ASSESSMENT_COMPLETE
            conversation_manager.clear_context(session_id)
    except Exception:
        logger.error(
            "Failed to advance workflow on session end (user=%s, session=%s, state=%s)",
            user_id,
            session_id,
            state,
            exc_info=True,
        )

    return final_state, follow_up, follow_up_args
