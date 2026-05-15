"""Workflow next-action resolution/emission helpers."""

from __future__ import annotations

import logging

from psychoanalyst_app.models.api_models import RequiredWorkflowAction
from psychoanalyst_app.orchestration.models import WorkflowState
from psychoanalyst_app.orchestration.workflow_next_action import resolve_next_action
from psychoanalyst_app.utils.ws_protocol import ServerMessageTypes

logger = logging.getLogger(__name__)


async def get_workflow_next_action(
    *,
    service_container,
    workflow_engine,
    session_lifecycle,
    user_id: str,
    session_id: str | None = None,
    session=None,
):
    """Build the next action instruction for a user using the resolver."""
    trio_db_service = service_container.get("trio_db_service")
    profile = await trio_db_service.get_user_profile(user_id)
    plan = await trio_db_service.get_latest_therapy_plan(user_id)
    workflow_state = await workflow_engine.get_user_state(user_id)
    if session is None and session_id:
        session = await session_lifecycle.get_session_info(user_id, session_id)

    return resolve_next_action(
        user_id=user_id,
        profile=profile,
        plan=plan,
        workflow_state=workflow_state,
        session=session,
    )


async def emit_workflow_next_action(
    *,
    user_id: str,
    session_id: str | None,
    session_lifecycle,
    conversation_manager,
    response_handler,
    send_initial_greeting,
    get_workflow_next_action,
) -> None:
    """Emit workflow_next_action event and trigger dependent background jobs."""
    resolved_session_id = session_id or session_lifecycle.get_active_session_id(user_id)
    if not resolved_session_id:
        return

    try:
        action = await get_workflow_next_action(user_id, session_id=resolved_session_id)
        await conversation_manager.send_json_message(
            resolved_session_id,
            ServerMessageTypes.WORKFLOW_NEXT_ACTION,
            action.model_dump(mode="json"),
        )

        if action.workflow_state == WorkflowState.REFLECTION_IN_PROGRESS.value:
            await response_handler.ensure_reflection_job(user_id, resolved_session_id)

        if action.required_action == RequiredWorkflowAction.SELECT_THERAPY_STYLE:
            await response_handler.emit_assessment_recommendations(
                resolved_session_id,
                user_id,
            )

        if action.required_action in (
            RequiredWorkflowAction.START_INTAKE,
            RequiredWorkflowAction.CONTINUE_THERAPY,
        ):
            if not conversation_manager.has_initial_greeting_sent(resolved_session_id):
                send_initial_greeting(user_id, resolved_session_id)
    except Exception:
        logger.warning(
            "Failed to emit workflow next action (user=%s, session=%s)",
            user_id,
            resolved_session_id,
            exc_info=True,
        )
