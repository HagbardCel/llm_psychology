"""Assessment processor tests."""

from __future__ import annotations

import pytest

from jung.domain.models import PlanContent, Profile
from jung.llm.errors import InvalidLLMOutput
from jung.llm.fake import FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.phases.assessment.models import (
    AssessmentInput,
    AssessmentResult,
    StyleRecommendation,
)
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.intake.models import IntakeRecord
from jung.styles import load_styles


def _plan() -> PlanContent:
    return PlanContent(
        focus="anxiety",
        themes=("worry",),
        goals=("sleep better",),
        current_progress="baseline",
        planned_interventions=("grounding",),
        revision_recommendations=(),
    )


def _recommendation(style_id: str, score: float) -> StyleRecommendation:
    return StyleRecommendation(
        style_id=style_id,
        score=score,
        rationale=f"Good fit for {style_id}",
        key_topics=("anxiety",),
        initial_plan=_plan(),
    )


@pytest.mark.asyncio
async def test_assessment_processor_makes_one_structured_call() -> None:
    styles = tuple(load_styles().values())
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=AssessmentResult(
                    formulation="Patient presents with anxiety.",
                    presenting_concerns=("anxiety",),
                    strengths_and_resources=("supportive partner",),
                    style_recommendations=(
                        _recommendation("jung", 0.8),
                        _recommendation("cbt", 0.9),
                        _recommendation("freud", 0.6),
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
            intake_record=IntakeRecord(),
            transcript=(),
            profile=Profile(name="Alex", primary_language="English"),
            available_styles=styles,
        )
    )
    assert len(result.style_recommendations) == 3
    assert result.style_recommendations[0].style_id == "cbt"
    gateway.assert_exhausted()


def test_assessment_result_revalidates() -> None:
    raw = AssessmentResult(
        formulation="Patient presents with anxiety.",
        presenting_concerns=("anxiety",),
        strengths_and_resources=("supportive partner",),
        style_recommendations=(_recommendation("cbt", 0.9),),
    )
    restored = AssessmentResult.model_validate_json(raw.model_dump_json())
    assert restored == raw


@pytest.mark.asyncio
async def test_assessment_processor_rejects_missing_style_coverage() -> None:
    styles = tuple(load_styles().values())
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=AssessmentResult(
                    formulation="Patient presents with anxiety.",
                    presenting_concerns=("anxiety",),
                    strengths_and_resources=("supportive partner",),
                    style_recommendations=(_recommendation("cbt", 0.9),),
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
    with pytest.raises(InvalidLLMOutput):
        await processor.assess(
            AssessmentInput(
                intake_record=IntakeRecord(),
                transcript=(),
                profile=Profile(name="Alex", primary_language="English"),
                available_styles=styles,
            )
        )
    gateway.assert_exhausted()
