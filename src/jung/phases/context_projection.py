"""Shared LLM-facing projections for plans, briefings, and evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from jung.domain.grounding import GroundedPatientTurn
from jung.domain.models import Plan
from jung.domain.session_artifacts import InterventionEvidence, SessionBriefing
from jung.domain.text import normalize_content
from jung.llm.prompt_context import serialize_context_json
from jung.phases.context_bounds import bounded_text
from jung.phases.transcript import TranscriptTurn

_PRIMARY_LANGUAGE_PROJECTION_LIMIT = 80
_SUMMARY_BASELINE_CHARS = 400

_PLAN_LIST_FIELDS = (
    "themes",
    "goals",
    "planned_interventions",
    "revision_recommendations",
)
_REQUIRED_PLAN_LIST_FIELDS = frozenset({"goals", "planned_interventions"})


@dataclass(frozen=True, slots=True)
class PackedProjection:
    document: dict[str, object]
    omitted: int


@dataclass(frozen=True, slots=True)
class AnalysisEvidenceAtom:
    kind: Literal["intervention", "patient_turn"]
    sequence: int
    payload: InterventionEvidence | GroundedPatientTurn


def project_primary_language(value: str) -> str | None:
    """Return a bounded language label, or None when absent/oversized."""
    normalized = normalize_content(value)
    if not normalized or len(normalized) > _PRIMARY_LANGUAGE_PROJECTION_LIMIT:
        return None
    return normalized


def _compact_string_list(
    items: Sequence[str],
    *,
    max_items: int,
    max_item_chars: int,
    keep_at_least_one: bool,
) -> list[str]:
    selected = list(items[:max_items])
    compacted = [
        bounded_text(item, max_item_chars) for item in selected if item.strip()
    ]
    if keep_at_least_one and items and not compacted:
        compacted = [bounded_text(str(items[0]), max_item_chars)]
    return compacted


def compact_plan_document(plan: Plan, *, limit: int) -> dict[str, object]:
    """Return a structured plan projection that fits within ``limit`` chars.

    Retains all semantic keys and at least one goal and planned intervention.
    Raises ``ValueError`` when even the minimal projection exceeds ``limit``.
    """
    base = {
        "focus": plan.focus,
        "themes": list(plan.themes),
        "goals": list(plan.goals),
        "current_progress": plan.current_progress,
        "planned_interventions": list(plan.planned_interventions),
        "revision_recommendations": list(plan.revision_recommendations),
    }
    for max_items in range(20, 0, -1):
        for max_item_chars in range(500, 20, -20):
            candidate = dict(base)
            candidate["focus"] = bounded_text(plan.focus, max_item_chars)
            candidate["current_progress"] = bounded_text(
                plan.current_progress,
                max_item_chars,
            )
            for field in _PLAN_LIST_FIELDS:
                candidate[field] = _compact_string_list(
                    getattr(plan, field),
                    max_items=max_items,
                    max_item_chars=max_item_chars,
                    keep_at_least_one=field in _REQUIRED_PLAN_LIST_FIELDS,
                )
            if len(serialize_context_json(candidate)) <= limit:
                return candidate
    minimal: dict[str, object] = {
        "focus": bounded_text(plan.focus, 80),
        "themes": [],
        "goals": _compact_string_list(
            plan.goals,
            max_items=1,
            max_item_chars=80,
            keep_at_least_one=True,
        ),
        "current_progress": bounded_text(plan.current_progress, 80),
        "planned_interventions": _compact_string_list(
            plan.planned_interventions,
            max_items=1,
            max_item_chars=80,
            keep_at_least_one=True,
        ),
        "revision_recommendations": [],
    }
    rendered = serialize_context_json(minimal)
    if len(rendered) > limit:
        raise ValueError(
            f"minimal plan projection exceeds budget: {len(rendered)} > {limit}"
        )
    return minimal


def intervention_payload(item: InterventionEvidence) -> dict[str, object]:
    return {
        "intervention_description": item.intervention_description,
        "status": item.status,
        "therapist_sequence": item.therapist_sequence,
        "therapist_content": item.therapist_content,
        "patient_sequence": item.patient_sequence,
        "patient_content": item.patient_content,
    }


def analysis_patient_turn_payload(item: GroundedPatientTurn) -> dict[str, object]:
    """Current-session evidence retains sequence (same-prompt transcript)."""
    return {
        "source_sequence": item.source_sequence,
        "content": item.content,
    }


def derived_profile_turn_payload(item: GroundedPatientTurn) -> dict[str, object]:
    """Cross-session profile projection is content-only."""
    return {"content": item.content}


def transcript_turn_payload(turn: TranscriptTurn) -> dict[str, object]:
    return {
        "sequence": turn.sequence,
        "role": turn.role,
        "content": normalize_content(turn.content),
    }


def compact_summary(text: str, *, limit: int = _SUMMARY_BASELINE_CHARS) -> str:
    return bounded_text(normalize_content(text), limit)


def project_session_briefing(
    briefing: SessionBriefing,
    *,
    selected_evidence: Sequence[InterventionEvidence],
    omitted: int,
) -> dict[str, object]:
    """Project a validated briefing with the given evidence selection."""
    return {
        "narrative_handoff": bounded_text(briefing.narrative_handoff, 400),
        "continuity_points": [
            bounded_text(item, 200)
            for item in briefing.continuity_points
            if item.strip()
        ],
        "unresolved_issues": [
            bounded_text(item, 200)
            for item in briefing.unresolved_issues
            if item.strip()
        ],
        "recommended_opening_focus": bounded_text(
            briefing.recommended_opening_focus, 400
        ),
        "things_to_avoid": [
            bounded_text(item, 200) for item in briefing.things_to_avoid if item.strip()
        ],
        "emotional_context": [
            bounded_text(item, 200)
            for item in briefing.emotional_context
            if item.strip()
        ],
        "intervention_evidence": [
            intervention_payload(item) for item in selected_evidence
        ],
        "intervention_evidence_omitted": omitted,
    }


def compact_session_briefing(
    briefing: SessionBriefing,
    *,
    fits: Callable[[dict[str, object]], bool],
) -> PackedProjection | None:
    """Pack briefing evidence under a caller-owned fitness predicate."""
    evidence = briefing.intervention_evidence
    total = len(evidence)

    empty = project_session_briefing(briefing, selected_evidence=(), omitted=total)
    if not fits(empty):
        return None

    selected_reverse: list[InterventionEvidence] = []
    for item in reversed(evidence):
        candidate = tuple(reversed([*selected_reverse, item]))
        omitted = total - len(candidate)
        projected = project_session_briefing(
            briefing,
            selected_evidence=candidate,
            omitted=omitted,
        )
        if fits(projected):
            selected_reverse.append(item)

    selected = tuple(reversed(selected_reverse))
    omitted = total - len(selected)
    document = project_session_briefing(
        briefing,
        selected_evidence=selected,
        omitted=omitted,
    )
    return PackedProjection(document=document, omitted=omitted)


def build_evidence_atoms(
    interventions: Sequence[InterventionEvidence],
    patient_turns: Sequence[GroundedPatientTurn],
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
                sequence=item.source_sequence,
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
                analysis_patient_turn_payload(item)  # type: ignore[arg-type]
                for item in selected_turns
            ],
            "patient_turns_omitted": total_patient_turns - len(selected_turns),
        }

    baseline = build_document(())
    if not fits(baseline):
        raise ValueError("minimal analysis evidence projection does not fit budget")

    selected_reverse: list[AnalysisEvidenceAtom] = []
    for atom in reversed(atoms):
        candidate = tuple(reversed([*selected_reverse, atom]))
        if fits(build_document(candidate)):
            selected_reverse.append(atom)

    selected = tuple(reversed(selected_reverse))
    return build_document(selected)


def pack_transcript_turns(
    turns: Sequence[TranscriptTurn],
    *,
    fits: Callable[[dict[str, object]], bool],
    require_two_roles: bool = False,
) -> PackedProjection:
    """Pack complete transcript turns newest-first.

    When ``require_two_roles`` is true, ensure at least one user and one
    assistant turn remain, attempting to recover a missing role if needed.
    """
    source = tuple(turns)
    total = len(source)

    def build_document(
        selected: Sequence[TranscriptTurn],
    ) -> dict[str, object]:
        return {
            "transcript": [transcript_turn_payload(turn) for turn in selected],
            "transcript_turns_omitted": total - len(selected),
        }

    empty = build_document(())
    if not fits(empty):
        raise ValueError(
            "analysis context budget cannot fit an empty transcript projection"
        )

    selected_reverse: list[TranscriptTurn] = []
    for turn in reversed(source):
        candidate = tuple(reversed([*selected_reverse, turn]))
        if fits(build_document(candidate)):
            selected_reverse.append(turn)

    selected = list(reversed(selected_reverse))
    selected_sequences = {turn.sequence for turn in selected}

    if require_two_roles:
        roles = {turn.role for turn in selected}
        for needed_role in ("user", "assistant"):
            if needed_role in roles:
                continue
            for turn in reversed(source):
                if turn.role != needed_role or turn.sequence in selected_sequences:
                    continue
                candidate = sorted(
                    [*selected, turn],
                    key=lambda item: item.sequence,
                )
                if fits(build_document(candidate)):
                    selected = candidate
                    selected_sequences.add(turn.sequence)
                    roles.add(needed_role)
                    break
        if "user" not in roles or "assistant" not in roles:
            raise ValueError(
                "analysis context budget cannot fit a complete conversational exchange"
            )

    selected_tuple = tuple(sorted(selected, key=lambda item: item.sequence))
    document = build_document(selected_tuple)
    return PackedProjection(
        document=document,
        omitted=int(document["transcript_turns_omitted"]),
    )


def pack_grounded_profile_turns(
    turns: Sequence[GroundedPatientTurn],
    *,
    fits: Callable[[dict[str, object]], bool],
    content_only: bool = True,
) -> PackedProjection | None:
    """Pack grounded profile turns under a caller-owned fitness predicate."""
    source = tuple(turns)
    total = len(source)

    def build_document(
        selected: Sequence[GroundedPatientTurn],
    ) -> dict[str, object]:
        payload_fn = (
            derived_profile_turn_payload
            if content_only
            else analysis_patient_turn_payload
        )
        return {
            "grounded_patient_turns": [payload_fn(item) for item in selected],
            "grounded_patient_turns_omitted": total - len(selected),
        }

    empty = build_document(())
    if not fits(empty):
        return None

    selected_reverse: list[GroundedPatientTurn] = []
    for item in reversed(source):
        candidate = tuple(reversed([*selected_reverse, item]))
        if fits(build_document(candidate)):
            selected_reverse.append(item)

    selected = tuple(reversed(selected_reverse))
    return PackedProjection(
        document=build_document(selected),
        omitted=total - len(selected),
    )
