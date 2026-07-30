"""Async OpenAI-compatible chat-completions gateway."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from jung.diagnostics import (
    DiagnosticRecorder,
    current_diagnostic_context,
    sanitize_url,
)
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


def _safe_exception_message(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:
        return "<exception message unavailable>"


async def _close_stream_safely(
    close: Callable[[], object],
    *,
    record_failure: Callable[[BaseException], None],
) -> None:
    """Close-stream helper that preserves ambient cancellations.

    Close-method `CancelledError` is treated as a secondary cleanup failure
    and swallowed. Ambient task cancellation is drained and re-raised.
    """
    try:
        result = close()
    except asyncio.CancelledError as exc:
        record_failure(exc)
        return
    except Exception as exc:
        record_failure(exc)
        return

    if not inspect.isawaitable(result):
        return

    close_task = asyncio.create_task(result)
    try:
        await asyncio.shield(close_task)
    except asyncio.CancelledError as exc:
        current = asyncio.current_task()
        # Distinguish close-method CancelledError (close raises) from ambient
        # cancellation (caller task has cancellation requested).
        if current is not None and current.cancelling() > 0:
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError as close_exc:
                record_failure(close_exc)
            except Exception as close_exc:
                record_failure(close_exc)
            raise

        record_failure(exc)
        return
    except Exception as exc:
        record_failure(exc)
        return

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
        recorder: DiagnosticRecorder | None = None,
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
        self._recorder = recorder

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

    def _provider_attempt_id(self) -> str | None:
        if self._recorder is None:
            return None
        return self._recorder.next_id("provider")

    def _record_provider(
        self,
        kind: str,
        data: dict[str, object],
    ) -> None:
        if self._recorder is None:
            return
        self._recorder.record(kind, data)

    def _record_provider_request(
        self,
        *,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
        attempt: Literal["initial", "correction"],
        provider_attempt_id: str | None,
        response_format: dict[str, object] | None,
        stream: bool,
        correction_trigger: str | None = None,
    ) -> None:
        self._record_provider(
            "llm.provider.request",
            self._request_evidence(
                messages=messages,
                policy=policy,
                attempt=attempt,
                provider_attempt_id=provider_attempt_id,
                response_format=response_format,
                stream=stream,
                correction_trigger=correction_trigger,
            ),
        )

    def _record_provider_success(
        self,
        *,
        provider_attempt_id: str | None,
        policy: ModelPolicy,
        attempt: Literal["initial", "correction"],
        started: float,
        raw_response_text: str | None,
        finish_reason: str | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> None:
        text = raw_response_text or ""
        self._record_provider(
            "llm.provider.response",
            {
                "provider_attempt_id": provider_attempt_id,
                "llm_call_id": current_diagnostic_context().llm_call_id,
                "task": policy.task.value,
                "attempt": attempt,
                "status": "success",
                "latency_seconds": time.perf_counter() - started,
                "raw_response_text": raw_response_text,
                "finish_reason": finish_reason,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "response_chars": len(text),
            },
        )

    def _record_provider_failure(
        self,
        *,
        provider_attempt_id: str | None,
        policy: ModelPolicy,
        attempt: Literal["initial", "correction"],
        status: str,
        started: float,
        error_type: str,
        error_message: str,
        partial_response_text: str | None = None,
        raw_response_text: str | None = None,
        finish_reason: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "provider_attempt_id": provider_attempt_id,
            "llm_call_id": current_diagnostic_context().llm_call_id,
            "task": policy.task.value,
            "attempt": attempt,
            "status": status,
            "latency_seconds": time.perf_counter() - started,
            "error_type": error_type,
            "error_message": error_message,
            "finish_reason": finish_reason,
        }
        if partial_response_text is not None:
            payload["partial_response_text"] = partial_response_text
        if raw_response_text is not None:
            payload["raw_response_text"] = raw_response_text
        self._record_provider("llm.provider.error", payload)

    def _request_evidence(
        self,
        *,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
        attempt: Literal["initial", "correction"],
        provider_attempt_id: str | None,
        response_format: dict[str, object] | None,
        stream: bool,
        correction_trigger: str | None = None,
    ) -> dict[str, object]:
        extra = _merge_extra_body(self._config, policy.task)
        context = current_diagnostic_context()
        payload: dict[str, object] = {
            "provider_attempt_id": provider_attempt_id,
            "llm_call_id": context.llm_call_id,
            "task": policy.task.value,
            "attempt": attempt,
            "stream": stream,
            "model": policy.model,
            "temperature": policy.temperature,
            "timeout_seconds": policy.timeout_seconds,
            "max_completion_tokens": policy.max_completion_tokens,
            "structured_output_mode": policy.structured_output_mode.value,
            "base_url": sanitize_url(self._config.base_url),
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in messages
            ],
            "response_format": response_format,
            "extra_body": extra,
        }
        if correction_trigger is not None:
            payload["correction_trigger"] = correction_trigger
        return payload

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]:
        if not messages:
            raise LLMProtocolError("messages must not be empty")
        request = self._base_request(messages, policy)
        request["stream"] = True
        prompt_char_count = _prompt_chars(messages)
        provider_attempt_id = self._provider_attempt_id()
        recording = self._recorder is not None
        started = time.perf_counter()
        status = "started"
        error_type: str | None = None
        error_message: str | None = None
        finish_reason: str | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        assembled: list[str] = []
        terminal_emitted = False
        sdk_stream = None

        self._record_provider_request(
            messages=messages,
            policy=policy,
            attempt="initial",
            provider_attempt_id=provider_attempt_id,
            response_format=None,
            stream=True,
        )

        try:
            try:
                sdk_stream = await self._client.chat.completions.create(**request)
                async for chunk in sdk_stream:
                    if getattr(chunk, "usage", None) is not None:
                        usage = chunk.usage
                        prompt_tokens = getattr(usage, "prompt_tokens", None)
                        completion_tokens = getattr(usage, "completion_tokens", None)
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    reason = getattr(choice, "finish_reason", None)
                    if reason:
                        finish_reason = reason
                    text = choice.delta.content if choice.delta is not None else None
                    if text:
                        if recording:
                            assembled.append(text)
                        yield text
                status = "success"
                raw_text = "".join(assembled) if recording else None
                if recording:
                    self._record_provider_success(
                        provider_attempt_id=provider_attempt_id,
                        policy=policy,
                        attempt="initial",
                        started=started,
                        raw_response_text=raw_text,
                        finish_reason=finish_reason,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                terminal_emitted = True
            except asyncio.CancelledError as exc:
                status = "cancelled"
                error_type = type(exc).__name__
                error_message = str(exc)
                if recording:
                    self._record_provider_failure(
                        provider_attempt_id=provider_attempt_id,
                        policy=policy,
                        attempt="initial",
                        status=status,
                        started=started,
                        error_type=error_type,
                        error_message=error_message,
                        partial_response_text="".join(assembled),
                        finish_reason=finish_reason,
                    )
                terminal_emitted = True
                raise
            except APITimeoutError as exc:
                status = "timeout"
                error_type = "LLMTimeout"
                error_message = str(exc)
                if recording:
                    self._record_provider_failure(
                        provider_attempt_id=provider_attempt_id,
                        policy=policy,
                        attempt="initial",
                        status=status,
                        started=started,
                        error_type=error_type,
                        error_message=error_message,
                        partial_response_text="".join(assembled),
                        finish_reason=finish_reason,
                    )
                terminal_emitted = True
                raise LLMTimeout(str(exc)) from exc
            except APIConnectionError as exc:
                status = "error"
                error_type = "LLMUnavailable"
                error_message = str(exc)
                if recording:
                    self._record_provider_failure(
                        provider_attempt_id=provider_attempt_id,
                        policy=policy,
                        attempt="initial",
                        status=status,
                        started=started,
                        error_type=error_type,
                        error_message=error_message,
                        partial_response_text="".join(assembled),
                        finish_reason=finish_reason,
                    )
                terminal_emitted = True
                raise LLMUnavailable(str(exc)) from exc
            except APIStatusError as exc:
                classified = _classify_status_error(exc)
                status = "timeout" if isinstance(classified, LLMTimeout) else "error"
                error_type = type(classified).__name__
                error_message = str(exc)
                if recording:
                    self._record_provider_failure(
                        provider_attempt_id=provider_attempt_id,
                        policy=policy,
                        attempt="initial",
                        status=status,
                        started=started,
                        error_type=error_type,
                        error_message=error_message,
                        partial_response_text="".join(assembled),
                        finish_reason=finish_reason,
                    )
                terminal_emitted = True
                raise classified from exc
            except Exception as exc:
                status = "error"
                error_type = type(exc).__name__
                error_message = str(exc)
                if recording:
                    self._record_provider_failure(
                        provider_attempt_id=provider_attempt_id,
                        policy=policy,
                        attempt="initial",
                        status=status,
                        started=started,
                        error_type=error_type,
                        error_message=error_message,
                        partial_response_text="".join(assembled),
                        finish_reason=finish_reason,
                    )
                terminal_emitted = True
                raise
        finally:
            await self._close_sdk_stream(
                sdk_stream,
                provider_attempt_id=provider_attempt_id,
                policy=policy,
                status=status,
            )
            if recording and not terminal_emitted and status != "success":
                status = "abandoned"
                error_type = "GeneratorExit"
                error_message = "stream closed before completion"
                self._record_provider_failure(
                    provider_attempt_id=provider_attempt_id,
                    policy=policy,
                    attempt="initial",
                    status=status,
                    started=started,
                    error_type=error_type,
                    error_message=error_message,
                    partial_response_text="".join(assembled),
                    finish_reason=finish_reason,
                )
            elapsed = time.perf_counter() - started
            self._emit_provider_attempt(
                ProviderAttemptEvent(
                    task=policy.task.value,
                    attempt="initial",
                    status=status if status != "started" else "abandoned",
                    latency_seconds=elapsed,
                    prompt_chars=prompt_char_count,
                    response_format_chars=None,
                    response_chars=len("".join(assembled)) if recording else None,
                    timeout_seconds=policy.timeout_seconds,
                    max_completion_tokens=policy.max_completion_tokens,
                    finish_reason=finish_reason,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    error_type=error_type,
                )
            )

    async def _close_sdk_stream(
        self,
        sdk_stream: object | None,
        *,
        provider_attempt_id: str | None,
        policy: ModelPolicy,
        status: str,
    ) -> None:
        if sdk_stream is None:
            return
        close_method = getattr(sdk_stream, "aclose", None)
        close_method_name = "aclose"
        if close_method is None:
            close_method = getattr(sdk_stream, "close", None)
            close_method_name = "close"
        if close_method is None:
            return

        terminal_outcome = status if status != "started" else "abandoned"

        def _record_close_failure(exc: BaseException) -> None:
            self._record_provider(
                "llm.provider.cleanup.error",
                {
                    "provider_attempt_id": provider_attempt_id,
                    "llm_call_id": current_diagnostic_context().llm_call_id,
                    "task": policy.task.value,
                    "attempt": "initial",
                    "outcome_status": terminal_outcome,
                    "close_method": close_method_name,
                    "error_type": type(exc).__name__,
                    "error_message": _safe_exception_message(exc),
                },
            )

        await _close_stream_safely(
            close_method,
            record_failure=_record_close_failure,
        )

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
        provider_attempt_id = self._provider_attempt_id()
        started = time.perf_counter()
        status = "started"
        error_type: str | None = None
        error_message: str | None = None
        response_chars: int | None = None
        finish_reason: str | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        raw_text: str | None = None
        terminal_emitted = False

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

        self._record_provider_request(
            messages=messages,
            policy=policy,
            attempt=attempt,
            provider_attempt_id=provider_attempt_id,
            response_format=response_format,
            stream=False,
            correction_trigger=correction_trigger,
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
            self._record_provider_success(
                provider_attempt_id=provider_attempt_id,
                policy=policy,
                attempt=attempt,
                started=started,
                raw_response_text=raw_text,
                finish_reason=finish_reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            terminal_emitted = True
            return text
        except asyncio.CancelledError as exc:
            status = "cancelled"
            error_type = type(exc).__name__
            error_message = str(exc)
            raise
        except InvalidLLMOutput as exc:
            status = "error"
            error_type = "InvalidLLMOutput"
            error_message = str(exc)
            raise
        except APITimeoutError as exc:
            status = "timeout"
            error_type = "LLMTimeout"
            error_message = str(exc)
            raise LLMTimeout(str(exc)) from exc
        except APIConnectionError as exc:
            status = "error"
            error_type = "LLMUnavailable"
            error_message = str(exc)
            raise LLMUnavailable(str(exc)) from exc
        except APIStatusError as exc:
            classified = _classify_status_error(exc)
            status = "timeout" if isinstance(classified, LLMTimeout) else "error"
            error_type = type(classified).__name__
            error_message = str(exc)
            raise classified from exc
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            error_message = str(exc)
            raise
        finally:
            elapsed = time.perf_counter() - started
            if status != "success" and error_type is not None and not terminal_emitted:
                logger.error(
                    "llm provider request failed task=%s attempt=%s "
                    "elapsed=%.3fs error_type=%s",
                    policy.task.value,
                    attempt,
                    elapsed,
                    error_type,
                )
                self._record_provider_failure(
                    provider_attempt_id=provider_attempt_id,
                    policy=policy,
                    attempt=attempt,
                    status=status,
                    started=started,
                    error_type=error_type,
                    error_message=error_message or error_type,
                    raw_response_text=raw_text,
                    finish_reason=finish_reason,
                )
            self._emit_provider_attempt(
                ProviderAttemptEvent(
                    task=policy.task.value,
                    attempt=attempt,
                    status=status if status != "started" else "error",
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
