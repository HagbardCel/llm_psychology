"""Assessment nested PlanContent contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jung.phases.assessment.models import StyleRecommendation


def test_style_recommendation_rejects_unknown_initial_plan_field() -> None:
    with pytest.raises(ValidationError):
        StyleRecommendation.model_validate(
            {
                "style_id": "cbt",
                "score": 0.9,
                "rationale": "fit",
                "key_topics": ("anxiety",),
                "initial_plan": {
                    "focus": "anxiety",
                    "themes": [],
                    "goals": ["sleep"],
                    "current_progress": "baseline",
                    "planned_interventions": ["grounding"],
                    "revision_recommendations": [],
                    "unknown": "field",
                },
            }
        )
