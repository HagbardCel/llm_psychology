"""Runtime helpers for optional structured intake note tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from psychoanalyst_app.agents.intake.note_tracker import extract_intake_record_patch
from psychoanalyst_app.agents.intake.record_completeness import (
    IntakeCompleteness,
    intake_record_completion_decision,
)
from psychoanalyst_app.agents.intake.record_merge import merge_intake_record_patch
from psychoanalyst_app.agents.intake.record_summary import (
    summarize_intake_record_for_prompt,
)
from psychoanalyst_app.agents.intake.slots import patient_messages
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import IntakeRecord
from psychoanalyst_app.orchestration.models import ConversationContext
from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntakeRecordState:
    record: IntakeRecord
    completeness: IntakeCompleteness
    error: str | None = None
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
    record = IntakeRecord.model_validate(context.intake_record or {})
    error = None
    has_existing_record = context.intake_record is not None
    if note_tracking_enabled and not is_guest and message.strip():
        record, error = await _update_intake_record(
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
        error=error,
        should_emit_metadata=note_tracking_enabled or has_existing_record,
    )


async def _update_intake_record(
    *,
    message: str,
    context: ConversationContext,
    current_record: IntakeRecord,
    llm_service: LLMService,
    strict_quote_validation: bool,
) -> tuple[IntakeRecord, str | None]:
    latest_index = _latest_user_message_index(context, message)
    if latest_index is None:
        return current_record, "latest_user_message_not_found"
    latest_message = context.message_history[latest_index]
    patch = await extract_intake_record_patch(
        llm_service=llm_service,
        current_record=current_record,
        latest_user_message=latest_message,
        previous_assistant_message=_previous_assistant_message(
            context.message_history,
            before_index=latest_index,
        ),
        source_message_index=latest_index,
    )
    if patch is None:
        return current_record, "note_tracking_failed"
    try:
        updated = merge_intake_record_patch(
            current_record,
            patch,
            latest_user_message=latest_message,
            source_message_index=latest_index,
            strict_quote_validation=strict_quote_validation,
        )
    except Exception as exc:
        logger.warning("Failed to merge intake record patch", exc_info=True)
        return current_record, f"record_merge_failed:{type(exc).__name__}"
    context.intake_record = updated.model_dump(mode="json")
    return updated, None


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
    if not state.should_emit_metadata:
        return {}
    metadata: dict[str, object] = {
        "intake_record": state.record.model_dump(mode="json"),
        "intake_record_completeness": state.completeness.model_dump(mode="json"),
        "legacy_intake_completion_diagnostics": legacy_diagnostics,
    }
    if state.error:
        metadata["note_tracking_error"] = state.error
    return metadata


def intake_response_metadata(
    *,
    context: ConversationContext,
    intake_slot_coverage: set[str],
    completion_diagnostics: dict[str, object],
    record_metadata: dict[str, object],
    user_profile: object | None = None,
    intake_complete: bool | None = None,
) -> dict[str, object]:
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
