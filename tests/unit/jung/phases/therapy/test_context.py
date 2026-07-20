"""Therapy context budgeting tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import Plan, Profile
from jung.phases.therapy.context import (
    _SECTION_SEPARATOR,
    build_context_sections,
    build_opening_context_sections,
)
from jung.phases.therapy.models import TherapyContextLimits, TherapyTurnInput
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles


def _plan() -> Plan:
    now = datetime.now(UTC)
    return Plan(
        id=uuid4(),
        version=1,
        selected_style="cbt",
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
        created_at=now,
    )


def _turn(sequence: int, role: str, content: str) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=sequence,
        role=role,
        content=content,
    )


def _input(**overrides: object) -> TherapyTurnInput:
    values: dict[str, object] = {
        "profile": Profile(name="Alex", primary_language="English"),
        "current_plan": _plan(),
        "selected_style": load_styles()["cbt"],
        "context_limits": TherapyContextLimits(
            max_transcript_turns=6,
            max_section_chars=200,
            max_total_chars=1000,
        ),
    }
    values.update(overrides)
    return TherapyTurnInput(**values)


def test_current_message_preserved_under_tight_budget() -> None:
    huge = "x" * 5000
    sections = build_context_sections(
        _input(
            latest_user_message=huge,
            transcript=(
                _turn(1, "assistant", "hello"),
                _turn(2, "user", huge),
            ),
        )
    )
    combined = "\n".join(sections)
    assert huge in combined
    assert combined.count(huge) == 1


def test_message_exceeding_total_budget_still_present() -> None:
    message = "y" * 2000
    sections = build_context_sections(
        _input(
            latest_user_message=message,
            transcript=(_turn(1, "user", message),),
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=200,
                max_total_chars=1000,
            ),
            session_briefing={"summary": "x" * 5000},
            derived_profile={"observations": ["y" * 5000]},
            recent_session_summaries=("z" * 5000,),
        )
    )
    combined = "\n".join(sections)
    assert message in combined
    assert combined.count(message) == 1
    assert "x" * 5000 not in combined
    assert "y" * 5000 not in combined
    assert "z" * 5000 not in combined


def test_transcript_dedupe_keeps_earlier_identical_user_turn() -> None:
    duplicate = "I feel anxious"
    sections = build_context_sections(
        _input(
            latest_user_message=duplicate,
            transcript=(
                _turn(1, "user", duplicate),
                _turn(2, "assistant", "Tell me more."),
                _turn(3, "user", duplicate),
            ),
        )
    )
    combined = "\n".join(sections)
    assert combined.count(duplicate) == 2
    assert "user: I feel anxious" in combined
    assert "Current patient message:\nI feel anxious" in combined


def test_opening_context_respects_total_budget() -> None:
    sections = build_opening_context_sections(
        _input(
            is_opening_turn=True,
            session_briefing={"summary": "b" * 5000},
            derived_profile={"observations": ["p" * 5000]},
            recent_session_summaries=("s" * 5000,),
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=2500,
                max_total_chars=1000,
            ),
            selected_style=load_styles()["cbt"],
        )
    )
    compressible = [
        section for section in sections if not section.startswith("Patient:")
    ]
    rendered = _SECTION_SEPARATOR.join(compressible)
    style_section = next(
        section
        for section in compressible
        if section.startswith("Therapy style instructions:")
    )
    plan_section = next(
        section for section in compressible if section.startswith("Current plan:")
    )
    assert style_section.split(":\n", 1)[1].strip()
    assert plan_section.split(":\n", 1)[1].strip()
    assert len(rendered) <= 1000


def test_dual_core_sections_preserve_style_and_plan_bodies() -> None:
    style = load_styles()["cbt"]
    huge_instructions = style.therapist_instructions + (" EXTRA " * 500)
    style = replace(style, therapist_instructions=huge_instructions)
    sections = build_opening_context_sections(
        _input(
            is_opening_turn=True,
            selected_style=style,
            session_briefing={"summary": "b" * 5000},
            derived_profile={"observations": ["p" * 5000]},
            recent_session_summaries=("s" * 5000,),
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=2500,
                max_total_chars=1000,
            ),
        )
    )
    compressible = [
        section for section in sections if not section.startswith("Patient:")
    ]
    rendered = _SECTION_SEPARATOR.join(compressible)
    style_section = next(
        section
        for section in compressible
        if section.startswith("Therapy style instructions:")
    )
    plan_section = next(
        section for section in compressible if section.startswith("Current plan:")
    )
    assert style_section.split(":\n", 1)[1].strip()
    assert plan_section.split(":\n", 1)[1].strip()
    assert len(rendered) <= 1000


def test_opening_context_includes_session_briefing() -> None:
    briefing = {"summary": "prior sleep focus"}
    sections = build_opening_context_sections(
        _input(is_opening_turn=True, session_briefing=briefing),
    )
    combined = "\n".join(sections)
    assert "prior sleep focus" in combined
    assert "Session briefing:" in combined


def test_oversized_transcript_retains_final_exchange() -> None:
    sections = build_context_sections(
        _input(
            latest_user_message="brand new answer",
            transcript=(
                _turn(1, "user", "old " * 500),
                _turn(2, "assistant", "How did that feel?"),
            ),
            context_limits=TherapyContextLimits(
                max_transcript_turns=6,
                max_section_chars=200,
                max_total_chars=1000,
            ),
        )
    )
    combined = "\n\n".join(sections)
    transcript_section = next(
        section
        for section in sections
        if section.startswith("Active session transcript:")
    )
    transcript_body = transcript_section.split(":\n", 1)[1]
    assert combined.count("Current patient message:\nbrand new answer") == 1
    assert "How did that feel?" in transcript_body
    assert "old " * 50 not in transcript_body
