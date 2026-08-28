"""Shared collector for local-model smoke acceptance summary."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jung.diagnostics import open_private_file
from jung.llm.openai_compatible import ProviderAttemptEvent


@dataclass(frozen=True, slots=True)
class ProviderAttemptSnapshot:
    provider_attempt_count: int
    correction_count: int
    correction_triggers: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider_attempt_count": self.provider_attempt_count,
            "correction_count": self.correction_count,
            "correction_triggers": list(self.correction_triggers),
        }


class ProviderAttemptCollector:
    """Mutable per-path attempt observer with immutable snapshots."""

    def __init__(self) -> None:
        self._summaries: dict[str, _MutableSummary] = {}

    def observe(self, event: ProviderAttemptEvent) -> None:
        summary = self._summaries.setdefault(event.task, _MutableSummary())
        summary.observe(event)

    def snapshot(self) -> dict[str, ProviderAttemptSnapshot]:
        return {
            task: ProviderAttemptSnapshot(
                provider_attempt_count=value.provider_attempt_count,
                correction_count=value.correction_count,
                correction_triggers=tuple(value.correction_triggers),
            )
            for task, value in self._summaries.items()
        }


@dataclass
class _MutableSummary:
    provider_attempt_count: int = 0
    correction_count: int = 0
    correction_triggers: list[str] = field(default_factory=list)

    def observe(self, event: ProviderAttemptEvent) -> None:
        self.provider_attempt_count += 1
        if event.attempt == "correction":
            self.correction_count += 1
            if event.correction_trigger is not None:
                self.correction_triggers.append(event.correction_trigger)


@dataclass
class SmokePathResult:
    success: bool
    status: str
    latency_seconds: float | None = None
    ttfc_seconds: float | None = None
    acceptance_passed: bool | None = None
    acceptance_max_seconds: float | None = None
    error_type: str | None = None
    provider_attempts_by_task: Mapping[str, ProviderAttemptSnapshot] = field(
        default_factory=dict
    )
    result_shape_valid: bool | None = None
    # Grounding and negation moved to the hard evals; these stay for
    # backward-compatible evidence JSON and are no longer populated by smoke.
    evidence_complete: bool | None = None
    negation_turn_selected: bool | None = None
    negation_invariant_evaluated: bool | None = None
    negation_invariant_passed: bool | None = None


def aggregate_provider_attempts(
    path_results: Sequence[SmokePathResult],
) -> dict[str, ProviderAttemptSnapshot]:
    counts: dict[str, int] = {}
    corrections: dict[str, int] = {}
    triggers: dict[str, list[str]] = {}
    for path in path_results:
        for task, snapshot in path.provider_attempts_by_task.items():
            counts[task] = counts.get(task, 0) + snapshot.provider_attempt_count
            corrections[task] = corrections.get(task, 0) + snapshot.correction_count
            triggers.setdefault(task, []).extend(snapshot.correction_triggers)
    return {
        task: ProviderAttemptSnapshot(
            provider_attempt_count=counts[task],
            correction_count=corrections[task],
            correction_triggers=tuple(triggers[task]),
        )
        for task in counts
    }


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
    intake: SmokePathResult | None = None

    def to_payload(self) -> dict[str, Any]:
        path_results = [
            result
            for result in (
                self.therapy,
                self.assessment,
                self.post_session,
                self.intake,
            )
            if result is not None
        ]
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
                task: snapshot.to_payload()
                for task, snapshot in aggregate_provider_attempts(path_results).items()
            },
        }
        if self.base_url is not None:
            payload["base_url"] = self.base_url
        for key in (
            "therapy",
            "assessment",
            "post_session",
            "intake",
        ):
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
        if result.provider_attempts_by_task:
            entry["provider_attempts_by_task"] = {
                task: snapshot.to_payload()
                for task, snapshot in result.provider_attempts_by_task.items()
            }
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
                self.intake,
            )
        )


def write_smoke_evidence_markdown(
    collector: SmokeEvidenceCollector, path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = collector.to_payload()
    lines = [
        "# Local LLM smoke evidence",
        "",
        f"server: {collector.server}",
        f"model: {collector.model}",
        f"structured_mode: {collector.structured_mode}",
        "",
        "## Paths",
        "",
        "```json",
        json.dumps(payload, indent=2, ensure_ascii=True, default=str),
        "```",
        "",
    ]
    with open_private_file(path, mode="w") as handle:
        handle.write("\n".join(lines) + "\n")


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
