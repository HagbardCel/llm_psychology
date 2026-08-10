"""Pure model policy construction from explicit settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from jung.llm.gateway import LLMSettings, LLMTask, ModelPolicy, StructuredOutputMode

_DEFAULT_TEMPERATURES: dict[LLMTask, float] = {
    LLMTask.INTAKE_PATCH: 0.1,
    LLMTask.ASSESSMENT: 0.1,
    LLMTask.POST_SESSION_ANALYSIS: 0.1,
    LLMTask.POST_SESSION_UPDATE: 0.1,
    LLMTask.INTAKE_RESPONSE: 0.7,
    LLMTask.THERAPY_RESPONSE: 0.7,
}

_DEFAULT_TIMEOUTS: dict[LLMTask, float] = dict.fromkeys(LLMTask, 120.0)

_DEFAULT_STRUCTURED_MODES: dict[LLMTask, StructuredOutputMode] = {
    LLMTask.INTAKE_PATCH: StructuredOutputMode.JSON_SCHEMA,
    LLMTask.ASSESSMENT: StructuredOutputMode.JSON_SCHEMA,
    LLMTask.POST_SESSION_ANALYSIS: StructuredOutputMode.JSON_SCHEMA,
    LLMTask.POST_SESSION_UPDATE: StructuredOutputMode.JSON_SCHEMA,
    LLMTask.INTAKE_RESPONSE: StructuredOutputMode.PROMPT,
    LLMTask.THERAPY_RESPONSE: StructuredOutputMode.PROMPT,
}


class TaskOverride(BaseModel):
    """Per-task operator overrides; absence means no override."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    model: str | None = None
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    timeout_seconds: Annotated[float, Field(gt=0)] | None = None
    max_completion_tokens: Annotated[StrictInt, Field(gt=0)] | None = None
    structured_output_mode: StructuredOutputMode | None = None
    extra_body: dict[str, object] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for name, field_value in value.items():
                if field_value is None:
                    raise ValueError(f"{name} must not be null")
        return value

    @field_validator("temperature", "timeout_seconds", mode="before")
    @classmethod
    def require_json_number(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a number")
        return value

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("must be non-empty")
        return value

    @field_validator("extra_body")
    @classmethod
    def require_finite_extra_body(
        cls,
        value: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if value is None:
            return None
        _assert_finite_json_numbers(value, path="extra_body")
        return value


def _assert_finite_json_numbers(value: object, *, path: str) -> None:
    import math

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must be a finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite_json_numbers(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite_json_numbers(item, path=f"{path}[{index}]")


def task_overrides_to_llm_settings(
    *,
    default_model: str,
    base_url: str,
    api_key: str,
    task_overrides: Mapping[LLMTask, TaskOverride],
    extra_body: dict[str, object] | None,
    default_headers: dict[str, str] | None,
) -> LLMSettings:
    """Temporary 6D.1 bridge: TaskOverride → six-map LLMSettings."""
    task_models: dict[LLMTask, str] = {}
    task_temperatures: dict[LLMTask, float] = {}
    task_timeouts: dict[LLMTask, float] = {}
    task_modes: dict[LLMTask, StructuredOutputMode] = {}
    task_max_tokens: dict[LLMTask, int] = {}
    task_extra_body: dict[LLMTask, dict[str, object]] = {}

    for task, override in task_overrides.items():
        if override.model is not None:
            task_models[task] = override.model
        if override.temperature is not None:
            task_temperatures[task] = override.temperature
        if override.timeout_seconds is not None:
            task_timeouts[task] = override.timeout_seconds
        if override.structured_output_mode is not None:
            task_modes[task] = override.structured_output_mode
        if override.max_completion_tokens is not None:
            task_max_tokens[task] = override.max_completion_tokens
        if override.extra_body:
            task_extra_body[task] = override.extra_body

    return LLMSettings(
        default_model=default_model,
        base_url=base_url,
        api_key=api_key,
        task_models=task_models or None,
        task_temperatures=task_temperatures or None,
        task_timeouts=task_timeouts or None,
        task_structured_modes=task_modes or None,
        task_max_completion_tokens=task_max_tokens or None,
        extra_body=extra_body,
        task_extra_body=task_extra_body or None,
        default_headers=default_headers,
    )


def build_model_policies(settings: LLMSettings) -> dict[LLMTask, ModelPolicy]:
    if not settings.default_model.strip():
        raise ValueError("default_model must be non-empty")
    if not settings.base_url.strip():
        raise ValueError("base_url must be non-empty")

    policies: dict[LLMTask, ModelPolicy] = {}
    for task in LLMTask:
        model = (settings.task_models or {}).get(task, settings.default_model)
        temperature = (settings.task_temperatures or {}).get(
            task, _DEFAULT_TEMPERATURES[task]
        )
        timeout = (settings.task_timeouts or {}).get(task, _DEFAULT_TIMEOUTS[task])
        mode = (settings.task_structured_modes or {}).get(
            task, _DEFAULT_STRUCTURED_MODES[task]
        )
        max_tokens = (settings.task_max_completion_tokens or {}).get(task)
        policies[task] = ModelPolicy(
            task=task,
            model=model,
            temperature=temperature,
            timeout_seconds=timeout,
            max_completion_tokens=max_tokens,
            structured_output_mode=mode,
        )
    return policies
