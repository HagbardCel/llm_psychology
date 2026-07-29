"""Shared collector for local-model smoke acceptance summary."""

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
    therapy: SmokePathResult | None = None
    assessment: SmokePathResult | None = None
    post_session: SmokePathResult | None = None

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
