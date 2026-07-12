"""Deterministic therapy context assembly."""

from __future__ import annotations

from jung.phases.context_bounds import bounded_json, bounded_text, newest_within_budget
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


def _transcript_lines(
    input: TherapyTurnInput,
    *,
    exclude_latest_user: bool,
) -> list[str]:
    turns = list(input.transcript[-input.context_limits.max_transcript_turns :])
    if exclude_latest_user and turns and turns[-1].role == "user":
        turns = turns[:-1]
    return [f"{turn.role}: {turn.content}" for turn in turns]


def build_context_sections(input: TherapyTurnInput) -> list[str]:
    limits = input.context_limits
    sections: list[str] = []

    style_section = bounded_text(
        input.selected_style.therapist_instructions,
        limits.max_section_chars,
    )
    plan_section = bounded_text(format_plan_section(input), limits.max_section_chars)
    sections.append(f"Therapy style instructions:\n{style_section}")
    sections.append(f"Current plan:\n{plan_section}")

    if input.latest_user_message:
        sections.append(
            f"Current patient message:\n{input.latest_user_message}"
        )

    optional_budget = limits.max_total_chars
    optional_budget -= sum(len(section) + 2 for section in sections)

    transcript_lines = _transcript_lines(input, exclude_latest_user=True)
    if transcript_lines:
        transcript = bounded_text(
            "\n".join(reversed(transcript_lines)),
            max(0, optional_budget // 2),
        )
        if transcript:
            sections.append(f"Active session transcript:\n{transcript}")
            optional_budget -= len(transcript) + 28

    if input.session_briefing:
        briefing = bounded_json(input.session_briefing, max(0, optional_budget // 3))
        if briefing:
            sections.append(f"Session briefing:\n{briefing}")
            optional_budget -= len(briefing) + 20

    if input.derived_profile:
        derived = bounded_json(input.derived_profile, max(0, optional_budget // 3))
        if derived:
            sections.append(f"Derived profile:\n{derived}")
            optional_budget -= len(derived) + 18

    if input.recent_session_summaries:
        summaries = newest_within_budget(
            input.recent_session_summaries,
            max(0, optional_budget),
        )
        if summaries:
            sections.append(
                "Recent session summaries:\n" + "\n".join(summaries)
            )

    return sections


def build_opening_context_sections(input: TherapyTurnInput) -> list[str]:
    limits = input.context_limits
    style = bounded_text(
        input.selected_style.therapist_instructions,
        limits.max_section_chars,
    )
    sections = [
        f"Patient: {input.profile.name}, language={input.profile.primary_language}",
        f"Therapy style instructions:\n{style}",
        (
            "Current plan:\n"
            f"{bounded_text(format_plan_section(input), limits.max_section_chars)}"
        ),
    ]
    if input.session_briefing:
        briefing = bounded_json(
            input.session_briefing,
            limits.max_section_chars,
        )
        if briefing:
            sections.append(f"Session briefing:\n{briefing}")
    if input.derived_profile:
        derived = bounded_json(input.derived_profile, limits.max_section_chars)
        if derived:
            sections.append(f"Derived profile:\n{derived}")
    if input.recent_session_summaries:
        summaries = newest_within_budget(
            input.recent_session_summaries,
            limits.max_section_chars,
        )
        if summaries:
            sections.append(
                "Recent session summaries:\n" + "\n".join(summaries)
            )
    return sections
