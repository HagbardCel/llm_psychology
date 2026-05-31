from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from psychoanalyst_app.models.data_models import Message, Session
from psychoanalyst_app.orchestration.helpers.active_sessions import (
    ActiveSessionRegistry,
    session_type_for_workflow_state,
)
from psychoanalyst_app.orchestration.helpers.persistence import persist_tier3_update
from psychoanalyst_app.orchestration.helpers.response_handler import (
    AgentResponseHandler,
    _extract_error_code,
)
from psychoanalyst_app.orchestration.helpers.response_jobs import run_assessment_job
from psychoanalyst_app.orchestration.helpers.session_lifecycle import (
    SessionLifecycleManager,
)
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    WorkflowEvent,
    WorkflowState,
)


def _session_with_agent(session_id: str, agent_name: str) -> Session:
    return Session(
        session_id=session_id,
        user_id="user_1",
        session_type="intake" if agent_name == "INTAKE" else "therapy",
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="hello",
                timestamp=datetime.now(),
                agent=agent_name,
            )
        ],
        topics=[],
    )


def test_active_session_registry_tracks_and_clears_sessions() -> None:
    registry = ActiveSessionRegistry()

    assert registry.get_active_session_id("u1") is None
    registry.set_active_session_id("u1", "s1")
    assert registry.get_active_session_id("u1") == "s1"
    assert registry.is_session_active("u1", "s1")

    registry.clear_active_session("u1", "other")
    assert registry.get_active_session_id("u1") == "s1"

    registry.clear_active_session("u1", "s1")
    assert registry.get_active_session_id("u1") is None


def test_session_type_for_workflow_state_mapping() -> None:
    assert session_type_for_workflow_state(WorkflowState.NEW) == "intake"
    assert (
        session_type_for_workflow_state(WorkflowState.ASSESSMENT_COMPLETE) == "intake"
    )
    assert session_type_for_workflow_state(WorkflowState.PLAN_UPDATE_FAILED) == "therapy"
    assert session_type_for_workflow_state(WorkflowState.PLAN_UPDATE_COMPLETE) == "therapy"


@pytest.mark.trio
async def test_session_lifecycle_ensure_session_id_sets_active_mapping() -> None:
    async def _process(_a: str, _b: str, _c: str | None):
        if False:  # pragma: no cover
            yield ""

    async def _run_reflection(_a: str, _b: str) -> None:
        return None

    manager = SessionLifecycleManager(
        service_container=MagicMock(),
        workflow_engine=AsyncMock(),
        conversation_manager=MagicMock(),
        nursery=MagicMock(),
        process_message=_process,
        run_reflection=_run_reflection,
    )

    resolved = await manager.ensure_session_id("user_1", "session_1")

    assert resolved == "session_1"
    assert manager.get_active_session_id("user_1") == "session_1"


@pytest.mark.trio
async def test_session_lifecycle_find_intake_sessions_filters_transcript_agent() -> (
    None
):
    db_service = AsyncMock()
    db_service.get_user_sessions.return_value = [
        _session_with_agent("intake_session", "INTAKE"),
        _session_with_agent("therapy_session", "THERAPIST"),
    ]
    service_container = MagicMock()
    service_container.get.return_value = db_service

    async def _process(_a: str, _b: str, _c: str | None):
        if False:  # pragma: no cover
            yield ""

    async def _run_reflection(_a: str, _b: str) -> None:
        return None

    manager = SessionLifecycleManager(
        service_container=service_container,
        workflow_engine=AsyncMock(),
        conversation_manager=MagicMock(),
        nursery=MagicMock(),
        process_message=_process,
        run_reflection=_run_reflection,
    )

    intake_sessions = await manager.find_intake_sessions("user_1")

    assert len(intake_sessions) == 1
    assert intake_sessions[0].session_id == "intake_session"


@pytest.mark.trio
async def test_session_lifecycle_ensure_session_reuses_intake_after_memory_loss() -> (
    None
):
    intake_session = _session_with_agent("intake_session", "INTAKE")
    db_service = AsyncMock()
    db_service.get_user_sessions.return_value = [intake_session]
    db_service.get_session.return_value = intake_session
    service_container = MagicMock()
    service_container.get.return_value = db_service
    workflow_engine = MagicMock()
    workflow_engine.get_user_state = AsyncMock(
        return_value=WorkflowState.INTAKE_IN_PROGRESS
    )
    workflow_engine.get_current_agent.return_value = "INTAKE"

    async def _process(_a: str, _b: str, _c: str | None):
        if False:  # pragma: no cover
            yield ""

    async def _run_reflection(_a: str, _b: str) -> None:
        return None

    manager = SessionLifecycleManager(
        service_container=service_container,
        workflow_engine=workflow_engine,
        conversation_manager=MagicMock(),
        nursery=MagicMock(),
        process_message=_process,
        run_reflection=_run_reflection,
    )

    session_info = await manager.ensure_session(
        "user_1",
        session_type="intake",
        send_initial_message=False,
    )

    assert session_info.session_id == "intake_session"
    assert manager.get_active_session_id("user_1") == "intake_session"
    db_service.save_session.assert_not_called()


@pytest.mark.trio
async def test_persist_tier3_update_returns_false_when_payload_incomplete() -> None:
    db_service = AsyncMock()
    result = await persist_tier3_update(
        trio_db_service=db_service,
        user_id="user_1",
        session_id="session_1",
        tier3_update={},
    )
    assert result is False
    db_service.save_patient_analysis_next_version_and_supersede.assert_not_called()


def test_extract_error_code_parses_common_patterns() -> None:
    assert _extract_error_code("HTTP 429 quota exceeded") == "429"
    assert _extract_error_code("status=503 backend unavailable") == "503"
    assert _extract_error_code("something failed: 500") == "500"
    assert _extract_error_code("no numeric code here") is None


@pytest.mark.trio
async def test_response_handler_job_queues_are_idempotent() -> None:
    nursery = MagicMock()
    handler = AgentResponseHandler(
        service_container=SimpleNamespace(
            config=SimpleNamespace(REFLECTION_TIMEOUT_SECONDS=60)
        ),
        workflow_engine=AsyncMock(),
        conversation_manager=MagicMock(),
        nursery=nursery,
        get_agent=AsyncMock(),
    )

    await handler.ensure_assessment_job("user_1", "session_1")
    await handler.ensure_assessment_job("user_1", "session_1")
    await handler.ensure_reflection_job("user_1", "session_1")
    await handler.ensure_reflection_job("user_1", "session_1")

    assert nursery.start_soon.call_count == 2


@pytest.mark.trio
async def test_run_reflection_without_persistable_update_fails_plan_update() -> None:
    session = Session(
        session_id="session_1",
        user_id="user_1",
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    db_service = AsyncMock()
    db_service.get_session.return_value = session
    db_service.update_session_reflection.return_value = True
    service_container = MagicMock()
    service_container.get.return_value = db_service

    workflow_engine = AsyncMock()
    workflow_engine.get_user_state.return_value = WorkflowState.PLAN_UPDATE_IN_PROGRESS

    conversation_manager = MagicMock()
    conversation_manager.get_context = AsyncMock(return_value=SimpleNamespace())
    conversation_manager.send_json_message = AsyncMock()
    conversation_manager.clear_context = MagicMock()

    reflection_agent = AsyncMock()
    reflection_agent.process_reflection.return_value = AgentResponse(
        content="done",
        next_action="transition",
        workflow_event=None,
        metadata={},
    )

    handler = AgentResponseHandler(
        service_container=service_container,
        workflow_engine=workflow_engine,
        conversation_manager=conversation_manager,
        nursery=MagicMock(),
        get_agent=AsyncMock(return_value=reflection_agent),
    )

    await handler.run_reflection("user_1", "session_1")

    workflow_engine.transition.assert_awaited_once_with(
        "user_1",
        WorkflowState.PLAN_UPDATE_FAILED,
        event=WorkflowEvent.FAIL_REFLECTION,
    )
    conversation_manager.clear_context.assert_called_once_with("session_1")


@pytest.mark.trio
async def test_surface_reflection_failure_exposes_retryable_state() -> None:
    workflow_engine = AsyncMock()
    workflow_engine.get_user_state.return_value = WorkflowState.PLAN_UPDATE_IN_PROGRESS
    conversation_manager = MagicMock()
    conversation_manager.send_json_message = AsyncMock()
    conversation_manager.clear_context = MagicMock()
    handler = AgentResponseHandler(
        service_container=SimpleNamespace(
            config=SimpleNamespace(REFLECTION_TIMEOUT_SECONDS=60)
        ),
        workflow_engine=workflow_engine,
        conversation_manager=conversation_manager,
        nursery=MagicMock(),
        get_agent=AsyncMock(),
    )

    await handler._surface_reflection_failure(
        "user_1", "session_1", RuntimeError("reflection failed")
    )

    workflow_engine.transition.assert_awaited_once_with(
        "user_1",
        WorkflowState.PLAN_UPDATE_FAILED,
        event=WorkflowEvent.FAIL_REFLECTION,
    )
    conversation_manager.clear_context.assert_called_once_with("session_1")


@pytest.mark.trio
async def test_assessment_job_emits_error_and_fallback_recommendations() -> None:
    workflow_engine = AsyncMock()
    workflow_engine.get_user_state.return_value = WorkflowState.INTAKE_COMPLETE
    conversation_manager = AsyncMock()
    conversation_manager.get_context.return_value = SimpleNamespace()
    assessment_agent = AsyncMock()
    assessment_agent.process_assessment.return_value = AgentResponse(
        content="failed",
        next_action="continue",
        metadata={"error": "quota exhausted"},
    )
    style_service = SimpleNamespace(
        get_available_styles=lambda: ["cbt", "freud", "jung"]
    )
    db_service = AsyncMock()
    service_container = MagicMock()
    service_container.create_agent.return_value = assessment_agent
    service_container.get.side_effect = lambda name: (
        db_service if name == "trio_db_service" else style_service
    )
    emitted_next_actions: list[tuple[str, str | None]] = []

    async def emit_next_action(user_id: str, session_id: str | None) -> None:
        emitted_next_actions.append((user_id, session_id))

    assessment_recommendations: dict[str, list[dict[str, Any]]] = {}
    assessment_jobs = {"user_1"}

    await run_assessment_job(
        workflow_engine=workflow_engine,
        conversation_manager=conversation_manager,
        service_container=service_container,
        emit_next_action=emit_next_action,
        assessment_recommendations=assessment_recommendations,
        assessment_jobs=assessment_jobs,
        user_id="user_1",
        intake_session_id="session_1",
    )

    message_types = [
        call.args[1] for call in conversation_manager.send_json_message.await_args_list
    ]
    assert "error" in message_types
    assert "assessment_recommendations" in message_types
    assert assessment_recommendations["user_1"][0]["style_id"] == "cbt"
    db_service.save_assessment_recommendations.assert_awaited_once_with(
        user_id="user_1",
        intake_session_block_id="session_1",
        recommendations=assessment_recommendations["user_1"],
    )
    workflow_engine.transition.assert_any_await(
        "user_1",
        WorkflowState.ASSESSMENT_COMPLETE,
        event=WorkflowEvent.COMPLETE_ASSESSMENT,
    )
    assert assessment_jobs == set()


@pytest.mark.trio
async def test_response_handler_reemits_persisted_assessment_recommendations() -> None:
    recommendations = [
        {
            "style_id": "cbt",
            "explanation": "Structured practical support.",
            "score": 0.9,
        }
    ]
    db_service = AsyncMock()
    db_service.get_latest_assessment_recommendations.return_value = recommendations
    service_container = MagicMock()
    service_container.get.return_value = db_service
    handler = AgentResponseHandler(
        service_container=service_container,
        workflow_engine=AsyncMock(),
        conversation_manager=AsyncMock(),
        nursery=MagicMock(),
        get_agent=AsyncMock(),
    )

    await handler.emit_assessment_recommendations("session_1", "user_1")

    db_service.get_latest_assessment_recommendations.assert_awaited_once_with("user_1")
    assert handler._assessment_recommendations["user_1"] == recommendations
    handler.conversation_manager.send_json_message.assert_awaited_once()
    args = handler.conversation_manager.send_json_message.await_args.args
    assert args[0] == "session_1"
    assert args[1] == "assessment_recommendations"
    assert args[2]["recommendations"] == recommendations
