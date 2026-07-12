"""Therapy context budgeting tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import Plan, Profile
from jung.phases.therapy.context import (
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
        )
    )
    assert any(message in section for section in sections)


def test_opening_context_includes_session_briefing() -> None:
    briefing = {"summary": "prior sleep focus"}
    sections = build_opening_context_sections(
        _input(session_briefing=briefing),
    )
    combined = "\n".join(sections)
    assert "prior sleep focus" in combined
    assert "Session briefing:" in combined
