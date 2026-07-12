"""Async OpenAI-compatible chat-completions gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel

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
    response_format_for_mode,
    strip_markdown_json_fence,
    validate_structured_text,
)

T = TypeVar("T", bound=BaseModel)


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
    return merged or None


def _classify_error(exc: Exception) -> Exception:
    if isinstance(
        exc,
        (InvalidLLMOutput, LLMUnavailable, LLMTimeout, LLMProtocolError),
    ):
        return exc
    if isinstance(exc, APITimeoutError):
        return LLMTimeout(str(exc), retryable=True)
    if isinstance(exc, APIConnectionError):
        return LLMUnavailable(str(exc), retryable=True)
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        if status in {408, 429} or status >= 500:
            return LLMUnavailable(str(exc), retryable=True)
        return LLMProtocolError(str(exc), retryable=False)
    return LLMProtocolError(str(exc), retryable=False)


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
            raise LLMProtocolError("messages must not be empty", retryable=False)
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
            raise _classify_error(exc) from exc

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
    ) -> T:
        if not messages:
            raise LLMProtocolError("messages must not be empty", retryable=False)

        prepared = self._prepare_structured_messages(messages, output_type, policy)
        invalid_text = ""
        try:
            invalid_text = await self._request_text(prepared, policy, output_type)
            return validate_structured_text(output_type, invalid_text)
        except InvalidLLMOutput as first_error:
            correction_messages = build_correction_messages(
                original_messages=list(messages),
                output_type=output_type,
                invalid_text=invalid_text,
                validation_message=str(first_error),
            )
            try:
                corrected = await self._request_text(
                    correction_messages,
                    policy,
                    output_type,
                )
                return validate_structured_text(output_type, corrected)
            except Exception as exc:
                classified = _classify_error(exc)
                raise classified from exc
        except Exception as exc:
            raise _classify_error(exc) from exc

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
        if policy.max_output_tokens is not None:
            request["max_output_tokens"] = policy.max_output_tokens
        extra = _merge_extra_body(self._config, policy.task)
        if extra:
            request["extra_body"] = extra
        return request

    async def _request_text(
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
        response = await self._client.chat.completions.create(**request)
        if not response.choices:
            raise InvalidLLMOutput("empty provider response", retryable=False)
        content = response.choices[0].message.content
        if not content or not str(content).strip():
            raise InvalidLLMOutput("missing text content", retryable=False)
        return strip_markdown_json_fence(str(content))
