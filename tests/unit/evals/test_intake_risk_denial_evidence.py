"""Deterministic tests for Category C risk-denial evidence helpers."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from evals.intake_risk_denial_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    MESSAGE_CANONICALIZATION,
    STRUCTURED_REQUEST_CANONICALIZATION,
    build_category_c_evidence_payload,
    digests_from_provider_request_event,
    provider_messages_sha256,
    resolve_debug_run_dir,
    structured_request_sha256,
    write_category_c_evidence,
)

_MANDATORY_KEYS = frozenset(
    {
        "evidence_schema_version",
        "fingerprint_canonicalization_messages",
        "fingerprint_canonicalization_structured",
        "model",
        "sanitized_endpoint",
        "structured_mode",
        "prompt_version",
        "extra_body",
        "frozen_fixture",
        "extraction_target",
        "accepted_fields",
        "validation_retained_paths",
        "persisted_changed_paths",
        "medical_urgency_absent",
        "merge_status",
        "raw_evidence_count",
        "retained_evidence_count",
        "dropped_evidence_count",
        "record_changed",
        "provider_attempts",
        "accepted_attempt",
        "canonical_fixture_provider_messages_sha256",
        "canonical_fixture_structured_request_sha256",
        "primary_failure_code",
        "primary_failure_exception_type",
        "success",
    }
)


def test_successful_payload_includes_mandatory_keys() -> None:
    payload = build_category_c_evidence_payload(
        success=True,
        model="test-model",
        sanitized_endpoint="http://localhost/v1",
        structured_mode="json_schema",
        prompt_version="intake-v4",
        extra_body={"thinking": False},
        frozen_fixture="I am not thinking about harming myself or anyone else.",
        extraction_target="risk_screen",
        accepted_fields=[
            {
                "path": "safety.self_harm",
                "status": "informative",
                "quote": "not thinking about harming myself",
                "quote_valid": True,
            }
        ],
        validation_retained_paths=["safety.self_harm", "safety.harm_to_others"],
        persisted_changed_paths=["safety.self_harm", "safety.harm_to_others"],
        medical_urgency_absent=True,
        merge_status="applied",
        raw_evidence_count=2,
        retained_evidence_count=2,
        dropped_evidence_count=0,
        record_changed=True,
        provider_attempts=[
            {
                "attempt": "initial",
                "provider_messages_sha256": "abc",
                "structured_request_sha256": "def",
                "status": "success",
            }
        ],
        accepted_attempt="initial",
        canonical_fixture_provider_messages_sha256="abc",
        canonical_fixture_structured_request_sha256="def",
    )
    assert set(payload) == _MANDATORY_KEYS
    assert payload["evidence_schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert payload["fingerprint_canonicalization_messages"] == MESSAGE_CANONICALIZATION
    assert (
        payload["fingerprint_canonicalization_structured"]
        == STRUCTURED_REQUEST_CANONICALIZATION
    )
    assert payload["success"] is True
    assert payload["extra_body"] == {"thinking": False}
    assert payload["medical_urgency_absent"] is True
    assert payload["accepted_attempt"] == "initial"
    assert payload["primary_failure_code"] is None
    assert payload["primary_failure_exception_type"] is None


def test_failure_before_result_payload_uses_none_for_result_fields() -> None:
    payload = build_category_c_evidence_payload(
        success=False,
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
    assert payload["extraction_target"] is None
    assert payload["accepted_fields"] is None
    assert payload["validation_retained_paths"] is None
    assert payload["persisted_changed_paths"] is None
    assert payload["medical_urgency_absent"] is None
    assert payload["merge_status"] is None
    assert payload["raw_evidence_count"] is None
    assert payload["retained_evidence_count"] is None
    assert payload["dropped_evidence_count"] is None
    assert payload["record_changed"] is None
    assert payload["accepted_attempt"] is None
    assert payload["provider_attempts"] == []
    assert payload["extra_body"] is None
    assert payload["primary_failure_exception_type"] == "AssertionError"


def test_write_category_c_evidence_permissions(tmp_path: Path) -> None:
    run_dir = tmp_path / "category-c-run"
    payload = build_category_c_evidence_payload(success=True, model="m")
    write_category_c_evidence(run_dir=run_dir, payload=payload)
    assert run_dir.is_dir()
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
    evidence = run_dir / "evidence.md"
    assert evidence.is_file()
    assert stat.S_IMODE(evidence.stat().st_mode) == 0o600
    text = evidence.read_text(encoding="utf-8")
    assert "```json" in text
    assert '"success": true' in text


def test_privacy_sentinels_absent_from_written_evidence(tmp_path: Path) -> None:
    secret = "SECRET_API_KEY_VALUE"
    reasoning = "REASONING_CONTENT_SENTINEL"
    excluded = {
        "api_key": secret,
        "reasoning_content": reasoning,
        "raw_provider_response": f"leak {secret} {reasoning}",
    }
    payload = build_category_c_evidence_payload(
        success=True,
        model="test-model",
        sanitized_endpoint="http://localhost/v1",
        frozen_fixture="I am not thinking about harming myself or anyone else.",
        accepted_fields=[
            {
                "path": "safety.self_harm",
                "status": "informative",
                "quote": "not thinking about harming myself",
                "quote_valid": True,
            }
        ],
        provider_attempts=[
            {
                "attempt": "initial",
                "provider_messages_sha256": "deadbeef",
                "structured_request_sha256": "cafebabe",
                "status": "success",
            }
        ],
        accepted_attempt="initial",
    )
    # Sentinels live only in an excluded source; they must not be copied in.
    assert secret in json.dumps(excluded)
    assert reasoning in json.dumps(excluded)
    run_dir = tmp_path / "private-run"
    write_category_c_evidence(run_dir=run_dir, payload=payload)
    written = (run_dir / "evidence.md").read_text(encoding="utf-8")
    assert secret not in written
    assert reasoning not in written
    assert "not thinking about harming myself" in written


def test_extra_body_none_vs_empty_dict() -> None:
    none_payload = build_category_c_evidence_payload(success=True, extra_body=None)
    empty_payload = build_category_c_evidence_payload(success=True, extra_body={})
    assert none_payload["extra_body"] is None
    assert empty_payload["extra_body"] == {}
    assert none_payload["extra_body"] is not empty_payload["extra_body"]


def test_provider_messages_sha256_stable() -> None:
    messages = [
        {"role": "system", "content": "Extract JSON."},
        {"role": "user", "content": "I am not thinking about harming myself."},
    ]
    first = provider_messages_sha256(messages)
    second = provider_messages_sha256(messages)
    assert first == second
    assert len(first) == 64
    assert first == provider_messages_sha256(
        [
            {"role": "system", "content": "Extract JSON."},
            {"role": "user", "content": "I am not thinking about harming myself."},
        ]
    )


def test_structured_request_sha256_stable() -> None:
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "IntakeExtraction", "strict": True},
    }
    first = structured_request_sha256(
        structured_mode="json_schema",
        response_format_or_schema_instruction=response_format,
    )
    second = structured_request_sha256(
        structured_mode="json_schema",
        response_format_or_schema_instruction=response_format,
    )
    assert first == second
    assert len(first) == 64
    # Key order in the input object must not change the digest (sort_keys).
    reordered = {
        "json_schema": {"strict": True, "name": "IntakeExtraction"},
        "type": "json_schema",
    }
    assert (
        structured_request_sha256(
            structured_mode="json_schema",
            response_format_or_schema_instruction=reordered,
        )
        == first
    )


def test_digests_from_provider_request_event() -> None:
    data = {
        "task": "intake_patch",
        "structured_output_mode": "json_schema",
        "messages": [{"role": "user", "content": "hello"}],
        "response_format": {"type": "json_object"},
    }
    digests = digests_from_provider_request_event(data)
    assert digests["provider_messages_sha256"] == provider_messages_sha256(
        [{"role": "user", "content": "hello"}]
    )
    assert digests["structured_request_sha256"] == structured_request_sha256(
        structured_mode="json_schema",
        response_format_or_schema_instruction={"type": "json_object"},
    )


def test_resolve_debug_run_dir_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUNG_DEBUG_RUN_DIR", raising=False)
    assert resolve_debug_run_dir() is None


def test_resolve_debug_run_dir_errors_if_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "already"
    existing.mkdir()
    monkeypatch.setenv("JUNG_DEBUG_RUN_DIR", str(existing))
    with pytest.raises(ValueError, match="must not already exist"):
        resolve_debug_run_dir()


def test_resolve_debug_run_dir_returns_path_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "fresh-run"
    monkeypatch.setenv("JUNG_DEBUG_RUN_DIR", str(missing))
    assert resolve_debug_run_dir() == missing
    assert not missing.exists()
