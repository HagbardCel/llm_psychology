"""Intake phase processor."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from jung.llm.gateway import LLMGateway, ModelPolicy
from jung.phases.intake.completion import intake_record_completion_decision
from jung.phases.intake.extraction import (
    IntakeExtraction,
    materialize_extraction,
    prompted_item_for_extraction,
)
from jung.phases.intake.merge import (
    MAX_INTAKE_DROP_REASONS,
    merge_intake_record_patch_with_diagnostics,
)
from jung.phases.intake.models import (
    IntakeMergeDiagnostics,
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
            prompted_item = prompted_item_for_extraction(
                record,
                patient_turn_count=input.patient_turn_count,
            )
            extraction = await self._gateway.generate_structured(
                build_patch_extraction_messages(
                    record=record,
                    latest_user_message=latest_turn,
                    previous_assistant_message=input.previous_assistant_message,
                    prompted_item=prompted_item,
                ),
                IntakeExtraction,
                self._patch_policy,
            )
            materialization = materialize_extraction(
                extraction,
                latest_user_turn=latest_turn,
                prompted_item=prompted_item,
            )
            merge_result = merge_intake_record_patch_with_diagnostics(
                record,
                materialization.patch,
                latest_user_message=latest_turn,
                source_message_sequence=latest_turn.sequence,
                strict_quote_validation=input.strict_quote_validation,
            )
            raw_count = materialization.raw_candidate_count
            retained_count = merge_result.retained_evidence_count
            if merge_result.status == "merge_failure":
                status = "merge_failure"
            elif raw_count == 0:
                status = "empty_patch"
            elif retained_count == 0:
                status = "empty_after_validation"
            else:
                status = merge_result.status
            combined_reasons = (
                *materialization.drop_reasons,
                *merge_result.drop_reasons,
            )[:MAX_INTAKE_DROP_REASONS]
            record = merge_result.record
            record_changed = merge_result.record_changed
            extraction_failed = status in _FAILURE_STATUSES
            merge_diagnostics = IntakeMergeDiagnostics(
                status=status,
                applied=merge_result.applied,
                record_changed=merge_result.record_changed,
                raw_evidence_count=raw_count,
                retained_evidence_count=retained_count,
                dropped_evidence_count=raw_count - retained_count,
                drop_reasons=combined_reasons,
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

    def stream_response(self, plan: IntakeTurnPlan) -> AsyncGenerator[str, None]:
        return self._gateway.stream_text(
            plan.response_messages,
            self._response_policy,
        )

    def _latest_user_turn(self, input: IntakeTurnInput) -> TranscriptTurn | None:
        if not input.transcript:
            return None
        latest = input.transcript[-1]
        return latest if latest.role == "user" else None
