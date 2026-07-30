"""Transcript-grounded semantic validation for session analysis."""

from __future__ import annotations

from jung.phases.post_session.models import (
    InterventionEvidence,
    PatientStatementCitation,
    SessionAnalysisResult,
)
from jung.phases.transcript import TranscriptTurn, normalize_transcript_content


def _contains_quote(turn: TranscriptTurn, quote: str) -> bool:
    return normalize_transcript_content(quote) in normalize_transcript_content(
        turn.content
    )


def _canonicalize_intervention(
    item: InterventionEvidence,
) -> InterventionEvidence:
    return InterventionEvidence(
        intervention_description=item.intervention_description,
        therapist_sequence=item.therapist_sequence,
        therapist_quote=normalize_transcript_content(item.therapist_quote),
        patient_sequence=item.patient_sequence,
        patient_quote=(
            None
            if item.patient_quote is None
            else normalize_transcript_content(item.patient_quote)
        ),
    )


def _canonicalize_patient_statement(
    item: PatientStatementCitation,
) -> PatientStatementCitation:
    return PatientStatementCitation(
        patient_sequence=item.patient_sequence,
        patient_quote=normalize_transcript_content(item.patient_quote),
    )


def _validate_intervention(
    item: InterventionEvidence,
    turns_by_sequence: dict[int, TranscriptTurn],
) -> None:
    therapist = turns_by_sequence.get(item.therapist_sequence)
    if therapist is None:
        raise ValueError(
            f"therapist_sequence {item.therapist_sequence} not found in transcript"
        )
    if therapist.role != "assistant":
        raise ValueError(
            f"therapist_sequence {item.therapist_sequence} "
            "must identify an assistant turn"
        )
    if not _contains_quote(therapist, item.therapist_quote):
        raise ValueError(
            f"therapist_quote not found in assistant turn {item.therapist_sequence}"
        )

    if item.patient_sequence is None:
        return

    patient = turns_by_sequence.get(item.patient_sequence)
    if patient is None:
        raise ValueError(
            f"patient_sequence {item.patient_sequence} not found in transcript"
        )
    if patient.role != "user":
        raise ValueError(
            f"patient_sequence {item.patient_sequence} must identify a user turn"
        )
    if item.patient_sequence <= item.therapist_sequence:
        raise ValueError(
            "responded intervention requires patient_quote from a later user turn"
        )
    assert item.patient_quote is not None
    if not _contains_quote(patient, item.patient_quote):
        raise ValueError(
            f"patient_quote not found in user turn {item.patient_sequence}"
        )


def _validate_patient_statement(
    item: PatientStatementCitation,
    turns_by_sequence: dict[int, TranscriptTurn],
) -> None:
    turn = turns_by_sequence.get(item.patient_sequence)
    if turn is None:
        raise ValueError(
            f"patient_sequence {item.patient_sequence} not found in transcript"
        )
    if turn.role != "user":
        raise ValueError(
            f"patient_sequence {item.patient_sequence} must identify a user turn"
        )
    if not _contains_quote(turn, item.patient_quote):
        raise ValueError(
            f"patient_quote not found in user turn {item.patient_sequence}"
        )


def validate_session_analysis(
    result: SessionAnalysisResult,
    transcript: tuple[TranscriptTurn, ...],
) -> SessionAnalysisResult:
    """Validate and canonicalize transcript-grounded analysis evidence.

    Raises ``ValueError`` for model-correctable semantic failures. Transcript
    structural defects are rejected by ``PostSessionInput`` before this runs.
    """
    turns_by_sequence = {turn.sequence: turn for turn in transcript}
    has_assistant = any(turn.role == "assistant" for turn in transcript)

    if not has_assistant and result.intervention_evidence:
        raise ValueError(
            "intervention_evidence must be empty when the transcript "
            "has no assistant turn"
        )

    seen_interventions: set[tuple[int, str, int | None, str]] = set()
    canonical_interventions: list[InterventionEvidence] = []
    for item in result.intervention_evidence:
        _validate_intervention(item, turns_by_sequence)
        canonical = _canonicalize_intervention(item)
        key = (
            canonical.therapist_sequence,
            canonical.therapist_quote,
            canonical.patient_sequence,
            canonical.patient_quote or "",
        )
        if key in seen_interventions:
            raise ValueError("duplicate intervention evidence citations")
        seen_interventions.add(key)
        canonical_interventions.append(canonical)

    seen_patient_sequences: set[int] = set()
    canonical_statements: list[PatientStatementCitation] = []
    for item in result.patient_statements:
        _validate_patient_statement(item, turns_by_sequence)
        if item.patient_sequence in seen_patient_sequences:
            raise ValueError(
                "patient statements must cite each patient turn at most once"
            )
        seen_patient_sequences.add(item.patient_sequence)
        canonical_statements.append(_canonicalize_patient_statement(item))

    return result.model_copy(
        update={
            "intervention_evidence": tuple(canonical_interventions),
            "patient_statements": tuple(canonical_statements),
        }
    )
