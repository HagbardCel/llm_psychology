"""Runtime helpers for optional structured intake note tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from psychoanalyst_app.agents.intake.note_tracker import (
    IntakePatchExtractionResult,
    extract_intake_record_patch,
)
from psychoanalyst_app.agents.intake.record_completeness import (
    IntakeCompleteness,
    intake_record_completion_decision,
)
from psychoanalyst_app.agents.intake.record_merge import (
    IntakePatchMergeResult,
    merge_intake_record_patch_with_diagnostics,
)
from psychoanalyst_app.agents.intake.record_summary import (
    summarize_intake_record_for_prompt,
)
from psychoanalyst_app.agents.intake.slots import patient_messages
from psychoanalyst_app.models.domain import Message, UserStatus
from psychoanalyst_app.models.intake_record import IntakeRecord
from psychoanalyst_app.orchestration.models import ConversationContext
from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def is_guest_intake_context(context: ConversationContext) -> bool:
    """Return whether intake is still collecting a usable patient name."""
    return (
        context.user_profile.name == "Guest"
        or context.user_profile.status == UserStatus.PROFILE_ONLY
        or context.user_profile.name == context.user_profile.user_id
    )


def should_use_structured_completion_gate(
    *,
    note_tracking_enabled: bool,
    completion_gate_enabled: bool,
) -> bool:
    """Temporarily guard structured gate until config invariants are enforced."""
    return note_tracking_enabled and completion_gate_enabled


@dataclass(frozen=True)
class IntakeRecordState:
    record: IntakeRecord
    completeness: IntakeCompleteness
    note_tracking_enabled: bool = False
    note_tracking: IntakePatchExtractionResult | None = None
    merge_result: IntakePatchMergeResult | None = None
    should_emit_metadata: bool = False


async def prepare_intake_record_state(
    *,
    message: str,
    context: ConversationContext,
    llm_service: LLMService,
    note_tracking_enabled: bool,
    strict_quote_validation: bool,
    is_guest: bool,
) -> IntakeRecordState:
    """Prepare typed intake record state and optional note-tracking diagnostics."""
    record = context.intake_record or IntakeRecord()
    has_existing_record = context.intake_record is not None
    note_tracking: IntakePatchExtractionResult | None = None
    merge_result: IntakePatchMergeResult | None = None

    if note_tracking_enabled and not is_guest and message.strip():
        record, note_tracking, merge_result = await _update_intake_record(
            message=message,
            context=context,
            current_record=record,
            llm_service=llm_service,
            strict_quote_validation=strict_quote_validation,
        )

    completeness = intake_record_completion_decision(
        record,
        patient_turn_count=len(patient_messages("", context.message_history)),
    )
    return IntakeRecordState(
        record=record,
        completeness=completeness,
        note_tracking_enabled=note_tracking_enabled,
        note_tracking=note_tracking,
        merge_result=merge_result,
        should_emit_metadata=note_tracking is not None or has_existing_record,
    )


async def _update_intake_record(
    *,
    message: str,
    context: ConversationContext,
    current_record: IntakeRecord,
    llm_service: LLMService,
    strict_quote_validation: bool,
) -> tuple[IntakeRecord, IntakePatchExtractionResult, IntakePatchMergeResult | None]:
    latest_index = _latest_user_message_index(context, message)
    if latest_index is None:
        result = IntakePatchExtractionResult(
            status="invalid_patch",
            error_message="Latest user message not found in context",
            error_code="latest_user_message_not_found",
        )
        return current_record, result, None

    latest_message = context.message_history[latest_index]
    result = await extract_intake_record_patch(
        llm_service=llm_service,
        current_record=current_record,
        latest_user_message=latest_message,
        previous_assistant_message=_previous_assistant_message(
            context.message_history,
            before_index=latest_index,
        ),
        source_message_index=latest_index,
    )
    if result.status != "success" or result.patch is None:
        return current_record, result, None

    merge_result = merge_intake_record_patch_with_diagnostics(
        current_record,
        result.patch,
        latest_user_message=latest_message,
        source_message_index=latest_index,
        strict_quote_validation=strict_quote_validation,
    )
    if merge_result.status == "merge_failure":
        logger.warning(
            "Failed to merge intake record patch: %s",
            merge_result.error_code,
        )
    return merge_result.record, result, merge_result


def _latest_user_message_index(
    context: ConversationContext,
    message: str,
) -> int | None:
    for index in range(len(context.message_history) - 1, -1, -1):
        item = context.message_history[index]
        if item.role == "user" and item.content == message:
            return index
    return None


def _previous_assistant_message(
    message_history: list[Message],
    *,
    before_index: int,
) -> Message | None:
    for index in range(before_index - 1, -1, -1):
        item = message_history[index]
        if item.role == "assistant":
            return item
    return None


def intake_record_metadata(
    state: IntakeRecordState,
    *,
    legacy_diagnostics: dict[str, object],
) -> dict[str, object]:
    """Build serializable response metadata for structured intake state."""
    if not state.should_emit_metadata:
        return {}

    tracking = state.note_tracking
    merge_result = state.merge_result
    status = tracking.status if tracking else "not_run"
    if tracking and tracking.status == "success":
        if merge_result is None:
            status = "merge_not_run"
        elif merge_result.status == "empty_patch":
            status = "empty_patch"
        elif merge_result.status == "empty_after_validation":
            status = "validation_failure"
        elif merge_result.status == "merge_failure":
            status = "merge_failure"
    tracking_metadata: dict[str, object] = {
        "status": status,
        "configured_enabled": state.note_tracking_enabled,
        "attempted": tracking is not None,
    }
    if tracking:
        tracking_metadata["raw_extraction_status"] = tracking.status
    if tracking and tracking.error_message:
        tracking_metadata["error_message"] = tracking.error_message
    if tracking and tracking.error_code:
        tracking_metadata["error_code"] = tracking.error_code
    if merge_result:
        tracking_metadata.update(
            {
                "merge_status": merge_result.status,
                "applied": merge_result.applied,
                "raw_evidence_count": merge_result.raw_evidence_count,
                "retained_evidence_count": merge_result.retained_evidence_count,
                "dropped_evidence_count": merge_result.dropped_evidence_count,
                "record_changed": merge_result.record_changed,
            }
        )
        if merge_result.error_message:
            tracking_metadata["merge_error_message"] = merge_result.error_message
        if merge_result.error_code:
            tracking_metadata["merge_error_code"] = merge_result.error_code

    return {
        "intake_record": state.record.model_dump(mode="json"),
        "intake_record_persistence": {
            "should_persist": bool(merge_result and merge_result.record_changed),
            "record_changed": bool(merge_result and merge_result.record_changed),
        },
        "intake_record_completeness": state.completeness.model_dump(mode="json"),
        "intake_note_tracking": tracking_metadata,
        "legacy_intake_completion_diagnostics": legacy_diagnostics,
    }


def intake_response_metadata(
    *,
    context: ConversationContext,
    intake_slot_coverage: set[str],
    completion_diagnostics: dict[str, object],
    record_metadata: dict[str, object],
    user_profile: object | None = None,
    intake_complete: bool | None = None,
) -> dict[str, object]:
    """Build common intake response metadata."""
    metadata: dict[str, object] = {
        "topics_covered": context.topics_covered,
        "intake_slot_coverage": sorted(intake_slot_coverage),
        "intake_completion_diagnostics": completion_diagnostics,
        **record_metadata,
        "time_remaining_minutes": context.time_remaining_minutes,
        "can_extend": context.can_extend,
        "is_time_up": context.is_time_up,
    }
    if user_profile is not None:
        metadata["user_profile"] = user_profile
    if intake_complete is not None:
        metadata["intake_complete"] = intake_complete
    return metadata


def build_continuation_prompt_context(
    *,
    record_state: IntakeRecordState,
    include_structured_guidance: bool,
    direct_ask_enabled: bool,
) -> str:
    """Return structured intake context for the response-generation prompt."""
    if not include_structured_guidance:
        return ""

    recommended_next_item = record_state.completeness.next_required_item or "None"
    if direct_ask_enabled and record_state.completeness.next_required_item:
        recommended_next_item = (
            f"{record_state.completeness.next_required_item} "
            "(ask directly; if the patient cannot answer, note that explicitly)"
        )
    summary = summarize_intake_record_for_prompt(
        record_state.record,
        record_state.completeness,
    )
    return (
        "\nStructured intake state:\n"
        f"{summary}"
        "\n\nOpen required intake items: "
        f"{', '.join(record_state.completeness.missing_required_items) or 'None'}"
        f"\nRecommended next item: {recommended_next_item}\n"
    )
