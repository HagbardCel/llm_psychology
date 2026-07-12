"""Shared collector for Phase 3 local-model smoke evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SmokePathResult:
    success: bool
    latency_seconds: float | None = None
    ttfc_seconds: float | None = None
    correction_count: int | None = None
    error_type: str | None = None


@dataclass
class SmokeEvidenceCollector:
    server: str | None = None
    base_url: str | None = None
    model: str | None = None
    structured_mode: str | None = None
    request_extras: dict[str, Any] = field(default_factory=dict)
    therapy: SmokePathResult | None = None
    assessment: SmokePathResult | None = None
    post_session: SmokePathResult | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "server": self.server,
            "model": self.model,
            "structured_mode": self.structured_mode,
            "request_extras": self.request_extras,
        }
        if self.base_url is not None:
            payload["base_url"] = self.base_url
        for key in ("therapy", "assessment", "post_session"):
            result = getattr(self, key)
            if result is None:
                continue
            entry: dict[str, Any] = {"success": result.success}
            if result.latency_seconds is not None:
                entry["latency_seconds"] = round(result.latency_seconds, 3)
            if result.ttfc_seconds is not None:
                entry["ttfc_seconds"] = round(result.ttfc_seconds, 3)
            if result.correction_count is not None:
                entry["correction_count"] = result.correction_count
            if result.error_type is not None:
                entry["error_type"] = result.error_type
            payload[key] = entry
        return payload

    def has_data(self) -> bool:
        return any(
            value is not None
            for value in (
                self.therapy,
                self.assessment,
                self.post_session,
            )
        )


COLLECTOR = SmokeEvidenceCollector()
