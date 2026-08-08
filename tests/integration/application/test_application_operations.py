"""TherapyApplication assessment and post-session operation tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from jung.domain.commands import (
    EndSession,
    SendMessage,
    UpdateProfile,
)
from jung.domain.models import (
    ChatTurnStatus,
    CommandName,
    MessageRole,
    OperationStatus,
    Profile,
    Stage,
)
from jung.events import OperationChanged
from jung.llm.errors import InvalidLLMOutput, LLMTimeout, LLMUnavailable
from jung.llm.fake import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.models import IntakeRecordPatch

from .application_fixtures import (
    assessment_result,
    build_test_application,
    completing_intake_patch,
    post_session_expectations,
    wait_for_chat_turn,
    wait_for_operation_status,
    wait_for_stage,
)
from .scenarios import (
    advance_to_post_session,
    advance_to_ready,
    complete_intake_for_assessment,
    open_intake,
)

pytestmark = pytest.mark.asyncio

SECRET_MARKER = "secret-marker https://api.example.com sk-test-key"


async def test_operation_worker_persists_sanitized_error_message(
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
            FailureExpectation(
                task=LLMTask.ASSESSMENT,
                error=LLMUnavailable(SECRET_MARKER),
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
    assert operation.error_code == "llm_unavailable"
    assert operation.error_message == "The language model is currently unavailable."
    assert SECRET_MARKER not in (operation.error_message or "")


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
    # Empty therapy transcript takes the deterministic zero-call path.
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        await wait_for_stage(runtime.application, Stage.READY)
        snapshot = await runtime.application.get_snapshot()
    assert snapshot.stage is Stage.READY
    fake.assert_exhausted()


async def test_conversational_post_session_persists_authoritative_grounded_turn(
    store: SQLiteStore,
) -> None:
    advance_to_ready(store)
    patient_text = "I do not think I want to die."
    fake = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Tell me more about that.",),
            ),
            *post_session_expectations(
                patient_sequence=1,
                update_fragments=(patient_text,),
            ),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        started = await runtime.application.start_session()
        session_id = started.session.id
        turn = await runtime.application.submit_message(
            SendMessage(
                session_id=session_id,
                client_message_id=uuid4(),
                content=patient_text,
            )
        )
        await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.COMPLETE,
        )
        messages = runtime.store.list_messages(session_id)
        user_message = next(
            message for message in messages if message.role == MessageRole.USER
        )
        await runtime.application.end_session(
            EndSession(
                session_id=session_id,
            )
        )
        await wait_for_stage(runtime.application, Stage.READY)

        profile = runtime.store.get_profile()
        assert profile is not None
        assert profile.derived_profile is not None
        turns = profile.derived_profile["grounded_patient_turns"]
        assert len(turns) == 1
        assert turns[0]["source_message_id"] == str(user_message.id)
        assert turns[0]["content"] == patient_text
        assert turns[0]["content"] != "I want to die."

        history = runtime.store.get_session(session_id)
        assert history is not None
        assert history.summary == "Patient explored sleep difficulties."
        assert history.briefing is not None
        assert history.briefing["narrative_handoff"] == "Session focused on sleep."

        plan = runtime.store.get_current_plan()
        assert plan is not None
        assert plan.source_session_id == session_id
        assert plan.current_progress == "some progress"
        assert plan.session_briefing is not None
        assert plan.session_briefing["narrative_handoff"] == "Session focused on sleep."
    fake.assert_exhausted()


async def test_malformed_derived_profile_fails_therapy_as_internal_error(
    store: SQLiteStore,
) -> None:
    advance_to_ready(store)
    with store._connect() as conn:
        conn.execute(
            "UPDATE profile SET derived_profile_json = ? WHERE singleton_id = 1",
            ('{"grounded_patient_turns": null}',),
        )
        conn.commit()

    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        started = await runtime.application.start_session()
        turn = await runtime.application.submit_message(
            SendMessage(
                session_id=started.session.id,
                client_message_id=uuid4(),
                content="I slept badly.",
            )
        )
        await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.FAILED,
        )
        failed = runtime.store.get_chat_turn(turn.id)
        assert failed is not None
        assert failed.error_code == "internal_error"
        assert failed.error_code != "invalid_llm_output"
    fake.assert_exhausted()


async def test_malformed_derived_profile_fails_post_session_as_internal_error(
    store: SQLiteStore,
) -> None:
    ready = advance_to_post_session(store)
    with store._connect() as conn:
        conn.execute(
            "UPDATE profile SET derived_profile_json = ? WHERE singleton_id = 1",
            ('{"grounded_patient_turns": null}',),
        )
        conn.commit()

    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        await wait_for_operation_status(
            runtime.application,
            ready.post_session_operation_id,
            OperationStatus.FAILED,
        )
        operation = runtime.store.get_operation(ready.post_session_operation_id)
        assert operation is not None
        assert operation.error_code == "internal_error"
        assert operation.error_code != "invalid_llm_output"
        session = runtime.store.get_session(ready.therapy_session_id)
        assert session is not None
        assert session.summary is None


async def test_post_session_processing_failure_leaves_session_artifacts_unchanged(
    store: SQLiteStore,
) -> None:
    advance_to_ready(store)
    fake = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Let's explore that.",),
            ),
            FailureExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                error=InvalidLLMOutput("analysis failed"),
            ),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        started = await runtime.application.start_session()
        session_id = started.session.id
        plan_before = runtime.store.get_current_plan()
        profile_before = runtime.store.get_profile()
        assert plan_before is not None
        assert profile_before is not None

        turn = await runtime.application.submit_message(
            SendMessage(
                session_id=session_id,
                client_message_id=uuid4(),
                content="I slept badly.",
            )
        )
        await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.COMPLETE,
        )
        await runtime.application.end_session(
            EndSession(
                session_id=session_id,
            )
        )
        operation = (await runtime.application.get_snapshot()).current_operation
        assert operation is not None
        await wait_for_operation_status(
            runtime.application,
            operation.id,
            OperationStatus.FAILED,
        )

        session_after = runtime.store.get_session(session_id)
        assert session_after is not None
        assert session_after.summary is None
        assert session_after.briefing is None
        plan_after = runtime.store.get_current_plan()
        profile_after = runtime.store.get_profile()
        assert plan_after is not None
        assert profile_after is not None
        assert plan_after.id == plan_before.id
        assert plan_after.version == plan_before.version
        assert profile_after.derived_profile == profile_before.derived_profile
        assert profile_after.current_plan_id == profile_before.current_plan_id
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
        await runtime.application.retry_operation()
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
        await runtime.application.retry_operation()
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


async def test_end_session_schedules_operation_when_publish_cancelled(
    store: SQLiteStore,
) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        session_id=therapy_id,
        now=ready.now,
    )
    fake = FakeLLM([])
    publish_gate = asyncio.Event()
    release_publish = asyncio.Event()

    class GatedPublishEventStream:
        def __init__(self, inner) -> None:
            self._inner = inner

        async def publish(self, event) -> None:
            if isinstance(event, OperationChanged):
                publish_gate.set()
                await release_publish.wait()
            await self._inner.publish(event)

        def subscribe(self):
            return self._inner.subscribe()

    async with build_test_application(store, fake) as runtime:
        runtime.events = GatedPublishEventStream(runtime.events)
        runtime.application._events = runtime.events
        end_task = asyncio.create_task(
            runtime.application.end_session(EndSession(session_id=therapy_id))
        )
        await asyncio.wait_for(publish_gate.wait(), timeout=2.0)
        end_task.cancel()
        release_publish.set()
        with pytest.raises(asyncio.CancelledError):
            await end_task
        await wait_for_stage(runtime.application, Stage.READY)
    fake.assert_exhausted()


async def test_retry_operation_schedules_operation_when_publish_fails(
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

    class FailingPublishEventStream:
        def __init__(self, inner) -> None:
            self._inner = inner
            self._fail_once = True

        async def publish(self, event) -> None:
            if self._fail_once and isinstance(event, OperationChanged):
                operation = event.operation
                if (
                    operation.id == operation_id
                    and operation.status is OperationStatus.PENDING
                ):
                    self._fail_once = False
                    raise RuntimeError("publish failed")
            await self._inner.publish(event)

        def subscribe(self):
            return self._inner.subscribe()

    async with build_test_application(store, fake) as runtime:
        runtime.events = FailingPublishEventStream(runtime.events)
        runtime.application._events = runtime.events
        await wait_for_operation_status(
            runtime.application,
            operation_id,
            OperationStatus.FAILED,
        )
        await runtime.application.retry_operation()
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
    fake.assert_exhausted()


async def test_end_session_schedules_when_assemble_cancelled(
    store: SQLiteStore,
) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        session_id=therapy_id,
        now=ready.now,
    )
    fake = FakeLLM([])
    assemble_entered = asyncio.Event()
    release_assemble = asyncio.Event()
    gate_next_assemble = False

    async with build_test_application(store, fake) as runtime:
        original_assemble = runtime.application._assemble_snapshot_locked

        async def gated_assemble():
            nonlocal gate_next_assemble
            result = await original_assemble()
            if gate_next_assemble:
                gate_next_assemble = False
                assemble_entered.set()
                await release_assemble.wait()
            return result

        runtime.application._assemble_snapshot_locked = gated_assemble
        gate_next_assemble = True
        end_task: asyncio.Task | None = None
        try:
            end_task = asyncio.create_task(
                runtime.application.end_session(EndSession(session_id=therapy_id))
            )
            await asyncio.wait_for(assemble_entered.wait(), timeout=2.0)
            end_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await end_task
            await wait_for_stage(runtime.application, Stage.READY)
        finally:
            release_assemble.set()
            if end_task is not None and not end_task.done():
                end_task.cancel()
                await asyncio.gather(end_task, return_exceptions=True)
    fake.assert_exhausted()


async def test_retry_operation_schedules_when_assemble_raises(
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
    gate_next_assemble = False

    async with build_test_application(store, fake) as runtime:
        original_assemble = runtime.application._assemble_snapshot_locked

        async def failing_assemble():
            nonlocal gate_next_assemble
            result = await original_assemble()
            if gate_next_assemble:
                gate_next_assemble = False
                raise RuntimeError("injected assemble failure")
            return result

        runtime.application._assemble_snapshot_locked = failing_assemble
        await wait_for_operation_status(
            runtime.application,
            operation_id,
            OperationStatus.FAILED,
        )
        gate_next_assemble = True
        with pytest.raises(RuntimeError, match="injected assemble failure"):
            await runtime.application.retry_operation()
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
    fake.assert_exhausted()


async def test_final_intake_schedules_when_load_message_fails(
    store: SQLiteStore,
) -> None:
    turn_messages = ("first turn", "second turn", "third turn")
    final_message_sequence = 5
    expectations: list[StructuredExpectation | StreamExpectation] = []
    for index, content in enumerate(turn_messages, start=1):
        if index < len(turn_messages):
            expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeRecordPatch,
                        response=IntakeRecordPatch(),
                    ),
                    StreamExpectation(
                        task=LLMTask.INTAKE_RESPONSE,
                        chunks=(f"Response {index}.",),
                    ),
                ]
            )
        else:
            expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeRecordPatch,
                        response=completing_intake_patch(
                            message_sequence=final_message_sequence,
                            quote=content,
                        ),
                    ),
                    StreamExpectation(
                        task=LLMTask.INTAKE_RESPONSE,
                        chunks=("Thank you for sharing.",),
                    ),
                ]
            )
    expectations.append(
        StructuredExpectation(
            task=LLMTask.ASSESSMENT,
            output_type=AssessmentResult,
            response=assessment_result(),
        )
    )
    fake = FakeLLM(expectations)
    fail_on_next_load = False

    async with build_test_application(store, fake) as runtime:
        original_load_message = runtime.application._load_message

        async def failing_load_message(session_id, message_id):
            if fail_on_next_load:
                raise RuntimeError("injected post-commit read failure")
            return await original_load_message(session_id, message_id)

        runtime.application._load_message = failing_load_message
        await runtime.application.update_profile(
            UpdateProfile(
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session_id = (await runtime.application.get_snapshot()).active_session
        assert session_id is not None
        for index, content in enumerate(turn_messages):
            if index == len(turn_messages) - 1:
                fail_on_next_load = True
            turn = await runtime.application.submit_message(
                SendMessage(
                    session_id=session_id.id,
                    client_message_id=uuid4(),
                    content=content,
                )
            )
            if index < len(turn_messages) - 1:
                await wait_for_chat_turn(
                    runtime.application,
                    turn.id,
                    ChatTurnStatus.COMPLETE,
                )
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
    fake.assert_exhausted()
