"""Deterministic post-session update context assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from jung.domain.grounding import GroundedPatientTurn, parse_grounded_patient_turns
from jung.domain.models import Plan
from jung.phases.context_bounds import (
    bounded_text,
    newest_lines_within_budget,
    pack_complete_json_items,
)
from jung.phases.post_session.models import (
    InterventionEvidence,
    PostSessionInput,
    ResolvedSessionAnalysis,
)

_UPDATE_CONTEXT_LIMIT = 8_000
_ANALYSIS_RESERVED_CHARS = 2_500
_PLAN_RESERVED_CHARS = 1_500
_PROFILE_RESERVED_CHARS = 1_200

_PLAN_LIST_FIELDS = (
    "themes",
    "goals",
    "planned_interventions",
    "revision_recommendations",
)
_REQUIRED_PLAN_LIST_FIELDS = frozenset({"goals", "planned_interventions"})


@dataclass(frozen=True, slots=True)
class AnalysisEvidenceAtom:
    kind: Literal["intervention", "patient_turn"]
    sequence: int
    payload: InterventionEvidence | GroundedPatientTurn


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


def _compact_plan_document(plan: Plan, limit: int) -> str:
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
            rendered = json.dumps(candidate, ensure_ascii=True, separators=(",", ":"))
            if len(rendered) <= limit:
                return rendered
    minimal = {
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
    return json.dumps(minimal, ensure_ascii=True, separators=(",", ":"))


def _intervention_payload(item: InterventionEvidence) -> dict[str, object]:
    return {
        "intervention_description": item.intervention_description,
        "status": item.status,
        "therapist_sequence": item.therapist_sequence,
        "therapist_content": item.therapist_content,
        "patient_sequence": item.patient_sequence,
        "patient_content": item.patient_content,
    }


def _patient_turn_payload(item: GroundedPatientTurn) -> dict[str, object]:
    return {
        "source_sequence": item.source_sequence,
        "content": item.content,
    }


def _compact_profile_document(profile: Mapping[str, Any], limit: int) -> str:
    if not profile:
        return json.dumps(
            {"grounded_patient_turns": [], "grounded_patient_turns_omitted": 0},
            ensure_ascii=True,
            separators=(",", ":"),
        )
    turns = parse_grounded_patient_turns(profile)

    def render(selected: Sequence[GroundedPatientTurn], omitted: int) -> str:
        document = {
            "grounded_patient_turns": [
                _patient_turn_payload(item) for item in selected
            ],
            "grounded_patient_turns_omitted": omitted,
        }
        return json.dumps(document, ensure_ascii=True, separators=(",", ":"))

    packed = pack_complete_json_items(turns, limit=limit, render_document=render)
    if packed is None:
        return ""
    return render(packed.items, packed.omitted)


def _build_evidence_atoms(
    context: PostSessionUpdateContext,
) -> tuple[AnalysisEvidenceAtom, ...]:
    atoms = [
        *(
            AnalysisEvidenceAtom(
                kind="intervention",
                sequence=item.therapist_sequence,
                payload=item,
            )
            for item in context.intervention_evidence
        ),
        *(
            AnalysisEvidenceAtom(
                kind="patient_turn",
                sequence=item.source_sequence,
                payload=item,
            )
            for item in context.patient_turns
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


def _compact_analysis_document(
    analysis: PostSessionUpdateContext,
    limit: int,
) -> str:
    total_interventions = len(analysis.intervention_evidence)
    total_turns = len(analysis.patient_turns)
    atoms = _build_evidence_atoms(analysis)

    def render_interpretive(max_items: int, max_item_chars: int) -> dict[str, object]:
        candidate: dict[str, object] = {
            "summary": bounded_text(analysis.summary, max_item_chars),
        }
        for field in (
            "key_themes",
            "dominant_affects",
            "important_moments",
            "patient_insights",
            "progress_indicators",
            "unresolved_topics",
            "safety_or_boundary_notes",
        ):
            candidate[field] = _compact_string_list(
                getattr(analysis, field),
                max_items=max_items,
                max_item_chars=max_item_chars,
                keep_at_least_one=False,
            )
        return candidate

    for max_items in range(20, 0, -1):
        for max_item_chars in range(400, 20, -20):
            interpretive = render_interpretive(max_items, max_item_chars)

            def render_document(
                selected: Sequence[AnalysisEvidenceAtom],
                _: int,
                interpretive_fields: dict[str, object] = interpretive,
            ) -> str:
                selected_interventions = [
                    item.payload for item in selected if item.kind == "intervention"
                ]
                selected_turns = [
                    item.payload for item in selected if item.kind == "patient_turn"
                ]
                document = {
                    **interpretive_fields,
                    "intervention_evidence": [
                        _intervention_payload(item)  # type: ignore[arg-type]
                        for item in selected_interventions
                    ],
                    "intervention_evidence_omitted": (
                        total_interventions - len(selected_interventions)
                    ),
                    "patient_turns": [
                        _patient_turn_payload(item)  # type: ignore[arg-type]
                        for item in selected_turns
                    ],
                    "patient_turns_omitted": total_turns - len(selected_turns),
                }
                return json.dumps(document, ensure_ascii=True, separators=(",", ":"))

            packed = pack_complete_json_items(
                atoms,
                limit=limit,
                render_document=render_document,
            )
            if packed is not None:
                return render_document(packed.items, packed.omitted)

    fallback = {"summary": bounded_text(analysis.summary, 200)}
    rendered = json.dumps(fallback, ensure_ascii=True, separators=(",", ":"))
    if len(rendered) > limit:
        return ""
    return rendered


def _render_section(heading: str, body: str) -> str:
    return f"{heading}:\n{body}"


def _briefing_prose(briefing: Mapping[str, Any], limit: int) -> str:
    parts: list[str] = []
    for key, value in briefing.items():
        if isinstance(value, list):
            text = ", ".join(str(item) for item in value if str(item).strip())
        else:
            text = str(value)
        if text.strip():
            parts.append(f"{key}: {text}")
    prose = "\n".join(parts)
    return bounded_text(prose, limit)


def _section_payload_budget(heading: str, cap: int, remaining: int) -> int:
    prefix = f"{heading}:\n"
    return max(0, min(cap, remaining) - len(prefix))


def build_update_context_document(
    input: PostSessionInput,
    resolved: ResolvedSessionAnalysis,
) -> dict[str, object]:
    """Build the untrusted JSON context document for the update call."""
    analysis_projection = PostSessionUpdateContext.from_resolved(resolved)
    document: dict[str, object] = {}

    analysis_body = _compact_analysis_document(
        analysis_projection,
        _ANALYSIS_RESERVED_CHARS,
    )
    if analysis_body:
        document["session_analysis"] = json.loads(analysis_body)

    plan_body = _compact_plan_document(input.current_plan, _PLAN_RESERVED_CHARS)
    document["current_plan"] = json.loads(plan_body)

    profile_body = _compact_profile_document(
        input.derived_profile or {},
        _PROFILE_RESERVED_CHARS,
    )
    if profile_body:
        document["derived_profile"] = json.loads(profile_body)

    if input.prior_session_briefing:
        briefing = _briefing_prose(
            input.prior_session_briefing,
            _UPDATE_CONTEXT_LIMIT // 4,
        )
        if briefing:
            document["prior_session_briefing"] = briefing

    if input.recent_session_summaries:
        summaries = newest_lines_within_budget(
            input.recent_session_summaries,
            _UPDATE_CONTEXT_LIMIT // 4,
            separator="\n",
        )
        if summaries:
            document["recent_session_summaries"] = list(summaries)

    return document


def build_update_context_sections(
    input: PostSessionInput,
    resolved: ResolvedSessionAnalysis,
) -> list[str]:
    """Legacy section list used by tests that inspect section headings."""
    analysis_projection = PostSessionUpdateContext.from_resolved(resolved)
    sections: list[str] = []
    remaining = _UPDATE_CONTEXT_LIMIT

    analysis_budget = _section_payload_budget(
        "Session analysis",
        _ANALYSIS_RESERVED_CHARS,
        remaining,
    )
    if analysis_budget > 0:
        analysis_body = _compact_analysis_document(
            analysis_projection,
            analysis_budget,
        )
        if analysis_body:
            section = _render_section("Session analysis", analysis_body)
            sections.append(section)
            remaining = max(0, remaining - len(section) - 2)

    plan_budget = _section_payload_budget(
        "Current plan",
        _PLAN_RESERVED_CHARS,
        remaining,
    )
    if plan_budget > 0:
        plan_body = _compact_plan_document(input.current_plan, plan_budget)
        section = _render_section("Current plan", plan_body)
        sections.append(section)
        remaining = max(0, remaining - len(section) - 2)

    profile_budget = _section_payload_budget(
        "Derived profile",
        _PROFILE_RESERVED_CHARS,
        remaining,
    )
    if profile_budget > 0:
        profile_body = _compact_profile_document(
            input.derived_profile or {},
            profile_budget,
        )
        if profile_body:
            section = _render_section("Derived profile", profile_body)
            sections.append(section)
            remaining = max(0, remaining - len(section) - 2)

    if input.prior_session_briefing and remaining > 0:
        briefing_budget = _section_payload_budget(
            "Prior session briefing",
            remaining,
            remaining,
        )
        briefing = _briefing_prose(input.prior_session_briefing, briefing_budget)
        if briefing:
            section = _render_section("Prior session briefing", briefing)
            sections.append(section)
            remaining = max(0, remaining - len(section) - 2)

    if input.recent_session_summaries and remaining > 0:
        summary_budget = _section_payload_budget(
            "Recent session summaries",
            remaining,
            remaining,
        )
        summaries = newest_lines_within_budget(
            input.recent_session_summaries,
            summary_budget,
            separator="\n",
        )
        if summaries:
            body = "\n".join(summaries)
            section = _render_section("Recent session summaries", body)
            if len(section) > remaining:
                heading_len = len("Recent session summaries:\n")
                body = bounded_text(body, max(0, remaining - heading_len))
                section = _render_section("Recent session summaries", body)
            if section.strip():
                sections.append(section)

    rendered = "\n\n".join(sections)
    if len(rendered) > _UPDATE_CONTEXT_LIMIT:
        raise ValueError(
            f"post-session update context exceeded budget: "
            f"{len(rendered)} > {_UPDATE_CONTEXT_LIMIT}"
        )
    return sections
