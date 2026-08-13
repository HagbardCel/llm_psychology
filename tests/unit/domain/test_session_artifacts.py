"""Tests for durable session briefing and session review artifacts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jung.domain.session_artifacts import (
    InterventionCitation,
    PatientTurnCitation,
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
    SessionReviewGeneration,
)


def _briefing(**overrides: object) -> SessionBriefing:
    values: dict[str, object] = {
        "narrative_handoff": "Continue with sleep and readiness.",
        "recommended_opening_focus": "Ask about readiness.",
    }
    values.update(overrides)
    return SessionBriefing(**values)  # type: ignore[arg-type]


def _analysis(**overrides: object) -> SessionAnalysis:
    values: dict[str, object] = {
        "summary": "Patient explored sleep difficulties.",
        "key_themes": ("sleep",),
    }
    values.update(overrides)
    return SessionAnalysis(**values)  # type: ignore[arg-type]


def _review(**overrides: object) -> SessionReview:
    values: dict[str, object] = {
        "analysis": _analysis(),
        "briefing": _briefing(),
        "plan_recommendation": PlanPatch(),
        "generation": None,
    }
    values.update(overrides)
    return SessionReview(**values)  # type: ignore[arg-type]


def test_session_briefing_round_trips_through_json_dump() -> None:
    briefing = _briefing(
        continuity_points=("sleep routine",),
        unresolved_issues=("readiness",),
        things_to_avoid=("pressure",),
        emotional_context=("fatigue",),
    )
    restored = SessionBriefing.model_validate(briefing.model_dump(mode="json"))
    assert restored == briefing
    assert "intervention_evidence" not in briefing.model_dump(mode="json")


def test_session_briefing_rejects_empty_required_text() -> None:
    with pytest.raises(ValidationError):
        _briefing(narrative_handoff="   ")
    with pytest.raises(ValidationError):
        _briefing(recommended_opening_focus="")


def test_session_briefing_has_no_intervention_evidence_field() -> None:
    assert "intervention_evidence" not in SessionBriefing.model_fields
    with pytest.raises(ValidationError):
        SessionBriefing.model_validate(
            {
                "narrative_handoff": "handoff",
                "recommended_opening_focus": "focus",
                "intervention_evidence": [],
            }
        )


def test_session_review_round_trips_through_json_dump() -> None:
    review = _review(
        analysis=_analysis(
            intervention_citations=(
                InterventionCitation(
                    intervention_description="Exploratory questioning",
                    therapist_sequence=2,
                    patient_sequence=3,
                ),
            ),
            patient_turn_citations=(PatientTurnCitation(patient_sequence=1),),
        ),
        plan_recommendation=PlanPatch(current_progress="improved"),
        generation=SessionReviewGeneration(
            analysis_model="analysis-model",
            analysis_prompt_version="post-session-v6",
            update_model="update-model",
            update_prompt_version="post-session-v6",
        ),
    )
    restored = SessionReview.model_validate(review.model_dump(mode="json"))
    assert restored == review
    assert restored.generation is not None
    assert restored.generation.analysis_model == "analysis-model"


def test_session_review_allows_null_generation() -> None:
    review = _review(generation=None)
    assert review.generation is None
    dumped = review.model_dump(mode="json")
    assert dumped["generation"] is None


def test_session_review_generation_rejects_blank_provenance() -> None:
    with pytest.raises(ValidationError):
        SessionReviewGeneration(
            analysis_model=" ",
            analysis_prompt_version="post-session-v6",
            update_model="update-model",
            update_prompt_version="post-session-v6",
        )


def test_session_analysis_rejects_empty_summary() -> None:
    with pytest.raises(ValidationError):
        _analysis(summary="\n\t")
