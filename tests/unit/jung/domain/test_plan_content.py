"""Unit tests for shared PlanContent contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jung.domain.models import PlanContent


def test_plan_content_rejects_non_string_list_items() -> None:
    with pytest.raises(ValidationError):
        PlanContent(
            focus="anxiety",
            themes=[],
            goals=[123],  # type: ignore[list-item]
            current_progress="baseline",
            planned_interventions=["grounding"],
            revision_recommendations=[],
        )


def test_plan_content_rejects_blank_list_items() -> None:
    with pytest.raises(ValidationError):
        PlanContent(
            focus="anxiety",
            themes=["   "],
            goals=["sleep"],
            current_progress="baseline",
            planned_interventions=["grounding"],
            revision_recommendations=[],
        )


def test_plan_content_normalizes_whitespace_and_dedupes() -> None:
    content = PlanContent(
        focus="anxiety",
        themes=[],
        goals=["sleep", " sleep "],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
    )
    assert content.goals == ["sleep"]
