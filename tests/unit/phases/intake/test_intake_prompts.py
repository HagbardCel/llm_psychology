"""Intake prompt semantics tests."""

from __future__ import annotations

from uuid import uuid4

from jung.domain.models import Profile
from jung.llm.gateway import ChatRole
from jung.phases.intake.completion import missing_items_from_record
from jung.phases.intake.models import IntakeRecord
from jung.phases.intake.prompts import (
    PROMPT_VERSION,
    build_patch_extraction_messages,
    build_response_messages,
)
from jung.phases.transcript import TranscriptTurn


def test_patch_extraction_uses_negative_ownership_boundary() -> None:
    assert PROMPT_VERSION == "intake-v4"
    user_turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=1,
        role="user",
        content="I've been anxious in seminars lately.",
    )
    messages = build_patch_extraction_messages(
        record=IntakeRecord(),
        latest_user_message=user_turn,
        previous_assistant_message=None,
        prompted_item="presenting_problem",
    )
    joined = "\n".join(message.content for message in messages)
    assert "Prompted item: presenting_problem" in joined
    assert "source_role=" not in joined
    assert "source_message_sequence=" not in joined
    assert "direct_ask=" not in joined
    assert (
        "Do not invent provenance, source identifiers, or direct-ask flags." in joined
    )


def test_patch_extraction_includes_category_c_safety_guidance() -> None:
    user_turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=2,
        role="user",
        content="I am not thinking about harming myself or anyone else.",
    )
    messages = build_patch_extraction_messages(
        record=IntakeRecord(),
        latest_user_message=user_turn,
        previous_assistant_message="Are you having thoughts of harming yourself or others?",
        prompted_item="risk_screen",
    )
    joined = "\n".join(message.content for message in messages)
    assert "Prompted item: risk_screen" in joined
    assert "response_status informative" in joined
    assert "risk_screen" in joined
    assert "presenting_problem.main_concern" in joined
    assert "source_role=" not in joined


def test_opening_targets_presenting_problem() -> None:
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
    assert "presenting problem" in messages[0].content
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
