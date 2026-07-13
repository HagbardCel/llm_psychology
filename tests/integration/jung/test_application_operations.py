"""TherapyApplication assessment and post-session operation tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from jung.domain.commands import RetryOperation
from jung.domain.models import CommandName, OperationStatus, Stage
from jung.events import OperationChanged
from jung.llm.errors import InvalidLLMOutput, LLMTimeout
from jung.llm.fake import FailureExpectation, FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult

from .application_fixtures import (
    assessment_result,
    build_test_application,
    post_session_expectations,
    wait_for_operation_status,
    wait_for_stage,
)
from .scenarios import (
    advance_to_post_session,
    complete_intake_for_assessment,
    open_intake,
)

pytestmark = pytest.mark.asyncio


async def test_pending_assessment_operation_completes(store: SQLiteStore) -> None:
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
        operation = (await runtime.application.get_snapshot()).current_operation
    assert operation is None
    fake.assert_exhausted()


async def test_post_session_operation_completes_to_ready(store: SQLiteStore) -> None:
    advance_to_post_session(store)
    fake = FakeLLM(post_session_expectations())
    async with build_test_application(store, fake) as runtime:
        await wait_for_stage(runtime.application, Stage.READY)
        snapshot = await runtime.application.get_snapshot()
    assert snapshot.stage is Stage.READY
    fake.assert_exhausted()


async def test_failed_operation_can_be_retried(store: SQLiteStore) -> None:
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
        await wait_for_operation_status(
            runtime.application,
            operation_id,
            OperationStatus.FAILED,
        )
        revision = (await runtime.application.get_snapshot()).revision
        await runtime.application.retry_operation(
            RetryOperation(expected_revision=revision, operation_id=operation_id)
        )
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
    fake.assert_exhausted()


async def test_permanent_operation_failure_is_not_retryable(store: SQLiteStore) -> None:
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
            FailureExpectation(
                task=LLMTask.ASSESSMENT,
                error=InvalidLLMOutput("invalid assessment output"),
            )
        ]
    )
    async with build_test_application(store, fake) as runtime:
        await wait_for_operation_status(
            runtime.application,
            operation_id,
            OperationStatus.FAILED,
        )
        operation = runtime.store.get_operation(operation_id)
        assert operation is not None
        assert operation.retryable is False
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.current_operation is not None
        assert CommandName.RETRY_OPERATION not in snapshot.available_commands
    fake.assert_exhausted()


async def test_operation_retry_during_teardown_completes(store: SQLiteStore) -> None:
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
        def __init__(self, expectations: list[object]) -> None:
            super().__init__(expectations)
            self._structured_calls = 0

        async def generate_structured(
            self,
            messages,
            output_type,
            policy,
            validate_result=None,
        ):
            self._structured_calls += 1
            if self._structured_calls > 1:
                await gate.wait()
            return await super().generate_structured(
                messages,
                output_type,
                policy,
                validate_result=validate_result,
            )

    fake = HoldingAssessmentFake(
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
        await wait_for_operation_status(
            runtime.application,
            operation_id,
            OperationStatus.FAILED,
        )
        revision = (await runtime.application.get_snapshot()).revision
        await runtime.application.retry_operation(
            RetryOperation(expected_revision=revision, operation_id=operation_id)
        )
        runtime.application.begin_shutdown()
        gate.set()
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
    fake.assert_exhausted()


async def test_operation_changed_events_are_published(store: SQLiteStore) -> None:
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
        seen: list[OperationChanged] = []
        async with runtime.events.subscribe() as events:
            await runtime.application.recover_on_startup()
            gate.set()
            while len(seen) < 2:
                event = await asyncio.wait_for(events.__anext__(), timeout=2.0)
                if isinstance(event, OperationChanged):
                    seen.append(event)
    assert seen[0].operation.status is OperationStatus.RUNNING
    assert seen[-1].operation.status is OperationStatus.COMPLETE
