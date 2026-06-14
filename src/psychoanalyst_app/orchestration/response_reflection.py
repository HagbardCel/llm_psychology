"""Reflection orchestration helper for response handling."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from psychoanalyst_app.models.llm_outputs import (
    StructuredTherapyPlanOutput,
    StructuredUserProfileOutput,
)
from psychoanalyst_app.orchestration.models import WorkflowEvent, WorkflowState
from psychoanalyst_app.orchestration.persistence import (
    persist_therapy_plan_from_output,
    persist_tier3_update,
)
from psychoanalyst_app.orchestration.profile_helpers import (
    persist_structured_user_profile_output,
)

logger = logging.getLogger(__name__)

GetAgentFn = Callable[[str, str], Awaitable[Any]]
EmitJobStatusFn = Callable[[str, str, str], Awaitable[None]]


async def run_reflection_transition(
    *,
    service_container: Any,
    workflow_engine: Any,
    conversation_manager: Any,
    get_agent: GetAgentFn,
    emit_job_status: EmitJobStatusFn,
    user_id: str,
    session_id: str,
) -> None:
    """Run reflection, persist outputs, and close the workflow transition."""
    await _emit_reflection_job_status(emit_job_status, user_id, session_id)
    state = await workflow_engine.get_user_state(user_id)
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
    trio_db_service = service_container.get("trio_db_service")
    session = await trio_db_service.get_session(session_id)
    if not session:
        raise RuntimeError(
            f"Auto reflection failed: session not found for {session_id}"
        )

    context = await conversation_manager.get_context(session_id)
    reflection_agent = await get_agent("REFLECTION", user_id)
    agent_response = await reflection_agent.process_reflection(session, context)
    metadata = agent_response.metadata or {}
    plan_output = _validated_plan_output(metadata)
    session_briefing = _validated_session_briefing(metadata)

    if _plan_revision_required(metadata):
        previous_plan = await trio_db_service.get_current_therapy_plan(user_id)
        persisted_plan = await persist_therapy_plan_from_output(
            trio_db_service=trio_db_service,
            user_id=user_id,
            plan_output=plan_output,
            session_briefing=session_briefing,
        )
        if previous_plan and persisted_plan.version <= previous_plan.version:
            raise RuntimeError("Reflection did not increment therapy plan version")

    await _persist_reflection_outputs(
        trio_db_service=trio_db_service,
        user_id=user_id,
        session_id=session_id,
        metadata=metadata,
        session_briefing=session_briefing,
    )
    if agent_response.workflow_event != WorkflowEvent.COMPLETE_REFLECTION:
        raise RuntimeError("Reflection did not signal completion")
    next_state = workflow_engine.get_next_state(state, agent_response.workflow_event)
    await workflow_engine.transition(
        user_id,
        next_state,
        event=agent_response.workflow_event,
    )
    conversation_manager.clear_context(session_id)
    logger.info(
        "reflection_completed session_id=%s user_id=%s final_state=%s",
        session_id,
        user_id,
        (await workflow_engine.get_user_state(user_id)).value,
    )
    await _emit_reflection_job_status(emit_job_status, user_id, session_id)


def _validated_plan_output(metadata: dict[str, Any]) -> StructuredTherapyPlanOutput:
    plan_output = metadata.get("therapy_plan_output")
    if isinstance(plan_output, dict):
        plan_output = StructuredTherapyPlanOutput.model_validate(plan_output)
    if not isinstance(plan_output, StructuredTherapyPlanOutput):
        raise RuntimeError("Reflection did not produce a therapy plan update")
    return plan_output


def _validated_session_briefing(metadata: dict[str, Any]) -> dict[str, Any]:
    session_briefing = metadata.get("session_briefing")
    if not isinstance(session_briefing, dict):
        raise RuntimeError("Reflection did not produce a session briefing")
    return session_briefing


def _plan_revision_required(metadata: dict[str, Any]) -> bool:
    return bool(
        metadata.get(
            "plan_revision_required",
            metadata.get("plan_update_applied", True),
        )
    )


async def _persist_reflection_outputs(
    *,
    trio_db_service: Any,
    user_id: str,
    session_id: str,
    metadata: dict[str, Any],
    session_briefing: dict[str, Any],
) -> None:
    reflection_payload = metadata.get("reflection")
    session_summary = None
    if isinstance(reflection_payload, dict):
        session_summary = reflection_payload.get("session_summary")
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
            "Failed to persist reflection summary/briefing for session "
            f"{session_id}"
        )
    await _persist_optional_tier_updates(
        trio_db_service=trio_db_service,
        user_id=user_id,
        session_id=session_id,
        metadata=metadata,
    )


async def _persist_optional_tier_updates(
    *,
    trio_db_service: Any,
    user_id: str,
    session_id: str,
    metadata: dict[str, Any],
) -> None:
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


async def _emit_reflection_job_status(
    emit_job_status: EmitJobStatusFn,
    user_id: str,
    session_id: str,
) -> None:
    await emit_job_status(f"plan_update:{session_id}", user_id, session_id)
    await emit_job_status(f"post_session_update:{session_id}", user_id, session_id)


__all__ = ["run_reflection_transition"]
