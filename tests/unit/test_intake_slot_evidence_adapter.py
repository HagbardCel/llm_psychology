from __future__ import annotations

import pytest

from psychoanalyst_app.shared.intake_slot_evidence import (
    GOAL_PREFERENCE_PROMPT,
    RISK_SCREEN_PROMPT,
    EvidenceMessage,
    intake_slot_evidence_from_messages,
    intake_slot_evidence_from_transcript,
)


def _transcript_from_messages(messages: list[EvidenceMessage]) -> list[dict[str, str]]:
    return [{"role": item["role"], "content": item["content"]} for item in messages]


def test_transcript_adapter_matches_message_history_entry_point():
    messages = [
        EvidenceMessage(
            role="user",
            content="I have been anxious about work for several months and sleeping badly.",
        ),
        EvidenceMessage(role="assistant", content=RISK_SCREEN_PROMPT),
        EvidenceMessage(
            role="user",
            content="No thoughts of harm. Chest tightness is not medically urgent.",
        ),
        EvidenceMessage(role="assistant", content=GOAL_PREFERENCE_PROMPT),
        EvidenceMessage(
            role="user",
            content="I want to sleep better and feel calmer at work.",
        ),
    ]

    assert intake_slot_evidence_from_transcript(
        _transcript_from_messages(messages)
    ) == intake_slot_evidence_from_messages(messages)


@pytest.mark.parametrize(
    ("message", "expected_status"),
    [
        ("This has been happening for three months.", "covered"),
        ("For the past few weeks I have been anxious before work.", "covered"),
        ("It happens twice a week before meetings.", "covered"),
        (
            "The tightness starts when I open email and feels urgent recently.",
            "missing",
        ),
    ],
)
def test_duration_evidence_stable_cases(message: str, expected_status: str):
    evidence = intake_slot_evidence_from_messages(
        [EvidenceMessage(role="user", content=message)]
    )

    assert evidence["duration"]["status"] == expected_status


@pytest.mark.parametrize(
    "answer",
    [
        "No thoughts of harm. Chest tightness is not medically urgent.",
        "No self-harm thoughts, but it feels medically urgent sometimes.",
    ],
)
def test_risk_screen_medical_urgency_answers_are_covered(answer: str):
    evidence = intake_slot_evidence_from_messages(
        [
            EvidenceMessage(role="assistant", content=RISK_SCREEN_PROMPT),
            EvidenceMessage(role="user", content=answer),
        ]
    )

    assert evidence["risk_screen"]["status"] == "covered"
    assert evidence["risk_screen"]["evidence_role"] == "user"
