"""Unit tests for smoke diagnostic helpers (no real LLM)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from jung.llm.errors import LLMTimeout
from jung.llm.gateway import (
    ChatMessage,
    ChatRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import ProviderAttemptEvent
from tests.smoke.jung.smoke_context import current_smoke_call_id
from tests.smoke.jung.smoke_env import (
    parse_bool_env,
    parse_completion_caps,
    parse_positive_finite_float_env,
    parse_smoke_extra_body,
)
from tests.smoke.jung.smoke_evidence import (
    SmokeEvidenceCollector,
    SmokePathResult,
    SmokeProviderAttemptResult,
    SmokeStructuredCallResult,
    render_smoke_evidence,
)
from tests.smoke.jung.smoke_gateway import SmokeObservingGateway
from tests.smoke.jung.smoke_path import SmokeOperationResult, run_smoke_path
from tests.smoke.jung.smoke_recorder import SmokeAttemptRecorder


class _Answer(BaseModel):
    value: str


class _AttemptEmittingGateway:
    def __init__(self, recorder: SmokeAttemptRecorder) -> None:
        self._recorder = recorder

    async def generate_structured(
        self,
        messages,
        output_type,
        policy,
        validate_result=None,
    ):
        self._recorder.record(
            ProviderAttemptEvent(
                task=policy.task.value,
                attempt="initial",
                status="success",
                latency_seconds=0.1,
                prompt_chars=10,
                response_format_chars=20,
                response_chars=15,
                timeout_seconds=policy.timeout_seconds,
                max_completion_tokens=policy.max_completion_tokens,
            )
        )
        return output_type(value="ok")


class _TimeoutRaisingGateway:
    def __init__(self, error: LLMTimeout) -> None:
        self._error = error

    async def generate_structured(
        self,
        messages,
        output_type,
        policy,
        validate_result=None,
    ):
        raise self._error


def _assessment_policy() -> ModelPolicy:
    return ModelPolicy(
        task=LLMTask.ASSESSMENT,
        model="test-model",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.JSON_OBJECT,
    )


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
    ],
)
def test_parse_bool_env_accepts_known_values(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("PHASE3_SMOKE_STRICT_ACCEPTANCE", raw)
    assert parse_bool_env("PHASE3_SMOKE_STRICT_ACCEPTANCE", default=False) is expected


@pytest.mark.parametrize(
    "raw",
    ["maybe", "2", "", "on"],
)
def test_parse_bool_env_rejects_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv("PHASE3_SMOKE_STRICT_ACCEPTANCE", raw)
    with pytest.raises(ValueError, match="PHASE3_SMOKE_STRICT_ACCEPTANCE"):
        parse_bool_env("PHASE3_SMOKE_STRICT_ACCEPTANCE", default=False)


@pytest.mark.parametrize(
    "raw",
    ["0", "-1", "NaN", "inf", "-inf", "not-a-number"],
)
def test_parse_positive_finite_float_env_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv("PHASE3_SMOKE_THERAPY_MAX_SECONDS", raw)
    with pytest.raises(ValueError):
        parse_positive_finite_float_env(
            "PHASE3_SMOKE_THERAPY_MAX_SECONDS",
            default=300.0,
        )


@pytest.mark.parametrize(
    "raw",
    ["not-json", "[]", '"scalar"', "true"],
)
def test_parse_smoke_extra_body_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_smoke_extra_body(raw)


def test_parse_smoke_extra_body_accepts_object() -> None:
    assert parse_smoke_extra_body('{"thinking": true}') == {"thinking": True}


def test_evidence_serialization_includes_calls_and_attempts() -> None:
    collector = SmokeEvidenceCollector(
        server="llama.cpp",
        base_url="http://localhost/v1",
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
    assert "call_attempt_summary" not in payload


def test_render_smoke_evidence_suppresses_synthetic_path_without_metadata() -> None:
    collector = SmokeEvidenceCollector(
        post_session=SmokePathResult(success=True, status="success"),
    )
    assert render_smoke_evidence(collector) is None


def test_render_smoke_evidence_emits_one_line_for_real_metadata() -> None:
    collector = SmokeEvidenceCollector(
        server="llama.cpp",
        base_url="http://localhost/v1",
        model="test-model",
        post_session=SmokePathResult(success=True, status="success"),
    )
    line = render_smoke_evidence(collector)
    assert line is not None
    assert line.startswith("PHASE3_SMOKE_EVIDENCE=")
    assert '"server":"llama.cpp"' in line


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


def test_smoke_observer_correlates_attempt_and_restores_context() -> None:
    async def exercise() -> None:
        collector = SmokeEvidenceCollector()
        recorder = SmokeAttemptRecorder(collector)
        gateway = SmokeObservingGateway(
            _AttemptEmittingGateway(recorder),
            collector=collector,
        )
        policy = _assessment_policy()
        messages = [ChatMessage(role=ChatRole.USER, content="hi")]

        outer_token = current_smoke_call_id.set("outer-call")
        try:
            result = await gateway.generate_structured(
                messages,
                _Answer,
                policy,
            )
            assert result.value == "ok"
            assert len(collector.provider_attempts) == 1
            assert len(collector.structured_calls) == 1
            attempt_call_id = collector.provider_attempts[0].call_id
            assert attempt_call_id is not None
            assert collector.structured_calls[0].call_id == attempt_call_id
            assert collector.instrumentation_errors == []
            assert current_smoke_call_id.get() == "outer-call"
        finally:
            current_smoke_call_id.reset(outer_token)

    asyncio.run(exercise())


def test_smoke_observer_recording_failure_preserves_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_error = LLMTimeout("provider stalled")

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "tests.smoke.jung.smoke_gateway.SmokeStructuredCallResult",
        boom,
    )

    async def exercise() -> None:
        collector = SmokeEvidenceCollector()
        gateway = SmokeObservingGateway(
            _TimeoutRaisingGateway(original_error),
            collector=collector,
        )
        policy = _assessment_policy()
        messages = [ChatMessage(role=ChatRole.USER, content="hi")]

        outer_token = current_smoke_call_id.set("outer-call")
        try:
            with pytest.raises(LLMTimeout) as exc_info:
                await gateway.generate_structured(
                    messages,
                    _Answer,
                    policy,
                )
            assert exc_info.value is original_error
            assert collector.structured_calls == []
            assert collector.instrumentation_errors == [
                "structured call recorder failed: RuntimeError"
            ]
            assert current_smoke_call_id.get() == "outer-call"
        finally:
            current_smoke_call_id.reset(outer_token)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("strict", "sleep_seconds", "budget", "expect_success", "expect_status"),
    [
        (True, 0.15, 0.05, False, "path_timeout"),
        (False, 0.15, 0.05, True, "success"),
    ],
)
def test_run_smoke_path_strict_vs_diagnostic_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    sleep_seconds: float,
    budget: float,
    expect_success: bool,
    expect_status: str,
) -> None:
    async def _run() -> None:
        collector = SmokeEvidenceCollector()
        monkeypatch.setenv(
            "PHASE3_SMOKE_STRICT_ACCEPTANCE",
            "1" if strict else "0",
        )

        async def operation() -> SmokeOperationResult[str]:
            await asyncio.sleep(sleep_seconds)
            return SmokeOperationResult(value="ok")

        if strict:
            with pytest.raises(TimeoutError):
                await run_smoke_path(
                    collector=collector,
                    name="post_session",
                    budget_seconds=budget,
                    operation=operation,
                )
        else:
            result = await run_smoke_path(
                collector=collector,
                name="post_session",
                budget_seconds=budget,
                operation=operation,
            )
            assert result == "ok"

        assert collector.post_session is not None
        assert collector.post_session.success is expect_success
        assert collector.post_session.status == expect_status
        if not strict:
            assert collector.post_session.acceptance_passed is False

    asyncio.run(_run())


def test_run_smoke_path_inner_timeout_error_is_not_path_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        collector = SmokeEvidenceCollector()
        monkeypatch.setenv("PHASE3_SMOKE_STRICT_ACCEPTANCE", "1")

        async def operation() -> SmokeOperationResult[str]:
            raise TimeoutError("inner timeout")

        with pytest.raises(TimeoutError, match="inner timeout"):
            await run_smoke_path(
                collector=collector,
                name="post_session",
                budget_seconds=5.0,
                operation=operation,
            )

        assert collector.post_session is not None
        assert collector.post_session.status == "error"
        assert collector.post_session.error_type == "TimeoutError"

    asyncio.run(_run())
