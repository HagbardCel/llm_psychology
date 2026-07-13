"""TherapyApplication startup recovery and shutdown tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.errors import Busy
from jung.domain.models import (
    ChatTurnStatus,
    OperationStatus,
    PlanContent,
    Profile,
    Stage,
)
from jung.llm.fake import FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult, StyleRecommendation

from .application_fixtures import build_test_application, wait_for_stage
from .scenarios import complete_intake_for_assessment, open_intake

pytestmark = pytest.mark.asyncio


def _assessment_result() -> AssessmentResult:
    plan = PlanContent(
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=["track sleep"],
    )
    return AssessmentResult(
        formulation="Anxiety presentation",
        presenting_concerns=("anxiety",),
        strengths_and_resources=("support",),
        style_recommendations=tuple(
            StyleRecommendation(
                style_id=style_id,
                score=0.9 if style_id == "cbt" else 0.5,
                rationale=f"Fit for {style_id}",
                key_topics=("anxiety",),
                initial_plan=plan,
            )
            for style_id in ("jung", "cbt", "freud")
        ),
    )


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
                response=_assessment_result(),
            )
        ]
    )
    async with build_test_application(store, fake) as runtime:
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
        snapshot = await runtime.application.get_snapshot()
    assert snapshot.stage is Stage.STYLE_SELECTION
    fake.assert_exhausted()


async def test_recover_on_startup_marks_stale_chat_turn_failed(store: SQLiteStore) -> None:
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
                response=_assessment_result(),
            )
        ]
    )
    async with build_test_application(store, fake) as runtime:
        operation = runtime.store.get_operation(operation_id)
        assert operation is not None
        assert operation.status is OperationStatus.PENDING
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
    fake.assert_exhausted()


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
