"""Transcript-grounded session analysis validation tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.phases.post_session.evidence_validation import validate_session_analysis
from jung.phases.post_session.models import (
    InterventionEvidence,
    PatientStatementCitation,
    SessionAnalysisResult,
)
from jung.phases.transcript import TranscriptTurn


def _turn(
    sequence: int,
    role: str,
    content: str,
) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=sequence,
        role=role,  # type: ignore[arg-type]
        content=content,
    )


def _analysis(**overrides: object) -> SessionAnalysisResult:
    values: dict[str, object] = {
        "summary": "Session summary",
        "key_themes": ("sleep",),
    }
    values.update(overrides)
    return SessionAnalysisResult(**values)  # type: ignore[arg-type]


def _conversational_transcript() -> tuple[TranscriptTurn, ...]:
    return (
        _turn(1, "user", "I slept badly."),
        _turn(2, "assistant", "What feels unclear about your sleep?"),
        _turn(3, "user", "I kept waking up."),
    )


def test_delivered_intervention_without_patient_fields_accepted() -> None:
    transcript = _conversational_transcript()
    result = validate_session_analysis(
        _analysis(
            intervention_evidence=(
                InterventionEvidence(
                    intervention_description="Exploratory questioning",
                    therapist_sequence=2,
                    therapist_quote="What feels unclear",
                ),
            )
        ),
        transcript,
    )
    assert result.intervention_evidence[0].status == "delivered"
    assert result.intervention_evidence[0].patient_quote is None


def test_responded_intervention_with_later_patient_quote_accepted() -> None:
    transcript = _conversational_transcript()
    result = validate_session_analysis(
        _analysis(
            intervention_evidence=(
                InterventionEvidence(
                    intervention_description="Exploratory questioning",
                    therapist_sequence=2,
                    therapist_quote="What feels unclear about your sleep?",
                    patient_sequence=3,
                    patient_quote="I kept waking up.",
                ),
            )
        ),
        transcript,
    )
    assert result.intervention_evidence[0].status == "responded"


def test_fabricated_evidence_without_assistant_turn_rejected() -> None:
    transcript = (_turn(1, "user", "I slept badly."),)
    with pytest.raises(ValueError, match="must be empty"):
        validate_session_analysis(
            _analysis(
                intervention_evidence=(
                    InterventionEvidence(
                        intervention_description="Exploratory questioning",
                        therapist_sequence=1,
                        therapist_quote="I slept badly",
                    ),
                )
            ),
            transcript,
        )


def test_therapist_sequence_wrong_role_rejected() -> None:
    transcript = _conversational_transcript()
    with pytest.raises(ValueError, match="must identify an assistant turn"):
        validate_session_analysis(
            _analysis(
                intervention_evidence=(
                    InterventionEvidence(
                        intervention_description="label",
                        therapist_sequence=1,
                        therapist_quote="I slept badly",
                    ),
                )
            ),
            transcript,
        )


def test_quote_not_in_cited_turn_rejected_even_if_present_elsewhere() -> None:
    transcript = (
        _turn(1, "assistant", "How are you sleeping?"),
        _turn(2, "user", "I slept badly."),
        _turn(3, "assistant", "Tell me more."),
    )
    with pytest.raises(ValueError, match="therapist_quote not found"):
        validate_session_analysis(
            _analysis(
                intervention_evidence=(
                    InterventionEvidence(
                        intervention_description="label",
                        therapist_sequence=3,
                        therapist_quote="How are you sleeping?",
                    ),
                )
            ),
            transcript,
        )


def test_patient_sequence_not_later_than_therapist_rejected() -> None:
    transcript = _conversational_transcript()
    with pytest.raises(ValueError, match="later user turn"):
        validate_session_analysis(
            _analysis(
                intervention_evidence=(
                    InterventionEvidence(
                        intervention_description="label",
                        therapist_sequence=2,
                        therapist_quote="What feels unclear",
                        patient_sequence=1,
                        patient_quote="I slept badly.",
                    ),
                )
            ),
            transcript,
        )


def test_empty_and_whitespace_quotes_rejected_by_model() -> None:
    with pytest.raises(ValidationError):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=1,
            therapist_quote="   ",
        )
    with pytest.raises(ValidationError):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=1,
            therapist_quote="ok",
            patient_sequence=2,
            patient_quote="",
        )
    with pytest.raises(ValidationError):
        PatientStatementCitation(patient_sequence=1, patient_quote="   ")


def test_patient_fields_must_be_together() -> None:
    with pytest.raises(ValidationError, match="both be present or both absent"):
        InterventionEvidence(
            intervention_description="label",
            therapist_sequence=1,
            therapist_quote="ok",
            patient_sequence=2,
        )


def test_intervention_duplicates_rejected_by_provenance() -> None:
    transcript = _conversational_transcript()
    with pytest.raises(ValueError, match="duplicate intervention"):
        validate_session_analysis(
            _analysis(
                intervention_evidence=(
                    InterventionEvidence(
                        intervention_description="label A",
                        therapist_sequence=2,
                        therapist_quote="What feels unclear",
                    ),
                    InterventionEvidence(
                        intervention_description="label B",
                        therapist_sequence=2,
                        therapist_quote="What feels unclear",
                    ),
                )
            ),
            transcript,
        )


def test_two_citations_from_same_patient_sequence_rejected() -> None:
    transcript = _conversational_transcript()
    with pytest.raises(ValueError, match="at most once"):
        validate_session_analysis(
            _analysis(
                patient_statements=(
                    PatientStatementCitation(
                        patient_sequence=1,
                        patient_quote="I slept badly",
                    ),
                    PatientStatementCitation(
                        patient_sequence=1,
                        patient_quote="slept badly",
                    ),
                )
            ),
            transcript,
        )


def test_same_quote_from_different_patient_sequences_accepted() -> None:
    transcript = (
        _turn(1, "user", "I don't know."),
        _turn(2, "assistant", "What feels unclear?"),
        _turn(3, "user", "I don't know."),
    )
    result = validate_session_analysis(
        _analysis(
            patient_statements=(
                PatientStatementCitation(
                    patient_sequence=1,
                    patient_quote="I don't know.",
                ),
                PatientStatementCitation(
                    patient_sequence=3,
                    patient_quote="I don't know.",
                ),
            )
        ),
        transcript,
    )
    assert len(result.patient_statements) == 2


def test_whitespace_variant_quotes_accepted_and_canonicalized() -> None:
    transcript = (_turn(1, "user", "I   slept\nbadly."),)
    result = validate_session_analysis(
        _analysis(
            patient_statements=(
                PatientStatementCitation(
                    patient_sequence=1,
                    patient_quote="I slept badly.",
                ),
            )
        ),
        transcript,
    )
    assert result.patient_statements[0].patient_quote == "I slept badly."


def test_provider_status_field_rejected_by_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        InterventionEvidence.model_validate(
            {
                "intervention_description": "label",
                "therapist_sequence": 1,
                "therapist_quote": "ok",
                "status": "responded",
            }
        )
