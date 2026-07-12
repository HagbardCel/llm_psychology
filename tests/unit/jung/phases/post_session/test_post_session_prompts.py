"""Post-session prompt construction tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import Plan, Profile
from jung.phases.post_session.models import (
    PostSessionInput,
    SessionAnalysisResult,
)
from jung.phases.post_session.prompts import (
    build_analysis_messages,
    build_update_messages,
)
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


def _input() -> PostSessionInput:
    style = load_styles()["cbt"]
    return PostSessionInput(
        transcript=(
            TranscriptTurn(
                message_id=uuid4(),
                sequence=1,
                role="user",
                content="I slept badly.",
            ),
        ),
        current_plan=_plan(),
        profile=Profile(name="Alex", primary_language="English"),
        selected_style=style,
    )


def test_analysis_prompt_includes_style_instructions() -> None:
    messages = build_analysis_messages(_input())
    combined = "\n".join(message.content for message in messages)
    style = load_styles()["cbt"]
    assert style.post_session_instructions in combined
    assert "I slept badly." in combined


def test_update_prompt_omits_raw_transcript() -> None:
    analysis = SessionAnalysisResult(
        summary="Sleep difficulties explored.",
        key_themes=("sleep",),
    )
    messages = build_update_messages(_input(), analysis)
    combined = "\n".join(message.content for message in messages)
    assert "I slept badly." not in combined
    assert "Sleep difficulties explored." in combined
