"""TherapyApplication startup recovery and shutdown tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.errors import Busy
from jung.domain.models import (
    ChatTurnStatus,
    OperationStatus,
    Profile,
    Stage,
)
from jung.llm.fake import FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult

from .application_fixtures import (
    assessment_result,
    build_test_application,
    wait_for_operation_status,
    wait_for_stage,
)
from .scenarios import complete_intake_for_assessment, open_intake

pytestmark = pytest.mark.asyncio


async def test_recover_on_startup_reschedules_pending_operation(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    fake = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=assessment_result(),
            )
        ]
    )
    async with build_test_application(store, fake) as runtime:
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
        snapshot = await runtime.application.get_snapshot()
    assert snapshot.stage is Stage.STYLE_SELECTION
    fake.assert_exhausted()


async def test_recover_on_startup_marks_stale_chat_turn_failed(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    turn_id = uuid4()
    store.accept_chat_message(
        expected_revision=store.get_app_state().revision,
        session_id=intake_id,
        client_message_id=uuid4(),
        turn_id=turn_id,
        user_message_id=uuid4(),
        content="hello",
        now=now,
    )
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        turn = await runtime.application.get_chat_turn(turn_id)
        snapshot = await runtime.application.get_snapshot()
    assert turn.status is ChatTurnStatus.FAILED
    assert turn.retryable is True
    assert snapshot.active_chat_turn is None


async def test_stale_running_operation_is_recovered_then_completes(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    fake = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=assessment_result(),
            )
        ]
    )
    async with build_test_application(store, fake) as runtime:
        operation = runtime.store.get_operation(operation_id)
        assert operation is not None
        assert operation.status is OperationStatus.PENDING
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
    fake.assert_exhausted()


async def test_blocked_running_operation_recovers_on_second_runtime(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    gate = asyncio.Event()

    class HoldingAssessmentFake(FakeLLM):
        async def generate_structured(
            self,
            messages,
            output_type,
            policy,
            validate_result=None,
        ):
            await gate.wait()
            return await super().generate_structured(
                messages,
                output_type,
                policy,
                validate_result=validate_result,
            )

    blocking_fake = HoldingAssessmentFake(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=assessment_result(),
            )
        ]
    )
    async with build_test_application(store, blocking_fake, recover=False) as runtime_a:
        await runtime_a.application.recover_on_startup()
        await wait_for_operation_status(
            runtime_a.application,
            operation_id,
            OperationStatus.RUNNING,
        )
        runtime_a.application.begin_shutdown()
        await runtime_a.supervisor.shutdown(timeout_seconds=0.05)
        gate.set()

    operation = store.get_operation(operation_id)
    assert operation is not None
    assert operation.status is OperationStatus.RUNNING

    success_fake = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=assessment_result(),
            )
        ]
    )
    async with build_test_application(store, success_fake) as runtime_b:
        await wait_for_stage(runtime_b.application, Stage.STYLE_SELECTION)
    success_fake.assert_exhausted()


async def test_begin_shutdown_while_mutation_lock_held_rejects_command(
    store: SQLiteStore,
) -> None:
    fake = FakeLLM([])
    async with build_test_application(store, fake, recover=False) as runtime:
        app = runtime.application
        original_run_store = app._run_store
        entered_slow_path = asyncio.Event()
        release_slow_path = asyncio.Event()

        async def gated_run_store(fn, *args, **kwargs):
            result = await original_run_store(fn, *args, **kwargs)
            if getattr(fn, "__name__", "") == "load_snapshot_facts":
                entered_slow_path.set()
                await release_slow_path.wait()
            return result

        app._run_store = gated_run_store

        first_update = asyncio.create_task(
            app.update_profile(
                UpdateProfile(
                    expected_revision=0,
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
        )
        await asyncio.wait_for(entered_slow_path.wait(), timeout=2.0)
        blocked_update = asyncio.create_task(
            app.update_profile(
                UpdateProfile(
                    expected_revision=0,
                    profile=Profile(name="Jordan", primary_language="English"),
                )
            )
        )
        await asyncio.sleep(0.01)
        app.begin_shutdown()
        release_slow_path.set()
        with pytest.raises(Busy, match="shutting down"):
            await blocked_update
        await first_update


async def test_shutdown_rejects_new_commands(store: SQLiteStore) -> None:
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        runtime.application.begin_shutdown()
        with pytest.raises(Busy, match="shutting down"):
            await runtime.application.update_profile(
                UpdateProfile(
                    expected_revision=0,
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
        await runtime.supervisor.shutdown(timeout_seconds=1.0)
        with pytest.raises(Busy, match="shutting down"):
            await runtime.application.submit_message(
                SendMessage(
                    expected_revision=0,
                    session_id=uuid4(),
                    client_message_id=uuid4(),
                    content="too late",
                )
            )
