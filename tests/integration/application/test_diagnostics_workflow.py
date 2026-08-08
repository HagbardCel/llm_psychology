"""Integration coverage for lean diagnostic logging."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from jung.composition import _record_cleanup_failure
from jung.diagnostics import DiagnosticRun
from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.models import (
    AppSnapshot,
    ChatTurnStatus,
    Operation,
    OperationKind,
    OperationStatus,
    Profile,
    Stage,
)
from jung.events import EventStream, OperationChanged, SnapshotChanged
from jung.llm.errors import LLMUnavailable
from jung.llm.fake import FailureExpectation, FakeLLM
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.supervisor import TaskSupervisor

from .application_fixtures import (
    build_test_application,
    intake_message_expectations,
    wait_for_chat_turn,
)

pytestmark = pytest.mark.asyncio


def _load_trace(run_dir: Path) -> list[dict[str, object]]:
    lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _kinds(events: list[dict[str, object]]) -> list[str]:
    return [str(event["kind"]) for event in events]


async def _wait_until_idle(supervisor: TaskSupervisor) -> None:
    for _ in range(200):
        if not supervisor._active:
            return
        await asyncio.sleep(0.01)
    raise TimeoutError("supervisor still active")


async def test_chat_handoff_correlation_and_provider_events(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"

    with DiagnosticRun(run_dir) as recorder:
        store = SQLiteStore(db_path)
        store.initialize()
        fake = FakeLLM(
            intake_message_expectations("Welcome. Tell me what brings you here.")
        )
        request_id = uuid4()
        client_message_id = uuid4()
        async with build_test_application(store, fake, recorder=recorder) as runtime:
            await runtime.application.update_profile(
                UpdateProfile(
                    expected_revision=0,
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            session = (await runtime.application.get_snapshot()).active_session
            assert session is not None
            turn = await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(
                        await runtime.application.get_snapshot()
                    ).revision,
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="I feel anxious.",
                    request_id=request_id,
                )
            )
            completed = await wait_for_chat_turn(
                runtime.application,
                turn.id,
                ChatTurnStatus.COMPLETE,
            )
            assert completed.status is ChatTurnStatus.COMPLETE

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert kinds[0] == "diagnostics.start"
    assert kinds[-1] == "diagnostics.end"
    assert "chat.turn.accepted" in kinds
    assert "llm.accepted" in kinds
    assert "chat.turn.completed" in kinds
    assert "task.started" in kinds
    assert "task.completed" in kinds
    assert "llm.call.start" not in kinds
    assert "application.event" not in kinds
    assert "store.call.start" not in kinds

    accepted = next(e for e in events if e["kind"] == "chat.turn.accepted")
    assert accepted["data"]["session_id"] == str(session.id)
    assert accepted["data"]["turn_id"] == str(turn.id)
    assert accepted["data"]["client_message_id"] == str(client_message_id)
    assert accepted["data"]["request_id"] == str(request_id)

    llm_accepted = [e for e in events if e["kind"] == "llm.accepted"]
    assert llm_accepted
    for event in llm_accepted:
        ctx = event["context"]
        assert ctx["session_id"] == str(session.id)
        assert ctx["turn_id"] == str(turn.id)
        assert ctx["client_message_id"] == str(client_message_id)
        assert ctx["request_id"] == str(request_id)
        assert ctx["task"].startswith("chat:")
        assert ctx.get("llm_call_id")

    task_events = [e for e in events if e["kind"] in {"task.started", "task.completed"}]
    assert {e["context"]["task"] for e in task_events} == {
        llm_accepted[0]["context"]["task"]
    }


async def test_chat_failure_domain_outcome(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"

    with DiagnosticRun(run_dir) as recorder:
        store = SQLiteStore(db_path)
        store.initialize()
        fake = FakeLLM(
            [
                FailureExpectation(
                    task=LLMTask.INTAKE_PATCH,
                    error=LLMUnavailable("provider down"),
                )
            ]
        )
        async with build_test_application(store, fake, recorder=recorder) as runtime:
            await runtime.application.update_profile(
                UpdateProfile(
                    expected_revision=0,
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            session = (await runtime.application.get_snapshot()).active_session
            assert session is not None
            turn = await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(
                        await runtime.application.get_snapshot()
                    ).revision,
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content="I feel anxious.",
                    request_id=uuid4(),
                )
            )
            failed = await wait_for_chat_turn(
                runtime.application,
                turn.id,
                ChatTurnStatus.FAILED,
            )
            assert failed.status is ChatTurnStatus.FAILED

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert "chat.turn.accepted" in kinds
    assert "chat.turn.failed" in kinds
    assert "task.completed" in kinds
    failed_event = next(e for e in events if e["kind"] == "chat.turn.failed")
    assert failed_event["data"]["error_code"]
    assert "retryable" in failed_event["data"]


async def test_snapshot_changed_emits_workflow_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    with DiagnosticRun(run_dir) as recorder:
        stream = EventStream(recorder=recorder)
        snapshot = AppSnapshot(
            revision=2,
            stage=Stage.INTAKE,
            profile_complete=True,
        )
        await stream.publish(SnapshotChanged(snapshot))

    events = _load_trace(run_dir)
    workflow = next(e for e in events if e["kind"] == "workflow.state")
    assert workflow["data"] == {"revision": 2, "stage": Stage.INTAKE.value}


async def test_operation_changed_emits_status_and_workflow_state(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "debug-run"
    with DiagnosticRun(run_dir) as recorder:
        stream = EventStream(recorder=recorder)
        now = datetime.now(UTC)
        operation = Operation(
            id=uuid4(),
            kind=OperationKind.ASSESSMENT,
            status=OperationStatus.FAILED,
            attempt=1,
            source_session_id=uuid4(),
            created_at=now,
            updated_at=now,
            error_code="llm_unavailable",
            error_message="down",
            retryable=True,
        )
        snapshot = AppSnapshot(
            revision=3,
            stage=Stage.ASSESSMENT,
            profile_complete=True,
        )
        await stream.publish(OperationChanged(operation, snapshot))

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert kinds.count("operation.status") == 1
    assert kinds.count("workflow.state") == 1
    status = next(e for e in events if e["kind"] == "operation.status")
    assert status["data"]["status"] == OperationStatus.FAILED.value
    assert status["data"]["error_code"] == "llm_unavailable"
    assert status["data"]["retryable"] is True
    assert status["data"]["revision"] == 3
    assert status["data"]["source_session_id"] == str(operation.source_session_id)
    workflow = next(e for e in events if e["kind"] == "workflow.state")
    assert workflow["data"] == {"revision": 3, "stage": Stage.ASSESSMENT.value}


async def test_pre_running_ownership_failure_emits_task_failed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "debug-run"
    with DiagnosticRun(run_dir) as recorder:
        supervisor = TaskSupervisor(recorder=recorder)

        async def failing_run() -> None:
            # Mimic worker body before running_owned: re-raise.
            raise RuntimeError("ownership failed")

        async with supervisor:
            assert supervisor.start(name="operation:test", run=failing_run)
            await _wait_until_idle(supervisor)

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert "task.started" in kinds
    assert "task.failed" in kinds
    assert "task.completed" not in kinds
    failed = next(e for e in events if e["kind"] == "task.failed")
    assert failed["context"]["task"] == "operation:test"
    assert failed["data"]["error_type"] == "RuntimeError"


async def test_dead_trace_cleanup_still_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_dir = tmp_path / "debug-run"
    with DiagnosticRun(run_dir) as recorder:
        real_write = recorder._trace_file.write

        def flaky(text: str) -> int:
            if '"kind":"workflow.state"' in text.replace(" ", ""):
                raise OSError("disk full")
            return real_write(text)

        monkeypatch.setattr(recorder._trace_file, "write", flaky)
        recorder.record("workflow.state", {"revision": 1, "stage": "intake"})
        with caplog.at_level(logging.WARNING):
            _record_cleanup_failure(
                recorder,
                step="llm.aclose",
                exc=RuntimeError("close failed"),
                selected_as_cleanup_error=False,
            )
        assert any("runtime cleanup failed" in r.message for r in caplog.records)


async def test_shutdown_timeout_recorded(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    with DiagnosticRun(run_dir) as recorder:
        supervisor = TaskSupervisor(recorder=recorder)
        async with supervisor:
            started = asyncio.Event()

            async def hang() -> None:
                started.set()
                await asyncio.sleep(60)

            assert supervisor.start(name="hang", run=hang)
            await started.wait()
            await supervisor.shutdown(timeout_seconds=0.01)

    kinds = _kinds(_load_trace(run_dir))
    assert "task.shutdown_timeout" in kinds
    assert "task.cancelled" in kinds
