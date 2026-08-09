"""TherapyApplication startup recovery and shutdown tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.errors import Busy
from jung.domain.models import (
    OperationStatus,
    Profile,
    Stage,
)
from jung.llm.errors import LLMTimeout
from jung.llm.fake import FailureExpectation, FakeLLM, StructuredExpectation
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
        await runtime_a.application.shutdown(timeout_seconds=0.05)
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


async def test_duplicate_recover_on_startup_leaves_live_running_operation(
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
    assessment_calls = 0

    class HoldingAssessmentFake(FakeLLM):
        async def generate_structured(
            self,
            messages,
            output_type,
            policy,
            validate_result=None,
        ):
            nonlocal assessment_calls
            if policy.task is LLMTask.ASSESSMENT:
                assessment_calls += 1
                await gate.wait()
            return await super().generate_structured(
                messages,
                output_type,
                policy,
                validate_result=validate_result,
            )

    fake = HoldingAssessmentFake(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=assessment_result(),
            )
        ]
    )
    async with build_test_application(store, fake, recover=False) as runtime:
        app = runtime.application
        await app.recover_on_startup()
        await wait_for_operation_status(
            app,
            operation_id,
            OperationStatus.RUNNING,
        )

        second = await app.recover_on_startup()
        assert second.stage is Stage.ASSESSMENT
        assert second.current_operation is not None
        assert second.current_operation.id == operation_id
        assert second.current_operation.status is OperationStatus.RUNNING

        stored = store.get_operation(operation_id)
        assert stored is not None
        assert stored.status is OperationStatus.RUNNING

        gate.set()
        await wait_for_stage(app, Stage.STYLE_SELECTION)
        assert assessment_calls == 1
    fake.assert_exhausted()


async def test_retry_after_failed_clears_owned_task_before_reschedule(
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
    assessment_calls = 0

    class CountingFake(FakeLLM):
        async def generate_structured(
            self,
            messages,
            output_type,
            policy,
            validate_result=None,
        ):
            nonlocal assessment_calls
            if policy.task is LLMTask.ASSESSMENT:
                assessment_calls += 1
            return await super().generate_structured(
                messages,
                output_type,
                policy,
                validate_result=validate_result,
            )

    fake = CountingFake(
        [
            FailureExpectation(
                task=LLMTask.ASSESSMENT,
                error=LLMTimeout("timeout"),
            ),
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=assessment_result(),
            ),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        app = runtime.application
        await wait_for_operation_status(
            app,
            operation_id,
            OperationStatus.FAILED,
        )
        assert not app._operations.has_live_task
        assert app._operations._operation_task is None
        assert app._operations._operation_task_id is None

        await app.retry_operation()
        await wait_for_stage(app, Stage.STYLE_SELECTION)

        completed = store.get_operation(operation_id)
        assert completed is not None
        assert completed.id == operation_id
        assert completed.status is OperationStatus.COMPLETE
        assert completed.attempt == 2
        assert assessment_calls == 2
    fake.assert_exhausted()


async def test_schedule_defers_when_different_owned_task_is_live(
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
    operation_b = store.get_operation(operation_id)
    assert operation_b is not None
    assert operation_b.status is OperationStatus.PENDING

    release_a = asyncio.Event()
    assessment_calls = 0

    class CountingFake(FakeLLM):
        async def generate_structured(
            self,
            messages,
            output_type,
            policy,
            validate_result=None,
        ):
            nonlocal assessment_calls
            if policy.task is LLMTask.ASSESSMENT:
                assessment_calls += 1
            return await super().generate_structured(
                messages,
                output_type,
                policy,
                validate_result=validate_result,
            )

    fake = CountingFake(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=assessment_result(),
            )
        ]
    )
    async with build_test_application(store, fake, recover=False) as runtime:
        app = runtime.application

        async def hold() -> None:
            await release_a.wait()

        holding_task = asyncio.create_task(hold(), name="synthetic-ownership")
        app._operations._operation_task = holding_task
        app._operations._operation_task_id = uuid4()

        app._operations.schedule(operation_b)
        pending = store.get_operation(operation_id)
        assert pending is not None
        assert pending.status is OperationStatus.PENDING
        assert assessment_calls == 0

        release_a.set()
        await holding_task
        await wait_for_stage(app, Stage.STYLE_SELECTION)

        completed = store.get_operation(operation_id)
        assert completed is not None
        assert completed.status is OperationStatus.COMPLETE
        assert assessment_calls == 1
    fake.assert_exhausted()


async def test_shutdown_while_mutation_lock_held_rejects_command(
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
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
        )
        await asyncio.wait_for(entered_slow_path.wait(), timeout=2.0)
        blocked_update = asyncio.create_task(
            app.update_profile(
                UpdateProfile(
                    profile=Profile(name="Jordan", primary_language="English"),
                )
            )
        )
        await asyncio.sleep(0.01)
        await app.shutdown(timeout_seconds=1.0)
        release_slow_path.set()
        with pytest.raises(Busy, match="shutting down"):
            await blocked_update
        await first_update


async def test_shutdown_rejects_new_commands(store: SQLiteStore) -> None:
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        await runtime.application.shutdown(timeout_seconds=1.0)
        with pytest.raises(Busy, match="shutting down"):
            await runtime.application.update_profile(
                UpdateProfile(
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
        with pytest.raises(Busy, match="shutting down"):
            async for _ in runtime.application.stream_message(
                SendMessage(
                    session_id=uuid4(),
                    client_message_id=uuid4(),
                    content="too late",
                )
            ):
                pass
