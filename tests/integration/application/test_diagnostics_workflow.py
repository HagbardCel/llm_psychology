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
    ChatTurnStatus,
    OperationKind,
    OperationStatus,
    Profile,
    Stage,
)
from jung.events import EventStream
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
    assert "chat.turn.started" in kinds
    assert "llm.output.accepted" in kinds
    assert "chat.turn.completed" in kinds
    assert "task.started" in kinds
    assert "task.completed" in kinds
    assert "workflow.state" not in kinds
    assert "operation.status" not in kinds
    assert "application.event" not in kinds
    assert "store.call.start" not in kinds

    accepted = next(e for e in events if e["kind"] == "chat.turn.accepted")
    assert accepted["context"]["session_id"] == str(session.id)
    assert accepted["context"]["turn_id"] == str(turn.id)
    assert accepted["context"]["client_message_id"] == str(client_message_id)
    assert accepted["context"]["request_id"] == str(request_id)
    assert accepted["context"]["run_id"] == str(recorder.run_id)

    llm_accepted = [e for e in events if e["kind"] == "llm.output.accepted"]
    assert llm_accepted
    for event in llm_accepted:
        ctx = event["context"]
        assert ctx["session_id"] == str(session.id)
        assert ctx["turn_id"] == str(turn.id)
        assert ctx["client_message_id"] == str(client_message_id)
        assert ctx["request_id"] == str(request_id)
        assert ctx["task"].startswith("chat:")
        assert ctx.get("llm_call_id")
        assert ctx["run_id"] == str(recorder.run_id)

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
    assert "chat.turn.started" in kinds
    assert "chat.turn.failed" in kinds
    assert "task.completed" in kinds
    failed_event = next(e for e in events if e["kind"] == "chat.turn.failed")
    assert failed_event["data"]["error_code"]
    assert "retryable" in failed_event["data"]
    assert failed_event["data"]["source"] == "generation"


async def test_workflow_transition_only_on_stage_change(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    with DiagnosticRun(run_dir) as recorder:
        store = SQLiteStore(db_path)
        store.initialize()
        fake = FakeLLM([])
        async with build_test_application(store, fake, recorder=recorder) as runtime:
            await runtime.application.update_profile(
                UpdateProfile(
                    expected_revision=0,
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            # Same-stage profile update should not emit workflow.transition again
            # beyond SETUP→INTAKE from the first complete profile.
            snapshot = await runtime.application.get_snapshot()
            assert snapshot.stage is Stage.INTAKE

    events = _load_trace(run_dir)
    transitions = [e for e in events if e["kind"] == "workflow.transition"]
    assert len(transitions) == 1
    assert transitions[0]["data"]["from_stage"] == Stage.SETUP.value
    assert transitions[0]["data"]["to_stage"] == Stage.INTAKE.value
    assert transitions[0]["data"]["trigger"] == "update_profile"
    assert "revision" in transitions[0]["data"]


async def test_event_stream_no_longer_projects_diagnostics(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    with DiagnosticRun(run_dir) as recorder:
        stream = EventStream()
        await stream.publish(
            __import__("jung.events", fromlist=["SnapshotChanged"]).SnapshotChanged(
                __import__("jung.domain.models", fromlist=["AppSnapshot"]).AppSnapshot(
                    revision=2,
                    stage=Stage.INTAKE,
                    profile_complete=True,
                )
            )
        )
        recorder.record("workflow.command.started", {"command": "update_profile"})

    kinds = _kinds(_load_trace(run_dir))
    assert "workflow.state" not in kinds
    assert "workflow.command.started" in kinds


async def test_pre_running_ownership_failure_emits_task_failed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "debug-run"
    with DiagnosticRun(run_dir) as recorder:
        supervisor = TaskSupervisor(recorder=recorder)

        async def failing_run() -> None:
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
            if '"kind":"workflow.transition"' in text.replace(" ", ""):
                raise OSError("disk full")
            return real_write(text)

        monkeypatch.setattr(recorder._trace_file, "write", flaky)
        recorder.record(
            "workflow.transition",
            {
                "from_stage": "intake",
                "to_stage": "assessment",
                "trigger": "x",
                "revision": 1,
            },
        )
        with caplog.at_level(logging.WARNING):
            _record_cleanup_failure(
                recorder,
                step="llm.aclose",
                exc=RuntimeError("close failed"),
                selected_as_cleanup_error=False,
            )
        assert any("runtime cleanup failed" in r.message for r in caplog.records)
    assert recorder.write_failed is True
    kinds = _kinds(_load_trace(run_dir))
    # After a latched write failure, later records (including runtime.error) are dropped.
    assert "diagnostics.start" in kinds


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


async def test_startup_recovery_diagnostics(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    store.initialize()
    fake = FakeLLM([])
    async with build_test_application(store, fake, recover=False) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session = (await runtime.application.get_snapshot()).active_session
        assert session is not None
        session_id = session.id

    now = datetime.now(UTC)
    turn_id = uuid4()
    client_message_id = uuid4()
    user_message_id = uuid4()
    op_id = uuid4()
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO messages (id, session_id, sequence, role, content, created_at)
            VALUES (?, ?, 1, 'user', 'stale', ?)
            """,
            (str(user_message_id), str(session_id), now.isoformat()),
        )
        conn.execute(
            """
            INSERT INTO chat_turns (
                id, session_id, client_message_id, user_message_id, status,
                retryable, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)
            """,
            (
                str(turn_id),
                str(session_id),
                str(client_message_id),
                str(user_message_id),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        conn.execute(
            """
            INSERT INTO operations (
                id, kind, status, attempt, source_session_id,
                created_at, updated_at, started_at, retryable
            ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, 0)
            """,
            (
                str(op_id),
                OperationKind.ASSESSMENT.value,
                OperationStatus.RUNNING.value,
                str(session_id),
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        conn.commit()

    run_dir = tmp_path / "debug-run"
    with DiagnosticRun(run_dir) as recorder:
        async with build_test_application(
            store, FakeLLM([]), recorder=recorder, recover=True
        ) as runtime:
            await runtime.application.get_snapshot()

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert "operation.recovered" in kinds
    failed = [e for e in events if e["kind"] == "chat.turn.failed"]
    assert any(e["data"].get("source") == "startup_recovery" for e in failed)
    recovered = next(e for e in events if e["kind"] == "operation.recovered")
    assert recovered["data"]["from_status"] == OperationStatus.RUNNING.value
    assert recovered["data"]["to_status"] == OperationStatus.PENDING.value
    assert recovered["context"]["operation_id"] == str(op_id)


async def test_chat_retry_emits_retried_not_accepted(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    client_message_id = uuid4()
    with DiagnosticRun(run_dir) as recorder:
        store = SQLiteStore(db_path)
        store.initialize()
        failing = FakeLLM(
            [
                FailureExpectation(
                    task=LLMTask.INTAKE_PATCH,
                    error=LLMUnavailable("provider down"),
                )
            ]
        )
        async with build_test_application(store, failing, recorder=recorder) as runtime:
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
                    content="retry me",
                    request_id=uuid4(),
                )
            )
            failed = await wait_for_chat_turn(
                runtime.application, turn.id, ChatTurnStatus.FAILED
            )
            assert failed.retryable

        # Second DiagnosticRun segment continues same recorder? reopen store with
        # new expectations for successful retry under same recorder by nesting.
        succeeding = FakeLLM(
            intake_message_expectations("Thanks for sharing more.")
        )
        async with build_test_application(
            store, succeeding, recorder=recorder, recover=False
        ) as runtime:
            retried = await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(
                        await runtime.application.get_snapshot()
                    ).revision,
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="retry me",
                    request_id=uuid4(),
                )
            )
            assert retried.id == turn.id
            completed = await wait_for_chat_turn(
                runtime.application, turn.id, ChatTurnStatus.COMPLETE
            )
            assert completed.status is ChatTurnStatus.COMPLETE

            # Idempotent existing complete
            again = await runtime.application.submit_message(
                SendMessage(
                    expected_revision=(
                        await runtime.application.get_snapshot()
                    ).revision,
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="retry me",
                    request_id=uuid4(),
                )
            )
            assert again.id == turn.id

    events = _load_trace(run_dir)
    assert "chat.turn.retried" in _kinds(events)
    completed_cmds = [
        e
        for e in events
        if e["kind"] == "workflow.command.completed"
        and e["data"].get("command") == "send_message"
    ]
    outcomes = [e["data"]["outcome"] for e in completed_cmds]
    assert "committed" in outcomes
    assert "idempotent_existing" in outcomes
    # First accept + later retry both committed; accepted once, retried once
    assert _kinds(events).count("chat.turn.accepted") == 1
    assert _kinds(events).count("chat.turn.retried") == 1
