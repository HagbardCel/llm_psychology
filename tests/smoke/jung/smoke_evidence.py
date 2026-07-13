"""Shared collector for Phase 3 local-model smoke evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SmokePathResult:
    success: bool
    status: str
    latency_seconds: float | None = None
    ttfc_seconds: float | None = None
    acceptance_passed: bool | None = None
    acceptance_max_seconds: float | None = None
    error_type: str | None = None


@dataclass
class SmokeStructuredCallResult:
    call_id: str
    task: str
    output_type: str
    status: str
    latency_seconds: float
    input_chars: int
    input_message_chars: tuple[int, ...]
    output_schema_chars: int
    result_chars: int | None = None
    error_type: str | None = None


@dataclass
class SmokeProviderAttemptResult:
    call_id: str
    attempt: str
    status: str
    latency_seconds: float
    prompt_chars: int
    response_format_chars: int | None
    response_chars: int | None
    timeout_seconds: float
    max_completion_tokens: int | None
    correction_trigger: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error_type: str | None = None


@dataclass
class SmokeEvidenceCollector:
    server: str | None = None
    base_url: str | None = None
    model: str | None = None
    structured_mode: str | None = None
    request_extras: dict[str, Any] = field(default_factory=dict)
    strict_acceptance: bool | None = None
    path_budgets_seconds: dict[str, float] = field(default_factory=dict)
    request_timeout_seconds: float | None = None
    effective_completion_caps: dict[str, int] = field(default_factory=dict)
    instrumentation_errors: list[str] = field(default_factory=list)
    structured_calls: list[SmokeStructuredCallResult] = field(default_factory=list)
    provider_attempts: list[SmokeProviderAttemptResult] = field(default_factory=list)
    therapy: SmokePathResult | None = None
    assessment: SmokePathResult | None = None
    post_session: SmokePathResult | None = None
    _call_counter: int = 0

    def next_call_id(self, task: str) -> str:
        self._call_counter += 1
        return f"{task}-{self._call_counter}"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "server": self.server,
            "model": self.model,
            "structured_mode": self.structured_mode,
            "request_extras": self.request_extras,
            "strict_acceptance": self.strict_acceptance,
            "path_budgets_seconds": self.path_budgets_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
            "effective_completion_caps": self.effective_completion_caps,
            "instrumentation_errors": list(self.instrumentation_errors),
        }
        if self.base_url is not None:
            payload["base_url"] = self.base_url
        if self.structured_calls:
            payload["calls"] = [
                self._serialize_structured_call(call) for call in self.structured_calls
            ]
        if self.provider_attempts:
            payload["provider_attempts"] = [
                self._serialize_provider_attempt(attempt)
                for attempt in self.provider_attempts
            ]
        for key in ("therapy", "assessment", "post_session"):
            result = getattr(self, key)
            if result is None:
                continue
            payload[key] = self._serialize_path_result(result)
        return payload

    def _serialize_path_result(self, result: SmokePathResult) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "success": result.success,
            "status": result.status,
        }
        if result.latency_seconds is not None:
            entry["latency_seconds"] = round(result.latency_seconds, 3)
        if result.ttfc_seconds is not None:
            entry["ttfc_seconds"] = round(result.ttfc_seconds, 3)
        if result.acceptance_passed is not None:
            entry["acceptance_passed"] = result.acceptance_passed
        if result.acceptance_max_seconds is not None:
            entry["acceptance_max_seconds"] = result.acceptance_max_seconds
        if result.error_type is not None:
            entry["error_type"] = result.error_type
        return entry

    def _serialize_structured_call(
        self,
        call: SmokeStructuredCallResult,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "call_id": call.call_id,
            "task": call.task,
            "output_type": call.output_type,
            "status": call.status,
            "latency_seconds": round(call.latency_seconds, 3),
            "input_chars": call.input_chars,
            "input_message_chars": list(call.input_message_chars),
            "output_schema_chars": call.output_schema_chars,
        }
        if call.result_chars is not None:
            entry["result_chars"] = call.result_chars
        if call.error_type is not None:
            entry["error_type"] = call.error_type
        return entry

    def _serialize_provider_attempt(
        self,
        attempt: SmokeProviderAttemptResult,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "call_id": attempt.call_id,
            "attempt": attempt.attempt,
            "status": attempt.status,
            "latency_seconds": round(attempt.latency_seconds, 3),
            "prompt_chars": attempt.prompt_chars,
            "timeout_seconds": attempt.timeout_seconds,
            "max_completion_tokens": attempt.max_completion_tokens,
        }
        if attempt.response_format_chars is not None:
            entry["response_format_chars"] = attempt.response_format_chars
        if attempt.response_chars is not None:
            entry["response_chars"] = attempt.response_chars
        if attempt.correction_trigger is not None:
            entry["correction_trigger"] = attempt.correction_trigger
        if attempt.finish_reason is not None:
            entry["finish_reason"] = attempt.finish_reason
        if attempt.prompt_tokens is not None:
            entry["prompt_tokens"] = attempt.prompt_tokens
        if attempt.completion_tokens is not None:
            entry["completion_tokens"] = attempt.completion_tokens
        if attempt.error_type is not None:
            entry["error_type"] = attempt.error_type
        return entry

    def has_data(self) -> bool:
        return any(
            value is not None
            for value in (
                self.therapy,
                self.assessment,
                self.post_session,
            )
        )


def render_smoke_evidence(collector: SmokeEvidenceCollector) -> str | None:
    if not all((collector.server, collector.model, collector.base_url)):
        return None
    if not collector.has_data():
        return None
    payload = json.dumps(
        collector.to_payload(),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"PHASE3_SMOKE_EVIDENCE={payload}"


COLLECTOR = SmokeEvidenceCollector()
