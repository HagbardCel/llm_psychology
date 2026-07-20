"""Deterministic therapy context assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from jung.phases.context_bounds import bounded_text, newest_lines_within_budget
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.transcript import normalize_transcript_content

_STYLE_HEADING = "Therapy style instructions"
_PLAN_HEADING = "Current plan"
_SECTION_SEPARATOR = "\n\n"


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
        final_content = normalize_transcript_content(turns[-1].content)
        if final_content == normalize_transcript_content(latest_user_message):
            turns = turns[:-1]
    return [f"{turn.role}: {turn.content}" for turn in turns]


def _render_core_sections(input: TherapyTurnInput) -> tuple[list[str], int]:
    limits = input.context_limits
    style_prefix = f"{_STYLE_HEADING}:\n"
    plan_prefix = f"{_PLAN_HEADING}:\n"

    core_body_budget = (
        limits.max_total_chars
        - len(style_prefix)
        - len(plan_prefix)
        - len(_SECTION_SEPARATOR)
    )
    if core_body_budget <= 0:
        raise ValueError("therapy core context budget is nonpositive")

    style_body_budget = min(limits.max_section_chars, core_body_budget // 2)
    plan_body_budget = min(
        limits.max_section_chars,
        core_body_budget - style_body_budget,
    )

    style_body = bounded_text(
        input.selected_style.therapist_instructions,
        style_body_budget,
    )
    plan_body = bounded_text(format_plan_section(input), plan_body_budget)

    style_section = f"{style_prefix}{style_body}"
    plan_section = f"{plan_prefix}{plan_body}"
    sections = [style_section, plan_section]

    rendered_core = _SECTION_SEPARATOR.join(sections)
    remaining = limits.max_total_chars - len(rendered_core)
    return sections, max(0, remaining)


def _append_optional_section(
    sections: list[str],
    *,
    heading: str,
    body: str,
    remaining: int,
) -> int:
    if not body.strip():
        return remaining
    prefix = f"{heading}:\n"
    separator_cost = len(_SECTION_SEPARATOR)
    payload_budget = max(0, remaining - separator_cost - len(prefix))
    bounded_body = bounded_text(body, payload_budget)
    if not bounded_body.strip():
        return remaining
    section = f"{prefix}{bounded_body}"
    if separator_cost + len(section) > remaining:
        return remaining
    sections.append(section)
    return max(0, remaining - separator_cost - len(section))


def build_therapy_context(
    input: TherapyTurnInput,
    *,
    include_current_message: bool,
) -> list[str]:
    sections, remaining = _render_core_sections(input)

    latest_message = input.latest_user_message if include_current_message else None
    transcript_lines = _transcript_lines(
        input,
        latest_user_message=latest_message,
    )
    if transcript_lines and remaining > 0:
        heading = "Active session transcript"
        payload_budget = max(
            0,
            remaining - len(f"{heading}:\n") - len(_SECTION_SEPARATOR),
        )
        selected_lines = newest_lines_within_budget(transcript_lines, payload_budget)
        transcript = "\n".join(selected_lines)
        remaining = _append_optional_section(
            sections,
            heading=heading,
            body=transcript,
            remaining=remaining,
        )

    if input.session_briefing and remaining > 0:
        heading = "Session briefing"
        payload_budget = max(
            0,
            remaining - len(f"{heading}:\n") - len(_SECTION_SEPARATOR),
        )
        briefing = _compact_mapping_json(input.session_briefing, payload_budget)
        remaining = _append_optional_section(
            sections,
            heading=heading,
            body=briefing,
            remaining=remaining,
        )

    if input.derived_profile and remaining > 0:
        heading = "Derived profile"
        payload_budget = max(
            0,
            remaining - len(f"{heading}:\n") - len(_SECTION_SEPARATOR),
        )
        derived = _compact_mapping_json(input.derived_profile, payload_budget)
        remaining = _append_optional_section(
            sections,
            heading=heading,
            body=derived,
            remaining=remaining,
        )

    if input.recent_session_summaries and remaining > 0:
        heading = "Recent session summaries"
        payload_budget = max(
            0,
            remaining - len(f"{heading}:\n") - len(_SECTION_SEPARATOR),
        )
        summaries = newest_lines_within_budget(
            input.recent_session_summaries,
            payload_budget,
            separator="\n",
        )
        if summaries:
            body = "\n".join(summaries)
            remaining = _append_optional_section(
                sections,
                heading=heading,
                body=body,
                remaining=remaining,
            )

    if include_current_message and input.latest_user_message:
        sections.insert(
            2,
            f"Current patient message:\n{input.latest_user_message}",
        )

    return sections


def build_context_sections(input: TherapyTurnInput) -> list[str]:
    return build_therapy_context(input, include_current_message=True)


def build_opening_context_sections(input: TherapyTurnInput) -> list[str]:
    sections = [
        (f"Patient: {input.profile.name}, language={input.profile.primary_language}"),
        *build_therapy_context(input, include_current_message=False),
    ]
    return sections
