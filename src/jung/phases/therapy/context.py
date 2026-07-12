"""Deterministic therapy context assembly."""

from __future__ import annotations

import json
from typing import Any

from jung.phases.therapy.models import TherapyTurnInput


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def format_plan_section(input: TherapyTurnInput) -> str:
    plan = input.current_plan
    return _truncate(
        "\n".join(
            [
                f"Focus: {plan.focus}",
                f"Themes: {', '.join(plan.themes) or 'None'}",
                f"Goals: {', '.join(plan.goals)}",
                f"Progress: {plan.current_progress}",
                f"Interventions: {', '.join(plan.planned_interventions)}",
            ]
        ),
        input.context_limits.max_section_chars,
    )


def format_briefing_section(briefing: dict[str, Any] | None, limit: int) -> str:
    if not briefing:
        return ""
    return _truncate(json.dumps(briefing, ensure_ascii=True), limit)


def format_derived_profile_section(
    derived_profile: dict[str, Any] | None,
    limit: int,
) -> str:
    if not derived_profile:
        return ""
    return _truncate(json.dumps(derived_profile, ensure_ascii=True), limit)


def bounded_transcript(input: TherapyTurnInput) -> str:
    turns = input.transcript[-input.context_limits.max_transcript_turns :]
    lines = [f"{turn.role}: {turn.content}" for turn in turns]
    return _truncate(
        "\n".join(lines),
        input.context_limits.max_section_chars,
    )


def build_context_sections(input: TherapyTurnInput) -> list[str]:
    sections = [
        f"Patient: {input.profile.name}, language={input.profile.primary_language}",
        f"Therapy style instructions:\n{input.selected_style.therapist_instructions}",
        f"Current plan:\n{format_plan_section(input)}",
    ]
    if input.latest_user_message:
        sections.append(f"Current patient message:\n{input.latest_user_message}")
    transcript = bounded_transcript(input)
    if transcript:
        sections.append(f"Active session transcript:\n{transcript}")
    briefing = format_briefing_section(
        input.session_briefing,
        input.context_limits.max_section_chars,
    )
    if briefing:
        sections.append(f"Session briefing:\n{briefing}")
    derived = format_derived_profile_section(
        input.derived_profile,
        input.context_limits.max_section_chars,
    )
    if derived:
        sections.append(f"Derived profile:\n{derived}")
    if input.recent_session_summaries:
        summaries = _truncate(
            "\n".join(input.recent_session_summaries),
            input.context_limits.max_section_chars,
        )
        sections.append(f"Recent session summaries:\n{summaries}")

    combined = "\n\n".join(sections)
    return [_truncate(combined, input.context_limits.max_total_chars)]
