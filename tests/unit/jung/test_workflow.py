"""Table-driven tests for pure workflow policy."""

from __future__ import annotations

import pytest

from jung.domain.errors import InvalidCommand
from jung.domain.models import (
    ChatTurnStatus,
    CommandName,
    OperationKind,
    OperationStatus,
    Stage,
    WorkflowFacts,
)
from jung.workflow import (
    available_commands,
    require_command_allowed,
    stage_after_intake_completion,
    stage_after_operation_completion,
    stage_after_profile_update,
    stage_after_session_end,
    stage_after_session_start,
    stage_after_style_selection,
)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (
            WorkflowFacts(stage=Stage.SETUP, profile_complete=False, has_active_session=False),
            frozenset({CommandName.UPDATE_PROFILE}),
        ),
        (
            WorkflowFacts(stage=Stage.INTAKE, profile_complete=True, has_active_session=True),
            frozenset({CommandName.UPDATE_PROFILE, CommandName.SEND_MESSAGE}),
        ),
        (
            WorkflowFacts(
                stage=Stage.ASSESSMENT,
                profile_complete=True,
                has_active_session=False,
                operation_kind=OperationKind.ASSESSMENT,
                operation_status=OperationStatus.FAILED,
            ),
            frozenset({CommandName.RETRY_OPERATION}),
        ),
        (
            WorkflowFacts(stage=Stage.STYLE_SELECTION, profile_complete=True, has_active_session=False),
            frozenset({CommandName.SELECT_STYLE}),
        ),
        (
            WorkflowFacts(stage=Stage.READY, profile_complete=True, has_active_session=False),
            frozenset({CommandName.START_SESSION}),
        ),
        (
            WorkflowFacts(stage=Stage.THERAPY, profile_complete=True, has_active_session=True),
            frozenset({CommandName.SEND_MESSAGE, CommandName.END_SESSION}),
        ),
        (
            WorkflowFacts(
                stage=Stage.POST_SESSION,
                profile_complete=True,
                has_active_session=False,
                operation_kind=OperationKind.POST_SESSION,
                operation_status=OperationStatus.FAILED,
            ),
            frozenset({CommandName.RETRY_OPERATION}),
        ),
    ],
)
def test_available_commands_matrix(facts: WorkflowFacts, expected: frozenset[CommandName]) -> None:
    assert available_commands(facts) == expected


def test_pending_chat_turn_blocks_commands():
    facts = WorkflowFacts(
        stage=Stage.THERAPY,
        profile_complete=True,
        has_active_session=True,
        chat_turn_status=ChatTurnStatus.PENDING,
    )
    assert available_commands(facts) == frozenset()


def test_require_command_allowed_rejects_invalid():
    facts = WorkflowFacts(stage=Stage.SETUP, profile_complete=False, has_active_session=False)
    with pytest.raises(InvalidCommand):
        require_command_allowed(CommandName.SEND_MESSAGE, facts)


@pytest.mark.parametrize(
    ("current", "profile_complete", "expected"),
    [
        (Stage.SETUP, False, Stage.SETUP),
        (Stage.SETUP, True, Stage.INTAKE),
        (Stage.INTAKE, True, Stage.INTAKE),
    ],
)
def test_stage_after_profile_update(current, profile_complete, expected):
    assert (
        stage_after_profile_update(current, profile_complete=profile_complete) == expected
    )


def test_stage_after_profile_update_rejects_other_stages():
    with pytest.raises(InvalidCommand):
        stage_after_profile_update(Stage.THERAPY, profile_complete=True)


def test_valid_stage_transitions():
    assert stage_after_intake_completion(Stage.INTAKE) == Stage.ASSESSMENT
    assert (
        stage_after_operation_completion(Stage.ASSESSMENT, OperationKind.ASSESSMENT)
        == Stage.STYLE_SELECTION
    )
    assert (
        stage_after_operation_completion(Stage.POST_SESSION, OperationKind.POST_SESSION)
        == Stage.READY
    )
    assert stage_after_style_selection(Stage.STYLE_SELECTION) == Stage.READY
    assert stage_after_session_start(Stage.READY) == Stage.THERAPY
    assert stage_after_session_end(Stage.THERAPY) == Stage.POST_SESSION


def test_invalid_stage_transitions_raise():
    with pytest.raises(InvalidCommand):
        stage_after_intake_completion(Stage.SETUP)
    with pytest.raises(InvalidCommand):
        stage_after_operation_completion(Stage.THERAPY, OperationKind.ASSESSMENT)
