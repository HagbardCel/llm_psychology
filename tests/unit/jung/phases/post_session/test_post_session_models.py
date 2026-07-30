"""Post-session nested model strictness tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    PostSessionResult,
    SessionAnalysisResult,
    SessionBriefing,
)
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles


def _plan() -> Plan:
    now = datetime.now(UTC)
    return Plan(
        id=uuid4(),
        version=1,
        selected_style="cbt",
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
        created_at=now,
    )


def _input(
    transcript: tuple[TranscriptTurn, ...] = (),
) -> PostSessionInput:
    return PostSessionInput(
        transcript=transcript,
        current_plan=_plan(),
        profile=Profile(name="Alex", primary_language="English"),
        selected_style=load_styles()["cbt"],
    )


def test_post_session_input_rejects_mismatched_style() -> None:
    with pytest.raises(ValidationError, match="selected_style must match"):
        PostSessionInput(
            transcript=(
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=1,
                    role="user",
                    content="I slept badly.",
                ),
            ),
            current_plan=_plan(),
            profile=Profile(name="Alex", primary_language="English"),
            selected_style=load_styles()["jung"],
        )


def test_post_session_input_rejects_duplicate_sequences() -> None:
    message_a = uuid4()
    message_b = uuid4()
    with pytest.raises(ValidationError, match="strictly increasing"):
        _input(
            (
                TranscriptTurn(
                    message_id=message_a,
                    sequence=1,
                    role="user",
                    content="first",
                ),
                TranscriptTurn(
                    message_id=message_b,
                    sequence=1,
                    role="assistant",
                    content="second",
                ),
            )
        )


def test_post_session_input_rejects_unordered_sequences() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        _input(
            (
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=2,
                    role="user",
                    content="first",
                ),
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=1,
                    role="assistant",
                    content="second",
                ),
            )
        )


def test_post_session_input_rejects_duplicate_message_ids() -> None:
    shared = uuid4()
    with pytest.raises(ValidationError, match="message IDs must be unique"):
        _input(
            (
                TranscriptTurn(
                    message_id=shared,
                    sequence=1,
                    role="user",
                    content="first",
                ),
                TranscriptTurn(
                    message_id=shared,
                    sequence=2,
                    role="assistant",
                    content="second",
                ),
            )
        )


def test_empty_transcript_is_valid_input() -> None:
    assert _input(()).transcript == ()


def test_computed_status_absent_from_validation_schema() -> None:
    schema = SessionAnalysisResult.model_json_schema(mode="validation")
    defs = schema.get("$defs", {})
    intervention = defs.get("InterventionEvidence", {})
    properties = intervention.get("properties", {})
    assert "status" not in properties


def test_computed_status_present_in_serialization() -> None:
    evidence = InterventionEvidence(
        intervention_description="Exploratory questioning",
        therapist_sequence=2,
        therapist_quote="What feels unclear?",
        patient_sequence=3,
        patient_quote="I kept waking up.",
    )
    dumped = evidence.model_dump(mode="json")
    assert dumped["status"] == "responded"
    delivered = InterventionEvidence(
        intervention_description="Exploratory questioning",
        therapist_sequence=2,
        therapist_quote="What feels unclear?",
    )
    assert delivered.model_dump(mode="json")["status"] == "delivered"


@pytest.mark.parametrize(
    ("payload", "model"),
    [
        (
            {
                "intervention_description": "breathing",
                "therapist_sequence": 1,
                "therapist_quote": "try this",
                "unexpected": "field",
            },
            InterventionEvidence,
        ),
        (
            {
                "intervention_description": "   ",
                "therapist_sequence": 1,
                "therapist_quote": "try this",
            },
            InterventionEvidence,
        ),
        (
            {
                "narrative_handoff": "   ",
                "recommended_opening_focus": "sleep",
            },
            SessionBriefing,
        ),
        (
            {
                "narrative_handoff": "handoff",
                "recommended_opening_focus": "   ",
            },
            SessionBriefing,
        ),
    ],
)
def test_post_session_models_reject_invalid_fields(
    payload: dict[str, object],
    model: type[object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)  # type: ignore[attr-defined]


def test_post_session_result_rejects_empty_summary() -> None:
    with pytest.raises(ValidationError):
        PostSessionResult.model_validate(
            {
                "session_summary": "   ",
                "session_briefing": {
                    "narrative_handoff": "handoff",
                    "recommended_opening_focus": "sleep",
                },
                "derived_profile_patch": {},
                "plan_patch": {},
            }
        )
