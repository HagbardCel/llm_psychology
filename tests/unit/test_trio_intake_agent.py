"""
Unit tests for TrioIntakeAgent.

Focus on intake completion and time-up behavior.
"""

from datetime import datetime, timedelta

import pytest

from psychoanalyst_app.agents.intake import (
    GOAL_PREFERENCE_PROMPT,
    RISK_SCREEN_PROMPT,
    TrioIntakeAgent,
)
from psychoanalyst_app.agents.intake.prompts import CLOSING_PROMPT
from psychoanalyst_app.agents.intake.slots import (
    identify_covered_topics,
    identify_required_slots,
)
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.domain import Message, UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import ConversationContext, WorkflowEvent


def _make_context(
    *,
    user_profile: UserProfile,
    topics_covered: list[str],
    session_start_time: datetime,
    duration_minutes: int,
    message_history: list[Message] | None = None,
) -> ConversationContext:
    return ConversationContext(
        session_id="session-123",
        user_profile=user_profile,
        therapy_plan=None,
        message_history=message_history
        or [Message(role="assistant", content="Previous prompt", timestamp=datetime.now())],
        topics_covered=topics_covered,
        session_start_time=session_start_time,
        duration_minutes=duration_minutes,
    )


@pytest.fixture
def intake_agent(mock_llm_service, app_config):
    """Create a TrioIntakeAgent for testing."""
    return TrioIntakeAgent(
        llm_service=mock_llm_service,
        user_context=UserContext("user-123"),
        config=app_config,
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_intake_completion_uses_closing_prompt(intake_agent, app_config):
    """Ensure completion uses the closing prompt and triggers the intake transition."""
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    context = _make_context(
        user_profile=profile,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        message_history=[
            Message(
                role="user",
                content=(
                    "For the last few weeks I have been anxious about a work "
                    "deadline, sleeping badly, and trying breathing exercises."
                ),
                timestamp=datetime.now(),
            ),
            Message(role="assistant", content=RISK_SCREEN_PROMPT, timestamp=datetime.now()),
            Message(
                role="user",
                content="No thoughts of harm, and the chest tightness is not urgent.",
                timestamp=datetime.now(),
            ),
            Message(role="assistant", content=GOAL_PREFERENCE_PROMPT, timestamp=datetime.now()),
            Message(
                role="user",
                content="I want to sleep better and stop freezing at work.",
                timestamp=datetime.now(),
            ),
        ],
    )

    response = await intake_agent.process_message(
        "I want to keep going.",
        context,
    )

    assert response.content == CLOSING_PROMPT
    assert response.workflow_event == WorkflowEvent.COMPLETE_INTAKE
    assert response.next_action == "transition"
    assert response.metadata["is_direct_response"] is True
    assert "?" not in response.content


def test_intake_topic_coverage_ignores_assistant_prompts():
    """Assistant-authored checklists must not satisfy patient intake coverage."""
    covered = identify_covered_topics(
        "I am not sure.",
        [
            Message(
                role="assistant",
                content="Tell me about work, family, relationships, health, alcohol, and goals.",
                timestamp=datetime.now(),
            )
        ],
    )

    assert covered == []


def test_intake_slot_coverage_counts_substance_based_coping():
    slots = identify_required_slots(
        "I have been drinking wine to get to sleep when work stress builds.",
        [],
    )

    assert "coping_attempts" in slots


@pytest.mark.trio
@pytest.mark.unit
async def test_time_up_without_completion_ends_with_notice(intake_agent):
    """Ensure time-up ends the session without transitioning intake."""
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    context = _make_context(
        user_profile=profile,
        topics_covered=[],
        session_start_time=datetime.now() - timedelta(minutes=90),
        duration_minutes=30,
    )

    response = await intake_agent.process_message(
        "Answering a question.",
        context,
    )

    assert response.content == (
        "Our time is up for today. We will continue this intake in our next session."
    )
    assert response.workflow_event is None
    assert response.next_action == "continue"
    assert response.metadata["is_direct_response"] is True
