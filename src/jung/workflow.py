"""Pure workflow command availability and stage transition policy."""

from __future__ import annotations

from jung.domain.errors import InvalidCommand, InvariantViolation
from jung.domain.models import (
    ChatTurnStatus,
    CommandName,
    OperationKind,
    OperationStatus,
    Stage,
    WorkflowFacts,
)


def available_commands(facts: WorkflowFacts) -> frozenset[CommandName]:
    """Return commands permitted for the current workflow facts."""
    if facts.chat_turn_status == ChatTurnStatus.PENDING:
        return frozenset()

    stage = facts.stage
    if stage == Stage.SETUP:
        return frozenset({CommandName.UPDATE_PROFILE})

    if stage == Stage.INTAKE:
        commands = {CommandName.UPDATE_PROFILE, CommandName.SEND_MESSAGE}
        return frozenset(commands)

    if stage == Stage.ASSESSMENT:
        if _failed_operation_retry_available(facts, OperationKind.ASSESSMENT):
            return frozenset({CommandName.RETRY_OPERATION})
        return frozenset()

    if stage == Stage.STYLE_SELECTION:
        return frozenset({CommandName.SELECT_STYLE})

    if stage == Stage.READY:
        return frozenset({CommandName.START_SESSION})

    if stage == Stage.THERAPY:
        commands = {CommandName.SEND_MESSAGE}
        if facts.has_active_session:
            commands.add(CommandName.END_SESSION)
        return frozenset(commands)

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


def stage_after_profile_update(
    current: Stage,
    *,
    profile_complete: bool,
) -> Stage:
    if current == Stage.SETUP and profile_complete:
        return Stage.INTAKE
    if current in {Stage.SETUP, Stage.INTAKE}:
        return current
    raise InvalidCommand(f"profile update is not allowed in stage {current.value}")


def stage_after_intake_completion(current: Stage) -> Stage:
    if current != Stage.INTAKE:
        raise InvalidCommand(
            f"intake completion is not allowed in stage {current.value}"
        )
    return Stage.ASSESSMENT


def stage_after_operation_completion(
    current: Stage,
    kind: OperationKind,
) -> Stage:
    if kind == OperationKind.ASSESSMENT:
        if current != Stage.ASSESSMENT:
            raise InvalidCommand(
                f"assessment completion is not allowed in stage {current.value}"
            )
        return Stage.STYLE_SELECTION

    if kind == OperationKind.POST_SESSION:
        if current != Stage.POST_SESSION:
            raise InvalidCommand(
                f"post-session completion is not allowed in stage {current.value}"
            )
        return Stage.READY

    raise InvariantViolation(f"unknown operation kind: {kind}")


def stage_after_style_selection(current: Stage) -> Stage:
    if current != Stage.STYLE_SELECTION:
        raise InvalidCommand(
            f"select_style is not allowed in stage {current.value}"
        )
    return Stage.READY


def stage_after_session_start(current: Stage) -> Stage:
    if current != Stage.READY:
        raise InvalidCommand(f"start_session is not allowed in stage {current.value}")
    return Stage.THERAPY


def stage_after_session_end(current: Stage) -> Stage:
    if current != Stage.THERAPY:
        raise InvalidCommand(f"end_session is not allowed in stage {current.value}")
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
