"""Therapy processor tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from jung.domain.models import Plan, Profile
from jung.llm.fake import FakeLLM, StreamExpectation
from jung.llm.gateway import LLMTask, ModelPolicy
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.therapy.processor import TherapyProcessor
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


async def test_build_messages_includes_style_and_plan() -> None:
    processor = TherapyProcessor(
        FakeLLM([]),
        response_policy=ModelPolicy(
            task=LLMTask.THERAPY_RESPONSE,
            model="fake",
            temperature=0.7,
            timeout_seconds=30.0,
        ),
    )
    style = load_styles()["cbt"]
    messages = processor.build_messages(
        TherapyTurnInput(
            profile=Profile(name="Alex", primary_language="English"),
            current_plan=_plan(),
            latest_user_message="I slept poorly again.",
            selected_style=style,
        )
    )
    combined = "\n".join(message.content for message in messages)
    assert style.therapist_instructions in combined
    assert "anxiety" in combined
    assert "I slept poorly again." in combined


async def test_stream_response_passes_chunks_unchanged() -> None:
    gateway = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("Hello", " there"),
            )
        ]
    )
    processor = TherapyProcessor(
        gateway,
        response_policy=ModelPolicy(
            task=LLMTask.THERAPY_RESPONSE,
            model="fake",
            temperature=0.7,
            timeout_seconds=30.0,
        ),
    )
    chunks = [
        chunk
        async for chunk in processor.stream_response(
            TherapyTurnInput(
                profile=Profile(name="Alex", primary_language="English"),
                current_plan=_plan(),
                latest_user_message="Hi",
                selected_style=load_styles()["cbt"],
            )
        )
    ]
    assert chunks == ["Hello", " there"]
    gateway.assert_exhausted()
