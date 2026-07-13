"""Records provider-attempt events into smoke evidence."""

from __future__ import annotations

from jung.llm.openai_compatible import ProviderAttemptEvent
from tests.smoke.jung.smoke_context import current_smoke_call_id
from tests.smoke.jung.smoke_evidence import (
    SmokeEvidenceCollector,
    SmokeProviderAttemptResult,
)


class SmokeAttemptRecorder:
    def __init__(self, collector: SmokeEvidenceCollector) -> None:
        self._collector = collector

    def record(self, event: ProviderAttemptEvent) -> None:
        try:
            self._record(event)
        except Exception as exc:
            self._collector.instrumentation_errors.append(
                f"attempt recorder failed: {type(exc).__name__}"
            )

    def _record(self, event: ProviderAttemptEvent) -> None:
        call_id = current_smoke_call_id.get()
        if call_id is None:
            self._collector.instrumentation_errors.append(
                "provider attempt emitted without smoke call_id"
            )
            return
        self._collector.provider_attempts.append(
            SmokeProviderAttemptResult(
                call_id=call_id,
                attempt=event.attempt,
                status=event.status,
                latency_seconds=event.latency_seconds,
                prompt_chars=event.prompt_chars,
                response_format_chars=event.response_format_chars,
                response_chars=event.response_chars,
                timeout_seconds=event.timeout_seconds,
                max_completion_tokens=event.max_completion_tokens,
                correction_trigger=event.correction_trigger,
                finish_reason=event.finish_reason,
                prompt_tokens=event.prompt_tokens,
                completion_tokens=event.completion_tokens,
                error_type=event.error_type,
            )
        )
