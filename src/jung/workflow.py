"""Pure workflow stage derivation and command availability policy."""

from __future__ import annotations

from uuid import UUID

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


def derive_stage(
    *,
    profile_complete: bool,
    active_session: Session | None,
    current_plan_id: UUID | None,
    has_any_plan: bool,
    current_operation: Operation | None,
    operation_source_session: Session | None,
    has_completed_assessment: bool,
) -> Stage:
    """Derive the current workflow stage from durable present-state signals."""
    has_progress = (
        active_session is not None
        or current_operation is not None
        or current_plan_id is not None
        or has_any_plan
        or has_completed_assessment
    )

    if not profile_complete:
        if has_progress:
            raise InvariantViolation(
                "incomplete profile cannot coexist with workflow progress"
            )
        return Stage.SETUP

    if current_operation is not None and active_session is not None:
        raise InvariantViolation(
            "current operation cannot coexist with an active session"
        )

    if current_operation is not None:
        if operation_source_session is None:
            raise InvariantViolation("current operation is missing its source session")
        if current_operation.kind is OperationKind.ASSESSMENT:
            return _derive_assessment_stage(
                current_plan_id=current_plan_id,
                has_any_plan=has_any_plan,
                has_completed_assessment=has_completed_assessment,
                source_session=operation_source_session,
            )
        if current_operation.kind is OperationKind.POST_SESSION:
            return _derive_post_session_stage(
                current_plan_id=current_plan_id,
                has_completed_assessment=has_completed_assessment,
                source_session=operation_source_session,
            )
        raise InvariantViolation(
            f"unknown operation kind: {current_operation.kind.value}"
        )

    if active_session is not None:
        if active_session.kind is SessionKind.INTAKE:
            return _derive_intake_stage(
                active_session=active_session,
                current_plan_id=current_plan_id,
                has_any_plan=has_any_plan,
                has_completed_assessment=has_completed_assessment,
            )
        if active_session.kind is SessionKind.THERAPY:
            return _derive_therapy_stage(
                active_session=active_session,
                current_plan_id=current_plan_id,
                has_completed_assessment=has_completed_assessment,
            )
        raise InvariantViolation(f"unknown session kind: {active_session.kind.value}")

    if current_plan_id is not None:
        if not has_completed_assessment:
            raise InvariantViolation("READY requires a completed assessment")
        if not has_any_plan:
            raise InvariantViolation("current plan exists but plans table is empty")
        return Stage.READY

    if has_completed_assessment:
        if has_any_plan:
            raise InvariantViolation(
                "STYLE_SELECTION cannot coexist with existing plans"
            )
        return Stage.STYLE_SELECTION

    if has_any_plan:
        raise InvariantViolation("plans exist without a current plan pointer")

    raise InvariantViolation(
        "complete profile has no derivable intake, assessment, or plan state"
    )


def available_commands(facts: WorkflowFacts) -> frozenset[CommandName]:
    """Return commands permitted for the current workflow facts."""
    stage = facts.stage
    if stage == Stage.SETUP:
        return frozenset({CommandName.UPDATE_PROFILE})

    if stage == Stage.INTAKE:
        return frozenset({CommandName.UPDATE_PROFILE, CommandName.SEND_MESSAGE})

    if stage == Stage.ASSESSMENT:
        if _failed_operation_retry_available(facts, OperationKind.ASSESSMENT):
            return frozenset({CommandName.RETRY_OPERATION})
        return frozenset()

    if stage == Stage.STYLE_SELECTION:
        return frozenset({CommandName.SELECT_STYLE})

    if stage == Stage.READY:
        return frozenset({CommandName.START_SESSION})

    if stage == Stage.THERAPY:
        return frozenset({CommandName.SEND_MESSAGE, CommandName.END_SESSION})

    if stage == Stage.POST_SESSION:
        if _failed_operation_retry_available(facts, OperationKind.POST_SESSION):
            return frozenset({CommandName.RETRY_OPERATION})
        return frozenset()

    raise InvariantViolation(f"unknown stage: {stage}")


def require_command_allowed(command: CommandName, facts: WorkflowFacts) -> None:
    """Raise InvalidCommand when the command is unavailable."""
    if command not in available_commands(facts):
        raise InvalidCommand(
            f"command {command.value} is not allowed in stage {facts.stage.value}"
        )


def _derive_intake_stage(
    *,
    active_session: Session,
    current_plan_id: UUID | None,
    has_any_plan: bool,
    has_completed_assessment: bool,
) -> Stage:
    if current_plan_id is not None:
        raise InvariantViolation("INTAKE cannot have a current plan")
    if has_any_plan:
        raise InvariantViolation("INTAKE cannot coexist with plan rows")
    if has_completed_assessment:
        raise InvariantViolation("INTAKE cannot coexist with a completed assessment")
    if active_session.plan_id is not None:
        raise InvariantViolation("intake session must not have a plan_id")
    return Stage.INTAKE


def _derive_assessment_stage(
    *,
    current_plan_id: UUID | None,
    has_any_plan: bool,
    has_completed_assessment: bool,
    source_session: Session,
) -> Stage:
    if current_plan_id is not None:
        raise InvariantViolation("ASSESSMENT cannot have a current plan")
    if has_any_plan:
        raise InvariantViolation("ASSESSMENT cannot coexist with plan rows")
    if has_completed_assessment:
        raise InvariantViolation(
            "ASSESSMENT cannot coexist with a previously completed assessment"
        )
    if source_session.kind is not SessionKind.INTAKE:
        raise InvariantViolation("assessment source session must be intake")
    if source_session.ended_at is None:
        raise InvariantViolation("assessment source intake session must be ended")
    if source_session.intake_record is None:
        raise InvariantViolation(
            "assessment source intake session must have an intake_record"
        )
    return Stage.ASSESSMENT


def _derive_therapy_stage(
    *,
    active_session: Session,
    current_plan_id: UUID | None,
    has_completed_assessment: bool,
) -> Stage:
    if current_plan_id is None:
        raise InvariantViolation("THERAPY requires a current plan")
    if not has_completed_assessment:
        raise InvariantViolation("THERAPY requires a completed assessment")
    if active_session.plan_id is None:
        raise InvariantViolation("therapy session requires a plan_id")
    if active_session.plan_id != current_plan_id:
        raise InvariantViolation(
            "therapy session plan_id must match profile.current_plan_id"
        )
    return Stage.THERAPY


def _derive_post_session_stage(
    *,
    current_plan_id: UUID | None,
    has_completed_assessment: bool,
    source_session: Session,
) -> Stage:
    if current_plan_id is None:
        raise InvariantViolation("POST_SESSION requires a current plan")
    if not has_completed_assessment:
        raise InvariantViolation("POST_SESSION requires a completed assessment")
    if source_session.kind is not SessionKind.THERAPY:
        raise InvariantViolation("post-session source session must be therapy")
    if source_session.ended_at is None:
        raise InvariantViolation("post-session source therapy session must be ended")
    if source_session.plan_id is None:
        raise InvariantViolation("post-session source therapy session requires plan_id")
    if source_session.plan_id != current_plan_id:
        raise InvariantViolation(
            "post-session source session plan_id must match profile.current_plan_id"
        )
    return Stage.POST_SESSION


def _failed_operation_retry_available(
    facts: WorkflowFacts,
    kind: OperationKind,
) -> bool:
    return (
        facts.operation_kind == kind
        and facts.operation_status == OperationStatus.FAILED
        and facts.operation_retryable is True
    )
