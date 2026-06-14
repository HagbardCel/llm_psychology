from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from psychoanalyst_app.models.domain import Session, TherapyPlan
from psychoanalyst_app.models.llm_outputs import StructuredTherapyPlanOutput
from psychoanalyst_app.orchestration import response_reflection as reflection_module
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    WorkflowEvent,
    WorkflowState,
)
from psychoanalyst_app.orchestration.response_reflection import (
    run_reflection_transition,
)


@pytest.mark.trio
async def test_run_reflection_transition_happy_path(monkeypatch) -> None:
    session = Session(
        session_id="session_1",
        user_id="user_1",
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    previous_plan = TherapyPlan(
        plan_id="plan_0",
        user_id="user_1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        version=1,
        selected_therapy_style="cbt",
        focus="anxiety",
        initial_goals=["goal"],
        current_progress="progress",
        planned_interventions=["intervention"],
    )
    persisted_plan = TherapyPlan(
        plan_id="plan_1",
        user_id="user_1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        version=2,
        selected_therapy_style="cbt",
        focus="anxiety",
        initial_goals=["goal"],
        current_progress="updated",
        planned_interventions=["intervention"],
    )

    db_service = AsyncMock()
    db_service.get_session.return_value = session
    db_service.get_current_therapy_plan.return_value = previous_plan
    db_service.update_session_reflection.return_value = True
    db_service.update_session_tier2.return_value = True

    service_container = MagicMock()
    service_container.get.return_value = db_service

    workflow_engine = MagicMock()
    workflow_engine.get_user_state = AsyncMock(
        side_effect=[
            WorkflowState.PLAN_UPDATE_IN_PROGRESS,
            WorkflowState.PLAN_UPDATE_COMPLETE,
        ]
    )
    workflow_engine.get_next_state.return_value = WorkflowState.PLAN_UPDATE_COMPLETE
    workflow_engine.transition = AsyncMock()

    conversation_manager = MagicMock()
    conversation_manager.get_context = AsyncMock(return_value=SimpleNamespace())
    conversation_manager.clear_context = MagicMock()

    plan_output = StructuredTherapyPlanOutput(
        focus="anxiety",
        initial_goals=["goal"],
        current_progress="updated",
        planned_interventions=["intervention"],
    )
    session_briefing = {"summary": "briefing"}
    reflection_agent = AsyncMock()
    reflection_agent.process_reflection.return_value = AgentResponse(
        content="done",
        next_action="transition",
        workflow_event=WorkflowEvent.COMPLETE_REFLECTION,
        metadata={
            "therapy_plan_output": plan_output.model_dump(),
            "session_briefing": session_briefing,
            "plan_revision_required": True,
            "user_profile": {"name": "Test User"},
            "reflection": {"session_summary": "summary text"},
            "tier2_enrichment": {"themes": ["work stress"]},
            "tier3_update": {"change_detected": True},
        },
    )

    get_agent = AsyncMock(return_value=reflection_agent)
    emit_job_status = AsyncMock()

    persist_plan = AsyncMock(return_value=persisted_plan)
    persist_profile = AsyncMock()
    persist_tier3 = AsyncMock()
    monkeypatch.setattr(
        reflection_module, "persist_therapy_plan_from_output", persist_plan
    )
    monkeypatch.setattr(
        reflection_module,
        "persist_structured_user_profile_output",
        persist_profile,
    )
    monkeypatch.setattr(reflection_module, "persist_tier3_update", persist_tier3)

    await run_reflection_transition(
        service_container=service_container,
        workflow_engine=workflow_engine,
        conversation_manager=conversation_manager,
        get_agent=get_agent,
        emit_job_status=emit_job_status,
        user_id="user_1",
        session_id="session_1",
    )

    get_agent.assert_awaited_once_with("REFLECTION", "user_1")
    reflection_agent.process_reflection.assert_awaited_once()
    persist_plan.assert_awaited_once()
    persist_profile.assert_awaited_once()
    db_service.update_session_reflection.assert_awaited_once_with(
        "session_1",
        "summary text",
        session_briefing,
    )
    db_service.update_session_tier2.assert_awaited_once()
    persist_tier3.assert_awaited_once()
    workflow_engine.transition.assert_awaited_once_with(
        "user_1",
        WorkflowState.PLAN_UPDATE_COMPLETE,
        event=WorkflowEvent.COMPLETE_REFLECTION,
    )
    conversation_manager.clear_context.assert_called_once_with("session_1")
    assert emit_job_status.await_count == 4
    emit_job_status.assert_has_awaits(
        [
            call("plan_update:session_1", "user_1", "session_1"),
            call("post_session_update:session_1", "user_1", "session_1"),
            call("plan_update:session_1", "user_1", "session_1"),
            call("post_session_update:session_1", "user_1", "session_1"),
        ]
    )
