from unittest.mock import AsyncMock

import pytest

from psychoanalyst_app.exceptions import InvalidStateTransitionError
from psychoanalyst_app.orchestration.models import WorkflowEvent, WorkflowState
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine


pytestmark = pytest.mark.unit


def test_workflow_engine_accepts_new_plan_state_path() -> None:
    engine = TrioWorkflowEngine(AsyncMock())

    assert engine.can_transition(
        WorkflowState.ASSESSMENT_COMPLETE, WorkflowState.INITIAL_PLAN_COMPLETE
    )
    assert engine.can_transition(
        WorkflowState.INITIAL_PLAN_COMPLETE, WorkflowState.THERAPY_IN_PROGRESS
    )
    assert engine.can_transition(
        WorkflowState.THERAPY_IN_PROGRESS, WorkflowState.PLAN_UPDATE_IN_PROGRESS
    )
    assert engine.can_transition(
        WorkflowState.PLAN_UPDATE_IN_PROGRESS, WorkflowState.PLAN_UPDATE_COMPLETE
    )
    assert engine.can_transition(
        WorkflowState.PLAN_UPDATE_COMPLETE, WorkflowState.THERAPY_IN_PROGRESS
    )


def test_workflow_engine_rejects_overloaded_plan_update_complete_jump() -> None:
    engine = TrioWorkflowEngine(AsyncMock())

    assert not engine.can_transition(
        WorkflowState.ASSESSMENT_COMPLETE, WorkflowState.PLAN_UPDATE_COMPLETE
    )
    assert not engine.can_transition(
        WorkflowState.THERAPY_IN_PROGRESS, WorkflowState.PLAN_UPDATE_COMPLETE
    )


def test_workflow_engine_session_end_enters_plan_update() -> None:
    engine = TrioWorkflowEngine(AsyncMock())

    assert (
        engine.get_next_state(
            WorkflowState.THERAPY_IN_PROGRESS, WorkflowEvent.COMPLETE_SESSION
        )
        == WorkflowState.PLAN_UPDATE_IN_PROGRESS
    )
    assert (
        engine.get_next_state(
            WorkflowState.PLAN_UPDATE_IN_PROGRESS, WorkflowEvent.COMPLETE_REFLECTION
        )
        == WorkflowState.PLAN_UPDATE_COMPLETE
    )

    with pytest.raises(InvalidStateTransitionError):
        engine.get_next_state(
            WorkflowState.THERAPY_IN_PROGRESS, WorkflowEvent.COMPLETE_REFLECTION
        )
