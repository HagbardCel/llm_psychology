"""Unit tests for smoke diagnostic helpers (no real LLM)."""

from __future__ import annotations

import anyio
import pytest

from jung.llm.gateway import LLMTask
from jung.llm.openai_compatible import ProviderAttemptEvent
from tests.smoke.jung.smoke_context import current_smoke_call_id
from tests.smoke.jung.smoke_evidence import (
    COLLECTOR,
    SmokeEvidenceCollector,
    SmokePathResult,
    SmokeProviderAttemptResult,
    SmokeStructuredCallResult,
)
from tests.smoke.jung.smoke_path import (
    SmokeOperationResult,
    parse_completion_caps,
    run_smoke_path,
)
from tests.smoke.jung.smoke_recorder import SmokeAttemptRecorder


@pytest.fixture(autouse=True)
def _reset_collector() -> None:
    COLLECTOR.server = None
    COLLECTOR.base_url = None
    COLLECTOR.model = None
    COLLECTOR.structured_mode = None
    COLLECTOR.request_extras = {}
    COLLECTOR.strict_acceptance = None
    COLLECTOR.path_budgets_seconds = {}
    COLLECTOR.request_timeout_seconds = None
    COLLECTOR.effective_completion_caps = {}
    COLLECTOR.instrumentation_errors = []
    COLLECTOR.structured_calls = []
    COLLECTOR.provider_attempts = []
    COLLECTOR.therapy = None
    COLLECTOR.assessment = None
    COLLECTOR.post_session = None
    COLLECTOR._call_counter = 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            '{"assessment": 2500, "post_session_update": 1800}',
            {
                LLMTask.ASSESSMENT: 2500,
                LLMTask.POST_SESSION_UPDATE: 1800,
            },
        ),
    ],
)
def test_parse_completion_caps_accepts_valid_mapping(
    raw: str,
    expected: dict[LLMTask, int],
) -> None:
    assert parse_completion_caps(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        '{"post_session_updates": 1800}',
        '{"assessment": "2500"}',
        '{"assessment": 0}',
        '{"assessment": true}',
    ],
)
def test_parse_completion_caps_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_completion_caps(raw)


def test_evidence_serialization_includes_calls_and_attempts() -> None:
    collector = SmokeEvidenceCollector(
        server="llama.cpp",
        model="test-model",
        structured_mode="json_schema",
        strict_acceptance=False,
        path_budgets_seconds={"post_session": 300},
        request_timeout_seconds=360,
        effective_completion_caps={"post_session_update": 1800},
        instrumentation_errors=[],
        structured_calls=[
            SmokeStructuredCallResult(
                call_id="post_session_analysis-1",
                task="post_session_analysis",
                output_type="SessionAnalysisResult",
                status="success",
                latency_seconds=82.7,
                input_chars=2800,
                input_message_chars=(1200, 1600),
                output_schema_chars=2940,
                result_chars=1320,
            )
        ],
        provider_attempts=[
            SmokeProviderAttemptResult(
                call_id="post_session_analysis-1",
                attempt="initial",
                status="success",
                latency_seconds=82.6,
                prompt_chars=3118,
                response_format_chars=3100,
                response_chars=1480,
                timeout_seconds=360.0,
                max_completion_tokens=None,
                finish_reason="stop",
            )
        ],
        post_session=SmokePathResult(
            success=True,
            status="success",
            latency_seconds=340.0,
            acceptance_passed=False,
            acceptance_max_seconds=300.0,
        ),
    )
    payload = collector.to_payload()
    assert payload["calls"][0]["output_schema_chars"] == 2940
    assert payload["provider_attempts"][0]["finish_reason"] == "stop"
    assert payload["post_session"]["acceptance_passed"] is False
    assert "prompt_tokens" not in payload["provider_attempts"][0]
    assert payload["call_attempt_summary"]["post_session_analysis-1"]["correction_count"] == 0


def test_attempt_recorder_records_missing_call_id_as_instrumentation_error() -> None:
    collector = SmokeEvidenceCollector()
    recorder = SmokeAttemptRecorder(collector)
    recorder.record(
        ProviderAttemptEvent(
            task="post_session_update",
            attempt="initial",
            status="success",
            latency_seconds=1.0,
            prompt_chars=100,
            response_format_chars=200,
            response_chars=50,
            timeout_seconds=300.0,
            max_completion_tokens=None,
        )
    )
    assert collector.instrumentation_errors == [
        "provider attempt emitted without smoke call_id"
    ]
    assert collector.provider_attempts == []


def test_attempt_recorder_swallows_internal_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = SmokeEvidenceCollector()
    recorder = SmokeAttemptRecorder(collector)

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "tests.smoke.jung.smoke_recorder.SmokeProviderAttemptResult",
        boom,
    )
    token = current_smoke_call_id.set("post_session_update-1")
    try:
        recorder.record(
            ProviderAttemptEvent(
                task="post_session_update",
                attempt="initial",
                status="success",
                latency_seconds=1.0,
                prompt_chars=100,
                response_format_chars=200,
                response_chars=50,
                timeout_seconds=300.0,
                max_completion_tokens=None,
            )
        )
    finally:
        current_smoke_call_id.reset(token)
    assert collector.instrumentation_errors == ["attempt recorder failed: RuntimeError"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strict", "sleep_seconds", "budget", "expect_success", "expect_status"),
    [
        (True, 0.15, 0.05, False, "path_timeout"),
        (False, 0.15, 0.05, True, "success"),
    ],
)
async def test_run_smoke_path_strict_vs_diagnostic_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    sleep_seconds: float,
    budget: float,
    expect_success: bool,
    expect_status: str,
) -> None:
    monkeypatch.setenv(
        "PHASE3_SMOKE_STRICT_ACCEPTANCE",
        "1" if strict else "0",
    )

    async def operation() -> SmokeOperationResult[str]:
        await anyio.sleep(sleep_seconds)
        return SmokeOperationResult(value="ok")

    if strict:
        with pytest.raises(TimeoutError):
            await run_smoke_path(
                name="post_session",
                budget_seconds=budget,
                operation=operation,
            )
    else:
        result = await run_smoke_path(
            name="post_session",
            budget_seconds=budget,
            operation=operation,
        )
        assert result == "ok"

    assert COLLECTOR.post_session is not None
    assert COLLECTOR.post_session.success is expect_success
    assert COLLECTOR.post_session.status == expect_status
    if not strict:
        assert COLLECTOR.post_session.acceptance_passed is False
