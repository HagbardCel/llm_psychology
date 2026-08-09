"""Diagnostic event helpers for application runtime components."""

from __future__ import annotations

from typing import Any

from jung.diagnostics import DiagnosticRecorder, _safe_exception_message
from jung.domain.models import Stage


def record(
    recorder: DiagnosticRecorder | None,
    kind: str,
    data: dict[str, Any] | None = None,
) -> None:
    if recorder is not None:
        recorder.record(kind, data)


def record_runtime_error(
    recorder: DiagnosticRecorder | None,
    *,
    phase: str,
    exc: BaseException,
    **extra: Any,
) -> None:
    payload: dict[str, Any] = {
        "phase": phase,
        "error_type": type(exc).__name__,
        "error_message": _safe_exception_message(exc),
    }
    payload.update(extra)
    record(recorder, "runtime.error", payload)


def record_command_error(
    recorder: DiagnosticRecorder | None,
    command: str,
    exc: BaseException,
) -> None:
    record_runtime_error(
        recorder,
        phase="workflow_command",
        exc=exc,
        command=command,
    )


def record_command_started(
    recorder: DiagnosticRecorder | None,
    command: str,
) -> None:
    record(recorder, "workflow.command.started", {"command": command})


def record_command_completed(
    recorder: DiagnosticRecorder | None,
    command: str,
    outcome: str,
) -> None:
    record(
        recorder,
        "workflow.command.completed",
        {"command": command, "outcome": outcome},
    )


def record_command_rejected(
    recorder: DiagnosticRecorder | None,
    command: str,
    exc: BaseException,
) -> None:
    record(
        recorder,
        "workflow.command.rejected",
        {"command": command, "error_type": type(exc).__name__},
    )


def record_transition(
    recorder: DiagnosticRecorder | None,
    *,
    from_stage: Stage,
    to_stage: Stage,
    trigger: str,
) -> None:
    if from_stage is to_stage:
        return
    record(
        recorder,
        "workflow.transition",
        {
            "from_stage": from_stage.value,
            "to_stage": to_stage.value,
            "trigger": trigger,
        },
    )
