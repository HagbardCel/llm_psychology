"""Table-driven tests for pure workflow policy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from jung.domain.errors import InvalidCommand, InvariantViolation
from jung.domain.models import (
    CommandName,
    Operation,
    OperationKind,
    OperationStatus,
    Session,
    SessionKind,
    Stage,
    WorkflowFacts,
)
from jung.workflow import available_commands, derive_stage, require_command_allowed


def _now() -> datetime:
    return datetime.now(UTC)


def _session(
    *,
    kind: SessionKind = SessionKind.INTAKE,
    plan_id: UUID | None = None,
    ended_at: datetime | None = None,
    intake_record: dict[str, Any] | None = None,
) -> Session:
    return Session(
        id=uuid4(),
        kind=kind,
        plan_id=plan_id,
        started_at=_now(),
        ended_at=ended_at,
        intake_record=intake_record,
    )


def _operation(
    *,
    kind: OperationKind = OperationKind.ASSESSMENT,
    status: OperationStatus = OperationStatus.PENDING,
    source_session_id: UUID | None = None,
    retryable: bool = False,
) -> Operation:
    stamp = _now()
    return Operation(
        id=uuid4(),
        kind=kind,
        status=status,
        source_session_id=source_session_id or uuid4(),
        attempt=0,
        retryable=retryable,
        created_at=stamp,
        updated_at=stamp,
    )


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (
            WorkflowFacts(stage=Stage.SETUP, profile_complete=False),
            frozenset({CommandName.UPDATE_PROFILE}),
        ),
        (
            WorkflowFacts(stage=Stage.INTAKE, profile_complete=True),
            frozenset({CommandName.UPDATE_PROFILE, CommandName.SEND_MESSAGE}),
        ),
        (
            WorkflowFacts(
                stage=Stage.ASSESSMENT,
                profile_complete=True,
                operation_kind=OperationKind.ASSESSMENT,
                operation_status=OperationStatus.FAILED,
                operation_retryable=True,
            ),
            frozenset({CommandName.RETRY_OPERATION}),
        ),
        (
            WorkflowFacts(
                stage=Stage.ASSESSMENT,
                profile_complete=True,
                operation_kind=OperationKind.ASSESSMENT,
                operation_status=OperationStatus.FAILED,
                operation_retryable=False,
            ),
            frozenset(),
        ),
        (
            WorkflowFacts(stage=Stage.STYLE_SELECTION, profile_complete=True),
            frozenset({CommandName.SELECT_STYLE}),
        ),
        (
            WorkflowFacts(stage=Stage.READY, profile_complete=True),
            frozenset({CommandName.START_SESSION}),
        ),
        (
            WorkflowFacts(stage=Stage.THERAPY, profile_complete=True),
            frozenset({CommandName.SEND_MESSAGE, CommandName.END_SESSION}),
        ),
        (
            WorkflowFacts(
                stage=Stage.POST_SESSION,
                profile_complete=True,
                operation_kind=OperationKind.POST_SESSION,
                operation_status=OperationStatus.FAILED,
                operation_retryable=True,
            ),
            frozenset({CommandName.RETRY_OPERATION}),
        ),
        (
            WorkflowFacts(
                stage=Stage.POST_SESSION,
                profile_complete=True,
                operation_kind=OperationKind.POST_SESSION,
                operation_status=OperationStatus.FAILED,
                operation_retryable=False,
            ),
            frozenset(),
        ),
    ],
)
def test_available_commands_matrix(
    facts: WorkflowFacts, expected: frozenset[CommandName]
) -> None:
    assert available_commands(facts) == expected


def test_therapy_commands_always_include_end_session() -> None:
    commands = available_commands(
        WorkflowFacts(stage=Stage.THERAPY, profile_complete=True)
    )
    assert CommandName.END_SESSION in commands
    assert CommandName.SEND_MESSAGE in commands


def test_require_command_allowed_rejects_invalid():
    facts = WorkflowFacts(stage=Stage.SETUP, profile_complete=False)
    with pytest.raises(InvalidCommand):
        require_command_allowed(CommandName.SEND_MESSAGE, facts)


def test_derive_stage_setup() -> None:
    assert (
        derive_stage(
            profile_complete=False,
            active_session=None,
            current_plan_id=None,
            has_any_plan=False,
            current_operation=None,
            operation_source_session=None,
            has_completed_assessment=False,
        )
        == Stage.SETUP
    )


def test_derive_stage_intake() -> None:
    assert (
        derive_stage(
            profile_complete=True,
            active_session=_session(kind=SessionKind.INTAKE),
            current_plan_id=None,
            has_any_plan=False,
            current_operation=None,
            operation_source_session=None,
            has_completed_assessment=False,
        )
        == Stage.INTAKE
    )


def test_derive_stage_assessment() -> None:
    source = _session(
        kind=SessionKind.INTAKE,
        ended_at=_now(),
        intake_record={"schema_version": 1},
    )
    operation = _operation(source_session_id=source.id)
    assert (
        derive_stage(
            profile_complete=True,
            active_session=None,
            current_plan_id=None,
            has_any_plan=False,
            current_operation=operation,
            operation_source_session=source,
            has_completed_assessment=False,
        )
        == Stage.ASSESSMENT
    )


def test_derive_stage_style_selection() -> None:
    assert (
        derive_stage(
            profile_complete=True,
            active_session=None,
            current_plan_id=None,
            has_any_plan=False,
            current_operation=None,
            operation_source_session=None,
            has_completed_assessment=True,
        )
        == Stage.STYLE_SELECTION
    )


def test_derive_stage_ready() -> None:
    plan_id = uuid4()
    assert (
        derive_stage(
            profile_complete=True,
            active_session=None,
            current_plan_id=plan_id,
            has_any_plan=True,
            current_operation=None,
            operation_source_session=None,
            has_completed_assessment=True,
        )
        == Stage.READY
    )


def test_derive_stage_therapy() -> None:
    plan_id = uuid4()
    assert (
        derive_stage(
            profile_complete=True,
            active_session=_session(kind=SessionKind.THERAPY, plan_id=plan_id),
            current_plan_id=plan_id,
            has_any_plan=True,
            current_operation=None,
            operation_source_session=None,
            has_completed_assessment=True,
        )
        == Stage.THERAPY
    )


def test_derive_stage_post_session() -> None:
    plan_id = uuid4()
    source = _session(
        kind=SessionKind.THERAPY,
        plan_id=plan_id,
        ended_at=_now(),
    )
    operation = _operation(
        kind=OperationKind.POST_SESSION,
        source_session_id=source.id,
    )
    assert (
        derive_stage(
            profile_complete=True,
            active_session=None,
            current_plan_id=plan_id,
            has_any_plan=True,
            current_operation=operation,
            operation_source_session=source,
            has_completed_assessment=True,
        )
        == Stage.POST_SESSION
    )


def test_derive_stage_rejects_intake_with_completed_assessment() -> None:
    with pytest.raises(
        InvariantViolation, match="INTAKE cannot coexist with a completed assessment"
    ):
        derive_stage(
            profile_complete=True,
            active_session=_session(kind=SessionKind.INTAKE),
            current_plan_id=None,
            has_any_plan=False,
            current_operation=None,
            operation_source_session=None,
            has_completed_assessment=True,
        )


def test_derive_stage_rejects_assessment_without_intake_record() -> None:
    source = _session(kind=SessionKind.INTAKE, ended_at=_now(), intake_record=None)
    operation = _operation(source_session_id=source.id)
    with pytest.raises(InvariantViolation, match="intake_record"):
        derive_stage(
            profile_complete=True,
            active_session=None,
            current_plan_id=None,
            has_any_plan=False,
            current_operation=operation,
            operation_source_session=source,
            has_completed_assessment=False,
        )


def test_derive_stage_rejects_style_selection_with_orphan_plans() -> None:
    with pytest.raises(
        InvariantViolation, match="STYLE_SELECTION cannot coexist with existing plans"
    ):
        derive_stage(
            profile_complete=True,
            active_session=None,
            current_plan_id=None,
            has_any_plan=True,
            current_operation=None,
            operation_source_session=None,
            has_completed_assessment=True,
        )


def test_derive_stage_rejects_complete_profile_without_signals() -> None:
    with pytest.raises(InvariantViolation, match="no derivable"):
        derive_stage(
            profile_complete=True,
            active_session=None,
            current_plan_id=None,
            has_any_plan=False,
            current_operation=None,
            operation_source_session=None,
            has_completed_assessment=False,
        )
