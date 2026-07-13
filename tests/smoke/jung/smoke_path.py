"""Smoke path runner and environment parsing."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

import anyio
import pytest

from jung.llm.async_compat import is_async_cancellation
from jung.llm.errors import LLMTimeout
from jung.llm.gateway import LLMTask
from tests.smoke.jung.smoke_evidence import COLLECTOR, SmokePathResult

T = TypeVar("T")

_SMOKE_COMPLETION_CAP_KEYS = {
    "assessment": LLMTask.ASSESSMENT,
    "post_session_analysis": LLMTask.POST_SESSION_ANALYSIS,
    "post_session_update": LLMTask.POST_SESSION_UPDATE,
    "therapy_response": LLMTask.THERAPY_RESPONSE,
}


@dataclass(frozen=True, slots=True)
class SmokeOperationResult(Generic[T]):
    value: T
    ttfc_seconds: float | None = None


def smoke_debug_enabled() -> bool:
    return os.environ.get("PHASE3_SMOKE_DEBUG", "").strip() in {"1", "true", "yes"}


def smoke_log_prompt_previews() -> bool:
    return os.environ.get("PHASE3_SMOKE_LOG_PROMPT_PREVIEWS", "").strip() in {
        "1",
        "true",
        "yes",
    }


def smoke_strict_acceptance() -> bool:
    raw = os.environ.get("PHASE3_SMOKE_STRICT_ACCEPTANCE", "1").strip().lower()
    return raw not in {"0", "false", "no"}


def smoke_request_timeout_seconds() -> float:
    raw = os.environ.get("PHASE3_SMOKE_REQUEST_TIMEOUT") or os.environ.get(
        "PHASE3_SMOKE_TIMEOUT",
        "120",
    )
    return float(raw)


def smoke_path_budget_seconds(name: str, *, default: float = 300.0) -> float:
    env_name = {
        "therapy": "PHASE3_SMOKE_THERAPY_MAX_SECONDS",
        "assessment": "PHASE3_SMOKE_ASSESSMENT_MAX_SECONDS",
        "post_session": "PHASE3_SMOKE_POST_SESSION_MAX_SECONDS",
    }[name]
    raw = os.environ.get(env_name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def parse_completion_caps(raw: str | None) -> dict[LLMTask, int]:
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("PHASE3_SMOKE_MAX_COMPLETION_TOKENS must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("PHASE3_SMOKE_MAX_COMPLETION_TOKENS must be a JSON object")
    caps: dict[LLMTask, int] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            raise ValueError("PHASE3_SMOKE_MAX_COMPLETION_TOKENS keys must be strings")
        task = _SMOKE_COMPLETION_CAP_KEYS.get(key)
        if task is None:
            raise ValueError(f"unknown completion cap task: {key}")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"completion cap for {key} must be a positive integer")
        if value <= 0:
            raise ValueError(f"completion cap for {key} must be positive")
        caps[task] = value
    return caps


def effective_completion_cap_labels(caps: dict[LLMTask, int]) -> dict[str, int]:
    labels: dict[str, int] = {}
    for label, task in _SMOKE_COMPLETION_CAP_KEYS.items():
        if task in caps:
            labels[label] = caps[task]
    return labels


async def run_smoke_path(
    *,
    name: str,
    budget_seconds: float,
    operation: Callable[[], Awaitable[SmokeOperationResult[T]]],
) -> T:
    started = time.perf_counter()
    path_attr = {
        "therapy": "therapy",
        "assessment": "assessment",
        "post_session": "post_session",
    }[name]
    strict = smoke_strict_acceptance()
    status = "error"
    success = False
    error_type: str | None = None
    ttfc_seconds: float | None = None
    result_value: T | None = None

    async def _execute() -> SmokeOperationResult[T]:
        return await operation()

    try:
        if strict:
            with anyio.fail_after(budget_seconds):
                operation_result = await _execute()
        else:
            operation_result = await _execute()
        result_value = operation_result.value
        ttfc_seconds = operation_result.ttfc_seconds
        status = "success"
        success = True
        return result_value
    except TimeoutError:
        status = "path_timeout"
        error_type = "PathTimeout"
        raise
    except BaseException as exc:
        if is_async_cancellation(exc):
            status = "cancelled"
            error_type = "CancelledError"
            raise
        if isinstance(exc, LLMTimeout):
            status = "timeout"
            error_type = "LLMTimeout"
            raise
        status = "error"
        error_type = type(exc).__name__
        raise
    finally:
        latency = time.perf_counter() - started
        acceptance_passed = latency <= budget_seconds if success else False
        if strict and status == "path_timeout":
            acceptance_passed = False
        path_result = SmokePathResult(
            success=success,
            status=status,
            latency_seconds=latency,
            ttfc_seconds=ttfc_seconds,
            acceptance_passed=acceptance_passed,
            acceptance_max_seconds=budget_seconds,
            error_type=error_type,
        )
        setattr(COLLECTOR, path_attr, path_result)
        if strict and path_result.acceptance_passed is False and success:
            pytest.fail(
                f"{name} path exceeded acceptance budget "
                f"({latency:.3f}s > {budget_seconds}s)"
            )
