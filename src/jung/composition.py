"""Production composition root for the target application core."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from jung._env import (
    assert_finite_json_numbers,
    optional_string,
    parse_bool,
    parse_optional_json_object,
    parse_positive_finite_float,
    parse_positive_int,
    require_non_empty_string,
)
from jung.application import TherapyApplication
from jung.events import EventStream
from jung.llm.gateway import (
    AdapterConfig,
    LLMSettings,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.llm.policies import build_model_policies
from jung.llm.structured import response_format_for_mode
from jung.llm.tracing import TracingLLMGateway
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.intake.models import IntakeRecordPatch
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.post_session.models import PostSessionResult, SessionAnalysisResult
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.processor import TherapyProcessor
from jung.styles import load_styles
from jung.supervisor import TaskSupervisor

_STREAMING_TASKS = frozenset(
    {
        LLMTask.INTAKE_RESPONSE,
        LLMTask.THERAPY_RESPONSE,
    }
)

_TASK_CONFIG_FIELDS = frozenset(
    {
        "model",
        "temperature",
        "timeout_seconds",
        "max_completion_tokens",
        "structured_output_mode",
        "extra_body",
    }
)

_TASK_CONFIG_ENV = "JUNG_LLM_TASK_CONFIG_JSON"


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: str | Path
    llm: LLMSettings
    shutdown_timeout_seconds: float = 30.0
    enable_llm_tracing: bool = False
    log_prompt_previews: bool = False
    event_queue_size: int = 64

    def __post_init__(self) -> None:
        timeout = self.shutdown_timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("shutdown_timeout_seconds must be finite and positive")

        queue_size = self.event_queue_size
        if (
            isinstance(queue_size, bool)
            or not isinstance(queue_size, int)
            or queue_size <= 0
        ):
            raise ValueError("event_queue_size must be a positive integer")


def _parse_default_headers(
    raw: dict[str, object] | None,
    *,
    env_name: str,
) -> dict[str, str] | None:
    if raw is None:
        return None
    headers: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{env_name} keys must be strings")
        if not isinstance(value, str):
            raise ValueError(f"{env_name}.{key} must be a string")
        headers[key] = value
    return headers or None


def _reject_null(path: str, value: object) -> None:
    if value is None:
        raise ValueError(f"{path} must not be null")


def _parse_task_model(path: str, value: object) -> str:
    _reject_null(path, value)
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    model = value.strip()
    if not model:
        raise ValueError(f"{path} must be non-empty")
    return model


def _parse_task_temperature(path: str, value: object) -> float:
    _reject_null(path, value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    temperature = float(value)
    if not math.isfinite(temperature) or not 0.0 <= temperature <= 2.0:
        raise ValueError(f"{path} must be a finite number between 0 and 2")
    return temperature


def _parse_task_timeout(path: str, value: object) -> float:
    _reject_null(path, value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite positive number")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(f"{path} must be a finite positive number")
    return timeout


def _parse_task_max_tokens(path: str, value: object) -> int:
    _reject_null(path, value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _parse_task_structured_mode(
    path: str,
    value: object,
    *,
    task: LLMTask,
) -> StructuredOutputMode:
    _reject_null(path, value)
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    try:
        mode = StructuredOutputMode(value)
    except ValueError as exc:
        raise ValueError(f"{path} must be a valid structured_output_mode") from exc
    if task in _STREAMING_TASKS and mode is not StructuredOutputMode.PROMPT:
        raise ValueError(f'{path} must be "prompt"')
    return mode


def _parse_task_extra_body(path: str, value: object) -> dict[str, object]:
    _reject_null(path, value)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a JSON object")
    assert_finite_json_numbers(value, path=path)
    return value


def _parse_task_config(
    raw: dict[str, object] | None,
) -> tuple[
    dict[LLMTask, str] | None,
    dict[LLMTask, float] | None,
    dict[LLMTask, float] | None,
    dict[LLMTask, StructuredOutputMode] | None,
    dict[LLMTask, int] | None,
    dict[LLMTask, dict[str, object]] | None,
]:
    if raw is None:
        return None, None, None, None, None, None

    task_models: dict[LLMTask, str] = {}
    task_temperatures: dict[LLMTask, float] = {}
    task_timeouts: dict[LLMTask, float] = {}
    task_modes: dict[LLMTask, StructuredOutputMode] = {}
    task_max_tokens: dict[LLMTask, int] = {}
    task_extra_body: dict[LLMTask, dict[str, object]] = {}

    for task_name, task_entry in raw.items():
        if not isinstance(task_name, str):
            raise ValueError(f"{_TASK_CONFIG_ENV} keys must be strings")
        try:
            task = LLMTask(task_name)
        except ValueError as exc:
            raise ValueError(
                f"{_TASK_CONFIG_ENV}.{task_name} is an unknown task"
            ) from exc
        if not isinstance(task_entry, dict):
            raise ValueError(f"{_TASK_CONFIG_ENV}.{task_name} must be a JSON object")
        for field_name, field_value in task_entry.items():
            if field_name not in _TASK_CONFIG_FIELDS:
                raise ValueError(
                    f"{_TASK_CONFIG_ENV}.{task_name}.{field_name} is an unknown field"
                )
            path = f"{_TASK_CONFIG_ENV}.{task_name}.{field_name}"
            if field_name == "model":
                task_models[task] = _parse_task_model(path, field_value)
            elif field_name == "temperature":
                task_temperatures[task] = _parse_task_temperature(path, field_value)
            elif field_name == "timeout_seconds":
                task_timeouts[task] = _parse_task_timeout(path, field_value)
            elif field_name == "max_completion_tokens":
                task_max_tokens[task] = _parse_task_max_tokens(path, field_value)
            elif field_name == "structured_output_mode":
                task_modes[task] = _parse_task_structured_mode(
                    path,
                    field_value,
                    task=task,
                )
            elif field_name == "extra_body":
                task_extra_body[task] = _parse_task_extra_body(path, field_value)

    return (
        task_models or None,
        task_temperatures or None,
        task_timeouts or None,
        task_modes or None,
        task_max_tokens or None,
        task_extra_body or None,
    )


def load_composition_settings(
    environ: Mapping[str, str],
    *,
    database_path: str | Path,
) -> Settings:
    llm_base_url = require_non_empty_string(
        "LLM_BASE_URL",
        environ.get("LLM_BASE_URL"),
        default="http://127.0.0.1:8080/v1",
    )
    llm_api_key = optional_string(environ.get("LLM_API_KEY"), default="")
    default_model = require_non_empty_string(
        "MODEL_NAME",
        environ.get("MODEL_NAME"),
        default="local-model",
    )
    shutdown_timeout = parse_positive_finite_float(
        "JUNG_SHUTDOWN_TIMEOUT",
        environ.get("JUNG_SHUTDOWN_TIMEOUT"),
        default=30.0,
    )
    event_queue_size = parse_positive_int(
        "JUNG_EVENT_QUEUE_SIZE",
        environ.get("JUNG_EVENT_QUEUE_SIZE"),
        default=64,
    )
    enable_llm_tracing = parse_bool(
        "JUNG_ENABLE_LLM_TRACING",
        environ.get("JUNG_ENABLE_LLM_TRACING"),
        default=False,
    )
    log_prompt_previews = parse_bool(
        "JUNG_LOG_PROMPT_PREVIEWS",
        environ.get("JUNG_LOG_PROMPT_PREVIEWS"),
        default=False,
    )
    if log_prompt_previews and not enable_llm_tracing:
        raise ValueError(
            "JUNG_LOG_PROMPT_PREVIEWS requires JUNG_ENABLE_LLM_TRACING=true"
        )

    extra_body = parse_optional_json_object(
        "JUNG_LLM_EXTRA_BODY_JSON",
        environ.get("JUNG_LLM_EXTRA_BODY_JSON"),
    )
    default_headers = _parse_default_headers(
        parse_optional_json_object(
            "JUNG_LLM_DEFAULT_HEADERS_JSON",
            environ.get("JUNG_LLM_DEFAULT_HEADERS_JSON"),
        ),
        env_name="JUNG_LLM_DEFAULT_HEADERS_JSON",
    )
    (
        task_models,
        task_temperatures,
        task_timeouts,
        task_modes,
        task_max_tokens,
        task_extra_body,
    ) = _parse_task_config(
        parse_optional_json_object(
            _TASK_CONFIG_ENV,
            environ.get(_TASK_CONFIG_ENV),
        ),
    )

    return Settings(
        database_path=database_path,
        llm=LLMSettings(
            default_model=default_model,
            base_url=llm_base_url,
            api_key=llm_api_key,
            task_models=task_models,
            task_temperatures=task_temperatures,
            task_timeouts=task_timeouts,
            task_structured_modes=task_modes,
            task_max_completion_tokens=task_max_tokens,
            extra_body=extra_body or None,
            task_extra_body=task_extra_body or None,
            default_headers=default_headers,
        ),
        shutdown_timeout_seconds=shutdown_timeout,
        enable_llm_tracing=enable_llm_tracing,
        log_prompt_previews=log_prompt_previews,
        event_queue_size=event_queue_size,
    )


def build_settings(
    *,
    database_path: str | Path,
    llm_base_url: str,
    llm_api_key: str,
    default_model: str,
) -> Settings:
    return Settings(
        database_path=database_path,
        llm=LLMSettings(
            default_model=default_model,
            base_url=llm_base_url,
            api_key=llm_api_key,
        ),
    )


@dataclass(frozen=True, slots=True)
class ApplicationRuntime:
    application: TherapyApplication
    events: EventStream
    supervisor: TaskSupervisor
    llm: OpenAICompatibleLLM


def _default_now() -> datetime:
    return datetime.now(UTC)


def _default_new_id() -> UUID:
    return uuid4()


_SCHEMA_OUTPUT_TYPES = {
    LLMTask.INTAKE_PATCH: IntakeRecordPatch,
    LLMTask.ASSESSMENT: AssessmentResult,
    LLMTask.POST_SESSION_ANALYSIS: SessionAnalysisResult,
    LLMTask.POST_SESSION_UPDATE: PostSessionResult,
}


def _preflight_json_schema_policies(
    policies: dict[LLMTask, ModelPolicy],
) -> None:
    for task, output_type in _SCHEMA_OUTPUT_TYPES.items():
        policy = policies[task]
        if policy.structured_output_mode is StructuredOutputMode.JSON_SCHEMA:
            response_format_for_mode(StructuredOutputMode.JSON_SCHEMA, output_type)


@asynccontextmanager
async def application_context(
    settings: Settings,
    *,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[], UUID] | None = None,
) -> AsyncIterator[ApplicationRuntime]:
    store = SQLiteStore(settings.database_path)
    await asyncio.to_thread(store.initialize)

    policies = build_model_policies(settings.llm)
    _preflight_json_schema_policies(policies)
    adapter_config = AdapterConfig(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        default_headers=settings.llm.default_headers,
        extra_body=settings.llm.extra_body,
        task_extra_body=settings.llm.task_extra_body,
    )
    llm = OpenAICompatibleLLM(adapter_config)
    try:
        gateway: OpenAICompatibleLLM | TracingLLMGateway = llm
        if settings.enable_llm_tracing:
            gateway = TracingLLMGateway(
                llm,
                log_prompt_previews=settings.log_prompt_previews,
            )

        styles = load_styles()
        intake = IntakeProcessor(
            gateway,
            patch_policy=policies[LLMTask.INTAKE_PATCH],
            response_policy=policies[LLMTask.INTAKE_RESPONSE],
        )
        assessment = AssessmentProcessor(
            gateway,
            assessment_policy=policies[LLMTask.ASSESSMENT],
        )
        therapy = TherapyProcessor(
            gateway,
            response_policy=policies[LLMTask.THERAPY_RESPONSE],
        )
        post_session = PostSessionProcessor(
            gateway,
            analysis_policy=policies[LLMTask.POST_SESSION_ANALYSIS],
            update_policy=policies[LLMTask.POST_SESSION_UPDATE],
        )
        events = EventStream(max_queue_size=settings.event_queue_size)

        async with TaskSupervisor() as supervisor:
            application = TherapyApplication(
                store=store,
                intake=intake,
                assessment=assessment,
                therapy=therapy,
                post_session=post_session,
                styles=styles,
                events=events,
                supervisor=supervisor,
                now=now or _default_now,
                new_id=new_id or _default_new_id,
            )
            await application.recover_on_startup()
            runtime = ApplicationRuntime(
                application=application,
                events=events,
                supervisor=supervisor,
                llm=llm,
            )
            try:
                yield runtime
            finally:
                application.begin_shutdown()
                await supervisor.shutdown(
                    timeout_seconds=settings.shutdown_timeout_seconds
                )
    finally:
        await llm.aclose()
