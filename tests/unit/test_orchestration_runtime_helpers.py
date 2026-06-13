from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from psychoanalyst_app.models.http import RequiredWorkflowAction
from psychoanalyst_app.orchestration.models import WorkflowState
from psychoanalyst_app.orchestration.response_handler import AgentResponseHandler
from psychoanalyst_app.orchestration.stream_dispatch import (
    send_json_message,
    send_stream_chunk,
    send_typing_indicator,
)
from psychoanalyst_app.orchestration.workflow_transitions import (
    emit_workflow_next_action,
)


class _DummyWS:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, payload: str) -> None:
        self.messages.append(payload)


@pytest.mark.trio
async def test_emit_workflow_next_action_sends_navigation_event_only() -> None:
    action = SimpleNamespace(
        workflow_state=WorkflowState.REFLECTION_IN_PROGRESS.value,
        required_action=RequiredWorkflowAction.SELECT_THERAPY_STYLE,
        state_signature="signature_1",
        emission_source=None,
        model_dump=lambda mode="json": {"required_action": "select_therapy_style"},
    )
    get_action = AsyncMock(return_value=action)

    session_lifecycle = SimpleNamespace(get_active_session_id=lambda _uid: "session_1")
    conversation_manager = SimpleNamespace(
        send_json_message=AsyncMock(),
        has_initial_greeting_sent=lambda _sid: False,
    )
    response_handler = SimpleNamespace(
        ensure_reflection_job=AsyncMock(),
        emit_assessment_recommendations=AsyncMock(),
    )
    send_initial_greeting = MagicMock()

    await emit_workflow_next_action(
        user_id="user_1",
        session_id=None,
        session_lifecycle=session_lifecycle,
        conversation_manager=conversation_manager,
        response_handler=response_handler,
        send_initial_greeting=send_initial_greeting,
        get_workflow_next_action=get_action,
        emitted_signatures={},
        emission_source="test_emit",
    )

    conversation_manager.send_json_message.assert_awaited_once()
    response_handler.ensure_reflection_job.assert_not_awaited()
    response_handler.emit_assessment_recommendations.assert_not_awaited()
    send_initial_greeting.assert_not_called()


@pytest.mark.trio
async def test_emit_workflow_next_action_replays_recommendations_on_resume() -> None:
    action = SimpleNamespace(
        workflow_state=WorkflowState.ASSESSMENT_COMPLETE.value,
        required_action=RequiredWorkflowAction.SELECT_THERAPY_STYLE,
        state_signature="signature_1",
        emission_source=None,
        model_dump=lambda mode="json": {"required_action": "select_therapy_style"},
    )
    response_handler = SimpleNamespace(
        emit_assessment_recommendations=AsyncMock(),
    )
    await emit_workflow_next_action(
        user_id="user_1",
        session_id="session_1",
        session_lifecycle=SimpleNamespace(get_active_session_id=lambda _uid: None),
        conversation_manager=SimpleNamespace(
            send_json_message=AsyncMock(),
            has_initial_greeting_sent=lambda _sid: False,
        ),
        response_handler=response_handler,
        send_initial_greeting=MagicMock(),
        get_workflow_next_action=AsyncMock(return_value=action),
        emitted_signatures={},
        emission_source="websocket_connect_emit",
        include_resume_payloads=True,
        force_emit=True,
    )

    response_handler.emit_assessment_recommendations.assert_awaited_once_with(
        "session_1", "user_1"
    )


@pytest.mark.trio
async def test_emit_workflow_next_action_suppresses_equivalent_normal_event() -> None:
    action = SimpleNamespace(
        workflow_state=WorkflowState.ASSESSMENT_IN_PROGRESS.value,
        required_action=RequiredWorkflowAction.WAIT,
        state_signature="signature_1",
        emission_source=None,
        model_dump=lambda mode="json": {"required_action": "wait"},
    )
    conversation_manager = SimpleNamespace(
        send_json_message=AsyncMock(),
        has_initial_greeting_sent=lambda _sid: False,
    )
    await emit_workflow_next_action(
        user_id="user_1",
        session_id="session_1",
        session_lifecycle=SimpleNamespace(get_active_session_id=lambda _uid: None),
        conversation_manager=conversation_manager,
        response_handler=SimpleNamespace(),
        send_initial_greeting=MagicMock(),
        get_workflow_next_action=AsyncMock(return_value=action),
        emitted_signatures={"user_1:session_1": "signature_1"},
        emission_source="test_emit",
    )

    conversation_manager.send_json_message.assert_not_awaited()


@pytest.mark.trio
async def test_stream_dispatch_helpers_emit_ws_payloads() -> None:
    ws = _DummyWS()
    websockets = {"session_1": ws}

    await send_stream_chunk(
        websockets=websockets,
        session_id="session_1",
        chunk="hello",
        is_complete=False,
    )
    await send_typing_indicator(
        websockets=websockets,
        session_id="session_1",
        is_typing=True,
    )
    await send_json_message(
        websockets=websockets,
        session_id="session_1",
        message_type="workflow_next_action",
        data={"required_action": "continue_therapy"},
    )

    assert len(ws.messages) == 3


@pytest.mark.trio
async def test_response_handler_emits_job_status_event() -> None:
    db_service = SimpleNamespace(
        get_session=AsyncMock(return_value=None),
        get_user_profile=AsyncMock(return_value=None),
    )
    service_container = SimpleNamespace(get=lambda name: db_service)
    workflow_engine = SimpleNamespace(
        get_user_state=AsyncMock(return_value=WorkflowState.ASSESSMENT_IN_PROGRESS)
    )
    conversation_manager = SimpleNamespace(send_json_message=AsyncMock())
    handler = AgentResponseHandler(
        service_container=service_container,
        workflow_engine=workflow_engine,
        conversation_manager=conversation_manager,
        nursery=SimpleNamespace(),
        get_agent=AsyncMock(),
    )
    handler._assessment_jobs.add("user_1")

    await handler.emit_job_status("assessment:user_1", "user_1", "session_1")

    conversation_manager.send_json_message.assert_awaited_once()
    args = conversation_manager.send_json_message.await_args.args
    assert args[0] == "session_1"
    assert args[1] == "job_status"
    assert args[2]["status"] == "running"
