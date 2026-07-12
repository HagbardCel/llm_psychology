"""Deterministic post-session update context assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jung.domain.models import Plan
from jung.phases.context_bounds import bounded_text, newest_within_budget
from jung.phases.post_session.models import PostSessionInput, SessionAnalysisResult

_UPDATE_CONTEXT_LIMIT = 8_000
_ANALYSIS_RESERVED_CHARS = 2_500
_PLAN_RESERVED_CHARS = 1_500
_PROFILE_RESERVED_CHARS = 1_200
_STYLE_RESERVED_CHARS = 800

_PLAN_LIST_FIELDS = (
    "themes",
    "goals",
    "planned_interventions",
    "revision_recommendations",
)
_REQUIRED_PLAN_LIST_FIELDS = frozenset({"goals", "planned_interventions"})


@dataclass(frozen=True, slots=True)
class PostSessionUpdateContext:
    """Pure projection of analysis for the update call — not an LLM contract."""

    summary: str
    key_themes: tuple[str, ...]
    dominant_affects: tuple[str, ...]
    important_moments: tuple[str, ...]
    patient_insights: tuple[str, ...]
    progress_indicators: tuple[str, ...]
    unresolved_topics: tuple[str, ...]
    interventions: tuple[dict[str, str | None], ...]
    safety_or_boundary_notes: tuple[str, ...]

    @classmethod
    def from_analysis(cls, analysis: SessionAnalysisResult) -> PostSessionUpdateContext:
        interventions = tuple(
            {
                "intervention": item.intervention,
                "status": item.status,
                "patient_quote": item.patient_quote,
            }
            for item in analysis.interventions_and_responses
        )
        return cls(
            summary=analysis.summary,
            key_themes=analysis.key_themes,
            dominant_affects=analysis.dominant_affects,
            important_moments=analysis.important_moments,
            patient_insights=analysis.patient_insights,
            progress_indicators=analysis.progress_indicators,
            unresolved_topics=analysis.unresolved_topics,
            interventions=interventions,
            safety_or_boundary_notes=analysis.safety_or_boundary_notes,
        )

    def to_document(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "key_themes": list(self.key_themes),
            "dominant_affects": list(self.dominant_affects),
            "important_moments": list(self.important_moments),
            "patient_insights": list(self.patient_insights),
            "progress_indicators": list(self.progress_indicators),
            "unresolved_topics": list(self.unresolved_topics),
            "interventions_and_responses": list(self.interventions),
            "safety_or_boundary_notes": list(self.safety_or_boundary_notes),
        }


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


def _compact_profile_document(profile: Mapping[str, Any], limit: int) -> str:
    if not profile:
        return "{}"
    priority_keys = ("observations", "hypotheses", "patient_stated_facts")
    ordered_keys = [key for key in priority_keys if key in profile]
    ordered_keys.extend(key for key in profile if key not in priority_keys)
    working: dict[str, Any] = dict(profile)
    for key in list(working):
        if key not in ordered_keys[:1] and len(
            json.dumps(working, ensure_ascii=True, separators=(",", ":"))
        ) > limit:
            working.pop(key, None)
    for max_items in range(20, 0, -1):
        candidate: dict[str, Any] = {}
        for key in ordered_keys:
            value = working.get(key)
            if isinstance(value, list):
                candidate[key] = [
                    bounded_text(str(item), 200)
                    for item in value[:max_items]
                    if str(item).strip()
                ]
            elif value is not None:
                candidate[key] = value
        rendered = json.dumps(candidate, ensure_ascii=True, separators=(",", ":"))
        if len(rendered) <= limit:
            return rendered
    return "{}"


def _compact_analysis_document(
    analysis: PostSessionUpdateContext,
    limit: int,
) -> str:
    document = analysis.to_document()
    for max_items in range(20, 0, -1):
        for max_item_chars in range(400, 20, -20):
            candidate = dict(document)
            candidate["summary"] = bounded_text(analysis.summary, max_item_chars)
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
                    tuple(candidate.get(field, [])),
                    max_items=max_items,
                    max_item_chars=max_item_chars,
                    keep_at_least_one=False,
                )
            interventions = list(analysis.interventions[:max_items])
            compacted_interventions: list[dict[str, str | None]] = []
            for item in interventions:
                compacted_interventions.append(
                    {
                        "intervention": bounded_text(
                            str(item["intervention"]),
                            max_item_chars,
                        ),
                        "status": str(item["status"]),
                        "patient_quote": (
                            bounded_text(str(item["patient_quote"]), max_item_chars)
                            if item.get("patient_quote")
                            else None
                        ),
                    }
                )
            candidate["interventions_and_responses"] = compacted_interventions
            rendered = json.dumps(candidate, ensure_ascii=True, separators=(",", ":"))
            if len(rendered) <= limit:
                return rendered
    return json.dumps(
        {"summary": bounded_text(analysis.summary, 200)},
        ensure_ascii=True,
        separators=(",", ":"),
    )


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


def build_update_context_sections(
    input: PostSessionInput,
    analysis: SessionAnalysisResult,
) -> list[str]:
    analysis_projection = PostSessionUpdateContext.from_analysis(analysis)
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
        section = _render_section("Derived profile", profile_body)
        sections.append(section)
        remaining = max(0, remaining - len(section) - 2)

    style_budget = _section_payload_budget(
        "Style reflection instructions",
        _STYLE_RESERVED_CHARS,
        remaining,
    )
    style_text = input.selected_style.post_session_instructions or ""
    if style_text.strip() and style_budget > 0:
        style_body = bounded_text(style_text, style_budget)
        if style_body:
            section = _render_section("Style reflection instructions", style_body)
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
        summaries = newest_within_budget(
            input.recent_session_summaries,
            summary_budget,
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
                remaining = max(0, remaining - len(section) - 2)

    rendered = "\n\n".join(sections)
    if len(rendered) > _UPDATE_CONTEXT_LIMIT:
        raise ValueError(
            f"post-session update context exceeded budget: "
            f"{len(rendered)} > {_UPDATE_CONTEXT_LIMIT}"
        )
    return sections
