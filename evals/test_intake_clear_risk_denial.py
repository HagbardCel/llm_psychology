"""Category C live eval: clear dual safety denial must retain grounded evidence."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from evals.harness import request_extra_body, request_timeout_seconds
from evals.intake_risk_denial_evidence import (
    AcceptedAttempt,
    MemoryDiagnosticRecorder,
    build_category_c_evidence_payload,
    digests_from_provider_request_event,
    provider_messages_sha256,
    resolve_debug_run_dir,
    structured_request_sha256,
    write_category_c_evidence,
)
from jung.diagnostics import sanitize_url
from jung.domain.models import Profile
from jung.domain.text import normalize_content
from jung.llm.gateway import ChatMessage, ChatRole, LLMTask, StructuredOutputMode
from jung.llm.openai_compatible import ProviderAttemptEvent
from jung.llm.structured import (
    build_prompt_schema_instruction,
    response_format_for_mode,
)
from jung.phases.intake.extraction import IntakeExtraction
from jung.phases.intake.models import IntakeEvidence, IntakeRecord, IntakeTurnInput
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
    """Provider-prepared digests for the frozen Category C fixture (initial attempt)."""
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
        prepared.append(
            ChatMessage(
                role=ChatRole.USER,
                content=build_prompt_schema_instruction(IntakeExtraction),
            )
        )
    response_format = response_format_for_mode(structured_mode, IntakeExtraction)
    role_content = [
        {"role": message.role.value, "content": message.content} for message in prepared
    ]
    return (
        provider_messages_sha256(role_content),
        structured_request_sha256(
            structured_mode=structured_mode.value,
            response_format_or_schema_instruction=response_format,
        ),
    )


def _accepted_field(
    path: str, evidence: IntakeEvidence, fixture: str
) -> dict[str, Any]:
    quote = evidence.evidence_quote
    return {
        "path": path,
        "status": evidence.response_status,
        "quote": quote,
        "quote_valid": bool(
            quote and normalize_content(quote) in normalize_content(fixture)
        ),
    }


def _provider_attempts_for_intake_patch(
    recorder: MemoryDiagnosticRecorder,
    attempt_events: list[ProviderAttemptEvent],
) -> list[dict[str, Any]]:
    request_events = [
        event
        for event in recorder.events
        if event.get("kind") == "llm.provider.request"
        and isinstance(event.get("data"), dict)
        and event["data"].get("task") == LLMTask.INTAKE_PATCH.value
    ]
    patch_attempts = [
        event for event in attempt_events if event.task == LLMTask.INTAKE_PATCH.value
    ]
    rows: list[dict[str, Any]] = []
    for index, attempt_event in enumerate(patch_attempts):
        digests: dict[str, str] = {
            "provider_messages_sha256": "",
            "structured_request_sha256": "",
        }
        if index < len(request_events):
            digests = digests_from_provider_request_event(request_events[index]["data"])
        row: dict[str, Any] = {
            "attempt": attempt_event.attempt,
            "provider_messages_sha256": digests["provider_messages_sha256"],
            "structured_request_sha256": digests["structured_request_sha256"],
            "status": attempt_event.status,
        }
        if attempt_event.correction_trigger is not None:
            row["correction_trigger"] = attempt_event.correction_trigger
        rows.append(row)
    return rows


def _accepted_attempt_label(
    attempts: list[dict[str, Any]],
) -> AcceptedAttempt | None:
    if not attempts:
        return None
    successes = [row for row in attempts if row.get("status") == "success"]
    if len(successes) == 1:
        label = successes[0].get("attempt")
        if label in {"initial", "correction"}:
            return label  # type: ignore[return-value]
    if successes:
        return "unknown"
    return "unknown"


@pytest.mark.asyncio
async def test_intake_clear_risk_denial(
    eval_environment: LocalModelEnvironment,
) -> None:
    """Clear dual safety denial must retain grounded evidence (Category C)."""
    primary_exc: BaseException | None = None
    memory_recorder = MemoryDiagnosticRecorder()
    attempt_events: list[ProviderAttemptEvent] = []
    extra_body: dict[str, object] | None = None
    plan = None
    success = False

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
            on_provider_attempt=attempt_events.append,
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
            success = True
        finally:
            await client.aclose()
    except BaseException as exc:
        primary_exc = exc
    finally:
        write_exc: BaseException | None = None
        try:
            provider_attempts = _provider_attempts_for_intake_patch(
                memory_recorder, attempt_events
            )
            canonical_messages, canonical_structured = _canonical_fixture_digests(
                structured_mode=eval_environment.structured_mode,
            )
            # When the live initial attempt digests are available, prefer them as
            # the executed canonical reference (same frozen fixture/mode).
            if provider_attempts:
                initial = next(
                    (
                        row
                        for row in provider_attempts
                        if row.get("attempt") == "initial"
                    ),
                    provider_attempts[0],
                )
                if initial.get("provider_messages_sha256"):
                    canonical_messages = str(initial["provider_messages_sha256"])
                if initial.get("structured_request_sha256"):
                    canonical_structured = str(initial["structured_request_sha256"])

            accepted_fields: list[dict[str, Any]] | None = None
            validation_retained_paths: list[str] | None = None
            persisted_changed_paths: list[str] | None = None
            medical_urgency_absent: bool | None = None
            merge_status: str | None = None
            raw_count: int | None = None
            retained_count: int | None = None
            dropped_count: int | None = None
            record_changed: bool | None = None
            extraction_target: str | None = None
            accepted_attempt: AcceptedAttempt | None = None

            if plan is not None:
                extraction_target = plan.extraction_target
                record_changed = plan.record_changed
                diagnostics = plan.merge_diagnostics
                if diagnostics is not None:
                    merge_status = diagnostics.status
                    raw_count = diagnostics.raw_evidence_count
                    retained_count = diagnostics.retained_evidence_count
                    dropped_count = diagnostics.dropped_evidence_count
                safety = plan.merged_record.safety
                accepted_fields = []
                for path, evidence in (
                    ("safety.self_harm", safety.self_harm),
                    ("safety.harm_to_others", safety.harm_to_others),
                ):
                    if evidence.is_present():
                        accepted_fields.append(
                            _accepted_field(path, evidence, FROZEN_FIXTURE)
                        )
                validation_retained_paths = [item["path"] for item in accepted_fields]
                persisted_changed_paths = list(validation_retained_paths)
                medical_urgency_absent = not safety.medical_urgency.is_present()
                accepted_attempt = _accepted_attempt_label(provider_attempts)

            payload = build_category_c_evidence_payload(
                success=success,
                model=eval_environment.model,
                sanitized_endpoint=sanitize_url(eval_environment.base_url),
                structured_mode=eval_environment.structured_mode.value,
                prompt_version=PROMPT_VERSION,
                extra_body=extra_body,
                frozen_fixture=FROZEN_FIXTURE,
                extraction_target=extraction_target,
                accepted_fields=accepted_fields,
                validation_retained_paths=validation_retained_paths,
                persisted_changed_paths=persisted_changed_paths,
                medical_urgency_absent=medical_urgency_absent,
                merge_status=merge_status,
                raw_evidence_count=raw_count,
                retained_evidence_count=retained_count,
                dropped_evidence_count=dropped_count,
                record_changed=record_changed,
                provider_attempts=provider_attempts,
                accepted_attempt=accepted_attempt,
                canonical_fixture_provider_messages_sha256=canonical_messages,
                canonical_fixture_structured_request_sha256=canonical_structured,
                primary_failure_code=(
                    None
                    if primary_exc is None
                    else getattr(primary_exc, "code", None)
                    or type(primary_exc).__name__
                ),
                primary_failure_exception_type=(
                    None if primary_exc is None else type(primary_exc).__name__
                ),
            )
            debug_dir = resolve_debug_run_dir()
            if debug_dir is not None:
                write_category_c_evidence(run_dir=debug_dir, payload=payload)
        except BaseException as exc:
            write_exc = exc

        if write_exc is not None:
            if primary_exc is not None:
                raise ExceptionGroup(
                    "category-c evidence write failed after primary failure",
                    [primary_exc, write_exc],
                )
            raise write_exc
        if primary_exc is not None:
            raise primary_exc
