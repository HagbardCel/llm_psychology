"""Transcript-grounded session analysis validation and resolution tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.domain.session_artifacts import (
    InterventionCitation,
    PatientTurnCitation,
    SessionAnalysis,
)
from jung.phases.post_session.evidence_validation import (
    resolve_session_analysis,
    validate_session_analysis,
)
from jung.phases.transcript import TranscriptTurn


def _turn(
    sequence: int,
    role: str,
    content: str,
    *,
    message_id=None,
) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=message_id or uuid4(),
        sequence=sequence,
        role=role,  # type: ignore[arg-type]
        content=content,
    )


def _analysis(**overrides: object) -> SessionAnalysis:
    values: dict[str, object] = {
        "summary": "Session summary",
        "key_themes": ("sleep",),
    }
    values.update(overrides)
    return SessionAnalysis(**values)  # type: ignore[arg-type]


def _conversational_transcript() -> tuple[TranscriptTurn, ...]:
    return (
        _turn(1, "user", "I slept badly."),
        _turn(2, "assistant", "What feels unclear about your sleep?"),
        _turn(3, "user", "I kept waking up."),
    )


def test_delivered_intervention_citation_accepted() -> None:
    transcript = _conversational_transcript()
    result = validate_session_analysis(
        _analysis(
            intervention_citations=(
                InterventionCitation(
                    intervention_description="Exploratory questioning",
                    therapist_sequence=2,
                ),
            )
        ),
        transcript,
    )
    resolved = resolve_session_analysis(result, transcript)
    evidence = resolved.intervention_evidence[0]
    assert evidence.patient_sequence is None
    assert evidence.patient_content is None
    assert "status" not in evidence.model_dump(mode="json")
    assert evidence.therapist_content == "What feels unclear about your sleep?"


def test_response_cited_intervention_with_later_patient_accepted() -> None:
    transcript = _conversational_transcript()
    result = validate_session_analysis(
        _analysis(
            intervention_citations=(
                InterventionCitation(
                    intervention_description="Exploratory questioning",
                    therapist_sequence=2,
                    patient_sequence=3,
                ),
            )
        ),
        transcript,
    )
    resolved = resolve_session_analysis(result, transcript)
    evidence = resolved.intervention_evidence[0]
    assert evidence.patient_sequence == 3
    assert evidence.patient_content == "I kept waking up."


def test_fabricated_evidence_without_assistant_turn_rejected() -> None:
    transcript = (_turn(1, "user", "I slept badly."),)
    with pytest.raises(ValueError, match="must be empty"):
        validate_session_analysis(
            _analysis(
                intervention_citations=(
                    InterventionCitation(
                        intervention_description="Exploratory questioning",
                        therapist_sequence=1,
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
                intervention_citations=(
                    InterventionCitation(
                        intervention_description="label",
                        therapist_sequence=1,
                    ),
                )
            ),
            transcript,
        )


def test_therapist_sequence_missing_rejected() -> None:
    transcript = _conversational_transcript()
    with pytest.raises(ValueError, match="not found in transcript"):
        validate_session_analysis(
            _analysis(
                intervention_citations=(
                    InterventionCitation(
                        intervention_description="label",
                        therapist_sequence=99,
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
                intervention_citations=(
                    InterventionCitation(
                        intervention_description="label",
                        therapist_sequence=2,
                        patient_sequence=1,
                    ),
                )
            ),
            transcript,
        )


def test_patient_sequence_wrong_role_rejected() -> None:
    transcript = _conversational_transcript()
    with pytest.raises(ValueError, match="must identify a user turn"):
        validate_session_analysis(
            _analysis(
                intervention_citations=(
                    InterventionCitation(
                        intervention_description="label",
                        therapist_sequence=2,
                        patient_sequence=2,
                    ),
                )
            ),
            transcript,
        )


def test_intervention_duplicates_rejected() -> None:
    transcript = _conversational_transcript()
    with pytest.raises(ValueError, match="at most once"):
        validate_session_analysis(
            _analysis(
                intervention_citations=(
                    InterventionCitation(
                        intervention_description="label A",
                        therapist_sequence=2,
                    ),
                    InterventionCitation(
                        intervention_description="label B",
                        therapist_sequence=2,
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
                patient_turn_citations=(
                    PatientTurnCitation(patient_sequence=1),
                    PatientTurnCitation(patient_sequence=1),
                )
            ),
            transcript,
        )


def test_same_content_from_different_patient_sequences_accepted() -> None:
    transcript = (
        _turn(1, "user", "I don't know."),
        _turn(2, "assistant", "What feels unclear?"),
        _turn(3, "user", "I don't know."),
    )
    result = validate_session_analysis(
        _analysis(
            patient_turn_citations=(
                PatientTurnCitation(patient_sequence=1),
                PatientTurnCitation(patient_sequence=3),
            )
        ),
        transcript,
    )
    resolved = resolve_session_analysis(result, transcript)
    assert len(resolved.selected_patient_turns) == 2
    assert all(
        turn.content == "I don't know." for turn in resolved.selected_patient_turns
    )


def test_resolve_attaches_message_id_and_normalizes_content() -> None:
    message_id = uuid4()
    transcript = (_turn(1, "user", "I   slept\nbadly.", message_id=message_id),)
    result = validate_session_analysis(
        _analysis(patient_turn_citations=(PatientTurnCitation(patient_sequence=1),)),
        transcript,
    )
    resolved = resolve_session_analysis(result, transcript)
    selected = resolved.selected_patient_turns[0]
    assert selected.message_id == message_id
    assert selected.sequence == 1
    assert selected.content == "I   slept\nbadly."


def test_resolve_sorts_evidence_by_sequence() -> None:
    transcript = (
        _turn(1, "user", "First."),
        _turn(2, "assistant", "Question A."),
        _turn(3, "user", "Answer A."),
        _turn(4, "assistant", "Question B."),
        _turn(5, "user", "Answer B."),
    )
    result = validate_session_analysis(
        _analysis(
            intervention_citations=(
                InterventionCitation(
                    intervention_description="B",
                    therapist_sequence=4,
                    patient_sequence=5,
                ),
                InterventionCitation(
                    intervention_description="A",
                    therapist_sequence=2,
                    patient_sequence=3,
                ),
            ),
            patient_turn_citations=(
                PatientTurnCitation(patient_sequence=5),
                PatientTurnCitation(patient_sequence=1),
            ),
        ),
        transcript,
    )
    resolved = resolve_session_analysis(result, transcript)
    assert [item.therapist_sequence for item in resolved.intervention_evidence] == [
        2,
        4,
    ]
    assert [item.sequence for item in resolved.selected_patient_turns] == [1, 5]


@pytest.mark.parametrize(
    "content",
    [
        "I do not think I want to die.",
        "I am not planning to hurt myself.",
        "It is not true that everyone hates me.",
    ],
)
def test_sequence_resolution_preserves_negation_context(content: str) -> None:
    message_id = uuid4()
    transcript = (_turn(1, "user", content, message_id=message_id),)
    result = validate_session_analysis(
        _analysis(patient_turn_citations=(PatientTurnCitation(patient_sequence=1),)),
        transcript,
    )
    resolved = resolve_session_analysis(result, transcript)
    selected = resolved.selected_patient_turns[0]
    assert selected.content == content
    assert selected.content != "I want to die."
    assert selected.content != "want to die"
    assert selected.message_id == message_id
