"""Therapy turn input contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import Plan, Profile
from jung.phases.therapy.models import TherapyTurnInput
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


def _turn() -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=1,
        role="user",
        content="hello",
    )


def test_opening_turn_requires_empty_transcript_and_no_message() -> None:
    TherapyTurnInput(
        profile=Profile(name="Alex", primary_language="English"),
        current_plan=_plan(),
        selected_style=load_styles()["cbt"],
        is_opening_turn=True,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_opening_turn": True, "latest_user_message": "hello"},
        {"is_opening_turn": True, "transcript": (_turn(),)},
    ],
)
def test_opening_turn_rejects_contradictory_state(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        TherapyTurnInput(
            profile=Profile(name="Alex", primary_language="English"),
            current_plan=_plan(),
            selected_style=load_styles()["cbt"],
            **overrides,
        )


def test_continuation_requires_latest_user_message() -> None:
    with pytest.raises(ValueError):
        TherapyTurnInput(
            profile=Profile(name="Alex", primary_language="English"),
            current_plan=_plan(),
            selected_style=load_styles()["cbt"],
        )


def test_selected_style_must_match_plan() -> None:
    with pytest.raises(ValueError):
        TherapyTurnInput(
            profile=Profile(name="Alex", primary_language="English"),
            current_plan=_plan(),
            selected_style=load_styles()["jung"],
            latest_user_message="hello",
        )
