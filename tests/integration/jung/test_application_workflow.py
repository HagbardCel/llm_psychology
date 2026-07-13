"""TherapyApplication workflow integration tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.domain.commands import (
    EndSession,
    SelectStyle,
    SendMessage,
    StartSession,
    UpdateProfile,
)
from jung.domain.models import (
    ChatTurnStatus,
    CommandName,
    OperationKind,
    OperationStatus,
    PlanContent,
    Profile,
    SessionKind,
    Stage,
)
from jung.llm.fake import FakeLLM, StreamExpectation, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult, StyleRecommendation
from jung.phases.post_session.models import (
    DerivedProfilePatch,
    PlanPatch,
    PostSessionResult,
    SessionAnalysisResult,
    SessionBriefing,
)

from .application_fixtures import (
    build_test_application,
    wait_for_chat_turn,
    wait_for_stage,
)
from .scenarios import advance_to_ready, complete_intake_for_assessment, open_intake

pytestmark = pytest.mark.asyncio


def _plan_content() -> PlanContent:
    return PlanContent(
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=["track sleep"],
    )


def _assessment_result() -> AssessmentResult:
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
                initial_plan=_plan_content(),
            )
            for style_id in ("jung", "cbt", "freud")
        ),
    )


def _post_session_expectations() -> list[StreamExpectation | StructuredExpectation]:
    return [
        StructuredExpectation(
            task=LLMTask.POST_SESSION_ANALYSIS,
            output_type=SessionAnalysisResult,
            response=SessionAnalysisResult(
                summary="Patient explored sleep difficulties.",
                key_themes=("sleep",),
            ),
        ),
        StructuredExpectation(
            task=LLMTask.POST_SESSION_UPDATE,
            output_type=PostSessionResult,
            response=PostSessionResult(
                session_summary="Sleep remained difficult.",
                session_briefing=SessionBriefing(
                    narrative_handoff="Session focused on sleep.",
                    recommended_opening_focus="sleep routine",
                ),
                derived_profile_patch=DerivedProfilePatch(
                    observations=("reports poor sleep",)
                ),
                plan_patch=PlanPatch(current_progress="some progress"),
            ),
        ),
    ]


async def test_update_profile_creates_intake_session(store: SQLiteStore) -> None:
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        snapshot = await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
    assert snapshot.stage is Stage.INTAKE
    assert snapshot.active_session is not None
    assert snapshot.active_session.kind is SessionKind.INTAKE


async def test_seeded_ready_snapshot_exposes_start_session(store: SQLiteStore) -> None:
    advance_to_ready(store)
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        snapshot = await runtime.application.get_snapshot()
    assert snapshot.stage is Stage.READY
    assert CommandName.START_SESSION in snapshot.available_commands


async def test_select_style_advances_to_ready(store: SQLiteStore) -> None:
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
        result=_assessment_result().model_dump(mode="json"),
        now=now,
    )
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        revision = (await runtime.application.get_snapshot()).revision
        snapshot = await runtime.application.select_style(
            SelectStyle(expected_revision=revision, style_id="cbt")
        )
    assert snapshot.stage is Stage.READY
    assert snapshot.selected_style == "cbt"


async def test_start_session_enters_therapy(store: SQLiteStore) -> None:
    advance_to_ready(store)
    fake = FakeLLM([])
    async with build_test_application(store, fake) as runtime:
        revision = (await runtime.application.get_snapshot()).revision
        session = await runtime.application.start_session(
            StartSession(expected_revision=revision)
        )
        snapshot = await runtime.application.get_snapshot()
    assert snapshot.stage is Stage.THERAPY
    assert session.kind is SessionKind.THERAPY
    assert snapshot.active_session is not None
    assert snapshot.active_session.id == session.id


async def test_end_session_creates_post_session_operation(store: SQLiteStore) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=ready.now,
    )
    fake = FakeLLM(_post_session_expectations())
    async with build_test_application(store, fake) as runtime:
        revision = (await runtime.application.get_snapshot()).revision
        snapshot = await runtime.application.end_session(
            EndSession(expected_revision=revision, session_id=therapy_id)
        )
    assert snapshot.stage is Stage.POST_SESSION
    assert snapshot.current_operation is not None
    assert snapshot.current_operation.kind is OperationKind.POST_SESSION
    assert snapshot.current_operation.status is OperationStatus.PENDING


async def test_full_assessment_e2e_with_fake_llm(store: SQLiteStore) -> None:
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
        revision = (await runtime.application.get_snapshot()).revision
        snapshot = await runtime.application.select_style(
            SelectStyle(expected_revision=revision, style_id="cbt")
        )
    assert snapshot.stage is Stage.READY
    fake.assert_exhausted()


async def test_full_therapy_to_post_session_e2e(store: SQLiteStore) -> None:
    advance_to_ready(store)
    fake = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Let's explore that.",),
            ),
            *_post_session_expectations(),
        ]
    )
    async with build_test_application(store, fake) as runtime:
        revision = (await runtime.application.get_snapshot()).revision
        session = await runtime.application.start_session(
            StartSession(expected_revision=revision)
        )
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session.id,
                client_message_id=uuid4(),
                content="I slept badly again.",
            )
        )
        await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.COMPLETE,
        )
        snapshot = await runtime.application.end_session(
            EndSession(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session.id,
            )
        )
        assert snapshot.stage is Stage.POST_SESSION
        assert snapshot.current_operation is not None
        await wait_for_stage(runtime.application, Stage.READY)
    fake.assert_exhausted()
