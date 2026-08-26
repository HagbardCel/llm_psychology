"""TherapyApplication assessment and post-session operation tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from jung._application.inputs import PhaseInputs
from jung._application.operations import OperationRuntime
from jung.diagnostics import DiagnosticRecorder
from jung.domain.commands import (
    EndSession,
    SendMessage,
    UpdateProfile,
)
from jung.domain.models import (
    CommandName,
    MessageRole,
    OperationKind,
    OperationStatus,
    Profile,
    Stage,
)
from jung.domain.results import ChatCompleted, ChatFailed
from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
)
from jung.llm.errors import InvalidLLMOutput, LLMTimeout, LLMUnavailable
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.intake.extraction import IntakeExtraction
from jung.phases.post_session.models import (
    PostSessionUpdateResult,
)
from jung.styles import load_styles
from tests.support.fake_llm import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from tests.support.session_review import minimal_review

from .application_fixtures import (
    assessment_result,
    build_test_application,
    collect_stream,
    completing_intake_extraction,
    post_session_expectations,
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
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session_id,
                client_message_id=uuid4(),
                content=patient_text,
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
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

        grounded = runtime.store.list_grounded_patient_messages()
        assert len(grounded) == 1
        assert grounded[0].id == user_message.id
        assert grounded[0].content == patient_text

        history = runtime.store.get_session(session_id)
        assert history is not None
        assert history.review is not None
        assert history.review.analysis.summary == "Patient explored sleep difficulties."
        assert history.review.briefing.narrative_handoff == "Session focused on sleep."

        plan = runtime.store.get_current_plan()
        assert plan is not None
        assert plan.source_session_id == session_id
        assert plan.current_progress == "some progress"
    fake.assert_exhausted()


async def test_malformed_review_json_fails_therapy_as_internal_error(
    store: SQLiteStore,
) -> None:
    ready = advance_to_ready(store)
    first_therapy_id = uuid4()
    store.start_therapy_session(session_id=first_therapy_id, now=ready.now)
    first_post_op = uuid4()
    store.end_therapy_session(
        session_id=first_therapy_id,
        operation_id=first_post_op,
        now=ready.now,
    )
    store.mark_operation_running(first_post_op, now=ready.now)
    store.complete_post_session(
        first_post_op,
        review=minimal_review(),
        new_plan=None,
        now=ready.now,
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE sessions SET review_json = ? WHERE id = ?",
            ('{"analysis": "not-an-object"}', str(first_therapy_id)),
        )
        conn.commit()

    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        started = await runtime.application.start_session()
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=started.session.id,
                client_message_id=uuid4(),
                content="I slept badly.",
            ),
        )
        assert isinstance(items[-1], ChatFailed)
        assert items[-1].code == "internal_error"
        assert items[-1].code != "invalid_llm_output"
    fake.assert_exhausted()


async def test_malformed_review_json_fails_post_session_as_internal_error(
    store: SQLiteStore,
) -> None:
    ready = advance_to_ready(store)
    first_therapy_id = uuid4()
    store.start_therapy_session(session_id=first_therapy_id, now=ready.now)
    first_post_op = uuid4()
    store.end_therapy_session(
        session_id=first_therapy_id,
        operation_id=first_post_op,
        now=ready.now,
    )
    store.mark_operation_running(first_post_op, now=ready.now)
    store.complete_post_session(
        first_post_op,
        review=minimal_review(),
        new_plan=None,
        now=ready.now,
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE sessions SET review_json = ? WHERE id = ?",
            ('{"analysis": "not-an-object"}', str(first_therapy_id)),
        )
        conn.commit()

    second_therapy_id = uuid4()
    store.start_therapy_session(session_id=second_therapy_id, now=ready.now)
    second_post_op = uuid4()
    store.end_therapy_session(
        session_id=second_therapy_id,
        operation_id=second_post_op,
        now=ready.now,
    )

    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        await wait_for_operation_status(
            runtime.application,
            second_post_op,
            OperationStatus.FAILED,
        )
        operation = runtime.store.get_operation(second_post_op)
        assert operation is not None
        assert operation.error_code == "internal_error"
        assert operation.error_code != "invalid_llm_output"
        session = runtime.store.get_session(second_therapy_id)
        assert session is not None
        assert session.review is None
    fake.assert_exhausted()


async def test_prior_session_briefing_reaches_next_session_without_plan_revision(
    store: SQLiteStore,
) -> None:
    briefing_b = SessionBriefing(
        narrative_handoff="Prior session handoff B.",
        recommended_opening_focus="continue sleep work",
    )
    advance_to_ready(store)
    patient_text = "I slept badly again."
    fake = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Let's explore that.",),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysis,
                response=SessionAnalysis(
                    summary="Patient explored sleep difficulties.",
                    key_themes=("sleep",),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionUpdateResult,
                response=PostSessionUpdateResult(
                    session_briefing=briefing_b,
                    plan_patch=PlanPatch(),
                ),
            ),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        started = await runtime.application.start_session()
        first_session_id = started.session.id
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=first_session_id,
                client_message_id=uuid4(),
                content=patient_text,
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
        plan_before = runtime.store.get_current_plan()
        assert plan_before is not None
        await runtime.application.end_session(EndSession(session_id=first_session_id))
        await wait_for_stage(runtime.application, Stage.READY)
        plan_after = runtime.store.get_current_plan()
        assert plan_after is not None
        assert plan_after.id == plan_before.id
        assert plan_after.version == plan_before.version

        second = await runtime.application.start_session()
        runtime.store.append_user_message(
            session_id=second.session.id,
            client_message_id=uuid4(),
            user_message_id=uuid4(),
            content="follow-up turn",
            now=second.session.started_at,
        )
        inputs = PhaseInputs(store=runtime.store, styles=load_styles())
        turn_input = await inputs.build_therapy_turn_input(second.session.id)
        assert turn_input.latest_supervisor_briefing == briefing_b
    fake.assert_exhausted()


async def test_phase_inputs_prior_reviews_ordered_oldest_to_newest(
    store: SQLiteStore,
) -> None:
    briefing_a = SessionBriefing(
        narrative_handoff="Prior session handoff A.",
        recommended_opening_focus="focus A",
    )
    briefing_b = SessionBriefing(
        narrative_handoff="Prior session handoff B.",
        recommended_opening_focus="focus B",
    )
    advance_to_ready(store)
    fake = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Let's explore session one.",),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysis,
                response=SessionAnalysis(
                    summary="First session explored sleep.",
                    key_themes=("sleep",),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionUpdateResult,
                response=PostSessionUpdateResult(
                    session_briefing=briefing_a,
                    plan_patch=PlanPatch(),
                ),
            ),
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Let's explore session two.",),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysis,
                response=SessionAnalysis(
                    summary="Second session explored worry.",
                    key_themes=("worry",),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionUpdateResult,
                response=PostSessionUpdateResult(
                    session_briefing=briefing_b,
                    plan_patch=PlanPatch(),
                ),
            ),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        first = await runtime.application.start_session()
        first_session_id = first.session.id
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=first_session_id,
                client_message_id=uuid4(),
                content="session one patient turn",
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
        await runtime.application.end_session(EndSession(session_id=first_session_id))
        await wait_for_stage(runtime.application, Stage.READY)
        first_session = runtime.store.get_session(first_session_id)
        assert first_session is not None
        review_a = first_session.review
        assert review_a is not None

        second = await runtime.application.start_session()
        second_session_id = second.session.id
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=second_session_id,
                client_message_id=uuid4(),
                content="session two patient turn",
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
        await runtime.application.end_session(EndSession(session_id=second_session_id))
        await wait_for_stage(runtime.application, Stage.READY)
        second_session = runtime.store.get_session(second_session_id)
        assert second_session is not None
        review_b = second_session.review
        assert review_b is not None

        third = await runtime.application.start_session()
        third_session_id = third.session.id
        runtime.store.append_user_message(
            session_id=third_session_id,
            client_message_id=uuid4(),
            user_message_id=uuid4(),
            content="session three patient turn",
            now=third.session.started_at,
        )
        inputs = PhaseInputs(store=runtime.store, styles=load_styles())
        turn_input = await inputs.build_therapy_turn_input(third_session_id)
        assert turn_input.latest_supervisor_briefing == briefing_b
        assert turn_input.latest_supervisor_briefing == review_b.briefing

        await runtime.application.end_session(EndSession(session_id=third_session_id))
        await wait_for_stage(runtime.application, Stage.POST_SESSION)
        operation = runtime.store.get_current_operation()
        assert operation is not None
        post_input = await inputs.build_post_session_input(operation)
        assert post_input.prior_reviews == (review_a, review_b)
    fake.assert_exhausted()


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

        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session_id,
                client_message_id=uuid4(),
                content="I slept badly.",
            ),
        )
        assert isinstance(items[-1], ChatCompleted)
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
        assert session_after.review is None
        plan_after = runtime.store.get_current_plan()
        profile_after = runtime.store.get_profile()
        assert plan_after is not None
        assert profile_after is not None
        assert plan_after.id == plan_before.id
        assert plan_after.version == plan_before.version
        assert profile_after.current_plan_id == profile_before.current_plan_id
        assert runtime.store.list_grounded_patient_messages() == []
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


async def test_retry_handoff_survives_shutdown_and_recovers_on_next_startup(
    store: SQLiteStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    failed_persisted = asyncio.Event()
    allow_worker_exit = asyncio.Event()
    original_persist = OperationRuntime._persist_operation_failure_if_running

    async def gated_persist(
        self: OperationRuntime,
        failed_operation_id,
        exc: Exception,
    ) -> None:
        await original_persist(self, failed_operation_id, exc)
        failed_persisted.set()
        await allow_worker_exit.wait()

    monkeypatch.setattr(
        OperationRuntime,
        "_persist_operation_failure_if_running",
        gated_persist,
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
    async with build_test_application(store, fake, recover=False) as runtime:
        app = runtime.application
        await app.recover_on_startup()
        await wait_for_operation_status(
            app,
            operation_id,
            OperationStatus.FAILED,
        )
        await asyncio.wait_for(failed_persisted.wait(), timeout=2.0)

        await app.retry_operation()
        operation = store.get_operation(operation_id)
        assert operation is not None
        assert operation.status is OperationStatus.PENDING
        assert operation.attempt == 1

        shutdown_task = asyncio.create_task(app.shutdown(timeout_seconds=5.0))
        await asyncio.wait_for(app._shutdown_started.wait(), timeout=2.0)

        allow_worker_exit.set()
        await shutdown_task

        operation = store.get_operation(operation_id)
        assert operation is not None
        assert operation.status is OperationStatus.PENDING
        assert operation.attempt == 1

    async with build_test_application(store, fake) as runtime_b:
        await wait_for_stage(runtime_b.application, Stage.STYLE_SELECTION)

    completed = store.get_operation(operation_id)
    assert completed is not None
    assert completed.status is OperationStatus.COMPLETE
    assert completed.attempt == 2
    fake.assert_exhausted()


async def test_pending_assessment_reaches_running_then_complete(
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
        await runtime.application.recover_on_startup()
        await wait_for_operation_status(
            runtime.application,
            operation_id,
            OperationStatus.RUNNING,
        )
        gate.set()
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
        operation = runtime.store.get_operation(operation_id)
    assert operation is not None
    assert operation.status is OperationStatus.COMPLETE
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


def _final_intake_expectations(
    turn_messages: tuple[str, ...],
) -> list[StructuredExpectation | StreamExpectation]:
    expectations: list[StructuredExpectation | StreamExpectation] = []
    for index, content in enumerate(turn_messages, start=1):
        if index < len(turn_messages):
            expectations.extend(
                [
                    StructuredExpectation(
                        task=LLMTask.INTAKE_PATCH,
                        output_type=IntakeExtraction,
                        response=IntakeExtraction(),
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
                        output_type=IntakeExtraction,
                        response=completing_intake_extraction(
                            quote=content,
                        ),
                    ),
                    StreamExpectation(
                        task=LLMTask.INTAKE_RESPONSE,
                        chunks=("Thank you for sharing.",),
                    ),
                ]
            )
    return expectations


def _load_trace(run_dir: Path) -> list[dict[str, object]]:
    lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


async def test_final_intake_spawn_failure_keeps_completion_and_pending_operation(
    store: SQLiteStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn_messages = ("first turn", "second turn", "third turn")
    fake = FakeLLM(_final_intake_expectations(turn_messages))
    run_dir = tmp_path / "schedule-failure"

    def boom_spawn(self, operation):  # type: ignore[no-untyped-def]
        del operation
        raise RuntimeError("injected schedule start failure")

    from jung._application.operations import OperationRuntime

    monkeypatch.setattr(OperationRuntime, "_spawn_operation_task", boom_spawn)

    with DiagnosticRecorder(run_dir) as recorder:
        async with build_test_application(
            store,
            fake,
            recorder=recorder,
        ) as runtime:
            await runtime.application.update_profile(
                UpdateProfile(
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )
            session = (await runtime.application.get_snapshot()).active_session
            assert session is not None
            for index, content in enumerate(turn_messages):
                items = await collect_stream(
                    runtime.application,
                    SendMessage(
                        session_id=session.id,
                        client_message_id=uuid4(),
                        content=content,
                    ),
                )
                if index < len(turn_messages) - 1:
                    assert isinstance(items[-1], ChatCompleted)
            snapshot = await runtime.application.get_snapshot()
            assert isinstance(items[-1], ChatCompleted)
            assert snapshot.stage is Stage.ASSESSMENT
            assert snapshot.current_operation is not None
            assert snapshot.current_operation.kind is OperationKind.ASSESSMENT
            assert snapshot.current_operation.status is OperationStatus.PENDING
            user, assistant = store.get_messages_by_client_id(
                session.id,
                items[-1].client_message_id,
            )
            assert user is not None
            assert assistant is not None
    fake.assert_exhausted()
    events = _load_trace(run_dir)
    kinds = [event["kind"] for event in events]
    assert "chat.turn.completed" in kinds
    assert "chat.turn.failed" not in kinds
    schedule_errors = [
        event
        for event in events
        if event["kind"] == "runtime.error"
        and event["data"].get("phase") == "operation_schedule"
    ]
    assert len(schedule_errors) == 1
    assert isinstance(items[-1], ChatCompleted)
