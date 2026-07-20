"""Unit tests for jung.application module-level helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.application import (
    _classify_worker_error,
    _response_has_content,
    _select_style_recommendation,
    _validate_snapshot_invariants,
)
from jung.domain.errors import InvalidCommand, InvariantViolation
from jung.domain.models import (
    AppSnapshot,
    CommandName,
    Plan,
    PlanContent,
    Session,
    SessionKind,
    Stage,
)
from jung.llm.errors import (
    InvalidLLMOutput,
    LLMProtocolError,
    LLMTimeout,
    LLMUnavailable,
)
from jung.phases.assessment.models import AssessmentResult, StyleRecommendation
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


def _recommendation(style_id: str) -> StyleRecommendation:
    return StyleRecommendation(
        style_id=style_id,
        score=0.9,
        rationale=f"fit for {style_id}",
        key_topics=("anxiety",),
        initial_plan=_plan_content(),
    )


def test_response_has_content() -> None:
    assert _response_has_content("hello") is True
    assert _response_has_content("  \n  ") is False


def test_select_style_recommendation_matches_style() -> None:
    result = AssessmentResult(
        formulation="Anxiety presentation",
        presenting_concerns=("anxiety",),
        strengths_and_resources=("support",),
        style_recommendations=(_recommendation("cbt"), _recommendation("jung")),
    )
    selected = _select_style_recommendation(result, "cbt")
    assert selected.style_id == "cbt"


def test_select_style_recommendation_rejects_unknown_style() -> None:
    result = AssessmentResult(
        formulation="Anxiety presentation",
        presenting_concerns=("anxiety",),
        strengths_and_resources=("support",),
        style_recommendations=(_recommendation("cbt"),),
    )
    with pytest.raises(InvalidCommand, match="not in assessment recommendations"):
        _select_style_recommendation(result, "freud")


def test_validate_snapshot_invariants_rejects_setup_with_session() -> None:
    now = datetime.now(UTC)
    session = Session(
        id=uuid4(),
        kind=SessionKind.INTAKE,
        started_at=now,
    )
    snapshot = AppSnapshot(
        revision=1,
        stage=Stage.SETUP,
        profile_complete=True,
        active_session=session,
        available_commands=frozenset(),
    )
    with pytest.raises(
        InvariantViolation, match="SETUP must not have an active session"
    ):
        _validate_snapshot_invariants(snapshot, None, load_styles())


def test_validate_snapshot_invariants_rejects_unknown_plan_style() -> None:
    now = datetime.now(UTC)
    plan = Plan(
        id=uuid4(),
        version=1,
        selected_style="unknown-style",
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
        created_at=now,
    )
    snapshot = AppSnapshot(
        revision=1,
        stage=Stage.READY,
        profile_complete=True,
        selected_style="unknown-style",
        available_commands=frozenset({CommandName.START_SESSION}),
    )
    with pytest.raises(InvariantViolation, match="unknown style"):
        _validate_snapshot_invariants(snapshot, plan, load_styles())


SECRET_MARKER = "secret-marker https://api.example.com sk-test-key"


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_message", "expected_retryable"),
    [
        (
            LLMUnavailable(SECRET_MARKER),
            "llm_unavailable",
            "The language model is currently unavailable.",
            True,
        ),
        (
            LLMTimeout(SECRET_MARKER),
            "llm_timeout",
            "The language model request timed out.",
            True,
        ),
        (
            InvalidLLMOutput(SECRET_MARKER),
            "invalid_llm_output",
            "The language model returned an invalid response.",
            False,
        ),
        (
            LLMProtocolError(SECRET_MARKER),
            "internal_error",
            "An unexpected error occurred.",
            False,
        ),
    ],
)
def test_classify_worker_error_maps_llm_errors_to_public_messages(
    error: Exception,
    expected_code: str,
    expected_message: str,
    expected_retryable: bool,
) -> None:
    code, message, retryable = _classify_worker_error(error)
    assert code == expected_code
    assert message == expected_message
    assert retryable is expected_retryable
    assert SECRET_MARKER not in message


def test_classify_worker_error_maps_unexpected_errors() -> None:
    code, message, retryable = _classify_worker_error(RuntimeError("boom"))
    assert code == "internal_error"
    assert message == "An unexpected error occurred."
    assert retryable is False
    assert "boom" not in message
