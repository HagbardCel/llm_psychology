"""Runtime helpers for canonical structured intake note tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from psychoanalyst_app.agents.intake.prompts import (
    CLOSING_PROMPT,
    CONTINUE_CONVERSATION_PROMPT,
    INITIAL_GREETING_PROMPT,
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
from psychoanalyst_app.agents.note_taker.intake_patch import IntakePatchExtractionResult
from psychoanalyst_app.models.domain import Message, UserStatus
from psychoanalyst_app.models.intake_record import IntakeRecord
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
    WorkflowEvent,
    direct_agent_response,
)

logger = logging.getLogger(__name__)

TIME_UP_INTAKE_PROMPT = (
    "Our time is up for today. We will continue this intake in our next session."
)


class IntakePatchExtractor(Protocol):
    async def __call__(
        self,
        *,
        current_record: IntakeRecord,
        latest_user_message: Message,
        previous_assistant_message: Message | None,
        source_message_index: int,
        timeout_seconds: float,
    ) -> IntakePatchExtractionResult: ...


def is_guest_intake_context(context: ConversationContext) -> bool:
    """Return whether intake is still collecting a usable patient name."""
    return (
        context.user_profile.name == "Guest"
        or context.user_profile.status == UserStatus.PROFILE_ONLY
        or context.user_profile.name == context.user_profile.user_id
    )


_FAILURE_TRACKING_STATUSES = frozenset(
    {
        "llm_failure",
        "invalid_patch",
        "timeout",
        "merge_failure",
        "validation_failure",
    }
)


@dataclass(frozen=True)
class IntakeGateOutcome:
    gate_complete: bool
    stale_record_used: bool
    max_turn_completion_blocked_by_failure: bool


@dataclass(frozen=True)
class IntakeRecordState:
    record: IntakeRecord
    completeness: IntakeCompleteness
    note_tracking_enabled: bool = False
    note_tracking: IntakePatchExtractionResult | None = None
    merge_result: IntakePatchMergeResult | None = None
    should_emit_metadata: bool = False
    gate_complete: bool = False
    stale_record_used: bool = False
    max_turn_completion_blocked_by_failure: bool = False


def _tracking_metadata_status(
    tracking: IntakePatchExtractionResult | None,
    merge_result: IntakePatchMergeResult | None,
) -> str:
    status = tracking.status if tracking else "not_run"
    if tracking and tracking.status == "success":
        if merge_result is None:
            return "merge_not_run"
        if merge_result.status == "empty_patch":
            return "empty_patch"
        if merge_result.status == "empty_after_validation":
            return "validation_failure"
        if merge_result.status == "merge_failure":
            return "merge_failure"
    return status


def note_tracking_failed(state: IntakeRecordState) -> bool:
    """Return whether this turn had a note-tracking failure relevant to gating."""
    return _tracking_metadata_status(state.note_tracking, state.merge_result) in (
        _FAILURE_TRACKING_STATUSES
    )


def compute_intake_gate_outcome(
    completeness: IntakeCompleteness,
    *,
    tracking_failed: bool,
) -> IntakeGateOutcome:
    """Derive structured completion-gate behavior for the current turn."""
    if not tracking_failed:
        return IntakeGateOutcome(
            gate_complete=completeness.complete,
            stale_record_used=False,
            max_turn_completion_blocked_by_failure=False,
        )

    stale_record_used = True
    genuinely_complete = completeness.complete and not completeness.max_turn_completion
    if genuinely_complete:
        return IntakeGateOutcome(
            gate_complete=True,
            stale_record_used=stale_record_used,
            max_turn_completion_blocked_by_failure=False,
        )
    if completeness.complete and completeness.max_turn_completion:
        return IntakeGateOutcome(
            gate_complete=False,
            stale_record_used=stale_record_used,
            max_turn_completion_blocked_by_failure=True,
        )
    return IntakeGateOutcome(
        gate_complete=False,
        stale_record_used=stale_record_used,
        max_turn_completion_blocked_by_failure=False,
    )


async def prepare_intake_record_state(
    *,
    message: str,
    context: ConversationContext,
    strict_quote_validation: bool,
    is_guest: bool,
    note_tracking_timeout_seconds: float = 20.0,
    extract_intake_patch: IntakePatchExtractor,
) -> IntakeRecordState:
    """Prepare typed intake record state and note-tracking diagnostics."""
    record = context.intake_record or IntakeRecord()
    has_existing_record = context.intake_record is not None
    note_tracking: IntakePatchExtractionResult | None = None
    merge_result: IntakePatchMergeResult | None = None

    if not is_guest and message.strip():
        record, note_tracking, merge_result = await _update_intake_record(
            message=message,
            context=context,
            current_record=record,
            strict_quote_validation=strict_quote_validation,
            timeout_seconds=note_tracking_timeout_seconds,
            extract_intake_patch=extract_intake_patch,
        )

    completeness = intake_record_completion_decision(
        record,
        patient_turn_count=len(patient_messages("", context.message_history)),
    )
    state = IntakeRecordState(
        record=record,
        completeness=completeness,
        note_tracking_enabled=True,
        note_tracking=note_tracking,
        merge_result=merge_result,
        should_emit_metadata=note_tracking is not None or has_existing_record,
    )
    gate_outcome = compute_intake_gate_outcome(
        completeness,
        tracking_failed=note_tracking_failed(state),
    )
    return IntakeRecordState(
        record=state.record,
        completeness=state.completeness,
        note_tracking_enabled=state.note_tracking_enabled,
        note_tracking=state.note_tracking,
        merge_result=state.merge_result,
        should_emit_metadata=state.should_emit_metadata,
        gate_complete=gate_outcome.gate_complete,
        stale_record_used=gate_outcome.stale_record_used,
        max_turn_completion_blocked_by_failure=gate_outcome.max_turn_completion_blocked_by_failure,
    )


async def _update_intake_record(
    *,
    message: str,
    context: ConversationContext,
    current_record: IntakeRecord,
    strict_quote_validation: bool,
    timeout_seconds: float = 20.0,
    extract_intake_patch: IntakePatchExtractor,
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
    result = await extract_intake_patch(
        current_record=current_record,
        latest_user_message=latest_message,
        previous_assistant_message=_previous_assistant_message(
            context.message_history,
            before_index=latest_index,
        ),
        source_message_index=latest_index,
        timeout_seconds=timeout_seconds,
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
) -> dict[str, object]:
    """Build serializable response metadata for structured intake state."""
    if not state.should_emit_metadata:
        return {}

    tracking = state.note_tracking
    merge_result = state.merge_result
    status = _tracking_metadata_status(tracking, merge_result)
    tracking_metadata: dict[str, object] = {
        "status": status,
        "configured_enabled": state.note_tracking_enabled,
        "attempted": tracking is not None,
        "stale_record_used": state.stale_record_used,
        "max_turn_completion_blocked_by_failure": (
            state.max_turn_completion_blocked_by_failure
        ),
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
                "drop_reasons": [dict(item) for item in merge_result.drop_reasons],
                "drop_reasons_total": merge_result.drop_reasons_total,
                "drop_reasons_truncated": merge_result.drop_reasons_truncated,
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
    }


def intake_response_metadata(
    *,
    context: ConversationContext,
    record_metadata: dict[str, object],
    user_profile: object | None = None,
    intake_complete: bool | None = None,
    intake_next_action_source: str | None = None,
    selected_direct_ask_item: str | None = None,
) -> dict[str, object]:
    """Build common intake response metadata."""
    metadata: dict[str, object] = {
        "topics_covered": context.topics_covered,
        **record_metadata,
        "time_remaining_minutes": context.time_remaining_minutes,
        "can_extend": context.can_extend,
        "is_time_up": context.is_time_up,
        "intake_next_action_source": intake_next_action_source,
        "selected_direct_ask_item": selected_direct_ask_item,
    }
    if user_profile is not None:
        metadata["user_profile"] = user_profile
    if intake_complete is not None:
        metadata["intake_complete"] = intake_complete
    return metadata


def build_structured_direct_ask_instruction(next_item: str | None) -> str:
    """Return mandatory structured direct-ask guidance for the response agent."""
    if next_item is None:
        return (
            "The structured intake record is not safe to complete yet, but no "
            "specific missing item is available. You must ask one concise "
            "clarification question (about the current problem, goals, coping "
            "attempts, or safety) that helps complete the record without "
            "switching topics. Ask only one main question. If the patient says "
            "they do not know or cannot answer, acknowledge that directly.\n\n"
            "Exception: if the patient has just raised an urgent safety or "
            "medical issue, respond to that first."
        )

    if next_item == "risk_screen":
        item_guidance = (
            "For risk_screen, ask directly whether the patient is having "
            "thoughts of harming themselves, thoughts of harming someone else, "
            "or any urgent medical or psychiatric safety concern."
        )
    else:
        item_guidance = (
            f"You must ask a direct, concise intake question about the required "
            f"structured item: {next_item}."
        )

    return (
        f"{item_guidance}\n"
        "Do not switch to another intake topic.\n"
        "Ask only one main question.\n"
        "If the patient says they do not know or cannot answer, acknowledge "
        "that directly.\n\n"
        "Exception: if the patient has just raised an urgent safety or medical "
        "issue, respond to that first."
    )


def build_continuation_prompt_context(
    *,
    record_state: IntakeRecordState,
) -> str:
    """Return structured intake context for the response-generation prompt."""
    parts: list[str] = []
    if record_state.should_emit_metadata:
        summary = summarize_intake_record_for_prompt(
            record_state.record,
            record_state.completeness,
        )
        parts.extend(
            [
                "\nStructured intake state:\n",
                summary,
                "\n\nOpen required intake items: ",
                ", ".join(record_state.completeness.missing_required_items) or "None",
            ]
        )

    parts.extend(
        [
            "\n\nStructured direct-ask instruction:\n",
            build_structured_direct_ask_instruction(
                record_state.completeness.next_required_item
            ),
        ]
    )
    return "".join(parts)


def build_initial_intake_prompt(context: ConversationContext) -> str:
    """Build initial greeting prompt."""
    return INITIAL_GREETING_PROMPT.format(
        user_name=context.user_profile.name,
        session_duration=context.duration_minutes,
    )


def build_intake_continuation_prompt(
    *,
    context: ConversationContext,
    record_state: IntakeRecordState,
    intake_topics: list[str],
) -> str:
    """Build continuation prompt with time, topic, and structured intake context."""
    remaining_minutes = max(0, int(context.time_remaining_minutes))
    covered = context.topics_covered
    pending = [topic for topic in intake_topics if topic not in covered]
    return CONTINUE_CONVERSATION_PROMPT.format(
        remaining_minutes=remaining_minutes,
        session_duration=context.duration_minutes,
        covered_topics=", ".join(covered) if covered else "None",
        pending_topics=", ".join(pending),
        structured_intake_context=build_continuation_prompt_context(
            record_state=record_state,
        ),
    )


@dataclass(frozen=True)
class IntakeContinuationPlan:
    prompt: str
    intake_next_action_source: str
    selected_direct_ask_item: str | None = None


async def resolve_intake_continuation_turn(
    *,
    message: str,
    context: ConversationContext,
    record_state: IntakeRecordState,
    is_complete: bool,
    intake_topics: list[str],
    record_metadata: dict[str, object],
) -> AgentResponse | IntakeContinuationPlan:
    """Resolve continuation turns that may complete, time out, or continue intake."""
    _ = message
    if is_complete:
        return direct_agent_response(
            content=CLOSING_PROMPT,
            next_action="transition",
            workflow_event=WorkflowEvent.COMPLETE_INTAKE,
            metadata=intake_response_metadata(
                context=context,
                record_metadata=record_metadata,
                user_profile=None,
                intake_complete=is_complete,
                intake_next_action_source="complete",
                selected_direct_ask_item=None,
            ),
        )
    if context.is_time_up:
        return direct_agent_response(
            content=TIME_UP_INTAKE_PROMPT,
            metadata=intake_response_metadata(
                context=context,
                record_metadata=record_metadata,
                intake_complete=is_complete,
                intake_next_action_source="time_up",
                selected_direct_ask_item=None,
            ),
        )
    selected_item = record_state.completeness.next_required_item
    return IntakeContinuationPlan(
        prompt=build_intake_continuation_prompt(
            context=context,
            record_state=record_state,
            intake_topics=intake_topics,
        ),
        intake_next_action_source="structured_direct_ask_llm",
        selected_direct_ask_item=selected_item,
    )
