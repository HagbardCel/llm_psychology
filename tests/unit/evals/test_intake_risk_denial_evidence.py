"""Deterministic tests for Category C risk-denial evidence helpers."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from evals.intake_risk_denial_evidence import (
    EVIDENCE_INTEGRITY_FAILURE,
    EVIDENCE_SCHEMA_VERSION,
    MESSAGE_CANONICALIZATION,
    STRUCTURED_REQUEST_CANONICALIZATION,
    MemoryDiagnosticRecorder,
    build_category_c_evidence_payload,
    build_evidence_stages,
    correlate_intake_patch_call,
    digests_from_provider_request_data,
    evaluate_evidence_integrity,
    provider_attempt_rows,
    provider_messages_sha256,
    resolve_debug_run_dir,
    structured_request_sha256,
    write_category_c_evidence,
)
from jung.llm.gateway import StructuredOutputMode
from jung.phases.intake.extraction import IntakeEvidenceField, IntakeExtraction
from jung.phases.intake.models import IntakeRecord
from jung.phases.transcript import TranscriptTurn

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
) -> dict[str, Any]:
    return {
        "sequence": 2,
        "kind": "llm.provider.response",
        "context": {},
        "data": {
            "provider_attempt_id": provider_attempt_id,
            "llm_call_id": llm_call_id,
            "task": "intake_patch",
            "attempt": attempt,
            "status": status,
        },
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
            status="failed",
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


def test_raw_medical_urgency_invented_then_dropped_fails_semantics() -> None:
    from jung.phases.intake.extraction import ExtractedIntakeEvidence

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


def test_provider_messages_sha256_stable() -> None:
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


def test_resolve_debug_run_dir_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUNG_DEBUG_RUN_DIR", raising=False)
    assert resolve_debug_run_dir() is None


def test_evidence_integrity_failure_constant() -> None:
    assert EVIDENCE_INTEGRITY_FAILURE == "category_c_evidence_integrity_failed"
    assert MESSAGE_CANONICALIZATION
    assert STRUCTURED_REQUEST_CANONICALIZATION
