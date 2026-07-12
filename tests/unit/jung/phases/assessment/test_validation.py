"""Assessment semantic validation tests."""

from __future__ import annotations

import pytest

from jung.domain.models import PlanContent
from jung.phases.assessment.models import AssessmentResult, StyleRecommendation
from jung.phases.assessment.validation import (
    validate_and_normalize_assessment,
    validate_exact_coverage,
)


def _plan() -> PlanContent:
    return PlanContent(
        focus="anxiety",
        themes=["worry"],
        goals=["sleep better"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
    )


def _recommendation(style_id: str, score: float) -> StyleRecommendation:
    return StyleRecommendation(
        style_id=style_id,
        score=score,
        rationale=f"fit for {style_id}",
        key_topics=["anxiety"],
        initial_plan=_plan(),
    )


def test_missing_style_raises() -> None:
    result = AssessmentResult(
        formulation="anxiety",
        presenting_concerns=["anxiety"],
        strengths_and_resources=["partner"],
        style_recommendations=[_recommendation("cbt", 0.9)],
    )
    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_exact_coverage(result, ("cbt", "jung", "freud"))


def test_out_of_order_complete_coverage_is_normalized() -> None:
    catalog = ("jung", "cbt", "freud")
    result = AssessmentResult(
        formulation="anxiety",
        presenting_concerns=["anxiety"],
        strengths_and_resources=["partner"],
        style_recommendations=(
            _recommendation("freud", 0.6),
            _recommendation("jung", 0.8),
            _recommendation("cbt", 0.9),
        ),
    )
    normalized = validate_and_normalize_assessment(result, catalog)
    assert [item.style_id for item in normalized.style_recommendations] == [
        "cbt",
        "jung",
        "freud",
    ]
