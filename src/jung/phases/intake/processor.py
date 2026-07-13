"""Intake phase processor."""

from __future__ import annotations

from collections.abc import AsyncIterator

from jung.llm.gateway import LLMGateway, ModelPolicy
from jung.phases.intake.completion import intake_record_completion_decision
from jung.phases.intake.merge import merge_intake_record_patch_with_diagnostics
from jung.phases.intake.models import (
    IntakeMergeDiagnostics,
    IntakeRecordPatch,
    IntakeTurnInput,
    IntakeTurnPlan,
    TranscriptTurn,
)
from jung.phases.intake.prompts import (
    build_patch_extraction_messages,
    build_response_messages,
)

_FAILURE_STATUSES = frozenset(
    {"empty_after_validation", "merge_failure"},
)


class IntakeProcessor:
    def __init__(
        self,
        gateway: LLMGateway,
        *,
        patch_policy: ModelPolicy,
        response_policy: ModelPolicy,
    ) -> None:
        self._gateway = gateway
        self._patch_policy = patch_policy
        self._response_policy = response_policy

    async def prepare_turn(self, input: IntakeTurnInput) -> IntakeTurnPlan:
        record = input.current_record
        merge_diagnostics: IntakeMergeDiagnostics | None = None
        extraction_failed = False
        record_changed = False
        latest_turn = self._latest_user_turn(input)

        if latest_turn is not None and input.latest_user_message:
            patch = await self._gateway.generate_structured(
                build_patch_extraction_messages(
                    record=record,
                    latest_user_message=latest_turn,
                    previous_assistant_message=input.previous_assistant_message,
                ),
                IntakeRecordPatch,
                self._patch_policy,
            )
            merge_result = merge_intake_record_patch_with_diagnostics(
                record,
                patch,
                latest_user_message=latest_turn,
                source_message_sequence=latest_turn.sequence,
                strict_quote_validation=input.strict_quote_validation,
            )
            record = merge_result.record
            record_changed = merge_result.record_changed
            extraction_failed = merge_result.status in _FAILURE_STATUSES
            merge_diagnostics = IntakeMergeDiagnostics(
                status=merge_result.status,
                applied=merge_result.applied,
                record_changed=merge_result.record_changed,
                raw_evidence_count=merge_result.raw_evidence_count,
                retained_evidence_count=merge_result.retained_evidence_count,
                dropped_evidence_count=merge_result.dropped_evidence_count,
                drop_reasons=merge_result.drop_reasons,
            )

        completeness = intake_record_completion_decision(
            record,
            input.patient_turn_count,
            extraction_failed=extraction_failed,
        )
        max_turn_completion_blocked = (
            extraction_failed and completeness.max_turn_completion
        )
        gate_complete = completeness.complete and not max_turn_completion_blocked

        is_opening = not input.transcript and not input.latest_user_message
        response_messages = tuple(
            build_response_messages(
                profile=input.profile,
                record=record,
                completeness=completeness.model_copy(
                    update={"complete": gate_complete}
                ),
                latest_user_message=input.latest_user_message,
                transcript=input.transcript,
                is_opening=is_opening,
            )
        )

        return IntakeTurnPlan(
            merged_record=record,
            record_changed=record_changed,
            completeness_complete=gate_complete,
            next_required_item=completeness.next_required_item,
            max_turn_completion_blocked=max_turn_completion_blocked,
            merge_diagnostics=merge_diagnostics,
            response_messages=response_messages,
        )

    async def stream_response(self, plan: IntakeTurnPlan) -> AsyncIterator[str]:
        async for chunk in self._gateway.stream_text(
            plan.response_messages,
            self._response_policy,
        ):
            yield chunk

    def _latest_user_turn(self, input: IntakeTurnInput) -> TranscriptTurn | None:
        if not input.transcript:
            return None
        latest = input.transcript[-1]
        return latest if latest.role == "user" else None
