"""Integration coverage for lean diagnostic logging."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from jung.diagnostics import SCHEMA_VERSION as DIAGNOSTIC_SCHEMA_VERSION
from jung.diagnostics import DiagnosticRecorder
from jung.domain.commands import SelectStyle, SendMessage, UpdateProfile
from jung.domain.errors import InvalidCommand, InvariantViolation
from jung.domain.models import (
    MessageRole,
    OperationStatus,
    Profile,
    Stage,
)
from jung.domain.results import ChatCompleted, ChatFailed
from jung.llm.errors import LLMUnavailable
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.intake.extraction import (
    ExtractedIntakeEvidence,
    IntakeEvidenceField,
    IntakeExtraction,
)
from tests.support.fake_llm import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)

from .application_fixtures import (
    build_test_application,
    collect_stream,
    intake_message_expectations,
)
from .assessment_test_data import assessment_result_data
from .scenarios import complete_intake_for_assessment, open_intake

pytestmark = pytest.mark.asyncio


def _load_trace(run_dir: Path) -> list[dict[str, object]]:
    lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _kinds(events: list[dict[str, object]]) -> list[str]:
    return [str(event["kind"]) for event in events]


async def test_chat_handoff_correlation_and_provider_events(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"

    with DiagnosticRecorder(run_dir) as recorder:
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
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            session = (await runtime.application.get_snapshot()).active_session
            assert session is not None
            items = await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="I feel anxious.",
                    request_id=request_id,
                ),
            )
            assert isinstance(items[-1], ChatCompleted)

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert kinds[0] == "diagnostics.start"
    assert kinds[-1] == "diagnostics.end"
    assert "chat.turn.accepted" in kinds
    assert "chat.turn.started" in kinds
    assert "llm.output.accepted" in kinds
    assert "chat.turn.completed" in kinds
    assert "workflow.command.started" in kinds
    assert "workflow.command.completed" in kinds

    accepted = next(e for e in events if e["kind"] == "chat.turn.accepted")
    assert accepted["context"]["session_id"] == str(session.id)
    assert accepted["context"]["client_message_id"] == str(client_message_id)
    assert accepted["context"]["request_id"] == str(request_id)
    assert accepted["context"]["run_id"] == str(recorder.run_id)

    completed_cmds = [
        e
        for e in events
        if e["kind"] == "workflow.command.completed"
        and e["data"].get("command") == "send_message"
    ]
    assert len(completed_cmds) == 1
    assert completed_cmds[0]["data"]["outcome"] == "committed"

    llm_accepted = [e for e in events if e["kind"] == "llm.output.accepted"]
    assert llm_accepted
    for event in llm_accepted:
        ctx = event["context"]
        assert ctx["run_id"] == str(recorder.run_id)
        assert ctx.get("llm_call_id")


async def test_intake_turn_evaluated_metadata_only(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    sentinel = "INTAKE_DIAGNOSTIC_SENTINEL_XYZ"

    with DiagnosticRecorder(run_dir) as recorder:
        store = SQLiteStore(db_path)
        store.initialize()
        fake = FakeLLM(
            [
                StructuredExpectation(
                    task=LLMTask.INTAKE_PATCH,
                    output_type=IntakeExtraction,
                    response=IntakeExtraction(
                        evidence=(
                            ExtractedIntakeEvidence(
                                field=IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                                value="anxiety",
                                evidence_quote="I feel anxious",
                                confidence="high",
                                response_status="informative",
                            ),
                        )
                    ),
                ),
                StreamExpectation(
                    task=LLMTask.INTAKE_RESPONSE,
                    chunks=("Thanks for sharing.",),
                ),
            ]
        )
        request_id = uuid4()
        client_message_id = uuid4()
        async with build_test_application(store, fake, recorder=recorder) as runtime:
            await runtime.application.update_profile(
                UpdateProfile(
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            session = (await runtime.application.get_snapshot()).active_session
            assert session is not None
            items = await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content=f"I feel anxious. {sentinel}",
                    request_id=request_id,
                ),
            )
            assert isinstance(items[-1], ChatCompleted)

    events = _load_trace(run_dir)
    evaluated = [e for e in events if e["kind"] == "intake.turn.evaluated"]
    assert len(evaluated) == 1
    event = evaluated[0]
    assert event["context"]["session_id"] == str(session.id)
    assert event["context"]["client_message_id"] == str(client_message_id)
    assert event["context"]["request_id"] == str(request_id)
    data = event["data"]
    assert data["extraction_target"] == "presenting_problem"
    assert data["merge_status"] == "applied"
    assert data["retained_evidence_count"] >= 1
    payload = json.dumps(data)
    assert sentinel not in payload


async def test_chat_failure_domain_outcome(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"

    with DiagnosticRecorder(run_dir) as recorder:
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
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            session = (await runtime.application.get_snapshot()).active_session
            assert session is not None
            items = await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=uuid4(),
                    content="I feel anxious.",
                    request_id=uuid4(),
                ),
            )
            assert isinstance(items[-1], ChatFailed)

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert "chat.turn.accepted" in kinds
    assert "chat.turn.started" in kinds
    assert "chat.turn.failed" in kinds
    assert "workflow.command.completed" in kinds
    failed_event = next(e for e in events if e["kind"] == "chat.turn.failed")
    assert failed_event["data"]["error_code"]
    assert "retryable" in failed_event["data"]
    assert failed_event["data"]["source"] == "chat_attempt"
    assert "runtime.error" not in kinds


async def test_workflow_transition_only_on_stage_change(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    with DiagnosticRecorder(run_dir) as recorder:
        store = SQLiteStore(db_path)
        store.initialize()
        fake = FakeLLM([])
        async with build_test_application(store, fake, recorder=recorder) as runtime:
            await runtime.application.update_profile(
                UpdateProfile(
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            # Same-stage profile update should not emit workflow.transition again
            # beyond SETUP→INTAKE from the first complete profile.
            snapshot = await runtime.application.get_snapshot()
            assert snapshot.stage is Stage.INTAKE

    events = _load_trace(run_dir)
    assert events[0]["schema_version"] == DIAGNOSTIC_SCHEMA_VERSION
    assert DIAGNOSTIC_SCHEMA_VERSION == 5
    transitions = [e for e in events if e["kind"] == "workflow.transition"]
    assert len(transitions) == 1
    assert transitions[0]["schema_version"] == 5
    assert transitions[0]["data"] == {
        "from_stage": Stage.SETUP.value,
        "to_stage": Stage.INTAKE.value,
        "trigger": "update_profile",
    }
    assert set(transitions[0]["data"]) == {"from_stage", "to_stage", "trigger"}


async def test_incomplete_intake_profile_update_is_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    with DiagnosticRecorder(run_dir) as recorder:
        store = SQLiteStore(db_path)
        store.initialize()
        fake = FakeLLM([])
        async with build_test_application(store, fake, recorder=recorder) as runtime:
            await runtime.application.update_profile(
                UpdateProfile(
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            profile_before = await runtime.application.get_profile()
            with pytest.raises(
                InvalidCommand,
                match="profile must remain complete during intake",
            ):
                await runtime.application.update_profile(
                    UpdateProfile(
                        profile=Profile(name=" ", primary_language="English"),
                    )
                )
            profile_after = await runtime.application.get_profile()

    assert profile_after.profile == profile_before.profile
    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert "workflow.command.rejected" in kinds
    rejected = [
        e
        for e in events
        if e["kind"] == "workflow.command.rejected"
        and e["data"].get("command") == "update_profile"
    ]
    assert len(rejected) == 1
    assert rejected[0]["data"]["error_type"] == "InvalidCommand"
    assert "runtime.error" not in kinds


async def test_startup_recovery_diagnostics(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    store.initialize()
    intake_id, now = open_intake(store)
    op_id = uuid4()
    client_message_id, _, _ = complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=op_id,
    )
    store.mark_operation_running(op_id, now=now)

    run_dir = tmp_path / "debug-run"
    with DiagnosticRecorder(run_dir) as recorder:
        async with build_test_application(
            store, FakeLLM([]), recorder=recorder, recover=True
        ) as runtime:
            await runtime.application.get_snapshot()

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert "operation.recovered" in kinds
    assert "chat.turn.failed" not in kinds
    recovered = next(e for e in events if e["kind"] == "operation.recovered")
    assert recovered["data"]["from_status"] == OperationStatus.RUNNING.value
    assert recovered["data"]["to_status"] == OperationStatus.PENDING.value
    assert recovered["context"]["operation_id"] == str(op_id)

    messages = store.list_messages(intake_id)
    assert messages
    assert any(
        message.role is MessageRole.USER
        and message.client_message_id == client_message_id
        for message in messages
    )


async def test_chat_retry_emits_retried_not_accepted(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    client_message_id = uuid4()
    with DiagnosticRecorder(run_dir) as recorder:
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
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            session = (await runtime.application.get_snapshot()).active_session
            assert session is not None
            first = await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="retry me",
                    request_id=uuid4(),
                ),
            )
            assert isinstance(first[-1], ChatFailed)

        succeeding = FakeLLM(intake_message_expectations("Thanks for sharing more."))
        async with build_test_application(
            store, succeeding, recorder=recorder, recover=False
        ) as runtime:
            retried = await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="retry me",
                    request_id=uuid4(),
                ),
            )
            assert isinstance(retried[-1], ChatCompleted)

            # Idempotent existing complete
            again = await collect_stream(
                runtime.application,
                SendMessage(
                    session_id=session.id,
                    client_message_id=client_message_id,
                    content="retry me",
                    request_id=uuid4(),
                ),
            )
            assert isinstance(again[-1], ChatCompleted)
            assert again[-1].user_message.id == retried[-1].user_message.id

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
    assert "task.started" not in _kinds(events)


async def test_select_style_invariant_records_runtime_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    store.initialize()
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result=assessment_result_data(),
        now=now,
    )
    assert store.load_snapshot_facts().stage == Stage.STYLE_SELECTION

    with DiagnosticRecorder(run_dir) as recorder:
        async with build_test_application(
            store, FakeLLM([]), recorder=recorder, recover=False
        ) as runtime:

            async def missing_assessment() -> None:
                return None

            monkeypatch.setattr(
                runtime.application,
                "_load_completed_assessment_locked",
                missing_assessment,
            )
            with pytest.raises(
                InvariantViolation, match="completed assessment result is required"
            ):
                await runtime.application.select_style(
                    SelectStyle(
                        style_id="cbt",
                    )
                )

    events = _load_trace(run_dir)
    runtime_errors = [e for e in events if e["kind"] == "runtime.error"]
    assert len(runtime_errors) == 1
    assert runtime_errors[0]["data"]["phase"] == "workflow_command"
    assert runtime_errors[0]["data"]["command"] == "select_style"
    assert runtime_errors[0]["data"]["error_type"] == "InvariantViolation"
    assert "workflow.command.rejected" not in _kinds(events)


async def test_retry_operation_invariant_records_runtime_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    store.initialize()
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.fail_operation(
        operation_id,
        error_code="llm_timeout",
        error_message="timeout",
        retryable=True,
        now=now,
    )

    with DiagnosticRecorder(run_dir) as recorder:
        async with build_test_application(
            store, FakeLLM([]), recorder=recorder, recover=False
        ) as runtime:
            monkeypatch.setattr(store, "get_current_operation", lambda: None)
            with pytest.raises(
                InvariantViolation,
                match="retry command available without current operation",
            ):
                await runtime.application.retry_operation()

    events = _load_trace(run_dir)
    runtime_errors = [
        e
        for e in events
        if e["kind"] == "runtime.error" and e["data"].get("phase") == "workflow_command"
    ]
    assert len(runtime_errors) == 1
    assert runtime_errors[0]["data"]["command"] == "retry_operation"
    assert runtime_errors[0]["data"]["error_type"] == "InvariantViolation"
    rejected = [
        e
        for e in events
        if e["kind"] == "workflow.command.rejected"
        and e["data"].get("command") == "retry_operation"
    ]
    assert rejected == []


async def test_store_drained_failure_records_runtime_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    import jung._application.store_calls as store_calls_module
    from jung._async_cleanup import drain_cancelled_task as real_drain

    run_dir = tmp_path / "debug-run"
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    store.initialize()
    open_intake(store)

    gate = threading.Event()
    release = threading.Event()

    def failing_get_profile(*args, **kwargs):
        gate.set()
        release.wait()
        raise RuntimeError("owned store failed after cancel")

    failing_get_profile.__name__ = "get_profile"

    drain_entered = asyncio.Event()

    async def observed_drain(task: asyncio.Future[Any]) -> BaseException | None:
        drain_entered.set()
        return await real_drain(task)

    monkeypatch.setattr(store_calls_module, "drain_cancelled_task", observed_drain)

    with DiagnosticRecorder(run_dir) as recorder:
        async with build_test_application(
            store, FakeLLM([]), recorder=recorder, recover=False
        ) as runtime:
            monkeypatch.setattr(store, "get_profile", failing_get_profile)

            read_task = asyncio.create_task(runtime.application.get_profile())
            assert await asyncio.to_thread(gate.wait, 2.0)
            read_task.cancel()
            await asyncio.wait_for(drain_entered.wait(), timeout=2.0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await read_task

    events = _load_trace(run_dir)
    drained = [
        e
        for e in events
        if e["kind"] == "runtime.error" and e["data"].get("phase") == "store_drained"
    ]
    assert len(drained) == 1
    assert drained[0]["data"]["error_type"] == "RuntimeError"
    assert drained[0]["data"]["function"] == "get_profile"
