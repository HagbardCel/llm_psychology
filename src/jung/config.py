"""Environment-backed Jung settings — sole production owner of os.environ."""

from __future__ import annotations

import ipaddress
import json
import math
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import (
    BeforeValidator,
    Field,
    PositiveFloat,
    field_validator,
)
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    SettingsConfigDict,
)

from jung.llm.gateway import LLMTask, StructuredOutputMode
from jung.llm.policies import TaskOverride

_STREAMING_TASKS = frozenset(
    {
        LLMTask.INTAKE_RESPONSE,
        LLMTask.THERAPY_RESPONSE,
    }
)

_TRUE_VALUES = frozenset({"1", "true", "yes"})
_FALSE_VALUES = frozenset({"0", "false", "no"})

_VALID_LOG_LEVELS = frozenset(
    {"critical", "error", "warning", "info", "debug", "trace"}
)


class LogLevel(StrEnum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"
    TRACE = "trace"


def _reject_json_constant(_value: str) -> None:
    raise ValueError("invalid JSON constant")


def _assert_finite_json_numbers(value: object, *, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must be a finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite_json_numbers(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite_json_numbers(item, path=f"{path}[{index}]")


def _parse_optional_json_object(value: object) -> dict[str, object] | None:
    """Absent/blank → None; nonblank must be a JSON object (not null/array/scalar)."""
    if value is None:
        return None
    if isinstance(value, dict):
        _assert_finite_json_numbers(value, path="value")
        return value
    if not isinstance(value, str):
        raise ValueError("must be a JSON object")
    if not value.strip():
        return None
    try:
        parsed = json.loads(value, parse_constant=_reject_json_constant)
    except ValueError as exc:
        raise ValueError("must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("must be a JSON object")
    _assert_finite_json_numbers(parsed, path="value")
    return parsed


def _parse_origins(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        raw_parts = value
    elif isinstance(value, list):
        raw_parts = tuple(value)
    elif isinstance(value, str):
        if not value.strip():
            return ()
        raw_parts = tuple(value.split(","))
    else:
        raise ValueError("invalid CORS origins")

    origins: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        if not isinstance(part, str):
            raise ValueError("CORS origins must be strings")
        origin = part.strip()
        if not origin:
            continue
        if origin == "*":
            raise ValueError("wildcard CORS origin is not allowed")
        if origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return tuple(origins)


def _parse_tight_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ValueError("must be one of 1/true/yes or 0/false/no")
    if not value.strip():
        raise ValueError("must be one of 1/true/yes or 0/false/no")
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError("must be one of 1/true/yes or 0/false/no")


def _parse_data_dir(value: object) -> Path:
    if value is None:
        return Path("./data")
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return Path("./data")
        return Path(stripped)
    raise ValueError("invalid data directory")


def _parse_optional_path(value: object) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        if not value.strip():
            return None
        return Path(value.strip())
    raise ValueError("invalid path")


def _parse_non_empty_trimmed(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("must be a non-empty string")
    stripped = value.strip()
    if not stripped:
        raise ValueError("must be non-empty")
    return stripped


def _parse_log_level(value: object) -> LogLevel:
    if isinstance(value, LogLevel):
        return value
    if not isinstance(value, str):
        raise ValueError("invalid log level")
    normalized = value.strip().lower()
    if normalized not in _VALID_LOG_LEVELS:
        raise ValueError(f"invalid log level: {value!r}")
    return LogLevel(normalized)


def _parse_task_config(
    value: object,
) -> dict[LLMTask, TaskOverride]:
    if isinstance(value, str) or value is None:
        raw = _parse_optional_json_object(value)
        if raw is None:
            return {}
    elif isinstance(value, dict):
        raw = value
    else:
        raise ValueError("task config must be a mapping")

    overrides: dict[LLMTask, TaskOverride] = {}
    for task_key, task_value in raw.items():
        try:
            task = task_key if isinstance(task_key, LLMTask) else LLMTask(task_key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{task_key} is an unknown task") from exc

        if isinstance(task_value, TaskOverride):
            override = task_value
        elif isinstance(task_value, dict):
            override = TaskOverride.model_validate(task_value)
        else:
            raise ValueError(f"{task.value} must be a task override object")

        if (
            task in _STREAMING_TASKS
            and override.structured_output_mode is not None
            and override.structured_output_mode is not StructuredOutputMode.PROMPT
        ):
            raise ValueError(f'{task.value}.structured_output_mode must be "prompt"')
        overrides[task] = override
    return overrides


def _parse_default_headers(value: object) -> dict[str, str] | None:
    raw = _parse_optional_json_object(value)
    if raw is None:
        return None
    headers: dict[str, str] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ValueError("header keys must be strings")
        if not isinstance(item, str):
            raise ValueError(f"{key} must be a string")
        headers[key] = item
    return headers or None


def _parse_extra_body(value: object) -> dict[str, object] | None:
    return _parse_optional_json_object(value)


CorsOrigins = Annotated[
    tuple[str, ...],
    NoDecode,
    BeforeValidator(_parse_origins),
]

TightBool = Annotated[bool, BeforeValidator(_parse_tight_bool)]
DataDir = Annotated[Path, BeforeValidator(_parse_data_dir)]
OptionalPath = Annotated[Path | None, BeforeValidator(_parse_optional_path)]
NonEmptyTrimmedStr = Annotated[str, BeforeValidator(_parse_non_empty_trimmed)]
NormalizedLogLevel = Annotated[LogLevel, BeforeValidator(_parse_log_level)]
TaskConfigMap = Annotated[
    dict[LLMTask, TaskOverride],
    NoDecode,
    BeforeValidator(_parse_task_config),
]
OptionalJsonObject = Annotated[
    dict[str, object] | None,
    NoDecode,
    BeforeValidator(_parse_extra_body),
]
OptionalHeaders = Annotated[
    dict[str, str] | None,
    NoDecode,
    BeforeValidator(_parse_default_headers),
]


class JungSettings(BaseSettings):
    """Validated operator configuration for Jung runtime and API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        dotenv_filtering="only_existing",
        case_sensitive=True,
        frozen=True,
        extra="forbid",
        validate_by_name=True,
        validate_by_alias=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    data_dir: DataDir = Field(default=Path("./data"), validation_alias="JUNG_DATA_DIR")

    llm_base_url: NonEmptyTrimmedStr = Field(
        default="http://127.0.0.1:8080/v1",
        validation_alias="LLM_BASE_URL",
    )
    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    model_name: NonEmptyTrimmedStr = Field(
        default="local-model",
        validation_alias="MODEL_NAME",
    )
    llm_extra_body: OptionalJsonObject = Field(
        default=None,
        validation_alias="JUNG_LLM_EXTRA_BODY_JSON",
    )
    llm_default_headers: OptionalHeaders = Field(
        default=None,
        validation_alias="JUNG_LLM_DEFAULT_HEADERS_JSON",
    )
    llm_task_config: TaskConfigMap = Field(
        default_factory=dict,
        validation_alias="JUNG_LLM_TASK_CONFIG_JSON",
    )

    shutdown_timeout_seconds: PositiveFloat = Field(
        default=30.0,
        validation_alias="JUNG_SHUTDOWN_TIMEOUT",
    )
    enable_llm_tracing: TightBool = Field(
        default=False,
        validation_alias="JUNG_ENABLE_LLM_TRACING",
    )
    debug_run_dir: OptionalPath = Field(
        default=None,
        validation_alias="JUNG_DEBUG_RUN_DIR",
    )

    api_host: NonEmptyTrimmedStr = Field(
        default="127.0.0.1",
        validation_alias="JUNG_API_HOST",
    )
    api_port: Annotated[int, Field(ge=1, le=65535)] = Field(
        default=8000,
        validation_alias="JUNG_API_PORT",
    )
    api_log_level: NormalizedLogLevel = Field(
        default=LogLevel.INFO,
        validation_alias="JUNG_API_LOG_LEVEL",
    )
    api_allowed_origins: CorsOrigins = Field(
        default=(),
        validation_alias="JUNG_API_ALLOWED_ORIGINS",
    )
    api_allow_remote_bind: TightBool = Field(
        default=False,
        validation_alias="JUNG_API_ALLOW_REMOTE_BIND",
    )

    websocket_send_timeout: PositiveFloat = Field(
        default=5.0,
        validation_alias="JUNG_WS_SEND_TIMEOUT",
    )
    websocket_close_timeout: PositiveFloat = Field(
        default=2.0,
        validation_alias="JUNG_WS_CLOSE_TIMEOUT",
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "jung.db"

    @field_validator("api_port", mode="before")
    @classmethod
    def reject_bool_port(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("port must be an integer between 1 and 65535")
        return value

    @field_validator(
        "shutdown_timeout_seconds",
        "websocket_send_timeout",
        "websocket_close_timeout",
        mode="before",
    )
    @classmethod
    def reject_bool_timeout(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("must be a positive finite number")
        return value


def load_settings() -> JungSettings:
    """Sole production environment-backed construction path."""
    return JungSettings()


def validate_bind_host(settings: JungSettings) -> None:
    host = settings.api_host.strip()
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    if settings.api_allow_remote_bind:
        return
    raise ValueError(
        "JUNG_API_HOST must be a loopback address unless "
        "JUNG_API_ALLOW_REMOTE_BIND=true. The API has no authentication or "
        "transport encryption."
    )
