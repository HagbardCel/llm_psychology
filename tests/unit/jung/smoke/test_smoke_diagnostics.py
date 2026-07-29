"""Unit tests for smoke diagnostic helpers (no real LLM)."""

from __future__ import annotations

import asyncio

import pytest

from jung.llm.gateway import LLMTask
from tests.smoke.jung.smoke_env import (
    parse_bool_env,
    parse_completion_caps,
    parse_positive_finite_float_env,
    parse_smoke_extra_body,
)
from tests.smoke.jung.smoke_evidence import (
    SmokeEvidenceCollector,
    SmokePathResult,
    render_smoke_evidence,
)
from tests.smoke.jung.smoke_path import SmokeOperationResult, run_smoke_path


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
    monkeypatch.setenv("LOCAL_LLM_SMOKE_STRICT_ACCEPTANCE", raw)
    assert (
        parse_bool_env("LOCAL_LLM_SMOKE_STRICT_ACCEPTANCE", default=False) is expected
    )


@pytest.mark.parametrize(
    "raw",
    ["maybe", "2", "", "on"],
)
def test_parse_bool_env_rejects_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv("LOCAL_LLM_SMOKE_STRICT_ACCEPTANCE", raw)
    with pytest.raises(ValueError, match="LOCAL_LLM_SMOKE_STRICT_ACCEPTANCE"):
        parse_bool_env("LOCAL_LLM_SMOKE_STRICT_ACCEPTANCE", default=False)


@pytest.mark.parametrize(
    "raw",
    ["0", "-1", "NaN", "inf", "-inf", "not-a-number"],
)
def test_parse_positive_finite_float_env_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv("LOCAL_LLM_SMOKE_THERAPY_MAX_SECONDS", raw)
    with pytest.raises(ValueError):
        parse_positive_finite_float_env(
            "LOCAL_LLM_SMOKE_THERAPY_MAX_SECONDS",
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


def test_evidence_serialization_includes_path_results() -> None:
    collector = SmokeEvidenceCollector(
        server="llama.cpp",
        base_url="http://localhost/v1",
        model="test-model",
        structured_mode="json_schema",
        strict_acceptance=False,
        path_budgets_seconds={"post_session": 300},
        request_timeout_seconds=360,
        effective_completion_caps={"post_session_update": 1800},
        post_session=SmokePathResult(
            success=True,
            status="success",
            latency_seconds=340.0,
            acceptance_passed=False,
            acceptance_max_seconds=300.0,
        ),
    )
    payload = collector.to_payload()
    assert payload["server"] == "llama.cpp"
    assert payload["effective_completion_caps"]["post_session_update"] == 1800
    assert payload["post_session"]["acceptance_passed"] is False
    assert "calls" not in payload
    assert "provider_attempts" not in payload
    assert "instrumentation_errors" not in payload


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
    assert line.startswith("LOCAL_LLM_SMOKE_EVIDENCE=")
    assert '"server":"llama.cpp"' in line


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
            "LOCAL_LLM_SMOKE_STRICT_ACCEPTANCE",
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
        monkeypatch.setenv("LOCAL_LLM_SMOKE_STRICT_ACCEPTANCE", "1")

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
