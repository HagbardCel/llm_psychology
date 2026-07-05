"""
Unit tests for TrioIntakeAgent.

Focus on intake completion and time-up behavior.
"""

from datetime import datetime, timedelta

import pytest

from psychoanalyst_app.agents.intake import (
    MAX_INTAKE_PATIENT_TURNS,
    MIN_INTAKE_PATIENT_TURNS,
    TrioIntakeAgent,
)
from psychoanalyst_app.agents.intake.prompts import CLOSING_PROMPT
from psychoanalyst_app.agents.intake.record_completeness import (
    intake_record_completion_decision,
)
from psychoanalyst_app.agents.intake.slots import identify_covered_topics
from psychoanalyst_app.agents.note_taker import NoteTakerAgent
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.domain import Message, UserProfile, UserStatus
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
    PresentingProblemRecord,
    TimeCourseRecord,
)
from psychoanalyst_app.orchestration.models import ConversationContext, WorkflowEvent
from psychoanalyst_app.services.llm_phases import INTAKE_NOTE_TRACKING

RISK_SCREEN_PROMPT = "Have you had any thoughts of harming yourself or someone else?"
GOAL_PREFERENCE_PROMPT = "what would you most want to be different"


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


def _make_note_taker(mock_llm_service, app_config) -> NoteTakerAgent:
    return NoteTakerAgent(
        intake_llm_service=mock_llm_service,
        reflection_llm_service=mock_llm_service,
        config=app_config,
    )


def _make_intake_agent(
    mock_llm_service, app_config, user_id: str = "user-123"
) -> TrioIntakeAgent:
    return TrioIntakeAgent(
        llm_service=mock_llm_service,
        user_context=UserContext(user_id),
        config=app_config,
        note_taker_agent=_make_note_taker(mock_llm_service, app_config),
    )


@pytest.fixture
def intake_agent(mock_llm_service, app_config):
    """Create a TrioIntakeAgent for testing."""
    return _make_intake_agent(mock_llm_service, app_config)


@pytest.mark.trio
@pytest.mark.unit
async def test_intake_completion_uses_closing_prompt(mock_llm_service, app_config):
    """Ensure completion uses the closing prompt and triggers the intake transition."""
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return IntakeRecordPatch(no_new_information=True)

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _make_intake_agent(mock_llm_service, app_config)
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
    context.intake_record = _genuinely_complete_record()

    response = await agent.process_message(
        "Thanks, that covers everything.",
        context,
    )

    assert response.content == CLOSING_PROMPT
    assert response.workflow_event == WorkflowEvent.COMPLETE_INTAKE
    assert response.next_action == "transition"
    assert response.metadata["is_direct_response"] is True
    assert "?" not in response.content
    assert "user_profile" not in response.metadata


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


@pytest.mark.trio
@pytest.mark.unit
async def test_note_tracking_merges_patch_into_typed_metadata(
    mock_llm_service, app_config
):
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="anxiety",
                evidence_quote="I feel anxious every day",
                source_message_index=1,
                source_role="user",
                confidence="high",
            )
        )
    )

    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return patch

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _make_intake_agent(mock_llm_service, app_config)
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
            Message(role="assistant", content="What brings you in?", timestamp=datetime.now()),
            Message(
                role="user",
                content="I feel anxious every day",
                timestamp=datetime.now(),
            ),
        ],
    )

    response = await agent.process_message("I feel anxious every day", context)

    assert context.intake_record is None
    assert response.metadata["intake_record"]["presenting_problem"]["main_concern"][
        "value"
    ] == "anxiety"
    assert response.metadata["intake_note_tracking"]["status"] == "success"
    assert response.metadata["intake_note_tracking"]["attempted"] is True
    assert response.metadata["intake_note_tracking"]["merge_status"] == "applied"
    assert response.metadata["intake_note_tracking"]["applied"] is True
    assert response.metadata["intake_note_tracking"]["record_changed"] is True
    assert response.metadata["intake_record_persistence"] == {
        "should_persist": True,
        "record_changed": True,
    }
    assert "intake_record_completeness" in response.metadata


@pytest.mark.trio
@pytest.mark.unit
async def test_note_tracking_no_new_information_keeps_current_record(
    mock_llm_service, app_config
):
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return IntakeRecordPatch(no_new_information=True)

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _make_intake_agent(mock_llm_service, app_config)
    existing = IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="stress",
                evidence_quote="I am stressed",
                source_message_index=1,
                source_role="user",
            )
        )
    )
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
            Message(role="assistant", content="Anything else?", timestamp=datetime.now()),
            Message(role="user", content="No, nothing else.", timestamp=datetime.now()),
        ],
    )
    context.intake_record = existing

    response = await agent.process_message("No, nothing else.", context)

    assert context.intake_record == existing
    assert response.metadata["intake_note_tracking"]["status"] == "no_new_information"
    assert response.metadata["intake_record_persistence"] == {
        "should_persist": False,
        "record_changed": False,
    }
    assert response.metadata["intake_record"]["presenting_problem"]["main_concern"][
        "value"
    ] == "stress"


@pytest.mark.trio
@pytest.mark.unit
async def test_note_tracking_duplicate_evidence_applies_without_persistence(
    mock_llm_service, app_config
):
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            symptoms=[
                IntakeEvidence(
                    value="racing thoughts",
                    evidence_quote="I have racing thoughts.",
                    source_message_index=1,
                    source_role="user",
                )
            ]
        )
    )

    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return patch

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _make_intake_agent(mock_llm_service, app_config)
    existing = IntakeRecord()
    existing.presenting_problem.symptoms = [
        IntakeEvidence(
            value="racing thoughts",
            evidence_quote="I have racing thoughts.",
            source_message_index=1,
            source_role="user",
        )
    ]
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
            Message(role="assistant", content="What symptoms show up?", timestamp=datetime.now()),
            Message(role="user", content="I have racing thoughts.", timestamp=datetime.now()),
        ],
    )
    context.intake_record = existing

    response = await agent.process_message("I have racing thoughts.", context)
    metadata = response.metadata["intake_note_tracking"]

    assert metadata["status"] == "success"
    assert metadata["merge_status"] == "applied"
    assert metadata["applied"] is True
    assert metadata["record_changed"] is False
    assert response.metadata["intake_record_persistence"] == {
        "should_persist": False,
        "record_changed": False,
    }


@pytest.mark.trio
@pytest.mark.unit
async def test_note_tracking_empty_patch_reports_noop_metadata(
    mock_llm_service, app_config
):
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return IntakeRecordPatch()

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _make_intake_agent(mock_llm_service, app_config)
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
            Message(role="assistant", content="What brings you in?", timestamp=datetime.now()),
            Message(role="user", content="I feel stuck.", timestamp=datetime.now()),
        ],
    )

    response = await agent.process_message("I feel stuck.", context)
    metadata = response.metadata["intake_note_tracking"]

    assert context.intake_record is None
    assert metadata["status"] == "empty_patch"
    assert metadata["raw_extraction_status"] == "success"
    assert metadata["merge_status"] == "empty_patch"
    assert metadata["applied"] is False
    assert metadata["record_changed"] is False
    assert metadata["raw_evidence_count"] == 0
    assert metadata["retained_evidence_count"] == 0
    assert response.metadata["intake_record_persistence"] == {
        "should_persist": False,
        "record_changed": False,
    }


@pytest.mark.trio
@pytest.mark.unit
async def test_note_tracking_invalid_evidence_reports_validation_failure(
    mock_llm_service, app_config
):
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="anxiety",
                evidence_quote="not in the latest message",
                source_message_index=1,
                source_role="user",
            )
        )
    )

    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return patch

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _make_intake_agent(mock_llm_service, app_config)
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
            Message(role="assistant", content="What brings you in?", timestamp=datetime.now()),
            Message(role="user", content="I feel anxious every day", timestamp=datetime.now()),
        ],
    )

    response = await agent.process_message("I feel anxious every day", context)
    metadata = response.metadata["intake_note_tracking"]

    assert context.intake_record is None
    assert metadata["status"] == "validation_failure"
    assert metadata["raw_extraction_status"] == "success"
    assert metadata["merge_status"] == "empty_after_validation"
    assert metadata["applied"] is False
    assert metadata["record_changed"] is False
    assert metadata["dropped_evidence_count"] == 1
    assert response.metadata["intake_record_persistence"] == {
        "should_persist": False,
        "record_changed": False,
    }
    assert not response.metadata["intake_record"]["presenting_problem"][
        "main_concern"
    ]["value"]


@pytest.mark.trio
@pytest.mark.unit
async def test_note_tracking_skips_guest_name_collection(mock_llm_service, app_config):
    structured_calls = 0

    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        nonlocal structured_calls
        _ = method, phase
        structured_calls += 1
        return IntakeRecordPatch(no_new_information=True)

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _make_intake_agent(mock_llm_service, app_config, user_id="guest_user")
    profile = UserProfile(
        user_id="guest_user",
        name="Guest",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    context = _make_context(
        user_profile=profile,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        message_history=[
            Message(role="assistant", content="May I have your name?", timestamp=datetime.now()),
            Message(role="user", content="Alex", timestamp=datetime.now()),
        ],
    )

    response = await agent.process_message("Alex", context)

    assert structured_calls == 0
    assert "intake_note_tracking" not in response.metadata
    assert "intake_record" not in response.metadata


def _record_evidence(value: str, *, status: str = "informative") -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=value,
        source_role="user",
        source_message_index=1,
        response_status=status,  # type: ignore[arg-type]
        direct_ask=status != "informative",
    )


def _max_turn_soft_incomplete_record() -> IntakeRecord:
    record = IntakeRecord()
    record.presenting_problem.main_concern = _record_evidence("anxiety")
    record.presenting_problem.time_course.duration_or_onset = _record_evidence(
        "I do not know",
        status="unknown",
    )
    record.presenting_problem.functional_impairment = _record_evidence("work impact")
    record.goals.therapy_goals = [_record_evidence("sleep better")]
    record.safety.self_harm = _record_evidence("denied")
    record.safety.harm_to_others = _record_evidence("denied")
    record.safety.medical_urgency = _record_evidence("denied")
    return record


def _genuinely_complete_record() -> IntakeRecord:
    record = _max_turn_soft_incomplete_record()
    record.presenting_problem.time_course.duration_or_onset = _record_evidence("months")
    record.presenting_problem.sleep_impact = _record_evidence("poor sleep")
    record.coping.attempted_strategies = [_record_evidence("exercise")]
    return record


def _max_turn_history(*extra: Message) -> list[Message]:
    return [
        Message(role="assistant", content="Previous prompt", timestamp=datetime.now()),
        *[
            Message(
                role="user",
                content=f"Turn {index}: anxiety affects work.",
                timestamp=datetime.now(),
            )
            for index in range(MAX_INTAKE_PATIENT_TURNS)
        ],
        *extra,
    ]


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_blocks_max_turn_completion_on_extraction_failure(
    mock_llm_service, app_config
):
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        raise RuntimeError("boom")

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _gate_agent(mock_llm_service, app_config)
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    record = _max_turn_soft_incomplete_record()
    completeness = intake_record_completion_decision(
        record,
        patient_turn_count=MAX_INTAKE_PATIENT_TURNS,
    )
    assert completeness.complete
    assert completeness.max_turn_completion

    context = _make_context(
        user_profile=profile,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        message_history=_max_turn_history(
            Message(
                role="user",
                content="Turn final: still unsure about coping.",
                timestamp=datetime.now(),
            ),
        ),
    )
    context.intake_record = record

    response = await agent.process_message(
        "Turn final: still unsure about coping.",
        context,
    )

    assert response.workflow_event != WorkflowEvent.COMPLETE_INTAKE
    assert response.content != CLOSING_PROMPT
    metadata = response.metadata["intake_note_tracking"]
    assert metadata["status"] == "llm_failure"
    assert metadata["stale_record_used"] is True
    assert metadata["max_turn_completion_blocked_by_failure"] is True


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_allows_genuinely_complete_record_despite_extraction_failure(
    mock_llm_service, app_config
):
    original_structured = mock_llm_service.generate_structured_output_async

    async def _generate_structured_output_async(
        prompt, schema, method="json_schema", *, phase, **kwargs
    ):
        if phase == INTAKE_NOTE_TRACKING:
            raise RuntimeError("boom")
        return await original_structured(
            prompt, schema, method=method, phase=phase, **kwargs
        )

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _gate_agent(mock_llm_service, app_config)
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    record = _genuinely_complete_record()
    completeness = intake_record_completion_decision(
        record,
        patient_turn_count=MIN_INTAKE_PATIENT_TURNS,
    )
    assert completeness.complete
    assert not completeness.max_turn_completion

    context = _make_context(
        user_profile=profile,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        message_history=_max_turn_history(),
    )
    context.intake_record = record

    response = await agent.process_message("Thanks, that covers everything.", context)

    assert response.workflow_event == WorkflowEvent.COMPLETE_INTAKE
    assert response.content == CLOSING_PROMPT
    assert "user_profile" not in response.metadata
    metadata = response.metadata["intake_note_tracking"]
    assert metadata["stale_record_used"] is True
    assert metadata["max_turn_completion_blocked_by_failure"] is False


def _gate_mode_config(app_config):
    return app_config


def _gate_agent(mock_llm_service, app_config):
    return _make_intake_agent(
        mock_llm_service,
        _gate_mode_config(app_config),
    )


def _incomplete_intake_context(*, message: str = "I feel anxious every day") -> ConversationContext:
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return _make_context(
        user_profile=profile,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        message_history=[
            Message(role="assistant", content="What brings you in?", timestamp=datetime.now()),
            Message(role="user", content=message, timestamp=datetime.now()),
        ],
    )


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_missing_risk_screen_uses_authoritative_llm_prompt(
    mock_llm_service, app_config
):
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return IntakeRecordPatch(no_new_information=True)

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _gate_agent(mock_llm_service, app_config)
    context = _incomplete_intake_context()
    context.intake_record = IntakeRecord()

    response = await agent.process_message("I feel anxious every day", context)

    assert response.metadata["intake_next_action_source"] == "structured_direct_ask_llm"
    assert response.metadata["selected_direct_ask_item"] == "risk_screen"
    assert "harming themselves" in response.content
    assert "harming someone else" in response.content
    assert response.content != RISK_SCREEN_PROMPT


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_missing_non_safety_item_uses_authoritative_llm_prompt(
    mock_llm_service, app_config
):
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return IntakeRecordPatch(no_new_information=True)

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _gate_agent(mock_llm_service, app_config)
    record = IntakeRecord()
    record.safety.self_harm = _record_evidence("denied")
    record.safety.harm_to_others = _record_evidence("denied")
    record.safety.medical_urgency = _record_evidence("denied")
    context = _incomplete_intake_context(message="Still figuring things out.")
    context.intake_record = record

    response = await agent.process_message("Still figuring things out.", context)

    assert response.metadata["intake_next_action_source"] == "structured_direct_ask_llm"
    assert response.metadata["selected_direct_ask_item"] == "presenting_problem"
    assert "presenting_problem" in response.content
    assert "Do not switch to another intake topic" in response.content


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_completion_metadata(mock_llm_service, app_config):
    agent = _gate_agent(mock_llm_service, app_config)
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
        message_history=_max_turn_history(),
    )
    context.intake_record = _genuinely_complete_record()

    response = await agent.process_message("Thanks, that covers everything.", context)

    assert response.metadata["intake_next_action_source"] == "complete"
    assert response.metadata["selected_direct_ask_item"] is None
    assert "user_profile" not in response.metadata


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_time_up_metadata(intake_agent):
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

    response = await intake_agent.process_message("Answering a question.", context)

    assert response.metadata["intake_next_action_source"] == "time_up"
    assert response.metadata["selected_direct_ask_item"] is None


@pytest.mark.trio
@pytest.mark.unit
async def test_initial_prompt_metadata(intake_agent):
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    context = ConversationContext(
        session_id="session-123",
        user_profile=profile,
        therapy_plan=None,
        message_history=[],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
    )

    response = await intake_agent.process_message("", context)

    assert response.metadata["intake_next_action_source"] == "initial_prompt"
    assert response.metadata["selected_direct_ask_item"] is None


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_generic_clarification_when_next_item_missing(
    mock_llm_service, app_config
):
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return IntakeRecordPatch(no_new_information=True)

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _gate_agent(mock_llm_service, app_config)
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    record = _genuinely_complete_record()
    completeness = intake_record_completion_decision(record, patient_turn_count=1)
    assert not completeness.complete
    assert completeness.next_required_item is None
    context = _make_context(
        user_profile=profile,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        message_history=[
            Message(role="assistant", content="What brings you in?", timestamp=datetime.now()),
            Message(
                role="user",
                content="Thanks, that covers everything for now.",
                timestamp=datetime.now(),
            ),
        ],
    )
    context.intake_record = record

    response = await agent.process_message(
        "Thanks, that covers everything for now.",
        context,
    )

    assert response.metadata["intake_next_action_source"] == "structured_direct_ask_llm"
    assert response.metadata["selected_direct_ask_item"] is None
    assert "no specific missing item is available" in response.content
    assert response.content != RISK_SCREEN_PROMPT


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_invalid_manual_config_still_authoritative(
    mock_llm_service, app_config
):
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = kwargs
        _ = method, phase
        return IntakeRecordPatch(no_new_information=True)

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _gate_agent(mock_llm_service, app_config)
    context = _incomplete_intake_context()
    context.intake_record = IntakeRecord()

    response = await agent.process_message("I feel anxious every day", context)

    assert response.metadata["intake_next_action_source"] == "structured_direct_ask_llm"
    assert response.metadata["selected_direct_ask_item"] == "risk_screen"
    assert "Structured direct-ask instruction:" in response.content
    assert "harming themselves" in response.content


def _record_ready_for_duration_unknown() -> IntakeRecord:
    record = IntakeRecord()
    record.presenting_problem.main_concern = _record_evidence("anxiety")
    record.safety.self_harm = _record_evidence("denied")
    record.safety.harm_to_others = _record_evidence("denied")
    record.safety.medical_urgency = _record_evidence("denied")
    return record


@pytest.mark.trio
@pytest.mark.unit
async def test_gate_mode_advances_direct_ask_after_unknown_duration_answer(
    mock_llm_service, app_config
):
    async def _generate_structured_output_async(
        _prompt, _schema, method="json_schema", *, phase, **kwargs
    ):
        _ = method, kwargs
        if phase == INTAKE_NOTE_TRACKING:
            return IntakeRecordPatch(
                presenting_problem=PresentingProblemRecord(
                    time_course=TimeCourseRecord(
                        duration_or_onset=IntakeEvidence(
                            evidence_quote="I don't know",
                            source_role="user",
                            source_message_index=2,
                            response_status="unknown",
                            direct_ask=True,
                        )
                    )
                )
            )
        return "Continue intake conversation."

    mock_llm_service.generate_structured_output_async = (
        _generate_structured_output_async
    )
    agent = _gate_agent(mock_llm_service, app_config)
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
                role="assistant",
                content="What brings you in?",
                timestamp=datetime.now(),
            ),
            Message(
                role="assistant",
                content="How long has this been happening?",
                timestamp=datetime.now(),
            ),
            Message(role="user", content="I don't know", timestamp=datetime.now()),
        ],
    )
    context.intake_record = _record_ready_for_duration_unknown()

    response = await agent.process_message("I don't know", context)

    completeness = response.metadata["intake_record_completeness"]
    assert "duration" in completeness["addressed_hard_items"]
    assert "duration" in completeness["unable_to_answer_items"]
    assert response.metadata["selected_direct_ask_item"] == "functional_impairment"
    assert response.metadata["intake_next_action_source"] == "structured_direct_ask_llm"
