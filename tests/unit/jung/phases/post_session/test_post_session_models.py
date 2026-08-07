"""Post-session nested model strictness tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.grounding import GroundedPatientTurn
from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    InterventionCitation,
    InterventionEvidence,
    PatientTurnCitation,
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


def test_post_session_input_rejects_empty_and_whitespace_turn_content() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        _input(
            (
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=1,
                    role="user",
                    content="",
                ),
            )
        )
    with pytest.raises(ValidationError, match="non-empty"):
        _input(
            (
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=1,
                    role="user",
                    content="   \n\t  ",
                ),
            )
        )


def test_empty_transcript_is_valid_input() -> None:
    assert _input(()).transcript == ()


def test_provider_citation_schema_has_no_content_quote_or_status() -> None:
    schema = SessionAnalysisResult.model_json_schema(mode="validation")
    defs = schema.get("$defs", {})
    intervention = defs.get("InterventionCitation", {})
    properties = intervention.get("properties", {})
    assert "status" not in properties
    assert "therapist_content" not in properties
    assert "patient_content" not in properties
    assert "therapist_quote" not in properties
    assert "patient_quote" not in properties
    assert set(properties) == {
        "intervention_description",
        "therapist_sequence",
        "patient_sequence",
    }

    patient = defs.get("PatientTurnCitation", {})
    patient_properties = patient.get("properties", {})
    assert set(patient_properties) == {"patient_sequence"}
    assert "content" not in patient_properties
    assert "quote" not in patient_properties


def test_status_present_in_intervention_evidence_validation_schema() -> None:
    schema = InterventionEvidence.model_json_schema(mode="validation")
    properties = schema.get("properties", {})
    assert "status" in properties


def test_status_is_response_cited_not_responded() -> None:
    evidence = InterventionEvidence(
        intervention_description="Exploratory questioning",
        therapist_sequence=2,
        therapist_content="What feels unclear?",
        patient_sequence=3,
        patient_content="I kept waking up.",
    )
    dumped = evidence.model_dump(mode="json")
    assert dumped["status"] == "response_cited"
    assert dumped["status"] != "responded"
    delivered = InterventionEvidence(
        intervention_description="Exploratory questioning",
        therapist_sequence=2,
        therapist_content="What feels unclear?",
    )
    assert delivered.model_dump(mode="json")["status"] == "delivered"


def test_intervention_evidence_pair_invariants() -> None:
    with pytest.raises(ValidationError, match="both be present or both absent"):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=1,
            therapist_content="ok",
            patient_sequence=2,
        )
    with pytest.raises(ValidationError, match="both be present or both absent"):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=1,
            therapist_content="ok",
            patient_content="response",
        )


def test_intervention_evidence_chronology_rejects_same_or_earlier_patient() -> None:
    with pytest.raises(ValidationError, match="must follow therapist_sequence"):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=2,
            therapist_content="question",
            patient_sequence=2,
            patient_content="same turn",
        )
    with pytest.raises(ValidationError, match="must follow therapist_sequence"):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=3,
            therapist_content="question",
            patient_sequence=1,
            patient_content="earlier",
        )


def test_whitespace_only_therapist_and_grounded_content_rejected() -> None:
    with pytest.raises(ValidationError):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=1,
            therapist_content="   ",
        )
    with pytest.raises(ValidationError):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=1,
            therapist_content="ok",
            patient_sequence=2,
            patient_content="",
        )
    with pytest.raises(ValidationError):
        GroundedPatientTurn(
            source_message_id=uuid4(),
            source_sequence=1,
            content="   ",
        )


def test_intervention_evidence_normalizes_content() -> None:
    evidence = InterventionEvidence(
        intervention_description="label",
        therapist_sequence=1,
        therapist_content="  hello\nworld  ",
        patient_sequence=2,
        patient_content="  patient\tresponse  ",
    )
    assert evidence.therapist_content == "hello world"
    assert evidence.patient_content == "patient response"


@pytest.mark.parametrize(
    ("payload", "model"),
    [
        (
            {
                "intervention_description": "breathing",
                "therapist_sequence": 1,
                "unexpected": "field",
            },
            InterventionCitation,
        ),
        (
            {
                "intervention_description": "   ",
                "therapist_sequence": 1,
            },
            InterventionCitation,
        ),
        (
            {"patient_sequence": 0},
            PatientTurnCitation,
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


def test_session_analysis_caps_citation_lists() -> None:
    with pytest.raises(ValidationError):
        SessionAnalysisResult(
            summary="summary",
            key_themes=("theme",),
            intervention_citations=tuple(
                InterventionCitation(
                    intervention_description=f"i{i}",
                    therapist_sequence=i + 1,
                )
                for i in range(21)
            ),
        )
    with pytest.raises(ValidationError):
        SessionAnalysisResult(
            summary="summary",
            key_themes=("theme",),
            patient_turn_citations=tuple(
                PatientTurnCitation(patient_sequence=i + 1) for i in range(21)
            ),
        )
