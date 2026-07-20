"""Async OpenAI-compatible chat-completions gateway."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from jung.llm.errors import (
    InvalidLLMOutput,
    LLMProtocolError,
    LLMTimeout,
    LLMUnavailable,
)
from jung.llm.gateway import (
    AdapterConfig,
    ChatMessage,
    ChatRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.structured import (
    build_correction_messages,
    build_prompt_schema_instruction,
    format_semantic_error,
    response_format_for_mode,
    strip_markdown_json_fence,
    validate_structured_text,
)

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

_FORBIDDEN_EXTRA_BODY_KEYS = frozenset(
    {
        "model",
        "messages",
        "response_format",
        "max_completion_tokens",
        "stream",
        "temperature",
    }
)


class _StructuredValidationFailure(InvalidLLMOutput):
    def __init__(self, message: str, *, trigger: str) -> None:
        super().__init__(message)
        self.trigger = trigger


@dataclass(frozen=True, slots=True)
class ProviderAttemptEvent:
    task: str
    attempt: Literal["initial", "correction"]
    status: str
    latency_seconds: float
    prompt_chars: int
    response_format_chars: int | None
    response_chars: int | None
    timeout_seconds: float
    max_completion_tokens: int | None
    correction_trigger: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error_type: str | None = None


def _to_openai_messages(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [
        {"role": message.role.value, "content": message.content} for message in messages
    ]


def _merge_extra_body(
    config: AdapterConfig,
    task: LLMTask,
) -> dict[str, object] | None:
    merged: dict[str, object] = {}
    if config.extra_body:
        merged.update(config.extra_body)
    if config.task_extra_body and task in config.task_extra_body:
        merged.update(config.task_extra_body[task])
    forbidden = merged.keys() & _FORBIDDEN_EXTRA_BODY_KEYS
    if forbidden:
        raise ValueError(
            f"extra_body cannot override adapter-owned fields: {sorted(forbidden)}"
        )
    return merged or None


def _classify_status_error(exc: APIStatusError) -> Exception:
    status = exc.status_code
    if status == 408:
        return LLMTimeout(str(exc))
    if status == 429 or status >= 500:
        return LLMUnavailable(str(exc))
    return LLMProtocolError(str(exc))


def _prompt_chars(messages: Sequence[ChatMessage]) -> int:
    return sum(len(message.content) for message in messages)


def _response_format_chars(
    response_format: dict[str, object] | None,
) -> int | None:
    if response_format is None:
        return None
    return len(json.dumps(response_format, separators=(",", ":")))


class OpenAICompatibleLLM:
    """Direct async OpenAI SDK adapter for Chat Completions-compatible servers."""

    def __init__(
        self,
        config: AdapterConfig,
        *,
        client: AsyncOpenAI | None = None,
        on_provider_attempt: Callable[[ProviderAttemptEvent], None] | None = None,
    ) -> None:
        for task in LLMTask:
            _merge_extra_body(config, task)

        self._config = config
        self._client = client or AsyncOpenAI(
            base_url=config.base_url,
            # OpenAI SDK rejects empty credentials; local OpenAI-compatible
            # servers often need no auth, so use a non-empty placeholder.
            api_key=config.api_key or "not-needed",
            max_retries=0,
            default_headers=config.default_headers,
        )
        self._on_provider_attempt = on_provider_attempt

    async def aclose(self) -> None:
        await self._client.close()

    def _emit_provider_attempt(self, event: ProviderAttemptEvent) -> None:
        if self._on_provider_attempt is None:
            return
        try:
            self._on_provider_attempt(event)
        except Exception as exc:
            logger.error(
                "llm provider attempt observer failed error_type=%s",
                type(exc).__name__,
            )

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]:
        if not messages:
            raise LLMProtocolError("messages must not be empty")
        request = self._base_request(messages, policy)
        request["stream"] = True
        try:
            stream = await self._client.chat.completions.create(**request)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                text = chunk.choices[0].delta.content
                if text:
                    yield text
        except APITimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc
        except APIConnectionError as exc:
            raise LLMUnavailable(str(exc)) from exc
        except APIStatusError as exc:
            raise _classify_status_error(exc) from exc

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: Callable[[T], T] | None = None,
    ) -> T:
        if not messages:
            raise LLMProtocolError("messages must not be empty")

        prepared = self._prepare_structured_messages(messages, output_type, policy)
        invalid_text = ""
        try:
            invalid_text = await self._make_provider_request(
                prepared,
                policy,
                output_type,
                attempt="initial",
            )
            return self._validate_result(
                output_type,
                invalid_text,
                validate_result,
            )
        except InvalidLLMOutput as first_error:
            if isinstance(first_error, _StructuredValidationFailure):
                correction_trigger = first_error.trigger
            else:
                correction_trigger = "syntactic_or_schema_validation"
            logger.info(
                "llm structured correction task=%s model=%s output=%s",
                policy.task.value,
                policy.model,
                output_type.__name__,
            )
            correction_messages = build_correction_messages(
                original_messages=prepared,
                output_type=output_type,
                invalid_text=invalid_text,
                validation_message=str(first_error),
            )
            corrected = await self._make_provider_request(
                correction_messages,
                policy,
                output_type,
                attempt="correction",
                correction_trigger=correction_trigger,
            )
            try:
                return self._validate_result(
                    output_type,
                    corrected,
                    validate_result,
                )
            except _StructuredValidationFailure as exc:
                raise InvalidLLMOutput(str(exc)) from exc

    def _validate_result(
        self,
        output_type: type[T],
        text: str,
        validate_result: Callable[[T], T] | None,
    ) -> T:
        try:
            parsed = validate_structured_text(output_type, text)
        except InvalidLLMOutput as exc:
            raise _StructuredValidationFailure(
                str(exc),
                trigger="syntactic_or_schema_validation",
            ) from exc
        if validate_result is None:
            return parsed
        try:
            return validate_result(parsed)
        except InvalidLLMOutput as exc:
            raise _StructuredValidationFailure(
                str(exc),
                trigger="semantic_validation",
            ) from exc
        except (ValueError, ValidationError) as exc:
            raise _StructuredValidationFailure(
                format_semantic_error(exc),
                trigger="semantic_validation",
            ) from exc

    def _prepare_structured_messages(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[BaseModel],
        policy: ModelPolicy,
    ) -> list[ChatMessage]:
        if policy.structured_output_mode is StructuredOutputMode.PROMPT:
            return [
                *messages,
                ChatMessage(
                    role=ChatRole.USER,
                    content=build_prompt_schema_instruction(output_type),
                ),
            ]
        return list(messages)

    def _base_request(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> dict[str, object]:
        request: dict[str, object] = {
            "model": policy.model,
            "messages": _to_openai_messages(messages),
            "temperature": policy.temperature,
            "timeout": policy.timeout_seconds,
        }
        if policy.max_completion_tokens is not None:
            request["max_completion_tokens"] = policy.max_completion_tokens
        extra = _merge_extra_body(self._config, policy.task)
        if extra:
            request["extra_body"] = extra
        return request

    async def _make_provider_request(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
        output_type: type[BaseModel],
        *,
        attempt: Literal["initial", "correction"],
        correction_trigger: str | None = None,
    ) -> str:
        request = self._base_request(messages, policy)
        request["stream"] = False
        response_format = response_format_for_mode(
            policy.structured_output_mode,
            output_type,
        )
        if response_format is not None:
            request["response_format"] = response_format

        prompt_char_count = _prompt_chars(messages)
        format_char_count = _response_format_chars(response_format)
        started = time.perf_counter()
        status = "error"
        error_type: str | None = None
        response_chars: int | None = None
        finish_reason: str | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None

        logger.info(
            "llm provider request start task=%s attempt=%s mode=%s "
            "prompt_chars=%s timeout=%s max_completion_tokens=%s",
            policy.task.value,
            attempt,
            policy.structured_output_mode.value,
            prompt_char_count,
            policy.timeout_seconds,
            policy.max_completion_tokens,
        )

        try:
            response = await self._client.chat.completions.create(**request)
            if not response.choices:
                raise InvalidLLMOutput("empty provider response")
            choice = response.choices[0]
            content = choice.message.content
            if not content or not str(content).strip():
                raise InvalidLLMOutput("missing text content")
            raw_text = str(content)
            response_chars = len(raw_text)
            text = strip_markdown_json_fence(raw_text)
            status = "success"
            finish_reason = choice.finish_reason
            if response.usage is not None:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
            logger.info(
                "llm provider request complete task=%s attempt=%s elapsed=%.3fs "
                "response_chars=%s finish_reason=%s prompt_tokens=%s "
                "completion_tokens=%s",
                policy.task.value,
                attempt,
                time.perf_counter() - started,
                response_chars,
                finish_reason,
                prompt_tokens,
                completion_tokens,
            )
            return text
        except asyncio.CancelledError as exc:
            status = "cancelled"
            error_type = type(exc).__name__
            raise
        except InvalidLLMOutput:
            status = "error"
            error_type = "InvalidLLMOutput"
            raise
        except APITimeoutError as exc:
            status = "timeout"
            error_type = "LLMTimeout"
            raise LLMTimeout(str(exc)) from exc
        except APIConnectionError as exc:
            status = "error"
            error_type = "LLMUnavailable"
            raise LLMUnavailable(str(exc)) from exc
        except APIStatusError as exc:
            classified = _classify_status_error(exc)
            status = "timeout" if isinstance(classified, LLMTimeout) else "error"
            error_type = type(classified).__name__
            raise classified from exc
        finally:
            elapsed = time.perf_counter() - started
            if status != "success" and error_type is not None:
                logger.error(
                    "llm provider request failed task=%s attempt=%s "
                    "elapsed=%.3fs error_type=%s",
                    policy.task.value,
                    attempt,
                    elapsed,
                    error_type,
                )
            self._emit_provider_attempt(
                ProviderAttemptEvent(
                    task=policy.task.value,
                    attempt=attempt,
                    status=status,
                    latency_seconds=elapsed,
                    prompt_chars=prompt_char_count,
                    response_format_chars=format_char_count,
                    response_chars=response_chars,
                    timeout_seconds=policy.timeout_seconds,
                    max_completion_tokens=policy.max_completion_tokens,
                    correction_trigger=correction_trigger,
                    finish_reason=finish_reason,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    error_type=error_type,
                )
            )
