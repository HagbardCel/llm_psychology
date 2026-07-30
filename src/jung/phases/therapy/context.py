"""Deterministic therapy context assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from jung.domain.grounding import GroundedPatientTurn, parse_grounded_patient_turns
from jung.phases.context_bounds import (
    bounded_text,
    newest_lines_within_budget,
    pack_complete_json_items,
)
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.transcript import normalize_transcript_content

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


def _append_prebounded_optional_section(
    sections: list[str],
    *,
    heading: str,
    body: str,
    remaining: int,
) -> int:
    """Append a body already compacted to fit; never character-slice again."""
    if not body:
        return remaining
    separator_cost = len(_SECTION_SEPARATOR) if sections else 0
    section = f"{heading}:\n{body}"
    required = separator_cost + len(section)
    if required > remaining:
        raise ValueError("prebounded optional section exceeds remaining budget")
    sections.append(section)
    return remaining - required


def _intervention_payload(item: Mapping[str, Any]) -> dict[str, object]:
    return {
        "intervention_description": item["intervention_description"],
        "status": item.get("status"),
        "therapist_sequence": item["therapist_sequence"],
        "therapist_content": item["therapist_content"],
        "patient_sequence": item.get("patient_sequence"),
        "patient_content": item.get("patient_content"),
    }


def _patient_turn_payload(item: GroundedPatientTurn) -> dict[str, object]:
    return {
        "source_sequence": item.source_sequence,
        "content": item.content,
    }


def _compact_session_briefing_json(
    briefing: Mapping[str, Any],
    limit: int,
) -> str:
    raw_evidence = briefing.get("intervention_evidence")
    if raw_evidence is None:
        evidence_items: list[Mapping[str, Any]] = []
    elif not isinstance(raw_evidence, list):
        raise ValueError("intervention_evidence must be a list")
    else:
        evidence_items = [item for item in raw_evidence if isinstance(item, Mapping)]
        if len(evidence_items) != len(raw_evidence):
            raise ValueError("intervention_evidence items must be objects")

    narrative_keys = (
        "narrative_handoff",
        "continuity_points",
        "unresolved_issues",
        "recommended_opening_focus",
        "things_to_avoid",
        "emotional_context",
    )

    def render(selected: Sequence[Mapping[str, Any]], omitted: int) -> str:
        document: dict[str, object] = {}
        for key in narrative_keys:
            if key not in briefing:
                continue
            value = briefing[key]
            if isinstance(value, list):
                document[key] = [
                    bounded_text(str(item), 200) for item in value if str(item).strip()
                ]
            elif isinstance(value, str):
                document[key] = bounded_text(value, 400)
            else:
                document[key] = value
        document["intervention_evidence"] = [
            _intervention_payload(item) for item in selected
        ]
        document["intervention_evidence_omitted"] = omitted
        return json.dumps(document, ensure_ascii=True, separators=(",", ":"))

    packed = pack_complete_json_items(
        evidence_items,
        limit=limit,
        render_document=render,
    )
    if packed is None:
        return ""
    return render(packed.items, packed.omitted)


def _compact_derived_profile_json(
    profile: Mapping[str, Any],
    limit: int,
) -> str:
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


def build_untrusted_therapy_document(
    input: TherapyTurnInput,
    *,
    include_current_message: bool,
) -> dict[str, object]:
    """Build the untrusted JSON context for therapy prompts."""
    limits = input.context_limits
    document: dict[str, object] = {
        "current_plan": {
            "focus": input.current_plan.focus,
            "themes": list(input.current_plan.themes),
            "goals": list(input.current_plan.goals),
            "current_progress": input.current_plan.current_progress,
            "planned_interventions": list(input.current_plan.planned_interventions),
        }
    }

    remaining = max(0, limits.max_total_chars - len(json.dumps(document)))

    latest_message = input.latest_user_message if include_current_message else None
    transcript_lines = _transcript_lines(
        input,
        latest_user_message=latest_message,
    )
    if transcript_lines and remaining > 0:
        selected_lines = newest_lines_within_budget(
            transcript_lines,
            min(limits.max_section_chars, remaining),
        )
        if selected_lines:
            document["active_session_transcript"] = "\n".join(selected_lines)
            remaining = max(
                0,
                limits.max_total_chars - len(json.dumps(document, ensure_ascii=True)),
            )

    if input.session_briefing and remaining > 0:
        briefing = _compact_session_briefing_json(
            input.session_briefing,
            min(limits.max_section_chars, remaining),
        )
        if briefing:
            document["session_briefing"] = json.loads(briefing)
            remaining = max(
                0,
                limits.max_total_chars - len(json.dumps(document, ensure_ascii=True)),
            )

    if input.derived_profile and remaining > 0:
        derived = _compact_derived_profile_json(
            input.derived_profile,
            min(limits.max_section_chars, remaining),
        )
        if derived:
            document["derived_profile"] = json.loads(derived)
            remaining = max(
                0,
                limits.max_total_chars - len(json.dumps(document, ensure_ascii=True)),
            )

    if input.recent_session_summaries and remaining > 0:
        summaries = newest_lines_within_budget(
            input.recent_session_summaries,
            min(limits.max_section_chars, remaining),
            separator="\n",
        )
        if summaries:
            document["recent_session_summaries"] = list(summaries)

    if include_current_message and input.latest_user_message:
        document["current_patient_message"] = input.latest_user_message

    return document


def build_therapy_context(
    input: TherapyTurnInput,
    *,
    include_current_message: bool,
) -> list[str]:
    """Section list for tests and diagnostics (plan + optional data only)."""
    limits = input.context_limits
    plan_prefix = f"{_PLAN_HEADING}:\n"
    plan_body = bounded_text(
        format_plan_section(input),
        min(
            limits.max_section_chars, max(0, limits.max_total_chars - len(plan_prefix))
        ),
    )
    sections = [f"{plan_prefix}{plan_body}"]
    remaining = max(0, limits.max_total_chars - len(sections[0]))

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
        if transcript:
            remaining = _append_prebounded_optional_section(
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
        briefing = _compact_session_briefing_json(
            input.session_briefing, payload_budget
        )
        if briefing:
            remaining = _append_prebounded_optional_section(
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
        derived = _compact_derived_profile_json(input.derived_profile, payload_budget)
        if derived:
            remaining = _append_prebounded_optional_section(
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
            remaining = _append_prebounded_optional_section(
                sections,
                heading=heading,
                body=body,
                remaining=remaining,
            )

    if include_current_message and input.latest_user_message:
        sections.insert(
            1,
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
