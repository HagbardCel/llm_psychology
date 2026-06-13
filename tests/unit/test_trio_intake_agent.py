"""
Unit tests for TrioIntakeAgent.

Focus on intake completion and time-up behavior.
"""

from datetime import datetime, timedelta

import pytest

from psychoanalyst_app.agents.intake import (
    COPING_ATTEMPTS_PROMPT,
    GOAL_PREFERENCE_PROMPT,
    MAX_INTAKE_PATIENT_TURNS,
    RISK_SCREEN_PROMPT,
    TrioIntakeAgent,
)
from psychoanalyst_app.agents.intake.prompts import CLOSING_PROMPT
from psychoanalyst_app.agents.intake.slots import (
    identify_covered_topics,
    identify_required_slots,
    intake_completion_diagnostics,
    intake_slot_evidence,
    is_intake_complete,
    next_required_follow_up,
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


@pytest.mark.parametrize(
    "message",
    [
        "I tried breathing exercises before meetings.",
        "Mostly I avoid speaking unless I have to.",
        "I take sleep medication when it gets bad.",
        "I have been talking to someone about it.",
        "I have not tried anything yet.",
    ],
)
def test_intake_slot_coverage_counts_common_coping_answers(message):
    slots = identify_required_slots(message, [])

    assert "coping_attempts" in slots


def test_duration_slot_requires_explicit_patient_evidence():
    slots = identify_required_slots(
        "The tightness starts when I open email and feels urgent recently.",
        [],
    )
    evidence = intake_slot_evidence(
        "The tightness starts when I open email and feels urgent recently.",
        [],
    )

    assert "duration" not in slots
    assert evidence["duration"]["status"] == "missing"
    assert evidence["duration"]["evidence_quote"] is None


@pytest.mark.parametrize(
    "message",
    [
        "This has been happening for three months.",
        "I have felt this way since January.",
        "It happens twice a week before meetings.",
        "For the past few weeks I have been anxious before work.",
    ],
)
def test_duration_slot_counts_clear_duration_or_frequency(message):
    slots = identify_required_slots(message, [])
    evidence = intake_slot_evidence(message, [])

    assert "duration" in slots
    assert evidence["duration"]["status"] == "covered"
    assert evidence["duration"]["explicitness"] == "explicit"
    assert evidence["duration"]["evidence_role"] == "user"
    assert evidence["duration"]["evidence_quote"]


def test_hard_slots_ignore_assistant_authored_evidence():
    slots = identify_required_slots(
        "I am not sure.",
        [
            Message(
                role="assistant",
                content=(
                    "The patient has anxiety for months, work impairment, "
                    "goals, and no safety concerns."
                ),
                timestamp=datetime.now(),
            )
        ],
    )

    assert not {
        "presenting_problem",
        "duration",
        "functional_impairment",
        "risk_screen",
        "goal_preference",
    } & slots


def test_next_required_follow_up_includes_coping_attempts_after_hard_prompts():
    covered = {
        "risk_screen",
        "goal_preference",
        "presenting_problem",
        "duration",
        "functional_impairment",
        "sleep_impact",
    }

    assert next_required_follow_up(covered) == COPING_ATTEMPTS_PROMPT


def test_intake_completes_after_max_turns_with_only_soft_slots_missing():
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
                    f"Turn {index}: anxiety for several months affects "
                    "work deadlines."
                ),
                timestamp=datetime.now(),
            )
            for index in range(MAX_INTAKE_PATIENT_TURNS)
        ]
        + [
            Message(role="assistant", content=RISK_SCREEN_PROMPT, timestamp=datetime.now()),
            Message(
                role="user",
                content="No thoughts of harm and I feel safe.",
                timestamp=datetime.now(),
            ),
            Message(role="assistant", content=GOAL_PREFERENCE_PROMPT, timestamp=datetime.now()),
            Message(
                role="user",
                content="I want to feel better at work.",
                timestamp=datetime.now(),
            ),
        ],
    )
    covered = {
        "risk_screen",
        "goal_preference",
        "presenting_problem",
        "duration",
        "functional_impairment",
    }

    diagnostics = intake_completion_diagnostics(context, covered)

    assert is_intake_complete(context, covered)
    assert diagnostics["missing_soft_slots"] == ["coping_attempts", "sleep_impact"]
    assert diagnostics["max_turn_completion"] is True


def test_intake_does_not_complete_without_risk_screen_after_max_turns():
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
                    f"Turn {index}: anxiety for several months affects "
                    "work and sleep."
                ),
                timestamp=datetime.now(),
            )
            for index in range(MAX_INTAKE_PATIENT_TURNS + 1)
        ]
        + [
            Message(role="assistant", content=GOAL_PREFERENCE_PROMPT, timestamp=datetime.now()),
            Message(
                role="user",
                content="I want to feel better at work.",
                timestamp=datetime.now(),
            ),
        ],
    )
    covered = {
        "goal_preference",
        "presenting_problem",
        "duration",
        "functional_impairment",
        "sleep_impact",
        "coping_attempts",
    }

    diagnostics = intake_completion_diagnostics(context, covered)

    assert not is_intake_complete(context, covered)
    assert diagnostics["missing_hard_slots"] == ["risk_screen"]


def test_intake_does_not_complete_without_duration_evidence_after_max_turns():
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
                content=f"Turn {index}: anxiety recently affects work and sleep.",
                timestamp=datetime.now(),
            )
            for index in range(MAX_INTAKE_PATIENT_TURNS)
        ]
        + [
            Message(role="assistant", content=RISK_SCREEN_PROMPT, timestamp=datetime.now()),
            Message(
                role="user",
                content="No thoughts of harm and I feel safe.",
                timestamp=datetime.now(),
            ),
            Message(role="assistant", content=GOAL_PREFERENCE_PROMPT, timestamp=datetime.now()),
            Message(
                role="user",
                content="I want to feel better at work.",
                timestamp=datetime.now(),
            ),
        ],
    )
    covered = {
        "risk_screen",
        "goal_preference",
        "presenting_problem",
        "duration",
        "functional_impairment",
        "sleep_impact",
        "coping_attempts",
    }

    diagnostics = intake_completion_diagnostics(context, covered)

    assert not is_intake_complete(context, covered)
    assert "duration" in diagnostics["missing_hard_slots"]
    assert diagnostics["slot_evidence"]["duration"]["status"] == "missing"


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
