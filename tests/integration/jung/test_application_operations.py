"""TherapyApplication assessment and post-session operation tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from jung.domain.commands import RetryOperation, SelectStyle
from jung.domain.models import OperationStatus, PlanContent, Stage
from jung.events import OperationChanged
from jung.llm.errors import LLMTimeout
from jung.llm.fake import FailureExpectation, FakeLLM, StructuredExpectation
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
    wait_for_operation_status,
    wait_for_stage,
)
from .scenarios import (
    advance_to_post_session,
    complete_intake_for_assessment,
    open_intake,
)

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


def _post_session_expectations() -> list[StructuredExpectation]:
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
                response=_assessment_result(),
            )
        ]
    )
    async with build_test_application(store, fake) as runtime:
        await wait_for_stage(runtime.application, Stage.STYLE_SELECTION)
        operation = (await runtime.application.get_snapshot()).current_operation
    assert operation is None
    fake.assert_exhausted()


async def test_select_style_uses_completed_assessment_result(store: SQLiteStore) -> None:
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
    assert snapshot.selected_style == "cbt"
    fake.assert_exhausted()


async def test_post_session_operation_completes_to_ready(store: SQLiteStore) -> None:
    advance_to_post_session(store)
    fake = FakeLLM(_post_session_expectations())
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
                response=_assessment_result(),
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
                response=_assessment_result(),
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
