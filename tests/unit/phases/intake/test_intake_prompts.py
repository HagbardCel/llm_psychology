"""Intake prompt semantics tests."""

from __future__ import annotations

from uuid import uuid4

from jung.domain.models import Profile
from jung.llm.gateway import ChatRole
from jung.phases.intake.completion import missing_items_from_record
from jung.phases.intake.models import IntakeRecord
from jung.phases.intake.prompts import build_response_messages
from jung.phases.transcript import TranscriptTurn


def test_opening_uses_multilingual_system_and_user_roles() -> None:
    profile = Profile(name="Alex", primary_language="Deutsch")
    messages = build_response_messages(
        profile=profile,
        record=IntakeRecord(),
        completeness=missing_items_from_record(IntakeRecord()),
        latest_user_message=None,
        transcript=(),
        is_opening=True,
    )
    assert messages[0].role is ChatRole.SYSTEM
    assert "Deutsch" in messages[0].content
    assert messages[1].role is ChatRole.USER
    assert "Alex" in messages[1].content


def test_continuation_excludes_duplicate_latest_user_turn() -> None:
    user_turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=1,
        role="user",
        content="I feel anxious",
    )
    record = IntakeRecord()
    completeness = missing_items_from_record(record)
    messages = build_response_messages(
        profile=Profile(name="Alex", primary_language="English"),
        record=record,
        completeness=completeness,
        latest_user_message="I feel anxious",
        transcript=(user_turn,),
        is_opening=False,
    )
    user_content = messages[-1].content
    assert user_content.count("I feel anxious") == 1
