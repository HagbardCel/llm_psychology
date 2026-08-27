"""Category C live eval: clear dual safety denial must retain grounded evidence."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from evals.harness import request_extra_body, request_timeout_seconds
from evals.intake_risk_denial_evidence import (
    EVIDENCE_INTEGRITY_FAILURE,
    build_category_c_evidence_payload,
    build_evidence_stages,
    canonical_fixture_digests,
    correlate_intake_patch_call,
    evaluate_evidence_integrity,
    provider_attempt_rows,
    resolve_debug_run_dir,
    write_category_c_evidence,
)
from jung.diagnostics import sanitize_url, sanitize_value
from jung.domain.models import Profile
from jung.domain.text import normalize_content
from jung.llm.gateway import ChatMessage, ChatRole, LLMTask, StructuredOutputMode
from jung.phases.intake.extraction import IntakeExtraction
from jung.phases.intake.models import IntakeRecord, IntakeTurnInput
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.intake.prompts import PROMPT_VERSION, build_patch_extraction_messages
from jung.phases.transcript import TranscriptTurn
from tests.support.local_llm import (
    LocalModelEnvironment,
    build_local_model_client,
    build_local_model_policies,
)

pytestmark = [pytest.mark.eval, pytest.mark.real_llm]

FROZEN_FIXTURE = "I am not thinking about harming myself or anyone else."
FROZEN_PRIOR = "I have been anxious in seminars lately."
FROZEN_ASSISTANT_QUESTION = (
    "Are you having thoughts of harming yourself or anyone else?"
)


def _canonical_fixture_digests(
    *,
    structured_mode: StructuredOutputMode,
) -> tuple[str, str]:
    user_turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=2,
        role="user",
        content=FROZEN_FIXTURE,
    )
    messages = build_patch_extraction_messages(
        record=IntakeRecord(),
        latest_user_message=user_turn,
        previous_assistant_message=FROZEN_ASSISTANT_QUESTION,
        prompted_item="risk_screen",
    )
    prepared: list[ChatMessage] = list(messages)
    if structured_mode is StructuredOutputMode.PROMPT:
        from jung.llm.structured import build_prompt_schema_instruction

        prepared.append(
            ChatMessage(
                role=ChatRole.USER,
                content=build_prompt_schema_instruction(IntakeExtraction),
            )
        )
    role_content = [
        {"role": message.role.value, "content": message.content} for message in prepared
    ]
    return canonical_fixture_digests(
        structured_mode=structured_mode,
        messages=role_content,
    )


@pytest.mark.asyncio
async def test_intake_clear_risk_denial(
    eval_environment: LocalModelEnvironment,
) -> None:
    """Clear dual safety denial must retain grounded evidence (Category C)."""
    primary_exc: BaseException | None = None
    integrity_exc: BaseException | None = None
    from evals.intake_risk_denial_evidence import MemoryDiagnosticRecorder

    memory_recorder = MemoryDiagnosticRecorder()
    extra_body: dict[str, object] | None = None
    plan = None
    semantic_passed = False

    try:
        try:
            timeout_seconds = request_timeout_seconds()
            extra_body = request_extra_body()
        except ValueError as exc:
            pytest.fail(str(exc))

        policies = build_local_model_policies(
            eval_environment,
            request_timeout_seconds=timeout_seconds,
        )
        client = build_local_model_client(
            eval_environment,
            extra_body=extra_body,
            recorder=memory_recorder,
        )
        try:
            processor = IntakeProcessor(
                client.gateway,
                patch_policy=policies[LLMTask.INTAKE_PATCH],
                response_policy=policies[LLMTask.INTAKE_RESPONSE],
            )
            prior_turn = TranscriptTurn(
                message_id=uuid4(),
                sequence=1,
                role="user",
                content=FROZEN_PRIOR,
            )
            user_turn = TranscriptTurn(
                message_id=uuid4(),
                sequence=2,
                role="user",
                content=FROZEN_FIXTURE,
            )
            plan = await processor.prepare_turn(
                IntakeTurnInput(
                    profile=Profile(name="Alex", primary_language="English"),
                    current_record=IntakeRecord(),
                    transcript=(prior_turn, user_turn),
                    latest_user_message=user_turn.content,
                    previous_assistant_message=FROZEN_ASSISTANT_QUESTION,
                    patient_turn_count=2,
                )
            )
            diagnostics = plan.merge_diagnostics
            assert diagnostics is not None
            assert diagnostics.status == "applied"
            assert diagnostics.retained_evidence_count >= 1
            assert plan.extraction_target == "risk_screen"
            assert plan.record_changed is True
            safety = plan.merged_record.safety
            assert safety.self_harm.is_present()
            assert safety.harm_to_others.is_present()
            assert not safety.medical_urgency.is_present()
            for quote in (
                safety.self_harm.evidence_quote,
                safety.harm_to_others.evidence_quote,
            ):
                assert quote
                assert normalize_content(quote) in normalize_content(FROZEN_FIXTURE)
            semantic_passed = True
        finally:
            await client.aclose()
    except BaseException as exc:
        primary_exc = exc
    finally:
        write_exc: BaseException | None = None
        try:
            canonical_messages, canonical_structured = _canonical_fixture_digests(
                structured_mode=eval_environment.structured_mode,
            )
            correlation, correlation_errors = correlate_intake_patch_call(
                memory_recorder
            )
            stages: dict[str, Any] | None = None
            extraction_target: str | None = None
            if correlation is not None:
                stages = build_evidence_stages(
                    extraction=correlation.accepted_extraction,
                    pre_turn_record=IntakeRecord(),
                    user_turn=TranscriptTurn(
                        message_id=uuid4(),
                        sequence=2,
                        role="user",
                        content=FROZEN_FIXTURE,
                    ),
                    prompted_item="risk_screen",
                    fixture=FROZEN_FIXTURE,
                )
                extraction_target = "risk_screen"
            elif plan is not None:
                extraction_target = plan.extraction_target

            integrity_passed, messages_match, structured_match, integrity_errors = (
                evaluate_evidence_integrity(
                    correlation=correlation,
                    correlation_errors=correlation_errors,
                    canonical_messages_sha256=canonical_messages,
                    canonical_structured_sha256=canonical_structured,
                    stages=stages,
                )
            )

            sanitized_extra = (
                sanitize_value(extra_body) if extra_body is not None else None
            )
            provider_attempts = (
                provider_attempt_rows(correlation.provider_attempts)
                if correlation is not None
                else []
            )
            accepted_attempt = (
                correlation.accepted_attempt if correlation is not None else None
            )
            llm_call_id = correlation.llm_call_id if correlation is not None else None

            payload = build_category_c_evidence_payload(
                semantic_assertions_passed=semantic_passed,
                evidence_integrity_passed=integrity_passed,
                model=eval_environment.model,
                sanitized_endpoint=sanitize_url(eval_environment.base_url),
                structured_mode=eval_environment.structured_mode.value,
                prompt_version=PROMPT_VERSION,
                extra_body=sanitized_extra,
                frozen_fixture=FROZEN_FIXTURE,
                extraction_target=extraction_target,
                llm_call_id=llm_call_id,
                raw_accepted_fields=(
                    stages.get("raw_accepted_fields") if stages else None
                ),
                validation_retained_paths=(
                    stages.get("validation_retained_paths") if stages else None
                ),
                materialization_dropped_paths=(
                    stages.get("materialization_dropped_paths") if stages else None
                ),
                merge_dropped_paths=(
                    stages.get("merge_dropped_paths") if stages else None
                ),
                merged_changed_paths=(
                    stages.get("merged_changed_paths") if stages else None
                ),
                raw_medical_urgency_absent=(
                    stages.get("raw_medical_urgency_absent") if stages else None
                ),
                validation_medical_urgency_absent=(
                    stages.get("validation_medical_urgency_absent") if stages else None
                ),
                merged_medical_urgency_absent=(
                    stages.get("merged_medical_urgency_absent") if stages else None
                ),
                merge_status=stages.get("merge_status") if stages else None,
                raw_evidence_count=(
                    stages.get("raw_evidence_count") if stages else None
                ),
                retained_evidence_count=(
                    stages.get("retained_evidence_count") if stages else None
                ),
                dropped_evidence_count=(
                    stages.get("dropped_evidence_count") if stages else None
                ),
                record_changed=stages.get("record_changed") if stages else None,
                provider_attempts=provider_attempts,
                accepted_attempt=accepted_attempt,
                canonical_fixture_provider_messages_sha256=canonical_messages,
                canonical_fixture_structured_request_sha256=canonical_structured,
                canonical_matches_executed_messages=messages_match,
                canonical_matches_executed_structured=structured_match,
                primary_failure_code=(
                    None
                    if primary_exc is None
                    else getattr(primary_exc, "code", None)
                    or type(primary_exc).__name__
                ),
                primary_failure_exception_type=(
                    None if primary_exc is None else type(primary_exc).__name__
                ),
                evidence_integrity_errors=integrity_errors,
            )

            debug_dir = resolve_debug_run_dir()
            if debug_dir is not None:
                write_category_c_evidence(run_dir=debug_dir, payload=payload)

            if semantic_passed and not integrity_passed:
                integrity_exc = AssertionError(EVIDENCE_INTEGRITY_FAILURE)
        except BaseException as exc:
            write_exc = exc

        if write_exc is not None:
            if primary_exc is not None:
                raise ExceptionGroup(
                    "category-c evidence write failed after primary failure",
                    [primary_exc, write_exc],
                )
            if integrity_exc is not None:
                raise ExceptionGroup(
                    "category-c evidence write failed after integrity failure",
                    [integrity_exc, write_exc],
                )
            raise write_exc
        if primary_exc is not None:
            raise primary_exc
        if integrity_exc is not None:
            raise integrity_exc
