"""Async OpenAI-compatible chat-completions gateway."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import TypeVar

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
    }
)


def _to_openai_messages(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [
        {"role": message.role.value, "content": message.content}
        for message in messages
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
            "extra_body cannot override adapter-owned fields: "
            f"{sorted(forbidden)}"
        )
    return merged or None


def _classify_provider_error(exc: Exception) -> Exception:
    if isinstance(
        exc,
        (InvalidLLMOutput, LLMUnavailable, LLMTimeout, LLMProtocolError),
    ):
        return exc
    if isinstance(exc, APITimeoutError):
        return LLMTimeout(str(exc))
    if isinstance(exc, APIConnectionError):
        return LLMUnavailable(str(exc))
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        if status == 408:
            return LLMTimeout(str(exc))
        if status == 429 or status >= 500:
            return LLMUnavailable(str(exc))
        return LLMProtocolError(str(exc))
    return LLMProtocolError(str(exc))


class OpenAICompatibleLLM:
    """Direct async OpenAI SDK adapter for Chat Completions-compatible servers."""

    def __init__(
        self,
        config: AdapterConfig,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._config = config
        self._client = client or AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            max_retries=0,
            default_headers=config.default_headers,
        )

    async def aclose(self) -> None:
        await self._client.close()

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
        except Exception as exc:
            raise _classify_provider_error(exc) from exc

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
            )
            return self._validate_result(
                output_type,
                invalid_text,
                validate_result,
            )
        except InvalidLLMOutput as first_error:
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
            )
            return self._validate_result(
                output_type,
                corrected,
                validate_result,
            )

    def _validate_result(
        self,
        output_type: type[T],
        text: str,
        validate_result: Callable[[T], T] | None,
    ) -> T:
        parsed = validate_structured_text(output_type, text)
        if validate_result is None:
            return parsed
        try:
            return validate_result(parsed)
        except InvalidLLMOutput:
            raise
        except (ValueError, ValidationError) as exc:
            raise InvalidLLMOutput(format_semantic_error(exc)) from exc

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
    ) -> str:
        request = self._base_request(messages, policy)
        request["stream"] = False
        response_format = response_format_for_mode(
            policy.structured_output_mode,
            output_type,
        )
        if response_format is not None:
            request["response_format"] = response_format
        try:
            response = await self._client.chat.completions.create(**request)
        except Exception as exc:
            raise _classify_provider_error(exc) from exc
        if not response.choices:
            raise InvalidLLMOutput("empty provider response")
        content = response.choices[0].message.content
        if not content or not str(content).strip():
            raise InvalidLLMOutput("missing text content")
        return strip_markdown_json_fence(str(content))
