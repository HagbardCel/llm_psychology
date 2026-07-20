"""Strict environment parsing for local-model smoke."""

from __future__ import annotations

import json
import math
import os

from jung.llm.gateway import LLMTask

_SMOKE_COMPLETION_CAP_KEYS = {
    "assessment": LLMTask.ASSESSMENT,
    "post_session_analysis": LLMTask.POST_SESSION_ANALYSIS,
    "post_session_update": LLMTask.POST_SESSION_UPDATE,
    "therapy_response": LLMTask.THERAPY_RESPONSE,
}

_TRUE_BOOL_VALUES = frozenset({"1", "true", "yes"})
_FALSE_BOOL_VALUES = frozenset({"0", "false", "no"})


def parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if not normalized:
        raise ValueError(f"{name} must be one of 1/true/yes or 0/false/no")
    if normalized in _TRUE_BOOL_VALUES:
        return True
    if normalized in _FALSE_BOOL_VALUES:
        return False
    raise ValueError(f"{name} must be one of 1/true/yes or 0/false/no")


def parse_positive_finite_float_env(name: str, *, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return _parse_positive_finite_float(name, raw)


def _parse_positive_finite_float(name: str, raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def smoke_log_prompt_previews() -> bool:
    return parse_bool_env("LOCAL_LLM_SMOKE_LOG_PROMPT_PREVIEWS", default=False)


def smoke_strict_acceptance() -> bool:
    return parse_bool_env("LOCAL_LLM_SMOKE_STRICT_ACCEPTANCE", default=True)


def smoke_request_timeout_seconds() -> float:
    for name in ("LOCAL_LLM_SMOKE_REQUEST_TIMEOUT", "LOCAL_LLM_SMOKE_TIMEOUT"):
        raw = os.environ.get(name)
        if raw is not None and raw.strip():
            return _parse_positive_finite_float(name, raw)
    return 120.0


def smoke_path_budget_seconds(name: str, *, default: float = 300.0) -> float:
    env_name = {
        "therapy": "LOCAL_LLM_SMOKE_THERAPY_MAX_SECONDS",
        "assessment": "LOCAL_LLM_SMOKE_ASSESSMENT_MAX_SECONDS",
        "post_session": "LOCAL_LLM_SMOKE_POST_SESSION_MAX_SECONDS",
    }[name]
    return parse_positive_finite_float_env(env_name, default=default)


def parse_completion_caps(raw: str | None) -> dict[LLMTask, int]:
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "LOCAL_LLM_SMOKE_MAX_COMPLETION_TOKENS must be valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("LOCAL_LLM_SMOKE_MAX_COMPLETION_TOKENS must be a JSON object")
    caps: dict[LLMTask, int] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            raise ValueError(
                "LOCAL_LLM_SMOKE_MAX_COMPLETION_TOKENS keys must be strings"
            )
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


def parse_smoke_extra_body(raw: str | None) -> dict[str, object] | None:
    if raw is None or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LOCAL_LLM_SMOKE_EXTRA_BODY must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LOCAL_LLM_SMOKE_EXTRA_BODY must be a JSON object")
    return parsed
