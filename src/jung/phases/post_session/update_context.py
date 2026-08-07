"""Deterministic post-session update context assembly."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from jung.domain.grounding import GroundedPatientTurn, parse_grounded_patient_turns
from jung.domain.session_artifacts import parse_session_briefing
from jung.llm.prompt_context import (
    render_context_user_message,
    rendered_context_user_message_length,
)
from jung.phases.context_bounds import bounded_text
from jung.phases.context_projection import (
    ProjectionBudgetError,
    build_evidence_atoms,
    compact_session_briefing,
    compact_summary,
    enrich_plan_projection,
    minimal_plan_projection,
    pack_evidence_atoms,
    pack_grounded_profile_turns,
)
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    ResolvedSessionAnalysis,
)

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
    patient_turns: tuple[GroundedPatientTurn, ...]
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
            patient_turns=resolved.grounded_patient_turns,
            safety_or_boundary_notes=analysis.safety_or_boundary_notes,
        )


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
        "patient_turns_omitted": len(analysis.patient_turns),
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


def _try_set(
    document: dict[str, object],
    key: str,
    value: object,
) -> bool:
    candidate = dict(document)
    candidate[key] = value
    if _fits_update(candidate):
        document[key] = value
        return True
    return False


def build_update_user_message(
    input: PostSessionInput,
    resolved: ResolvedSessionAnalysis,
) -> str:
    """Build the final update user-role message within the configured limit."""
    analysis = PostSessionUpdateContext.from_resolved(resolved)
    baseline_analysis = _baseline_analysis_document(analysis)
    minimal_plan = minimal_plan_projection(input.current_plan)
    document: dict[str, object] = {
        "current_plan": minimal_plan,
        "session_analysis": baseline_analysis,
    }
    if not _fits_update(document):
        raise ValueError(
            "post-session update minimal plan and analysis baseline "
            f"exceed the {_UPDATE_USER_MESSAGE_LIMIT}-character user-message limit"
        )

    # 1. Pack current resolved evidence under one shared chronological budget.
    atoms = build_evidence_atoms(
        analysis.intervention_evidence,
        analysis.patient_turns,
    )

    def analysis_fits(session_analysis: dict[str, object]) -> bool:
        candidate = dict(document)
        candidate["session_analysis"] = session_analysis
        return _fits_update(candidate)

    try:
        best_analysis = pack_evidence_atoms(
            atoms,
            total_interventions=len(analysis.intervention_evidence),
            total_patient_turns=len(analysis.patient_turns),
            interpretive={"summary": compact_summary(analysis.summary)},
            fits=analysis_fits,
        )
    except ProjectionBudgetError as exc:
        raise ValueError(
            "post-session update cannot fit analysis evidence "
            f"within the {_UPDATE_USER_MESSAGE_LIMIT}-character user-message limit"
        ) from exc
    document["session_analysis"] = best_analysis

    # 2. Enrich plan only after evidence is frozen (may not starve evidence).
    def plan_fits(plan_doc: dict[str, object]) -> bool:
        candidate = dict(document)
        candidate["current_plan"] = plan_doc
        candidate["session_analysis"] = best_analysis
        return _fits_update(candidate)

    document["current_plan"] = enrich_plan_projection(
        input.current_plan,
        baseline=minimal_plan,
        fits=plan_fits,
    )

    # 3. Optional interpretive lists without changing frozen summary/evidence.
    interpretive_candidates = (
        _interpretive_list_fields(
            analysis,
            max_items=max_items,
            max_item_chars=_SUMMARY_LIST_ITEM_CHARS,
        )
        for max_items in range(20, 0, -1)
    )

    def interpretive_fits(session_analysis: dict[str, object]) -> bool:
        candidate = dict(document)
        candidate["session_analysis"] = session_analysis
        return _fits_update(candidate)

    document["session_analysis"] = enrich_analysis_without_evicting_evidence(
        best_analysis,
        interpretive_candidates=interpretive_candidates,
        fits=interpretive_fits,
    )

    # 4. Grounded derived profile.
    if input.derived_profile is not None:
        turns = parse_grounded_patient_turns(input.derived_profile)

        def profile_fits(profile_doc: dict[str, object]) -> bool:
            candidate = dict(document)
            candidate["derived_profile"] = profile_doc
            return _fits_update(candidate)

        packed = pack_grounded_profile_turns(
            turns,
            fits=profile_fits,
            content_only=True,
        )
        if packed is not None:
            document["derived_profile"] = packed.document

    # 5. Prior session briefing (typed, atomic evidence).
    if input.prior_session_briefing is not None:
        briefing = parse_session_briefing(input.prior_session_briefing)

        def briefing_fits(briefing_doc: dict[str, object]) -> bool:
            candidate = dict(document)
            candidate["prior_session_briefing"] = briefing_doc
            return _fits_update(candidate)

        packed_briefing = compact_session_briefing(briefing, fits=briefing_fits)
        if packed_briefing is not None:
            document["prior_session_briefing"] = packed_briefing.document

    # 6. Recent session summaries (character-bounded interpretive prose).
    if input.recent_session_summaries:
        selected: list[str] = []
        for summary in reversed(input.recent_session_summaries):
            text = bounded_text(str(summary), 400)
            if not text.strip():
                continue
            candidate_list = [text, *selected]
            if _try_set(document, "recent_session_summaries", candidate_list):
                selected = candidate_list
            else:
                break

    final = render_context_user_message(document, task=_UPDATE_TASK)
    if len(final) > _UPDATE_USER_MESSAGE_LIMIT:
        raise ValueError(
            "post-session update user message exceeds the "
            f"{_UPDATE_USER_MESSAGE_LIMIT}-character user-message limit"
        )
    return final
