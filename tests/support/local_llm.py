"""Shared local-model client construction for opt-in real-model suites.

Used by the manual local-model smoke and by future behavioural evaluations.
This module must stay free of suite-specific concerns (evidence collection,
path budgets, acceptance policy) and must not import `tests.smoke`.

Environment is read inside functions only, never at import time, so importing
this module is safe in suites that never talk to a real model.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from jung.diagnostics import DiagnosticRecorder
from jung.llm.gateway import (
    AdapterConfig,
    LLMSettings,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import OpenAICompatibleLLM, ProviderAttemptEvent
from jung.llm.policies import build_model_policies
from jung.llm.tracing import ObservedLLMGateway

BASE_URL_ENV = "LOCAL_LLM_SMOKE_BASE_URL"
MODEL_ENV = "LOCAL_LLM_SMOKE_MODEL"
STRUCTURED_MODE_ENV = "LOCAL_LLM_SMOKE_STRUCTURED_MODE"
API_KEY_ENV = "OPENAI_API_KEY"

DEFAULT_STRUCTURED_MODE = StructuredOutputMode.JSON_SCHEMA
DEFAULT_API_KEY = "not-needed"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0


class MissingLocalModelEnv(RuntimeError):
    """Raised when a required local-model environment variable is unset."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} must be set for local-model runs")
        self.name = name


@dataclass(frozen=True, slots=True)
class LocalModelEnvironment:
    """Resolved connection details for an OpenAI-compatible local server."""

    base_url: str
    model: str
    api_key: str
    structured_mode: StructuredOutputMode


@dataclass
class LocalModelClient:
    """Observed gateway plus the raw adapter that owns the HTTP client."""

    gateway: ObservedLLMGateway
    raw: OpenAICompatibleLLM

    async def aclose(self) -> None:
        await self.raw.aclose()


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingLocalModelEnv(name)
    return value


def resolve_structured_mode() -> StructuredOutputMode:
    raw = os.environ.get(STRUCTURED_MODE_ENV, "").strip()
    if not raw:
        return DEFAULT_STRUCTURED_MODE
    return StructuredOutputMode(raw)


def resolve_local_model_environment() -> LocalModelEnvironment:
    return LocalModelEnvironment(
        base_url=required_env(BASE_URL_ENV),
        model=required_env(MODEL_ENV),
        api_key=os.environ.get(API_KEY_ENV, "") or DEFAULT_API_KEY,
        structured_mode=resolve_structured_mode(),
    )


def build_local_model_settings(
    environment: LocalModelEnvironment,
    *,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    completion_caps: dict[LLMTask, int] | None = None,
) -> LLMSettings:
    return LLMSettings(
        default_model=environment.model,
        base_url=environment.base_url,
        api_key=environment.api_key,
        task_structured_modes=dict.fromkeys(LLMTask, environment.structured_mode),
        task_timeouts=dict.fromkeys(LLMTask, request_timeout_seconds),
        task_max_completion_tokens=completion_caps or None,
    )


def build_local_model_policies(
    environment: LocalModelEnvironment,
    *,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    completion_caps: dict[LLMTask, int] | None = None,
) -> dict[LLMTask, ModelPolicy]:
    return build_model_policies(
        build_local_model_settings(
            environment,
            request_timeout_seconds=request_timeout_seconds,
            completion_caps=completion_caps,
        )
    )


def build_local_model_client(
    environment: LocalModelEnvironment,
    *,
    extra_body: dict[str, object] | None = None,
    recorder: DiagnosticRecorder | None = None,
    on_provider_attempt: Callable[[ProviderAttemptEvent], None] | None = None,
) -> LocalModelClient:
    raw = OpenAICompatibleLLM(
        AdapterConfig(
            base_url=environment.base_url,
            api_key=environment.api_key,
            extra_body=extra_body,
        ),
        recorder=recorder,
        on_provider_attempt=on_provider_attempt,
    )
    return LocalModelClient(
        gateway=ObservedLLMGateway(raw, log_metadata=True, recorder=recorder),
        raw=raw,
    )
