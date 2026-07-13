"""Project-owned LLM gateway contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel, field_validator

T = TypeVar("T", bound=BaseModel)

ResultValidator = Callable[[T], T]


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str

    @field_validator("content")
    @classmethod
    def content_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must be non-empty")
        return value


class LLMTask(StrEnum):
    INTAKE_PATCH = "intake_patch"
    INTAKE_RESPONSE = "intake_response"
    ASSESSMENT = "assessment"
    THERAPY_RESPONSE = "therapy_response"
    POST_SESSION_ANALYSIS = "post_session_analysis"
    POST_SESSION_UPDATE = "post_session_update"


class StructuredOutputMode(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    task: LLMTask
    model: str
    temperature: float
    timeout_seconds: float
    max_completion_tokens: int | None = None
    structured_output_mode: StructuredOutputMode = StructuredOutputMode.PROMPT

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature out of range")
        if self.max_completion_tokens is not None and self.max_completion_tokens <= 0:
            raise ValueError("max_completion_tokens must be positive")


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    base_url: str
    api_key: str
    default_headers: dict[str, str] | None = None
    extra_body: dict[str, object] | None = None
    task_extra_body: dict[LLMTask, dict[str, object]] | None = None


@dataclass(frozen=True, slots=True)
class LLMSettings:
    default_model: str
    base_url: str
    api_key: str
    task_models: dict[LLMTask, str] | None = None
    task_temperatures: dict[LLMTask, float] | None = None
    task_timeouts: dict[LLMTask, float] | None = None
    task_structured_modes: dict[LLMTask, StructuredOutputMode] | None = None
    task_max_completion_tokens: dict[LLMTask, int] | None = None
    extra_body: dict[str, object] | None = None
    task_extra_body: dict[LLMTask, dict[str, object]] | None = None
    default_headers: dict[str, str] | None = None


class LLMGateway(Protocol):
    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]: ...

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: ResultValidator[T] | None = None,
    ) -> T: ...
