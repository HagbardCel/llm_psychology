"""Processor contract compatibility with Phase 2 store seams."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import NewPlanRevision, Plan, PlanContent, Profile
from jung.llm.fake import FakeLLM, StreamExpectation, StructuredExpectation
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.phases.assessment.models import (
    AssessmentInput,
    AssessmentResult,
    StyleRecommendation,
)
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.intake.models import IntakeRecord, IntakeTurnInput
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.post_session.merge import merge_plan_revision
from jung.phases.post_session.models import (
    DerivedProfilePatch,
    PlanPatch,
    PostSessionInput,
    PostSessionResult,
    SessionAnalysisResult,
    SessionBriefing,
)
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.therapy.processor import TherapyProcessor
from jung.styles import load_styles


def _plan_content() -> PlanContent:
    return PlanContent(
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=["track sleep"],
    )


def _plan() -> Plan:
    now = datetime.now(UTC)
    return Plan(
        id=uuid4(),
        version=1,
        selected_style="cbt",
        created_at=now,
        **_plan_content().model_dump(),
    )


@pytest.mark.asyncio
async def test_intake_plan_record_maps_to_complete_chat_turn_shape() -> None:
    gateway = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.INTAKE_RESPONSE,
                chunks=("Welcome.",),
            )
        ]
    )
    processor = IntakeProcessor(
        gateway,
        patch_policy=ModelPolicy(
            task=LLMTask.INTAKE_PATCH,
            model="fake",
            temperature=0.0,
            timeout_seconds=30.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
        response_policy=ModelPolicy(
            task=LLMTask.INTAKE_RESPONSE,
            model="fake",
            temperature=0.7,
            timeout_seconds=30.0,
        ),
    )
    plan = await processor.prepare_turn(
        IntakeTurnInput(profile=Profile(name="Alex", primary_language="English"))
    )
    intake_record = plan.merged_record.model_dump()
    assert isinstance(intake_record, dict)
    restored = IntakeRecord.model_validate(intake_record)
    assert restored == plan.merged_record
    content = "".join([chunk async for chunk in processor.stream_response(plan)])
    assert content == "Welcome."


@pytest.mark.asyncio
async def test_assessment_result_maps_to_select_style_plan_content() -> None:
    styles = tuple(load_styles().values())
    recommendation = StyleRecommendation(
        style_id="cbt",
        score=0.9,
        rationale="Strong fit",
        key_topics=("anxiety",),
        initial_plan=_plan_content(),
    )
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=AssessmentResult(
                    formulation="Anxiety presentation",
                    presenting_concerns=("anxiety",),
                    strengths_and_resources=("support",),
                    style_recommendations=tuple(
                        recommendation.model_copy(update={"style_id": style.id})
                        for style in styles
                    ),
                ),
            )
        ]
    )
    processor = AssessmentProcessor(
        gateway,
        assessment_policy=ModelPolicy(
            task=LLMTask.ASSESSMENT,
            model="fake",
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
    )
    result = await processor.assess(
        AssessmentInput(
            intake_record=IntakeRecord().model_dump(),
            transcript=(),
            profile=Profile(name="Alex", primary_language="English"),
            available_styles=styles,
        )
    )
    restored = AssessmentResult.model_validate_json(result.model_dump_json())
    selected = next(
        item for item in restored.style_recommendations if item.style_id == "cbt"
    )
    plan_content = PlanContent.model_validate(selected.initial_plan.model_dump())
    assert plan_content.focus == "anxiety"


def test_therapy_build_messages_is_valid() -> None:
    processor = TherapyProcessor(
        FakeLLM([]),
        response_policy=ModelPolicy(
            task=LLMTask.THERAPY_RESPONSE,
            model="fake",
            temperature=0.7,
            timeout_seconds=30.0,
        ),
    )
    messages = processor.build_messages(
        TherapyTurnInput(
            profile=Profile(name="Alex", primary_language="English"),
            current_plan=_plan(),
            latest_user_message="Hello",
            selected_style=load_styles()["cbt"],
        )
    )
    assert messages
    assert all(message.content.strip() for message in messages)


@pytest.mark.asyncio
async def test_post_session_result_merges_to_plan_revision_or_none() -> None:
    plan = _plan()
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysisResult,
                response=SessionAnalysisResult(
                    summary="Worked on sleep",
                    key_themes=("sleep",),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionResult,
                response=PostSessionResult(
                    session_summary="Worked on sleep",
                    session_briefing=SessionBriefing(
                        narrative_handoff="Sleep focus",
                        recommended_opening_focus="sleep",
                    ),
                    derived_profile_patch=DerivedProfilePatch(),
                    plan_patch=PlanPatch(),
                ),
            ),
        ]
    )
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=ModelPolicy(
            task=LLMTask.POST_SESSION_ANALYSIS,
            model="fake",
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
        update_policy=ModelPolicy(
            task=LLMTask.POST_SESSION_UPDATE,
            model="fake",
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
    )
    result = await processor.process(
        PostSessionInput(
            transcript=(),
            current_plan=plan,
            profile=Profile(name="Alex", primary_language="English"),
            selected_style=load_styles()["cbt"],
        )
    )
    assert merge_plan_revision(plan, result.plan_patch) is None

    changed = merge_plan_revision(
        plan,
        PlanPatch(current_progress="better sleep this week"),
    )
    assert isinstance(changed, NewPlanRevision)
