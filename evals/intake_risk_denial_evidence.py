"""Category C clear-risk-denial evidence helpers (eval-local only)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from jung.diagnostics import open_private_file

EVIDENCE_SCHEMA_VERSION = 1
MESSAGE_CANONICALIZATION = "ordered-role-content-json-v1"
STRUCTURED_REQUEST_CANONICALIZATION = "structured-request-sorted-json-v1"

AcceptedAttempt = Literal["initial", "correction", "unknown"]


def provider_messages_sha256(messages: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 of ordered provider-prepared ``{role, content}`` messages."""
    payload = [{"role": item["role"], "content": item["content"]} for item in messages]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def structured_request_sha256(
    *,
    structured_mode: str,
    response_format_or_schema_instruction: object,
) -> str:
    """SHA-256 of mode + exact response_format / schema instruction."""
    payload = {
        "structured_output_mode": structured_mode,
        "response_format_or_schema": response_format_or_schema_instruction,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MemoryDiagnosticRecorder:
    """In-memory diagnostic sink for eval digests; never writes files."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._id_counters: dict[str, int] = {}

    def next_id(self, prefix: str) -> str:
        count = self._id_counters.get(prefix, 0) + 1
        self._id_counters[prefix] = count
        return f"{prefix}-{count}"

    def record(self, kind: str, data: Mapping[str, Any] | None = None) -> None:
        self.events.append({"kind": kind, "data": dict(data or {})})


def digests_from_provider_request_event(data: Mapping[str, Any]) -> dict[str, str]:
    """Extract provider message + structured-request digests from request data."""
    raw_messages = data.get("messages")
    messages: list[Mapping[str, Any]] = []
    if isinstance(raw_messages, Sequence) and not isinstance(
        raw_messages, (str, bytes)
    ):
        for item in raw_messages:
            if isinstance(item, Mapping) and "role" in item and "content" in item:
                messages.append(item)
    structured_mode = data.get("structured_output_mode")
    mode = structured_mode if isinstance(structured_mode, str) else ""
    return {
        "provider_messages_sha256": provider_messages_sha256(messages),
        "structured_request_sha256": structured_request_sha256(
            structured_mode=mode,
            response_format_or_schema_instruction=data.get("response_format"),
        ),
    }


def build_category_c_evidence_payload(
    *,
    success: bool,
    model: str | None = None,
    sanitized_endpoint: str | None = None,
    structured_mode: str | None = None,
    prompt_version: str | None = None,
    extra_body: dict[str, object] | None = None,
    frozen_fixture: str | None = None,
    extraction_target: str | None = None,
    accepted_fields: list[dict[str, Any]] | None = None,
    validation_retained_paths: list[str] | None = None,
    persisted_changed_paths: list[str] | None = None,
    medical_urgency_absent: bool | None = None,
    merge_status: str | None = None,
    raw_evidence_count: int | None = None,
    retained_evidence_count: int | None = None,
    dropped_evidence_count: int | None = None,
    record_changed: bool | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
    accepted_attempt: AcceptedAttempt | None = None,
    canonical_fixture_provider_messages_sha256: str | None = None,
    canonical_fixture_structured_request_sha256: str | None = None,
    primary_failure_code: str | None = None,
    primary_failure_exception_type: str | None = None,
) -> dict[str, Any]:
    """Build the mandatory Category C evidence payload (None for N/A on failure)."""
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "fingerprint_canonicalization_messages": MESSAGE_CANONICALIZATION,
        "fingerprint_canonicalization_structured": STRUCTURED_REQUEST_CANONICALIZATION,
        "model": model,
        "sanitized_endpoint": sanitized_endpoint,
        "structured_mode": structured_mode,
        "prompt_version": prompt_version,
        "extra_body": extra_body,
        "frozen_fixture": frozen_fixture,
        "extraction_target": extraction_target,
        "accepted_fields": accepted_fields,
        "validation_retained_paths": validation_retained_paths,
        "persisted_changed_paths": persisted_changed_paths,
        "medical_urgency_absent": medical_urgency_absent,
        "merge_status": merge_status,
        "raw_evidence_count": raw_evidence_count,
        "retained_evidence_count": retained_evidence_count,
        "dropped_evidence_count": dropped_evidence_count,
        "record_changed": record_changed,
        "provider_attempts": provider_attempts if provider_attempts is not None else [],
        "accepted_attempt": accepted_attempt,
        "canonical_fixture_provider_messages_sha256": (
            canonical_fixture_provider_messages_sha256
        ),
        "canonical_fixture_structured_request_sha256": (
            canonical_fixture_structured_request_sha256
        ),
        "primary_failure_code": primary_failure_code,
        "primary_failure_exception_type": primary_failure_exception_type,
        "success": success,
    }


def write_category_c_evidence(*, run_dir: Path, payload: Mapping[str, Any]) -> None:
    """Create ``run_dir`` exclusively (0700) and write ``evidence.md`` as 0600."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        os.chmod(run_dir, 0o700)
    except OSError:
        pass
    lines = [
        "# Category C clear-risk-denial evidence",
        "",
        "```json",
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        "```",
        "",
    ]
    evidence_path = run_dir / "evidence.md"
    with open_private_file(evidence_path, mode="w") as handle:
        handle.write("\n".join(lines))


def resolve_debug_run_dir() -> Path | None:
    """Return ``JUNG_DEBUG_RUN_DIR`` when set; path must not already exist."""
    raw = os.environ.get("JUNG_DEBUG_RUN_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.exists():
        raise ValueError(
            f"JUNG_DEBUG_RUN_DIR must not already exist (got existing path: {path})"
        )
    return path
