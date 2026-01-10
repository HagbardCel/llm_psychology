"""
Unit tests for TrioIntakeAgent.

Focus on intake completion and time-up behavior.
"""

from datetime import datetime, timedelta

import pytest

from psychoanalyst_app.agents.trio_intake_agent import TrioIntakeAgent
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import Message, UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import ConversationContext, WorkflowEvent
from psychoanalyst_app.prompts.intake_prompts import CLOSING_PROMPT


def _make_context(
    *,
    user_profile: UserProfile,
    topics_covered: list[str],
    session_start_time: datetime,
    duration_minutes: int,
    message_history: list[Message] | None = None,
) -> ConversationContext:
    return ConversationContext(
        session_block_id="session-123",
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
    topics_threshold = int(len(app_config.INTAKE_TOPICS) * 0.8)
    covered_topics = app_config.INTAKE_TOPICS[:topics_threshold]

    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    context = _make_context(
        user_profile=profile,
        topics_covered=covered_topics,
        session_start_time=datetime.now(),
        duration_minutes=50,
    )

    response = await intake_agent.process_message(
        "I want to keep going.",
        context,
    )

    assert response.content == CLOSING_PROMPT
    assert response.workflow_event == WorkflowEvent.COMPLETE_INTAKE
    assert response.next_action == "transition"


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
