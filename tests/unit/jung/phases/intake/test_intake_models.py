"""Intake turn input contract tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.domain.models import Profile
from jung.phases.intake.models import IntakeTurnInput
from jung.phases.transcript import TranscriptTurn


def _turn(role: str, content: str) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=1,
        role=role,
        content=content,
    )


def _profile() -> Profile:
    return Profile(name="Alex", primary_language="English")


@pytest.mark.parametrize(
    ("transcript", "latest_user_message"),
    [
        ((), None),
        (
            (_turn("user", "I feel anxious"),),
            "I feel anxious",
        ),
    ],
)
def test_intake_turn_input_accepts_valid_shapes(
    transcript: tuple[TranscriptTurn, ...],
    latest_user_message: str | None,
) -> None:
    IntakeTurnInput(
        profile=_profile(),
        transcript=transcript,
        latest_user_message=latest_user_message,
    )


@pytest.mark.parametrize(
    ("transcript", "latest_user_message"),
    [
        (
            (_turn("user", "I feel anxious"),),
            "different answer",
        ),
        (
            (_turn("assistant", "Tell me more."),),
            "I feel anxious",
        ),
        (
            (_turn("user", "I feel anxious"),),
            None,
        ),
    ],
)
def test_intake_turn_input_rejects_incoherent_shapes(
    transcript: tuple[TranscriptTurn, ...],
    latest_user_message: str | None,
) -> None:
    with pytest.raises(ValueError):
        IntakeTurnInput(
            profile=_profile(),
            transcript=transcript,
            latest_user_message=latest_user_message,
        )
