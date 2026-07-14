"""Neutral assessment JSON fixtures for store and application integration tests."""

from __future__ import annotations

from jung.domain.models import PlanContent
from jung.phases.assessment.models import AssessmentResult, StyleRecommendation
from jung.phases.assessment.validation import validate_and_normalize_assessment
from jung.styles import load_styles


def plan_content() -> PlanContent:
    return PlanContent(
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=["track sleep"],
    )


def _raw_assessment_result() -> AssessmentResult:
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
                initial_plan=plan_content(),
            )
            for style_id in ("jung", "cbt", "freud")
        ),
    )


def assessment_result_data() -> dict[str, object]:
    """Return valid assessment JSON in canonical persisted order (cbt, jung, freud)."""
    styles = load_styles()
    normalized = validate_and_normalize_assessment(
        _raw_assessment_result(),
        tuple(styles),
    )
    return normalized.model_dump(mode="json")
