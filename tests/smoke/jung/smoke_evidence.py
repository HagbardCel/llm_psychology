"""Shared collector for local-model smoke acceptance summary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from jung.llm.openai_compatible import ProviderAttemptEvent


@dataclass
class ProviderAttemptSummary:
    provider_attempt_count: int = 0
    correction_count: int = 0
    correction_triggers: list[str] = field(default_factory=list)

    def observe(self, event: ProviderAttemptEvent) -> None:
        self.provider_attempt_count += 1
        if event.attempt == "correction":
            self.correction_count += 1
            if event.correction_trigger is not None:
                self.correction_triggers.append(event.correction_trigger)

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider_attempt_count": self.provider_attempt_count,
            "correction_count": self.correction_count,
            "correction_triggers": list(self.correction_triggers),
        }


@dataclass
class SmokePathResult:
    success: bool
    status: str
    latency_seconds: float | None = None
    ttfc_seconds: float | None = None
    acceptance_passed: bool | None = None
    acceptance_max_seconds: float | None = None
    error_type: str | None = None
    provider_attempts: ProviderAttemptSummary | None = None
    result_shape_valid: bool | None = None
    evidence_complete: bool | None = None
    negation_turn_selected: bool | None = None
    negation_invariant_evaluated: bool | None = None
    negation_invariant_passed: bool | None = None


@dataclass
class SmokeEvidenceCollector:
    server: str | None = None
    server_version: str | None = None
    base_url: str | None = None
    model: str | None = None
    structured_mode: str | None = None
    request_extras_configured: bool = False
    strict_acceptance: bool | None = None
    path_budgets_seconds: dict[str, float] = field(default_factory=dict)
    request_timeout_seconds: float | None = None
    effective_completion_caps: dict[str, int] = field(default_factory=dict)
    therapy: SmokePathResult | None = None
    assessment: SmokePathResult | None = None
    post_session: SmokePathResult | None = None
    provider_attempts_by_task: dict[str, ProviderAttemptSummary] = field(
        default_factory=dict
    )

    def reset_provider_attempts(self) -> None:
        self.provider_attempts_by_task = {}

    def observe_provider_attempt(self, event: ProviderAttemptEvent) -> None:
        summary = self.provider_attempts_by_task.setdefault(
            event.task, ProviderAttemptSummary()
        )
        summary.observe(event)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "server": self.server,
            "server_version": self.server_version,
            "model": self.model,
            "structured_mode": self.structured_mode,
            "request_extras_configured": self.request_extras_configured,
            "strict_acceptance": self.strict_acceptance,
            "path_budgets_seconds": self.path_budgets_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
            "effective_completion_caps": self.effective_completion_caps,
            "provider_attempts_by_task": {
                task: summary.to_payload()
                for task, summary in self.provider_attempts_by_task.items()
            },
        }
        if self.base_url is not None:
            payload["base_url"] = self.base_url
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
        if result.provider_attempts is not None:
            entry.update(result.provider_attempts.to_payload())
        if result.result_shape_valid is not None:
            entry["result_shape_valid"] = result.result_shape_valid
        if result.evidence_complete is not None:
            entry["evidence_complete"] = result.evidence_complete
        if result.negation_turn_selected is not None:
            entry["negation_turn_selected"] = result.negation_turn_selected
        if result.negation_invariant_evaluated is not None:
            entry["negation_invariant_evaluated"] = result.negation_invariant_evaluated
        if result.negation_invariant_passed is not None:
            entry["negation_invariant_passed"] = result.negation_invariant_passed
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
    return f"LOCAL_LLM_SMOKE_EVIDENCE={payload}"


COLLECTOR = SmokeEvidenceCollector()
