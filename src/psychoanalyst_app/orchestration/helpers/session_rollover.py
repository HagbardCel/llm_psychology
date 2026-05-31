"""Therapy-session rollover after assessment completes."""

from __future__ import annotations

import uuid
from datetime import datetime

from psychoanalyst_app.models.data_models import Message, Session
from psychoanalyst_app.orchestration.models import SessionInfo, WorkflowEvent, WorkflowState
from psychoanalyst_app.utils.ws_protocol import ServerMessageTypes


async def start_therapy_session(manager, user_id: str, current_session_id: str) -> SessionInfo:
    """Replace the intake control session with a plan-linked therapy session."""
    if not manager.is_session_active(user_id, current_session_id):
        raise ValueError("Intake session is not active for this user")

    db_service = manager.service_container.get("trio_db_service")
    current_session = await db_service.get_session(current_session_id)
    if not current_session or current_session.session_type != "intake":
        raise ValueError("Therapy can only start from the active intake session")
    if await manager.workflow_engine.get_user_state(user_id) != WorkflowState.INITIAL_PLAN_COMPLETE:
        raise ValueError("Therapy can only start after the initial plan is complete")

    plan = await db_service.get_current_therapy_plan(user_id)
    if not plan or not plan.selected_therapy_style:
        raise ValueError("Therapy plan with selected style not found")

    new_session_id = str(uuid.uuid4())
    therapy_session = Session(
        session_id=new_session_id,
        user_id=user_id,
        session_type="therapy",
        plan_id=plan.plan_id,
        timestamp=datetime.now(),
        transcript=[Message(role="system", content="Session started", timestamp=datetime.now())],
        topics=[],
    )
    if not await db_service.save_session(therapy_session):
        raise ValueError("Failed to save therapy session to database")

    await manager.workflow_engine.transition(
        user_id, WorkflowState.THERAPY_IN_PROGRESS, event=WorkflowEvent.START_THERAPY
    )
    manager.active_sessions.set_active_session_id(user_id, new_session_id)
    manager.conversation_manager.clear_context(current_session_id)

    ws = manager.conversation_manager.websockets.get(current_session_id)
    if ws is not None:
        manager.conversation_manager.unregister_websocket(current_session_id)
        manager.conversation_manager.register_websocket(new_session_id, ws)

    session_info = await manager._build_session_info(user_id, new_session_id)
    if ws is not None:
        await manager.conversation_manager.send_json_message(
            new_session_id, ServerMessageTypes.SESSION_STARTED, session_info.to_dict()
        )
        if manager._emit_next_action:
            await manager._emit_next_action(user_id, new_session_id)
    manager.send_initial_greeting(user_id, new_session_id)
    return session_info
