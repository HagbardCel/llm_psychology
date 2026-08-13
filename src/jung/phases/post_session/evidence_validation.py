"""Transcript-grounded semantic validation and resolution for session analysis."""

from __future__ import annotations

from jung.domain.session_artifacts import InterventionCitation, PatientTurnCitation
from jung.domain.text import normalize_content
from jung.phases.post_session.models import (
    InterventionEvidence,
    ResolvedSessionAnalysis,
    SessionAnalysis,
    SessionAnalysisResult,
)
from jung.phases.transcript import TranscriptTurn


def _validate_intervention_citation(
    item: InterventionCitation,
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
        raise ValueError("response-cited intervention requires a later user turn")


def _validate_patient_turn_citation(
    item: PatientTurnCitation,
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


def validate_session_analysis(
    result: SessionAnalysisResult,
    transcript: tuple[TranscriptTurn, ...],
    *,
    allowed_sequences: frozenset[int] | None = None,
) -> SessionAnalysisResult:
    """Validate sequence-only analysis citations.

    Raises ``ValueError`` for model-correctable semantic failures. Transcript
    structural defects are rejected by ``PostSessionInput`` before this runs.

    When ``allowed_sequences`` is provided, citations must refer only to turns
    that were visible in the analysis prompt projection.
    """
    turns_by_sequence = {turn.sequence: turn for turn in transcript}
    has_assistant = any(turn.role == "assistant" for turn in transcript)

    if not has_assistant and result.intervention_citations:
        raise ValueError(
            "intervention_citations must be empty when the transcript "
            "has no assistant turn"
        )

    def _assert_visible(sequence: int, *, label: str) -> None:
        if allowed_sequences is not None and sequence not in allowed_sequences:
            raise ValueError(
                f"{label} {sequence} was not visible in the analysis prompt"
            )

    seen_therapist_sequences: set[int] = set()
    for item in result.intervention_citations:
        _assert_visible(item.therapist_sequence, label="therapist_sequence")
        if item.patient_sequence is not None:
            _assert_visible(item.patient_sequence, label="patient_sequence")
        _validate_intervention_citation(item, turns_by_sequence)
        if item.therapist_sequence in seen_therapist_sequences:
            raise ValueError(
                "intervention citations must cite each therapist turn at most once"
            )
        seen_therapist_sequences.add(item.therapist_sequence)

    seen_patient_sequences: set[int] = set()
    for item in result.patient_turn_citations:
        _assert_visible(item.patient_sequence, label="patient_sequence")
        _validate_patient_turn_citation(item, turns_by_sequence)
        if item.patient_sequence in seen_patient_sequences:
            raise ValueError(
                "patient turn citations must cite each patient turn at most once"
            )
        seen_patient_sequences.add(item.patient_sequence)

    return result


def resolve_session_analysis(
    result: SessionAnalysis,
    transcript: tuple[TranscriptTurn, ...],
) -> ResolvedSessionAnalysis:
    """Resolve validated citations to ephemeral full-turn evidence."""
    turns_by_sequence = {turn.sequence: turn for turn in transcript}

    interventions: list[InterventionEvidence] = []
    for citation in result.intervention_citations:
        therapist = turns_by_sequence[citation.therapist_sequence]
        patient_content: str | None = None
        if citation.patient_sequence is not None:
            patient = turns_by_sequence[citation.patient_sequence]
            patient_content = normalize_content(patient.content)
        interventions.append(
            InterventionEvidence(
                intervention_description=citation.intervention_description,
                therapist_sequence=citation.therapist_sequence,
                therapist_content=normalize_content(therapist.content),
                patient_sequence=citation.patient_sequence,
                patient_content=patient_content,
            )
        )

    selected: list[TranscriptTurn] = []
    for citation in result.patient_turn_citations:
        selected.append(turns_by_sequence[citation.patient_sequence])

    interventions_sorted = tuple(
        sorted(
            interventions,
            key=lambda item: (
                item.therapist_sequence,
                item.patient_sequence or 0,
            ),
        )
    )
    selected_sorted = tuple(sorted(selected, key=lambda item: item.sequence))
    return ResolvedSessionAnalysis(
        analysis=result,
        intervention_evidence=interventions_sorted,
        selected_patient_turns=selected_sorted,
    )
