from datetime import datetime

import pytest

from psychoanalyst_app.agents.intake.note_tracker import (
    IntakePatchExtractionResult,
)
from psychoanalyst_app.agents.intake.record_completeness import IntakeCompleteness
from psychoanalyst_app.agents.intake.record_merge import IntakePatchMergeResult
from psychoanalyst_app.agents.intake.runtime import (
    IntakeRecordState,
    compute_intake_gate_outcome,
    intake_record_metadata,
    note_tracking_failed,
    prepare_intake_record_state,
)
from psychoanalyst_app.models.domain import Message, UserProfile, UserStatus
from psychoanalyst_app.models.intake_record import IntakeRecord, IntakeRecordPatch
from psychoanalyst_app.orchestration.models import ConversationContext


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
        legacy_diagnostics={},
    )

    tracking = metadata["intake_note_tracking"]
    assert tracking["status"] == "merge_not_run"
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
    assert outcome.gate_blocked_by_failure is False


def test_gate_outcome_blocks_max_turn_completion_on_failure() -> None:
    completeness = IntakeCompleteness(complete=True, max_turn_completion=True)
    outcome = compute_intake_gate_outcome(completeness, tracking_failed=True)

    assert outcome.gate_complete is False
    assert outcome.stale_record_used is True
    assert outcome.gate_blocked_by_failure is True


def test_gate_outcome_keeps_incomplete_record_blocked_on_failure() -> None:
    completeness = IntakeCompleteness(complete=False, max_turn_completion=False)
    outcome = compute_intake_gate_outcome(completeness, tracking_failed=True)

    assert outcome.gate_complete is False
    assert outcome.stale_record_used is True
    assert outcome.gate_blocked_by_failure is False


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
            gate_blocked_by_failure=True,
        ),
        legacy_diagnostics={},
    )

    tracking = metadata["intake_note_tracking"]
    assert tracking["status"] == "llm_failure"
    assert tracking["stale_record_used"] is True
    assert tracking["gate_blocked_by_failure"] is True
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
    ):
        _ = method, phase
        raise RuntimeError("boom")


@pytest.mark.trio
@pytest.mark.unit
async def test_prepare_state_without_gate_omits_gate_diagnostics_on_failure() -> None:
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
            Message(role="assistant", content="What brings you in?", timestamp=datetime.now()),
            Message(role="user", content=message, timestamp=datetime.now()),
        ],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
    )

    state = await prepare_intake_record_state(
        message=message,
        context=context,
        llm_service=_FailingLLM(),
        note_tracking_enabled=True,
        strict_quote_validation=True,
        is_guest=False,
        structured_gate_enabled=False,
    )
    metadata = intake_record_metadata(state, legacy_diagnostics={})

    assert state.stale_record_used is False
    assert state.gate_blocked_by_failure is False
    tracking = metadata["intake_note_tracking"]
    assert tracking["status"] == "llm_failure"
    assert tracking["stale_record_used"] is False
    assert tracking["gate_blocked_by_failure"] is False
