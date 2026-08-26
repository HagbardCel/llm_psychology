"""Intake turn input contract tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.domain.models import Profile
from jung.phases.intake.models import IntakeTurnInput
from jung.phases.transcript import TranscriptTurn


def _turn(role: str, content: str, *, sequence: int = 1) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=sequence,
        role=role,
        content=content,
    )


def _profile() -> Profile:
    return Profile(name="Alex", primary_language="English")


@pytest.mark.parametrize(
    ("transcript", "latest_user_message", "patient_turn_count"),
    [
        ((), None, 0),
        (
            (_turn("user", "I feel anxious"),),
            "I feel anxious",
            1,
        ),
        (
            (
                _turn("user", "first", sequence=1),
                _turn("assistant", "ask", sequence=2),
                _turn("user", "second", sequence=3),
            ),
            "second",
            2,
        ),
    ],
)
def test_intake_turn_input_accepts_valid_shapes(
    transcript: tuple[TranscriptTurn, ...],
    latest_user_message: str | None,
    patient_turn_count: int,
) -> None:
    IntakeTurnInput(
        profile=_profile(),
        transcript=transcript,
        latest_user_message=latest_user_message,
        patient_turn_count=patient_turn_count,
    )


@pytest.mark.parametrize(
    ("transcript", "latest_user_message", "patient_turn_count"),
    [
        (
            (_turn("user", "I feel anxious"),),
            "different answer",
            1,
        ),
        (
            (_turn("assistant", "Tell me more."),),
            "I feel anxious",
            0,
        ),
        (
            (_turn("user", "I feel anxious"),),
            None,
            1,
        ),
        (
            (_turn("user", "I feel anxious"),),
            "I feel anxious",
            0,
        ),
        (
            (),
            None,
            1,
        ),
    ],
)
def test_intake_turn_input_rejects_incoherent_shapes(
    transcript: tuple[TranscriptTurn, ...],
    latest_user_message: str | None,
    patient_turn_count: int,
) -> None:
    with pytest.raises(ValueError):
        IntakeTurnInput(
            profile=_profile(),
            transcript=transcript,
            latest_user_message=latest_user_message,
            patient_turn_count=patient_turn_count,
        )
