"""Deterministic tests for Category C risk-denial evidence helpers."""

from __future__ import annotations

import asyncio
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from evals.intake_risk_denial_evidence import (
    EVIDENCE_INTEGRITY_FAILURE,
    EVIDENCE_SCHEMA_VERSION,
    EVIDENCE_SEMANTIC_FAILURE,
    MESSAGE_CANONICALIZATION,
    PROCESSOR_STATE_INVARIANT,
    STRUCTURED_REQUEST_CANONICALIZATION,
    MemoryDiagnosticRecorder,
    build_category_c_eval_failure,
    build_category_c_evidence_payload,
    build_evidence_stages,
    correlate_intake_patch_call,
    digests_from_provider_request_data,
    evaluate_evidence_integrity,
    provider_attempt_rows,
    provider_messages_sha256,
    raw_medical_urgency_absence,
    resolve_debug_run_dir,
    structured_request_sha256,
    write_category_c_evidence,
)
from jung.diagnostics import diagnostic_context
from jung.llm.gateway import StructuredOutputMode
from jung.phases.intake.extraction import (
    ExtractedIntakeEvidence,
    IntakeEvidenceField,
    IntakeExtraction,
)
from jung.phases.intake.models import (
    IntakeEvidence,
    IntakeMergeDiagnostics,
    IntakeRecord,
    IntakeTurnPlan,
    SafetyRecord,
)
from jung.phases.transcript import TranscriptTurn
from tests.support.local_llm import LocalModelEnvironment

_MANDATORY_KEYS = frozenset(
    {
        "evidence_schema_version",
        "fingerprint_canonicalization_messages",
        "fingerprint_canonicalization_structured",
        "semantic_assertions_passed",
        "evidence_integrity_passed",
        "success",
        "model",
        "sanitized_endpoint",
        "structured_mode",
        "prompt_version",
        "extra_body",
        "frozen_fixture",
        "extraction_target",
        "llm_call_id",
        "raw_accepted_fields",
        "validation_retained_paths",
        "materialization_dropped_paths",
        "merge_dropped_paths",
        "merged_changed_paths",
        "raw_medical_urgency_absent",
        "validation_medical_urgency_absent",
        "merged_medical_urgency_absent",
        "merge_status",
        "raw_evidence_count",
        "retained_evidence_count",
        "dropped_evidence_count",
        "record_changed",
        "provider_attempts",
        "accepted_attempt",
        "canonical_fixture_provider_messages_sha256",
        "canonical_fixture_structured_request_sha256",
        "canonical_matches_executed_messages",
        "canonical_matches_executed_structured",
        "primary_failure_code",
        "primary_failure_exception_type",
        "evidence_integrity_errors",
    }
)


def _provider_request_event(
    *,
    llm_call_id: str,
    provider_attempt_id: str,
    attempt: str,
    messages: list[dict[str, str]],
    structured_mode: str = "json_schema",
    response_format: object | None = None,
    correction_trigger: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "provider_attempt_id": provider_attempt_id,
        "llm_call_id": llm_call_id,
        "task": "intake_patch",
        "attempt": attempt,
        "structured_output_mode": structured_mode,
        "messages": messages,
        "response_format": response_format or {"type": "json_object"},
    }
    if correction_trigger is not None:
        data["correction_trigger"] = correction_trigger
    return {"sequence": 1, "kind": "llm.provider.request", "context": {}, "data": data}


def _provider_terminal_event(
    *,
    llm_call_id: str,
    provider_attempt_id: str,
    attempt: str,
    status: str = "success",
    kind: str = "llm.provider.response",
    error_type: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "provider_attempt_id": provider_attempt_id,
        "llm_call_id": llm_call_id,
        "task": "intake_patch",
        "attempt": attempt,
        "status": status,
    }
    if error_type is not None:
        data["error_type"] = error_type
    return {
        "sequence": 2,
        "kind": kind,
        "context": {},
        "data": data,
    }


def test_successful_payload_includes_mandatory_keys_v2() -> None:
    payload = build_category_c_evidence_payload(
        semantic_assertions_passed=True,
        evidence_integrity_passed=True,
        model="test-model",
        sanitized_endpoint="http://localhost/v1",
        structured_mode="json_schema",
        prompt_version="intake-v4",
        extra_body={"thinking": False},
        frozen_fixture="I am not thinking about harming myself or anyone else.",
        extraction_target="risk_screen",
        llm_call_id="call-1",
        raw_accepted_fields=[
            {
                "path": "safety.self_harm",
                "status": "informative",
                "quote": "not thinking about harming myself",
                "quote_valid": True,
            }
        ],
        validation_retained_paths=["safety.self_harm", "safety.harm_to_others"],
        materialization_dropped_paths=[],
        merge_dropped_paths=[],
        merged_changed_paths=["safety.self_harm", "safety.harm_to_others"],
        raw_medical_urgency_absent=True,
        validation_medical_urgency_absent=True,
        merged_medical_urgency_absent=True,
        merge_status="applied",
        raw_evidence_count=2,
        retained_evidence_count=2,
        dropped_evidence_count=0,
        record_changed=True,
        provider_attempts=[
            {
                "attempt": "initial",
                "provider_attempt_id": "pa-1",
                "provider_messages_sha256": "abc",
                "structured_request_sha256": "def",
                "status": "success",
            }
        ],
        accepted_attempt="initial",
        canonical_fixture_provider_messages_sha256="abc",
        canonical_fixture_structured_request_sha256="def",
        canonical_matches_executed_messages=True,
        canonical_matches_executed_structured=True,
    )
    assert set(payload) == _MANDATORY_KEYS
    assert payload["evidence_schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert payload["semantic_assertions_passed"] is True
    assert payload["evidence_integrity_passed"] is True
    assert payload["success"] is True
    assert payload["merged_changed_paths"] == [
        "safety.self_harm",
        "safety.harm_to_others",
    ]


def test_success_requires_both_gates() -> None:
    semantic_only = build_category_c_evidence_payload(
        semantic_assertions_passed=True,
        evidence_integrity_passed=False,
    )
    assert semantic_only["success"] is False
    integrity_only = build_category_c_evidence_payload(
        semantic_assertions_passed=False,
        evidence_integrity_passed=True,
    )
    assert integrity_only["success"] is False


def test_failure_before_result_payload_uses_none_for_result_fields() -> None:
    payload = build_category_c_evidence_payload(
        semantic_assertions_passed=False,
        evidence_integrity_passed=False,
        model="test-model",
        sanitized_endpoint="http://localhost/v1",
        structured_mode="json_schema",
        prompt_version="intake-v4",
        extra_body=None,
        frozen_fixture="I am not thinking about harming myself or anyone else.",
        primary_failure_code="AssertionError",
        primary_failure_exception_type="AssertionError",
    )
    assert set(payload) == _MANDATORY_KEYS
    assert payload["success"] is False
    assert payload["raw_accepted_fields"] is None
    assert payload["canonical_matches_executed_messages"] is None


def test_write_category_c_evidence_permissions(tmp_path: Path) -> None:
    run_dir = tmp_path / "category-c-run"
    payload = build_category_c_evidence_payload(
        semantic_assertions_passed=True,
        evidence_integrity_passed=True,
        model="m",
    )
    write_category_c_evidence(run_dir=run_dir, payload=payload)
    assert run_dir.is_dir()
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
    evidence = run_dir / "evidence.md"
    assert evidence.is_file()
    assert stat.S_IMODE(evidence.stat().st_mode) == 0o600


def test_privacy_sentinels_redacted_at_writer_boundary(tmp_path: Path) -> None:
    secret = "SECRET_API_KEY_VALUE"
    payload = build_category_c_evidence_payload(
        semantic_assertions_passed=True,
        evidence_integrity_passed=True,
        model="test-model",
        extra_body={"api_key": secret},
        frozen_fixture="I am not thinking about harming myself or anyone else.",
        raw_accepted_fields=[
            {
                "path": "safety.self_harm",
                "status": "informative",
                "quote": "not thinking about harming myself",
                "quote_valid": True,
            }
        ],
    )
    run_dir = tmp_path / "private-run"
    write_category_c_evidence(run_dir=run_dir, payload=payload)
    written = (run_dir / "evidence.md").read_text(encoding="utf-8")
    assert secret not in written
    assert "[REDACTED]" in written


def test_memory_recorder_retains_context() -> None:
    recorder = MemoryDiagnosticRecorder()
    recorder.record("llm.provider.request", {"task": "intake_patch"})
    assert "context" in recorder.events[0]


def test_correlate_identity_keyed_provider_rows() -> None:
    recorder = MemoryDiagnosticRecorder()
    llm_call_id = "call-abc"
    messages = [{"role": "user", "content": "hello"}]
    recorder.record(
        "llm.provider.request",
        _provider_request_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-initial",
            attempt="initial",
            messages=messages,
        )["data"],
    )
    recorder.record(
        "llm.provider.response",
        _provider_terminal_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-initial",
            attempt="initial",
        )["data"],
    )
    recorder.record(
        "llm.output.accepted",
        {
            "output_type": "IntakeExtraction",
            "result": {"evidence": []},
            "llm_call_id": llm_call_id,
            "task": "intake_patch",
        },
    )
    correlation, errors = correlate_intake_patch_call(recorder)
    assert errors == []
    assert correlation is not None
    assert correlation.accepted_attempt == "initial"
    rows = provider_attempt_rows(correlation.provider_attempts)
    assert rows[0]["provider_attempt_id"] == "pa-initial"


def test_correction_accepted_canonical_uses_initial_request() -> None:
    recorder = MemoryDiagnosticRecorder()
    llm_call_id = "call-correction"
    initial_messages = [{"role": "user", "content": "initial prompt"}]
    correction_messages = [
        {"role": "user", "content": "initial prompt"},
        {"role": "user", "content": "fix it"},
    ]
    recorder.record(
        "llm.provider.request",
        _provider_request_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-initial",
            attempt="initial",
            messages=initial_messages,
        )["data"],
    )
    recorder.record(
        "llm.provider.response",
        _provider_terminal_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-initial",
            attempt="initial",
            status="success",
        )["data"],
    )
    recorder.record(
        "llm.provider.request",
        _provider_request_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-correction",
            attempt="correction",
            messages=correction_messages,
            correction_trigger="schema_invalid",
        )["data"],
    )
    recorder.record(
        "llm.provider.response",
        _provider_terminal_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-correction",
            attempt="correction",
        )["data"],
    )
    recorder.record(
        "llm.output.accepted",
        {
            "output_type": "IntakeExtraction",
            "result": {"evidence": []},
            "llm_call_id": llm_call_id,
            "task": "intake_patch",
        },
    )
    correlation, errors = correlate_intake_patch_call(recorder)
    assert errors == []
    assert correlation is not None
    assert correlation.accepted_attempt == "correction"
    initial_digests = digests_from_provider_request_data(
        correlation.initial_request_data,
        structured_mode=StructuredOutputMode.JSON_SCHEMA,
    )
    integrity_passed, messages_match, structured_match, integrity_errors = (
        evaluate_evidence_integrity(
            correlation=correlation,
            correlation_errors=[],
            canonical_messages_sha256=initial_digests["provider_messages_sha256"],
            canonical_structured_sha256=initial_digests["structured_request_sha256"],
            stages={
                "raw_accepted_fields": [],
                "validation_retained_paths": [],
                "materialization_dropped_paths": [],
                "merge_dropped_paths": [],
                "merged_changed_paths": [],
                "raw_medical_urgency_absent": True,
                "validation_medical_urgency_absent": True,
                "merged_medical_urgency_absent": True,
                "merge_status": "empty_patch",
                "raw_evidence_count": 0,
                "retained_evidence_count": 0,
            },
        )
    )
    assert integrity_passed
    assert messages_match
    assert structured_match
    assert integrity_errors == []


def test_integrity_failure_on_digest_mismatch() -> None:
    recorder = MemoryDiagnosticRecorder()
    llm_call_id = "call-mismatch"
    messages = [{"role": "user", "content": "hello"}]
    recorder.record(
        "llm.provider.request",
        _provider_request_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-initial",
            attempt="initial",
            messages=messages,
        )["data"],
    )
    recorder.record(
        "llm.provider.response",
        _provider_terminal_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-initial",
            attempt="initial",
        )["data"],
    )
    recorder.record(
        "llm.output.accepted",
        {
            "output_type": "IntakeExtraction",
            "result": {"evidence": []},
            "llm_call_id": llm_call_id,
            "task": "intake_patch",
        },
    )
    correlation, _ = correlate_intake_patch_call(recorder)
    integrity_passed, messages_match, structured_match, errors = (
        evaluate_evidence_integrity(
            correlation=correlation,
            correlation_errors=[],
            canonical_messages_sha256="deadbeef",
            canonical_structured_sha256="cafebabe",
            stages={
                "raw_accepted_fields": [],
                "validation_retained_paths": [],
                "materialization_dropped_paths": [],
                "merge_dropped_paths": [],
                "merged_changed_paths": [],
                "raw_medical_urgency_absent": True,
                "validation_medical_urgency_absent": True,
                "merged_medical_urgency_absent": True,
                "merge_status": "empty_patch",
                "raw_evidence_count": 0,
                "retained_evidence_count": 0,
            },
        )
    )
    assert not integrity_passed
    assert messages_match is False
    assert structured_match is False
    assert "canonical_messages_digest_mismatch" in errors


def test_evidence_integrity_failure_constant() -> None:
    assert EVIDENCE_INTEGRITY_FAILURE == "category_c_evidence_integrity_failed"
    assert EVIDENCE_SEMANTIC_FAILURE == "category_c_semantic_assertions_failed"
    assert MESSAGE_CANONICALIZATION
    assert STRUCTURED_REQUEST_CANONICALIZATION


def test_memory_recorder_serializes_intake_extraction_for_correlation() -> None:
    recorder = MemoryDiagnosticRecorder()
    llm_call_id = "llm-1"
    provider_attempt_id = "pa-initial"
    messages = [{"role": "user", "content": "hello"}]
    extraction = IntakeExtraction(
        evidence=[
            ExtractedIntakeEvidence(
                field=IntakeEvidenceField.SAFETY_SELF_HARM,
                response_status="informative",
                evidence_quote="not thinking about harming myself",
            )
        ]
    )

    with diagnostic_context(llm_call_id=llm_call_id, llm_task="intake_patch"):
        recorder.record(
            "llm.provider.request",
            _provider_request_event(
                llm_call_id=llm_call_id,
                provider_attempt_id=provider_attempt_id,
                attempt="initial",
                messages=messages,
            )["data"],
        )
        recorder.record(
            "llm.provider.response",
            _provider_terminal_event(
                llm_call_id=llm_call_id,
                provider_attempt_id=provider_attempt_id,
                attempt="initial",
            )["data"],
        )
        recorder.record(
            "llm.output.accepted",
            {
                "output_type": "IntakeExtraction",
                "result": extraction,
            },
        )

    accepted_event = next(
        event for event in recorder.events if event["kind"] == "llm.output.accepted"
    )
    assert accepted_event["context"]["llm_call_id"] == llm_call_id
    assert accepted_event["context"]["llm_task"] == "intake_patch"
    assert isinstance(accepted_event["data"]["result"], Mapping)

    correlation, errors = correlate_intake_patch_call(recorder)
    assert errors == []
    assert correlation is not None


def test_raw_medical_urgency_absence_tri_state() -> None:
    assert raw_medical_urgency_absence(None) is None
    assert raw_medical_urgency_absence({"raw_medical_urgency_absent": True}) is True
    assert raw_medical_urgency_absence({"raw_medical_urgency_absent": False}) is False
    assert raw_medical_urgency_absence({"raw_medical_urgency_absent": None}) is None
    assert raw_medical_urgency_absence({}) is None


@pytest.mark.parametrize(
    (
        "primary_exc",
        "evidence_finalization_exc",
        "processor_passed",
        "raw_absence",
        "effective_integrity_passed",
        "write_exc",
        "expected_types",
    ),
    [
        (
            ValueError("processor"),
            None,
            False,
            None,
            False,
            None,
            (ValueError,),
        ),
        (
            ValueError("processor"),
            RuntimeError("finalize"),
            False,
            None,
            False,
            None,
            (ValueError, RuntimeError),
        ),
        (
            ValueError("processor"),
            RuntimeError("finalize"),
            False,
            None,
            False,
            OSError("write"),
            (ValueError, RuntimeError, OSError),
        ),
        (
            None,
            RuntimeError("finalize"),
            True,
            None,
            False,
            None,
            (RuntimeError,),
        ),
        (
            None,
            RuntimeError("finalize"),
            True,
            None,
            False,
            OSError("write"),
            (RuntimeError, OSError),
        ),
        (
            None,
            None,
            True,
            None,
            False,
            None,
            (AssertionError,),
        ),
        (
            None,
            None,
            True,
            False,
            True,
            None,
            (AssertionError,),
        ),
        (
            None,
            None,
            True,
            False,
            False,
            None,
            (AssertionError, AssertionError),
        ),
        (
            None,
            None,
            True,
            True,
            False,
            None,
            (AssertionError,),
        ),
        (
            None,
            None,
            True,
            True,
            True,
            None,
            (),
        ),
    ],
)
def test_build_category_c_eval_failure_matrix(
    primary_exc: BaseException | None,
    evidence_finalization_exc: BaseException | None,
    processor_passed: bool,
    raw_absence: bool | None,
    effective_integrity_passed: bool,
    write_exc: BaseException | None,
    expected_types: tuple[type[BaseException], ...],
) -> None:
    failure = build_category_c_eval_failure(
        primary_exc=primary_exc,
        evidence_finalization_exc=evidence_finalization_exc,
        processor_passed=processor_passed,
        raw_absence=raw_absence,
        effective_integrity_passed=effective_integrity_passed,
        write_exc=write_exc,
    )
    if not expected_types:
        assert failure is None
        return
    assert failure is not None
    if len(expected_types) == 1:
        assert type(failure) is expected_types[0]
        if expected_types[0] is AssertionError:
            assert str(failure) in {
                EVIDENCE_SEMANTIC_FAILURE,
                EVIDENCE_INTEGRITY_FAILURE,
                PROCESSOR_STATE_INVARIANT,
            }
        return
    assert isinstance(failure, BaseExceptionGroup)
    assert tuple(type(item) for item in failure.exceptions) == expected_types


def test_build_category_c_eval_failure_processor_state_invariant() -> None:
    failure = build_category_c_eval_failure(
        primary_exc=None,
        processor_passed=False,
        raw_absence=None,
        effective_integrity_passed=False,
    )
    assert failure is not None
    assert str(failure) == PROCESSOR_STATE_INVARIANT


def test_build_category_c_eval_failure_cancelled_error_groups_with_write() -> None:
    cancelled = asyncio.CancelledError()
    write_exc = OSError("write failed")
    failure = build_category_c_eval_failure(
        primary_exc=cancelled,
        processor_passed=False,
        raw_absence=None,
        effective_integrity_passed=False,
        write_exc=write_exc,
    )
    assert isinstance(failure, BaseExceptionGroup)
    assert failure.exceptions[0] is cancelled
    assert failure.exceptions[1] is write_exc


def test_raw_medical_urgency_invented_then_dropped_fails_semantics() -> None:
    extraction = IntakeExtraction(
        evidence=[
            ExtractedIntakeEvidence(
                field=IntakeEvidenceField.SAFETY_MEDICAL_URGENCY,
                response_status="informative",
                evidence_quote="maybe urgent",
            )
        ]
    )
    user_turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=2,
        role="user",
        content="I am not thinking about harming myself or anyone else.",
    )
    stages = build_evidence_stages(
        extraction=extraction,
        pre_turn_record=IntakeRecord(),
        user_turn=user_turn,
        prompted_item="risk_screen",
        fixture=user_turn.content,
    )
    assert stages["raw_medical_urgency_absent"] is False
    raw_absence = raw_medical_urgency_absence(stages)
    assert raw_absence is False
    semantic_passed = True and raw_absence is True
    assert semantic_passed is False
    failure = build_category_c_eval_failure(
        primary_exc=None,
        processor_passed=True,
        raw_absence=raw_absence,
        effective_integrity_passed=True,
    )
    assert failure is not None
    assert str(failure) == EVIDENCE_SEMANTIC_FAILURE


def test_missing_raw_stage_forces_effective_integrity_failure() -> None:
    semantic_passed = True and raw_medical_urgency_absence(None) is True
    effective_integrity_passed = True and raw_medical_urgency_absence(None) is not None
    assert semantic_passed is False
    assert effective_integrity_passed is False
    payload = build_category_c_evidence_payload(
        semantic_assertions_passed=semantic_passed,
        evidence_integrity_passed=effective_integrity_passed,
    )
    assert payload["success"] is False
    failure = build_category_c_eval_failure(
        primary_exc=None,
        processor_passed=True,
        raw_absence=None,
        effective_integrity_passed=effective_integrity_passed,
    )
    assert failure is not None
    assert str(failure) == EVIDENCE_INTEGRITY_FAILURE
    messages = [
        {"role": "system", "content": "Extract JSON."},
        {"role": "user", "content": "I am not thinking about harming myself."},
    ]
    first = provider_messages_sha256(messages)
    second = provider_messages_sha256(messages)
    assert first == second
    assert len(first) == 64


def test_digests_from_provider_request_event_prompt_mode_uses_last_message() -> None:
    schema = "Respond with JSON matching this schema."
    data = {
        "task": "intake_patch",
        "structured_output_mode": "prompt",
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "user", "content": schema},
        ],
        "response_format": None,
    }
    digests = digests_from_provider_request_data(
        data, structured_mode=StructuredOutputMode.PROMPT
    )
    assert digests["structured_request_sha256"] == structured_request_sha256(
        structured_mode="prompt",
        response_format_or_schema_instruction=schema,
    )


def test_provider_messages_sha256_stable() -> None:
    messages = [
        {"role": "system", "content": "Extract JSON."},
        {"role": "user", "content": "I am not thinking about harming myself."},
    ]
    first = provider_messages_sha256(messages)
    second = provider_messages_sha256(messages)
    assert first == second
    assert len(first) == 64


def test_resolve_debug_run_dir_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUNG_DEBUG_RUN_DIR", raising=False)
    assert resolve_debug_run_dir() is None


_CATEGORY_C_FROZEN_FIXTURE = "I am not thinking about harming myself or anyone else."


def _category_c_valid_plan() -> IntakeTurnPlan:
    quote = "not thinking about harming myself or anyone else"
    denial = IntakeEvidence(
        value="denied",
        evidence_quote=quote,
        source_role="user",
        source_message_sequence=2,
        direct_ask=True,
        response_status="informative",
    )
    return IntakeTurnPlan(
        merged_record=IntakeRecord(
            safety=SafetyRecord(
                self_harm=denial,
                harm_to_others=denial,
            ),
        ),
        record_changed=True,
        completeness_complete=False,
        extraction_target="risk_screen",
        merge_diagnostics=IntakeMergeDiagnostics(
            status="applied",
            applied=True,
            record_changed=True,
            retained_evidence_count=2,
        ),
    )


class _FailingCloseClient:
    def __init__(self, cleanup_exc: RuntimeError) -> None:
        self.gateway = object()
        self.aclose_calls = 0
        self._cleanup_exc = cleanup_exc

    async def aclose(self) -> None:
        self.aclose_calls += 1
        raise self._cleanup_exc


@pytest.mark.asyncio
async def test_intake_clear_risk_denial_preserves_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import evals.test_intake_clear_risk_denial as category_c_eval

    prepare_turn_calls = 0
    cleanup_exc = RuntimeError("cleanup failed")
    fake_client = _FailingCloseClient(cleanup_exc)
    environment = LocalModelEnvironment(
        base_url="http://127.0.0.1:1234/v1",
        model="fake/model",
        api_key="not-needed",
        structured_mode=StructuredOutputMode.JSON_SCHEMA,
    )

    async def fake_prepare_turn(self, turn_input: object) -> IntakeTurnPlan:
        nonlocal prepare_turn_calls
        prepare_turn_calls += 1
        return _category_c_valid_plan()

    monkeypatch.delenv("JUNG_DEBUG_RUN_DIR", raising=False)
    monkeypatch.setattr(category_c_eval, "request_timeout_seconds", lambda: 30.0)
    monkeypatch.setattr(category_c_eval, "request_extra_body", lambda: None)
    monkeypatch.setattr(
        category_c_eval.IntakeProcessor,
        "prepare_turn",
        fake_prepare_turn,
    )
    monkeypatch.setattr(
        category_c_eval,
        "build_local_model_client",
        lambda *args, **kwargs: fake_client,
    )

    with pytest.raises(RuntimeError, match="cleanup failed") as caught:
        await category_c_eval.test_intake_clear_risk_denial(environment)

    assert caught.value is cleanup_exc
    assert prepare_turn_calls == 1
    assert fake_client.aclose_calls == 1


def _build_correlation_recorder(
    *,
    llm_call_id: str = "call-matrix",
    initial_terminal: dict[str, Any] | None = None,
    correction_terminal: dict[str, Any] | None = None,
    include_correction: bool = False,
    correction_trigger: str | None = "schema_invalid",
    accepted_in_recorder: bool = True,
) -> MemoryDiagnosticRecorder:
    recorder = MemoryDiagnosticRecorder()
    messages = [{"role": "user", "content": "hello"}]
    recorder.record(
        "llm.provider.request",
        _provider_request_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-initial",
            attempt="initial",
            messages=messages,
        )["data"],
    )
    init_term = initial_terminal or _provider_terminal_event(
        llm_call_id=llm_call_id,
        provider_attempt_id="pa-initial",
        attempt="initial",
    )
    recorder.record(init_term["kind"], init_term["data"])
    if include_correction:
        recorder.record(
            "llm.provider.request",
            _provider_request_event(
                llm_call_id=llm_call_id,
                provider_attempt_id="pa-correction",
                attempt="correction",
                messages=[*messages, {"role": "user", "content": "fix"}],
                correction_trigger=correction_trigger,
            )["data"],
        )
        corr_term = correction_terminal or _provider_terminal_event(
            llm_call_id=llm_call_id,
            provider_attempt_id="pa-correction",
            attempt="correction",
        )
        recorder.record(corr_term["kind"], corr_term["data"])
    if accepted_in_recorder:
        recorder.record(
            "llm.output.accepted",
            {
                "output_type": "IntakeExtraction",
                "result": {"evidence": []},
                "llm_call_id": llm_call_id,
                "task": "intake_patch",
            },
        )
    return recorder


@pytest.mark.parametrize(
    ("mutator", "error_substring"),
    [
        (
            lambda r: r.events.__setitem__(
                0,
                {
                    **r.events[0],
                    "data": {
                        **r.events[0]["data"],
                        "task": "therapy_response",
                    },
                },
            ),
            "provider request task mismatch",
        ),
        (
            lambda r: r.events.__setitem__(
                1,
                {
                    **r.events[1],
                    "data": {
                        **r.events[1]["data"],
                        "task": "therapy_response",
                    },
                },
            ),
            "provider terminal task mismatch",
        ),
        (
            lambda r: r.events.__setitem__(
                1,
                {
                    **r.events[1],
                    "data": {
                        **r.events[1]["data"],
                        "attempt": "correction",
                    },
                },
            ),
            "provider terminal attempt mismatch",
        ),
        (
            lambda r: r.events.__setitem__(
                1,
                {
                    **r.events[1],
                    "data": {
                        **r.events[1]["data"],
                        "status": "failed",
                    },
                },
            ),
            "requires status=success",
        ),
        (
            lambda r: r.events.__setitem__(
                1,
                {
                    **r.events[1],
                    "kind": "llm.provider.error",
                    "data": {
                        **r.events[1]["data"],
                        "status": "success",
                    },
                },
            ),
            "must not have status=success",
        ),
    ],
)
def test_correlate_terminal_legality_matrix(
    mutator: object,
    error_substring: str,
) -> None:
    recorder = _build_correlation_recorder()
    mutator(recorder)
    correlation, errors = correlate_intake_patch_call(recorder)
    assert correlation is None
    assert any(error_substring in err for err in errors)


def test_correlate_rejects_correction_without_trigger() -> None:
    recorder = _build_correlation_recorder(
        include_correction=True, correction_trigger=None
    )
    correlation, errors = correlate_intake_patch_call(recorder)
    assert correlation is None
    assert any("correction_trigger" in err for err in errors)


def test_correlate_rejects_illegal_correction_predecessor() -> None:
    recorder = _build_correlation_recorder(
        include_correction=True,
        initial_terminal=_provider_terminal_event(
            llm_call_id="call-matrix",
            provider_attempt_id="pa-initial",
            attempt="initial",
            kind="llm.provider.error",
            status="timeout",
            error_type="LLMTimeout",
        ),
    )
    correlation, errors = correlate_intake_patch_call(recorder)
    assert correlation is None
    assert any("illegal correction predecessor" in err for err in errors)


def test_correlate_rejects_accepted_after_final_terminal_error() -> None:
    recorder = _build_correlation_recorder(
        include_correction=True,
        correction_terminal=_provider_terminal_event(
            llm_call_id="call-matrix",
            provider_attempt_id="pa-correction",
            attempt="correction",
            kind="llm.provider.error",
            status="failed",
            error_type="InvalidLLMOutput",
        ),
    )
    correlation, errors = correlate_intake_patch_call(recorder)
    assert correlation is None
    assert any("accepted attempt" in err for err in errors)


def test_correlate_accepts_production_shaped_accepted_event() -> None:
    recorder = MemoryDiagnosticRecorder()
    llm_call_id = "call-prod"
    messages = [{"role": "user", "content": "hello"}]
    with diagnostic_context(llm_call_id=llm_call_id, llm_task="intake_patch"):
        recorder.record(
            "llm.provider.request",
            _provider_request_event(
                llm_call_id=llm_call_id,
                provider_attempt_id="pa-initial",
                attempt="initial",
                messages=messages,
            )["data"],
        )
        recorder.record(
            "llm.provider.response",
            _provider_terminal_event(
                llm_call_id=llm_call_id,
                provider_attempt_id="pa-initial",
                attempt="initial",
            )["data"],
        )
        recorder.record(
            "llm.output.accepted",
            {
                "output_type": "IntakeExtraction",
                "result": {"evidence": []},
            },
        )
    correlation, errors = correlate_intake_patch_call(recorder)
    assert errors == []
    assert correlation is not None


def test_correlate_rejects_conflicting_accepted_task_sources() -> None:
    recorder = MemoryDiagnosticRecorder()
    llm_call_id = "call-conflict"
    with diagnostic_context(llm_call_id=llm_call_id, llm_task="intake_patch"):
        recorder.record(
            "llm.output.accepted",
            {
                "output_type": "IntakeExtraction",
                "result": {"evidence": []},
                "task": "therapy_response",
            },
        )
    correlation, errors = correlate_intake_patch_call(recorder)
    assert correlation is None
    assert any("task conflict" in err for err in errors)
