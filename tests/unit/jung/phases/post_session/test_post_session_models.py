"""Post-session model semantics: chronology, evidence pairs, status, completeness."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    InterventionCitation,
    InterventionEvidence,
    PatientTurnCitation,
    PostSessionInput,
    SessionAnalysisResult,
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
