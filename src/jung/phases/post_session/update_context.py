"""Deterministic post-session update context assembly."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from jung.domain.text import normalize_content
from jung.llm.prompt_context import (
    render_context_user_message,
    rendered_context_user_message_length,
)
from jung.phases.context_bounds import bounded_text
from jung.phases.context_projection import (
    ProjectionBudgetError,
    compact_summary,
    enrich_plan_projection,
    enrich_session_briefing_projection,
    minimal_plan_projection,
    minimal_session_briefing_projection,
    pack_grounded_patient_messages,
    pack_prior_session_reviews,
)
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    ResolvedSessionAnalysis,
)
from jung.phases.transcript import TranscriptTurn

_UPDATE_USER_MESSAGE_LIMIT = 8_000
_UPDATE_TASK = "Produce the next-session briefing draft and plan patch."
_SUMMARY_LIST_ITEM_CHARS = 200

_FROZEN_ANALYSIS_KEYS = frozenset(
    {
        "summary",
        "intervention_evidence",
        "intervention_evidence_omitted",
        "patient_turns",
        "patient_turns_omitted",
    }
)

_INTERPRETIVE_LIST_FIELDS = (
    "key_themes",
    "dominant_affects",
    "important_moments",
    "patient_insights",
    "progress_indicators",
    "unresolved_topics",
    "safety_or_boundary_notes",
)


@dataclass(frozen=True, slots=True)
class AnalysisEvidenceAtom:
    kind: Literal["intervention", "patient_turn"]
    sequence: int
    payload: InterventionEvidence | TranscriptTurn


@dataclass(frozen=True, slots=True)
class PostSessionUpdateContext:
    """Pure projection of resolved analysis for the update call."""

    summary: str
    key_themes: tuple[str, ...]
    dominant_affects: tuple[str, ...]
    important_moments: tuple[str, ...]
    patient_insights: tuple[str, ...]
    progress_indicators: tuple[str, ...]
    unresolved_topics: tuple[str, ...]
    intervention_evidence: tuple[InterventionEvidence, ...]
    selected_patient_turns: tuple[TranscriptTurn, ...]
    safety_or_boundary_notes: tuple[str, ...]

    @classmethod
    def from_resolved(
        cls, resolved: ResolvedSessionAnalysis
    ) -> PostSessionUpdateContext:
        analysis = resolved.analysis
        return cls(
            summary=analysis.summary,
            key_themes=analysis.key_themes,
            dominant_affects=analysis.dominant_affects,
            important_moments=analysis.important_moments,
            patient_insights=analysis.patient_insights,
            progress_indicators=analysis.progress_indicators,
            unresolved_topics=analysis.unresolved_topics,
            intervention_evidence=resolved.intervention_evidence,
            selected_patient_turns=resolved.selected_patient_turns,
            safety_or_boundary_notes=analysis.safety_or_boundary_notes,
        )


def intervention_payload(item: InterventionEvidence) -> dict[str, object]:
    return {
        "intervention_description": item.intervention_description,
        "status": (
            "response_cited" if item.patient_sequence is not None else "delivered"
        ),
        "therapist_sequence": item.therapist_sequence,
        "therapist_content": item.therapist_content,
        "patient_sequence": item.patient_sequence,
        "patient_content": item.patient_content,
    }


def current_patient_turn_payload(item: TranscriptTurn) -> dict[str, object]:
    """Current-session evidence retains sequence (same-prompt transcript)."""
    return {
        "source_sequence": item.sequence,
        "content": normalize_content(item.content),
    }


def build_evidence_atoms(
    interventions: Sequence[InterventionEvidence],
    patient_turns: Sequence[TranscriptTurn],
) -> tuple[AnalysisEvidenceAtom, ...]:
    atoms = [
        *(
            AnalysisEvidenceAtom(
                kind="intervention",
                sequence=item.therapist_sequence,
                payload=item,
            )
            for item in interventions
        ),
        *(
            AnalysisEvidenceAtom(
                kind="patient_turn",
                sequence=item.sequence,
                payload=item,
            )
            for item in patient_turns
        ),
    ]
    return tuple(
        sorted(
            atoms,
            key=lambda item: (
                item.sequence,
                0 if item.kind == "intervention" else 1,
            ),
        )
    )


def pack_evidence_atoms(
    atoms: Sequence[AnalysisEvidenceAtom],
    *,
    total_interventions: int,
    total_patient_turns: int,
    interpretive: Mapping[str, object],
    fits: Callable[[dict[str, object]], bool],
) -> dict[str, object]:
    """Pack evidence newest-first under a shared chronological budget."""

    def build_document(
        selected: Sequence[AnalysisEvidenceAtom],
    ) -> dict[str, object]:
        selected_interventions = [
            item.payload for item in selected if item.kind == "intervention"
        ]
        selected_turns = [
            item.payload for item in selected if item.kind == "patient_turn"
        ]
        return {
            **dict(interpretive),
            "intervention_evidence": [
                intervention_payload(item)  # type: ignore[arg-type]
                for item in selected_interventions
            ],
            "intervention_evidence_omitted": (
                total_interventions - len(selected_interventions)
            ),
            "patient_turns": [
                current_patient_turn_payload(item)  # type: ignore[arg-type]
                for item in selected_turns
            ],
            "patient_turns_omitted": total_patient_turns - len(selected_turns),
        }

    baseline = build_document(())
    if not fits(baseline):
        raise ProjectionBudgetError("minimal analysis evidence projection does not fit")

    selected_reverse: list[AnalysisEvidenceAtom] = []
    for atom in reversed(atoms):
        candidate = tuple(reversed([*selected_reverse, atom]))
        if fits(build_document(candidate)):
            selected_reverse.append(atom)

    selected = tuple(reversed(selected_reverse))
    return build_document(selected)


def _fits_update(
    document: dict[str, object],
    *,
    task: str = _UPDATE_TASK,
    limit: int = _UPDATE_USER_MESSAGE_LIMIT,
) -> bool:
    return rendered_context_user_message_length(document, task=task) <= limit


def _interpretive_list_fields(
    analysis: PostSessionUpdateContext,
    *,
    max_items: int,
    max_item_chars: int,
) -> dict[str, object]:
    fields: dict[str, object] = {}
    for field in _INTERPRETIVE_LIST_FIELDS:
        values = getattr(analysis, field)
        fields[field] = [
            bounded_text(item, max_item_chars)
            for item in list(values)[:max_items]
            if str(item).strip()
        ]
    return fields


def _baseline_analysis_document(
    analysis: PostSessionUpdateContext,
) -> dict[str, object]:
    return {
        "summary": compact_summary(analysis.summary),
        "intervention_evidence": [],
        "intervention_evidence_omitted": len(analysis.intervention_evidence),
        "patient_turns": [],
        "patient_turns_omitted": len(analysis.selected_patient_turns),
    }


def enrich_analysis_without_evicting_evidence(
    best_analysis: Mapping[str, object],
    *,
    interpretive_candidates: Iterable[Mapping[str, object]],
    fits: Callable[[dict[str, object]], bool],
) -> dict[str, object]:
    """Add optional interpretive lists without changing frozen analysis fields."""
    frozen = {key: best_analysis[key] for key in _FROZEN_ANALYSIS_KEYS}
    best = dict(best_analysis)
    for candidate in interpretive_candidates:
        conflicts = _FROZEN_ANALYSIS_KEYS.intersection(candidate)
        if conflicts:
            raise ValueError(
                f"interpretive candidate contains reserved fields: {sorted(conflicts)}"
            )
        merged = {**dict(candidate), **frozen}
        if fits(merged):
            return merged
    return best


def build_update_user_message(
    input: PostSessionInput,
    resolved: ResolvedSessionAnalysis,
) -> str:
    """Build the final update user-role message within the configured limit.

    Priority packing:
    1. minimal current plan + validated analysis baseline
    2. pack current resolved evidence (summary + intervention/patient atoms)
    3. enrich current-session interpretive analysis without evicting evidence
    4. enrich current plan without evicting evidence or interpretive fields
    5. optional longitudinal context: briefing, grounded turns, prior reviews
    """
    analysis = PostSessionUpdateContext.from_resolved(resolved)
    baseline_analysis = _baseline_analysis_document(analysis)
    minimal_plan = minimal_plan_projection(input.current_plan)
    document: dict[str, object] = {
        "current_plan": minimal_plan,
        "validated_session_analysis": baseline_analysis,
    }
    if not _fits_update(document):
        raise ValueError(
            "post-session update minimal plan and analysis baseline "
            f"exceed the {_UPDATE_USER_MESSAGE_LIMIT}-character user-message limit"
        )

    # 1. Pack current resolved evidence under one shared chronological budget.
    atoms = build_evidence_atoms(
        analysis.intervention_evidence,
        analysis.selected_patient_turns,
    )

    def analysis_fits(validated_session_analysis: dict[str, object]) -> bool:
        candidate = dict(document)
        candidate["validated_session_analysis"] = validated_session_analysis
        return _fits_update(candidate)

    try:
        best_analysis = pack_evidence_atoms(
            atoms,
            total_interventions=len(analysis.intervention_evidence),
            total_patient_turns=len(analysis.selected_patient_turns),
            interpretive={"summary": compact_summary(analysis.summary)},
            fits=analysis_fits,
        )
    except ProjectionBudgetError as exc:
        raise ValueError(
            "post-session update cannot fit analysis evidence "
            f"within the {_UPDATE_USER_MESSAGE_LIMIT}-character user-message limit"
        ) from exc
    document["validated_session_analysis"] = best_analysis

    # 2. Optional interpretive lists without changing frozen summary/evidence.
    interpretive_candidates = (
        _interpretive_list_fields(
            analysis,
            max_items=max_items,
            max_item_chars=_SUMMARY_LIST_ITEM_CHARS,
        )
        for max_items in range(20, 0, -1)
    )

    def interpretive_fits(validated_session_analysis: dict[str, object]) -> bool:
        candidate = dict(document)
        candidate["validated_session_analysis"] = validated_session_analysis
        return _fits_update(candidate)

    document["validated_session_analysis"] = enrich_analysis_without_evicting_evidence(
        best_analysis,
        interpretive_candidates=interpretive_candidates,
        fits=interpretive_fits,
    )

    # 3. Enrich plan only after current-session interpretive analysis is frozen.
    def plan_fits(plan_doc: dict[str, object]) -> bool:
        candidate = dict(document)
        candidate["current_plan"] = plan_doc
        return _fits_update(candidate)

    document["current_plan"] = enrich_plan_projection(
        input.current_plan,
        baseline=minimal_plan,
        fits=plan_fits,
    )

    longitudinal: dict[str, object] = {}
    briefing = input.prior_reviews[-1].briefing if input.prior_reviews else None
    if briefing is not None:
        minimal_briefing = minimal_session_briefing_projection(briefing)

        def briefing_fits(briefing_doc: dict[str, object]) -> bool:
            candidate = dict(document)
            candidate["longitudinal_context"] = {
                **longitudinal,
                "latest_supervisor_briefing": briefing_doc,
            }
            return _fits_update(candidate)

        if briefing_fits(minimal_briefing):
            enriched_briefing = enrich_session_briefing_projection(
                briefing,
                baseline=minimal_briefing,
                fits=briefing_fits,
            )
            longitudinal["latest_supervisor_briefing"] = enriched_briefing

    if input.grounded_patient_messages:

        def grounded_fits(grounded_doc: dict[str, object]) -> bool:
            candidate = dict(document)
            candidate["longitudinal_context"] = {
                **longitudinal,
                **grounded_doc,
            }
            return _fits_update(candidate)

        packed = pack_grounded_patient_messages(
            input.grounded_patient_messages,
            fits=grounded_fits,
        )
        if packed is not None:
            longitudinal.update(packed.document)

    if input.prior_reviews:

        def reviews_fits(reviews_doc: dict[str, object]) -> bool:
            candidate = dict(document)
            candidate["longitudinal_context"] = {
                **longitudinal,
                **reviews_doc,
            }
            return _fits_update(candidate)

        packed_reviews = pack_prior_session_reviews(
            input.prior_reviews,
            fits=reviews_fits,
        )
        if packed_reviews is not None:
            longitudinal.update(packed_reviews.document)

    if longitudinal:
        document["longitudinal_context"] = longitudinal

    final = render_context_user_message(document, task=_UPDATE_TASK)
    if len(final) > _UPDATE_USER_MESSAGE_LIMIT:
        raise ValueError(
            "post-session update user message exceeds the "
            f"{_UPDATE_USER_MESSAGE_LIMIT}-character user-message limit"
        )
    return final
