"""Deterministic therapy context assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from jung.phases.context_bounds import bounded_text, newest_within_budget
from jung.phases.therapy.models import TherapyTurnInput


def format_plan_section(input: TherapyTurnInput) -> str:
    plan = input.current_plan
    return "\n".join(
        [
            f"Focus: {plan.focus}",
            f"Themes: {', '.join(plan.themes) or 'None'}",
            f"Goals: {', '.join(plan.goals)}",
            f"Progress: {plan.current_progress}",
            f"Interventions: {', '.join(plan.planned_interventions)}",
        ]
    )


def _normalize_content(text: str) -> str:
    return " ".join(text.split())


def _compact_mapping_json(document: Mapping[str, Any], limit: int) -> str:
    if not document or limit <= 0:
        return ""
    keys = list(document)
    for keep_count in range(len(keys), 0, -1):
        for max_item_chars in range(400, 20, -20):
            candidate: dict[str, Any] = {}
            for key in keys[:keep_count]:
                value = document[key]
                if isinstance(value, list):
                    candidate[key] = [
                        bounded_text(str(item), max_item_chars)
                        for item in value
                        if str(item).strip()
                    ]
                elif isinstance(value, str):
                    candidate[key] = bounded_text(value, max_item_chars)
                else:
                    candidate[key] = value
            rendered = json.dumps(candidate, ensure_ascii=True, separators=(",", ":"))
            if len(rendered) <= limit:
                return rendered
    return ""


def _transcript_lines(
    input: TherapyTurnInput,
    *,
    latest_user_message: str | None,
) -> list[str]:
    turns = list(input.transcript[-input.context_limits.max_transcript_turns :])
    if turns and latest_user_message and turns[-1].role == "user":
        if _normalize_content(turns[-1].content) == _normalize_content(
            latest_user_message
        ):
            turns = turns[:-1]
    return [f"{turn.role}: {turn.content}" for turn in turns]


def build_therapy_context(
    input: TherapyTurnInput,
    *,
    include_current_message: bool,
) -> list[str]:
    limits = input.context_limits
    # max_total_chars = maximum compressible context characters
    remaining = limits.max_total_chars
    sections: list[str] = []

    style_cap = min(limits.max_section_chars, remaining)
    style_body = bounded_text(input.selected_style.therapist_instructions, style_cap)
    style_section = f"Therapy style instructions:\n{style_body}"
    sections.append(style_section)
    remaining = max(0, remaining - len(style_section))

    plan_cap = min(limits.max_section_chars, remaining)
    plan_body = bounded_text(format_plan_section(input), plan_cap)
    plan_section = f"Current plan:\n{plan_body}"
    sections.append(plan_section)
    remaining = max(0, remaining - len(plan_section))

    if include_current_message and input.latest_user_message:
        sections.append(f"Current patient message:\n{input.latest_user_message}")

    latest_message = input.latest_user_message if include_current_message else None
    transcript_lines = _transcript_lines(
        input,
        latest_user_message=latest_message,
    )
    if transcript_lines and remaining > 0:
        heading = "Active session transcript:\n"
        payload_budget = max(0, remaining - len(heading))
        transcript = bounded_text("\n".join(transcript_lines), payload_budget)
        if transcript:
            transcript_section = f"{heading}{transcript}"
            sections.append(transcript_section)
            remaining = max(0, remaining - len(transcript_section))

    if input.session_briefing and remaining > 0:
        heading = "Session briefing:\n"
        payload_budget = max(0, remaining - len(heading))
        briefing = _compact_mapping_json(input.session_briefing, payload_budget)
        if briefing:
            briefing_section = f"{heading}{briefing}"
            sections.append(briefing_section)
            remaining = max(0, remaining - len(briefing_section))

    if input.derived_profile and remaining > 0:
        heading = "Derived profile:\n"
        payload_budget = max(0, remaining - len(heading))
        derived = _compact_mapping_json(input.derived_profile, payload_budget)
        if derived:
            derived_section = f"{heading}{derived}"
            sections.append(derived_section)
            remaining = max(0, remaining - len(derived_section))

    if input.recent_session_summaries and remaining > 0:
        heading = "Recent session summaries:\n"
        payload_budget = max(0, remaining - len(heading))
        summaries = newest_within_budget(
            input.recent_session_summaries,
            payload_budget,
        )
        if summaries:
            body = "\n".join(summaries)
            summary_section = f"{heading}{body}"
            if len(summary_section) > remaining:
                body = bounded_text(body, max(0, remaining - len(heading)))
                summary_section = f"{heading}{body}" if body else ""
            if summary_section:
                sections.append(summary_section)

    return sections


def build_context_sections(input: TherapyTurnInput) -> list[str]:
    return build_therapy_context(input, include_current_message=True)


def build_opening_context_sections(input: TherapyTurnInput) -> list[str]:
    sections = [
        (
            f"Patient: {input.profile.name}, "
            f"language={input.profile.primary_language}"
        ),
        *build_therapy_context(input, include_current_message=False),
    ]
    return sections
