from datetime import datetime

import pytest

from psychoanalyst_app.agents.intake.record_completeness import IntakeCompleteness
from psychoanalyst_app.agents.intake.record_merge import IntakePatchMergeResult
from psychoanalyst_app.agents.intake.runtime import (
    IntakeRecordState,
    build_continuation_prompt_context,
    build_structured_direct_ask_instruction,
    compute_intake_gate_outcome,
    intake_record_metadata,
    note_tracking_failed,
    prepare_intake_record_state,
    resolve_intake_continuation_turn,
)
from psychoanalyst_app.agents.note_taker import NoteTakerAgent
from psychoanalyst_app.agents.note_taker.intake_patch import IntakePatchExtractionResult
from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.domain import Message, UserProfile, UserStatus
from psychoanalyst_app.models.intake_record import IntakeRecord, IntakeRecordPatch
from psychoanalyst_app.orchestration.models import ConversationContext


def _extractor_from_llm(llm):
    note_taker = NoteTakerAgent(
        intake_llm_service=llm,
        reflection_llm_service=llm,
        config=Settings(_env_file=None),
    )
    return note_taker.extract_intake_patch


def test_successful_note_tracking_without_merge_result_is_not_plain_success() -> None:
    metadata = intake_record_metadata(
        IntakeRecordState(
            record=IntakeRecord(),
            completeness=IntakeCompleteness(complete=False),
            note_tracking_enabled=True,
            note_tracking=IntakePatchExtractionResult(
                status="success",
                patch=IntakeRecordPatch(),
            ),
            merge_result=None,
            should_emit_metadata=True,
        ),
    )

    tracking = metadata["intake_note_tracking"]
    assert tracking["raw_extraction_status"] == "success"
    assert metadata["intake_record_persistence"] == {
        "should_persist": False,
        "record_changed": False,
    }


def _record_state(
    *,
    tracking: IntakePatchExtractionResult | None = None,
    merge_result: IntakePatchMergeResult | None = None,
    completeness: IntakeCompleteness | None = None,
) -> IntakeRecordState:
    return IntakeRecordState(
        record=IntakeRecord(),
        completeness=completeness or IntakeCompleteness(complete=False),
        note_tracking_enabled=True,
        note_tracking=tracking,
        merge_result=merge_result,
        should_emit_metadata=True,
    )


def test_note_tracking_failed_truth_table() -> None:
    assert not note_tracking_failed(_record_state())
    assert not note_tracking_failed(
        _record_state(
            tracking=IntakePatchExtractionResult(status="no_new_information"),
        )
    )
    assert not note_tracking_failed(
        _record_state(
            tracking=IntakePatchExtractionResult(
                status="success",
                patch=IntakeRecordPatch(),
            ),
            merge_result=IntakePatchMergeResult(
                record=IntakeRecord(),
                status="empty_patch",
                applied=False,
                raw_evidence_count=0,
                retained_evidence_count=0,
                dropped_evidence_count=0,
                record_changed=False,
            ),
        )
    )
    assert note_tracking_failed(
        _record_state(
            tracking=IntakePatchExtractionResult(
                status="llm_failure",
                error_message="boom",
                error_code="RuntimeError",
            ),
        )
    )
    assert note_tracking_failed(
        _record_state(
            tracking=IntakePatchExtractionResult(
                status="invalid_patch",
                error_message="bad",
                error_code="ValidationError",
            ),
        )
    )
    assert note_tracking_failed(
        _record_state(
            tracking=IntakePatchExtractionResult(
                status="timeout",
                error_message="slow",
                error_code="TooSlowError",
            ),
        )
    )
    assert note_tracking_failed(
        _record_state(
            tracking=IntakePatchExtractionResult(
                status="success",
                patch=IntakeRecordPatch(),
            ),
            merge_result=IntakePatchMergeResult(
                record=IntakeRecord(),
                status="empty_after_validation",
                applied=False,
                raw_evidence_count=1,
                retained_evidence_count=0,
                dropped_evidence_count=1,
                record_changed=False,
            ),
        )
    )


def test_gate_outcome_allows_genuinely_complete_record_on_failure() -> None:
    completeness = IntakeCompleteness(complete=True, max_turn_completion=False)
    outcome = compute_intake_gate_outcome(completeness, tracking_failed=True)

    assert outcome.gate_complete is True
    assert outcome.stale_record_used is True
    assert outcome.max_turn_completion_blocked_by_failure is False


def test_gate_outcome_blocks_max_turn_completion_on_failure() -> None:
    completeness = IntakeCompleteness(complete=True, max_turn_completion=True)
    outcome = compute_intake_gate_outcome(completeness, tracking_failed=True)

    assert outcome.gate_complete is False
    assert outcome.stale_record_used is True
    assert outcome.max_turn_completion_blocked_by_failure is True


def test_gate_outcome_keeps_incomplete_record_blocked_on_failure() -> None:
    completeness = IntakeCompleteness(complete=False, max_turn_completion=False)
    outcome = compute_intake_gate_outcome(completeness, tracking_failed=True)

    assert outcome.gate_complete is False
    assert outcome.stale_record_used is True
    assert outcome.max_turn_completion_blocked_by_failure is False


def test_failure_metadata_includes_gate_flags() -> None:
    metadata = intake_record_metadata(
        IntakeRecordState(
            record=IntakeRecord(),
            completeness=IntakeCompleteness(complete=True, max_turn_completion=True),
            note_tracking_enabled=True,
            note_tracking=IntakePatchExtractionResult(
                status="llm_failure",
                error_message="boom",
                error_code="RuntimeError",
            ),
            should_emit_metadata=True,
            gate_complete=False,
            stale_record_used=True,
            max_turn_completion_blocked_by_failure=True,
        ),
    )

    tracking = metadata["intake_note_tracking"]
    assert tracking["status"] == "llm_failure"
    assert tracking["stale_record_used"] is True
    assert tracking["max_turn_completion_blocked_by_failure"] is True
    assert tracking["error_message"] == "boom"
    assert tracking["error_code"] == "RuntimeError"


class _FailingLLM:
    async def generate_structured_output_async(
        self,
        _prompt,
        _schema,
        method="json_schema",
        *,
        phase,
        **kwargs,
    ):
        _ = method, phase, kwargs
        raise RuntimeError("boom")


@pytest.mark.trio
@pytest.mark.unit
async def test_prepare_state_sets_gate_diagnostics_on_failure() -> None:
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    message = "I feel anxious every day"
    context = ConversationContext(
        session_id="session-123",
        user_profile=profile,
        therapy_plan=None,
        message_history=[
            Message(
                role="assistant",
                content="What brings you in?",
                timestamp=datetime.now(),
            ),
            Message(role="user", content=message, timestamp=datetime.now()),
        ],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
    )

    state = await prepare_intake_record_state(
        message=message,
        context=context,
        strict_quote_validation=True,
        is_guest=False,
        extract_intake_patch=_extractor_from_llm(_FailingLLM()),
    )
    metadata = intake_record_metadata(state)

    assert state.stale_record_used is True
    assert state.max_turn_completion_blocked_by_failure is False
    tracking = metadata["intake_note_tracking"]
    assert tracking["status"] == "llm_failure"
    assert tracking["stale_record_used"] is True
    assert tracking["max_turn_completion_blocked_by_failure"] is False


def test_build_structured_direct_ask_instruction_risk_screen() -> None:
    instruction = build_structured_direct_ask_instruction("risk_screen")

    assert "harming themselves" in instruction
    assert "harming someone else" in instruction
    assert "urgent medical" in instruction
    assert "You must ask" in instruction or "ask directly" in instruction
    assert "urgent safety or medical issue" in instruction


def test_build_structured_direct_ask_instruction_presenting_problem() -> None:
    instruction = build_structured_direct_ask_instruction("presenting_problem")

    assert "presenting_problem" in instruction
    assert "Do not switch to another intake topic" in instruction
    assert "Ask only one main question" in instruction
    assert "You must ask" in instruction


def test_build_structured_direct_ask_instruction_generic_clarification() -> None:
    instruction = build_structured_direct_ask_instruction(None)

    assert "no specific missing item is available" in instruction
    assert "You must ask one concise clarification question" in instruction
    assert "without switching topics" in instruction


def test_build_continuation_prompt_context_gate_active_risk_screen() -> None:
    state = IntakeRecordState(
        record=IntakeRecord(),
        completeness=IntakeCompleteness(
            complete=False,
            next_required_item="risk_screen",
            missing_required_items=["risk_screen"],
        ),
        should_emit_metadata=True,
    )
    context = build_continuation_prompt_context(record_state=state)

    assert "Structured direct-ask instruction:" in context
    assert "harming themselves" in context
    assert "Recommended next item:" not in context


def test_build_continuation_prompt_context_omits_record_summary_when_metadata_disabled() -> None:
    state = IntakeRecordState(
        record=IntakeRecord(),
        completeness=IntakeCompleteness(
            complete=False,
            next_required_item="risk_screen",
            missing_required_items=["risk_screen"],
        ),
        should_emit_metadata=False,
    )
    context = build_continuation_prompt_context(record_state=state)

    assert "Structured direct-ask instruction:" in context
    assert "Structured intake state:" not in context


def test_build_continuation_prompt_context_always_authoritative() -> None:
    state = IntakeRecordState(
        record=IntakeRecord(),
        completeness=IntakeCompleteness(
            complete=False,
            next_required_item="risk_screen",
            missing_required_items=["risk_screen"],
        ),
        should_emit_metadata=True,
    )
    context = build_continuation_prompt_context(record_state=state)

    assert "Structured direct-ask instruction:" in context
    assert "harming themselves" in context


def test_build_continuation_prompt_context_without_metadata_still_authoritative() -> None:
    state = IntakeRecordState(
        record=IntakeRecord(),
        completeness=IntakeCompleteness(
            complete=False,
            next_required_item="risk_screen",
            missing_required_items=["risk_screen"],
        ),
        should_emit_metadata=False,
    )
    context = build_continuation_prompt_context(record_state=state)

    assert "Structured direct-ask instruction:" in context
    assert "harming themselves" in context
    assert "Structured intake state:" not in context


def test_build_continuation_prompt_context_gate_active_no_next_item() -> None:
    state = IntakeRecordState(
        record=IntakeRecord(),
        completeness=IntakeCompleteness(complete=False, next_required_item=None),
        should_emit_metadata=True,
    )
    context = build_continuation_prompt_context(record_state=state)

    assert "no specific missing item is available" in context
    assert "Have you had any thoughts of harming yourself" not in context


class _BlockingSlowLLM:
    def generate_structured_output(self, *_args, **_kwargs):
        import time

        time.sleep(5)
        from psychoanalyst_app.models.intake_record import IntakeRecordPatch

        return IntakeRecordPatch()

    async def generate_structured_output_async(self, *args, **kwargs):
        import trio

        return await trio.to_thread.run_sync(
            lambda: self.generate_structured_output(*args, **kwargs),
            abandon_on_cancel=kwargs.get("abandon_on_cancel", False),
        )


@pytest.mark.trio
@pytest.mark.unit
async def test_prepare_state_timeout_does_not_mutate_record() -> None:
    profile = UserProfile(
        user_id="user-123",
        name="Test User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    message = "I feel anxious every day"
    baseline = IntakeRecord()
    context = ConversationContext(
        session_id="session-123",
        user_profile=profile,
        therapy_plan=None,
        message_history=[
            Message(
                role="assistant",
                content="What brings you in?",
                timestamp=datetime.now(),
            ),
            Message(role="user", content=message, timestamp=datetime.now()),
        ],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        intake_record=baseline,
    )

    state = await prepare_intake_record_state(
        message=message,
        context=context,
        strict_quote_validation=True,
        is_guest=False,
        note_tracking_timeout_seconds=0.05,
        extract_intake_patch=_extractor_from_llm(_BlockingSlowLLM()),
    )
    metadata = intake_record_metadata(state)

    assert state.record == baseline
    assert state.note_tracking is not None
    assert state.note_tracking.status == "timeout"
    assert metadata["intake_record_persistence"]["should_persist"] is False
    assert metadata["intake_record_persistence"]["record_changed"] is False


class _PhaseCapturingLLM:
    def __init__(self) -> None:
        self.phases: list[str | None] = []

    async def generate_structured_output(
        self,
        _prompt: str,
        _schema: object,
        *,
        phase: str | None = None,
        **_kwargs: object,
    ) -> object:
        self.phases.append(phase)
        return None

    async def generate_structured_output_with_timeout(
        self,
        _prompt: str,
        _schema: object,
        *,
        phase: str | None = None,
        **_kwargs: object,
    ) -> object:
        self.phases.append(phase)
        return None


@pytest.mark.trio
@pytest.mark.unit
async def test_intake_completion_does_not_call_intake_extraction() -> None:
    llm = _PhaseCapturingLLM()
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
        message_history=[
            Message(
                role="assistant",
                content="What brings you in?",
                timestamp=datetime.now(),
            ),
            Message(role="user", content="I feel anxious.", timestamp=datetime.now()),
        ],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        intake_record=IntakeRecord(),
    )
    record_state = IntakeRecordState(
        record=IntakeRecord(),
        completeness=IntakeCompleteness(complete=True),
        gate_complete=True,
    )

    response = await resolve_intake_continuation_turn(
        message="done",
        context=context,
        record_state=record_state,
        is_complete=True,
        intake_topics=[],
        record_metadata={},
    )

    assert response.metadata is not None
    assert response.metadata.get("user_profile") is None
    assert "intake_extraction" not in [p for p in llm.phases if p]

