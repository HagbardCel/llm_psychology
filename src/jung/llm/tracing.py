"""Gateway observer for safe metadata logs and optional diagnostic capture."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from jung.diagnostics import DiagnosticRecorder, diagnostic_context
from jung.llm.errors import LLMTimeout
from jung.llm.gateway import ChatMessage, LLMGateway, ModelPolicy

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class ObservedLLMGateway:
    """Optional safe metadata logging and/or exact diagnostic capture."""

    def __init__(
        self,
        inner: LLMGateway,
        *,
        log_metadata: bool = False,
        recorder: DiagnosticRecorder | None = None,
    ) -> None:
        self._inner = inner
        self._log_metadata = log_metadata
        self._recorder = recorder

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]:
        call_id = self._recorder.next_id("llm") if self._recorder is not None else None
        started = time.perf_counter()
        first_chunk_at: float | None = None
        chunk_count = 0
        char_count = 0
        terminal_emitted = False
        status = "started"

        with diagnostic_context(llm_call_id=call_id):
            self._begin_call(call_id, policy, "stream_text", messages)
            inner_stream = self._inner.stream_text(messages, policy)
            try:
                try:
                    async for chunk in inner_stream:
                        if first_chunk_at is None:
                            first_chunk_at = time.perf_counter()
                        chunk_count += 1
                        char_count += len(chunk)
                        yield chunk
                except asyncio.CancelledError as exc:
                    status = "cancelled"
                    self._fail_call(
                        call_id=call_id,
                        call_type="stream_text",
                        policy=policy,
                        status=status,
                        started=started,
                        error_type=type(exc).__name__,
                    )
                    terminal_emitted = True
                    if self._log_metadata:
                        logger.error(
                            "llm stream failed task=%s model=%s status=cancelled "
                            "elapsed=%.3fs error_type=%s",
                            policy.task.value,
                            policy.model,
                            time.perf_counter() - started,
                            type(exc).__name__,
                        )
                    raise
                except Exception as exc:
                    status = "timeout" if isinstance(exc, LLMTimeout) else "error"
                    self._fail_call(
                        call_id=call_id,
                        call_type="stream_text",
                        policy=policy,
                        status=status,
                        started=started,
                        error_type=type(exc).__name__,
                    )
                    terminal_emitted = True
                    if self._log_metadata:
                        logger.error(
                            "llm stream failed task=%s model=%s status=%s "
                            "elapsed=%.3fs error_type=%s",
                            policy.task.value,
                            policy.model,
                            status,
                            time.perf_counter() - started,
                            type(exc).__name__,
                        )
                    raise
                else:
                    status = "success"
                    elapsed = time.perf_counter() - started
                    ttfc = (
                        (first_chunk_at - started)
                        if first_chunk_at is not None
                        else None
                    )
                    if self._log_metadata:
                        logger.info(
                            "llm stream complete task=%s model=%s status=success "
                            "elapsed=%.3fs ttfc=%s chunks=%s chars=%s",
                            policy.task.value,
                            policy.model,
                            elapsed,
                            f"{ttfc:.3f}s" if ttfc is not None else "n/a",
                            chunk_count,
                            char_count,
                        )
                    self._complete_call(
                        call_id=call_id,
                        call_type="stream_text",
                        policy=policy,
                        elapsed=elapsed,
                        response_chars=char_count,
                        chunk_count=chunk_count,
                        ttfc_seconds=ttfc,
                    )
                    terminal_emitted = True
            finally:
                close = getattr(inner_stream, "aclose", None)
                if close is not None:
                    try:
                        await close()
                    except Exception:
                        pass
                if not terminal_emitted and status != "success":
                    self._fail_call(
                        call_id=call_id,
                        call_type="stream_text",
                        policy=policy,
                        status="abandoned",
                        started=started,
                        error_type="GeneratorExit",
                    )

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: Callable[[T], T] | None = None,
    ) -> T:
        call_id = self._recorder.next_id("llm") if self._recorder is not None else None
        started = time.perf_counter()
        terminal_emitted = False
        status = "started"

        with diagnostic_context(llm_call_id=call_id):
            self._begin_call(
                call_id,
                policy,
                "generate_structured",
                messages,
                output_type.__name__,
            )
            try:
                try:
                    result = await self._inner.generate_structured(
                        messages,
                        output_type,
                        policy,
                        validate_result=validate_result,
                    )
                except asyncio.CancelledError as exc:
                    status = "cancelled"
                    self._fail_call(
                        call_id=call_id,
                        call_type="generate_structured",
                        policy=policy,
                        status=status,
                        started=started,
                        error_type=type(exc).__name__,
                        output_type=output_type.__name__,
                    )
                    terminal_emitted = True
                    if self._log_metadata:
                        logger.error(
                            "llm structured failed task=%s model=%s output=%s "
                            "status=cancelled elapsed=%.3fs error_type=%s",
                            policy.task.value,
                            policy.model,
                            output_type.__name__,
                            time.perf_counter() - started,
                            type(exc).__name__,
                        )
                    raise
                except Exception as exc:
                    status = "timeout" if isinstance(exc, LLMTimeout) else "error"
                    self._fail_call(
                        call_id=call_id,
                        call_type="generate_structured",
                        policy=policy,
                        status=status,
                        started=started,
                        error_type=type(exc).__name__,
                        output_type=output_type.__name__,
                    )
                    terminal_emitted = True
                    if self._log_metadata:
                        logger.error(
                            "llm structured failed task=%s model=%s output=%s "
                            "status=%s elapsed=%.3fs error_type=%s",
                            policy.task.value,
                            policy.model,
                            output_type.__name__,
                            status,
                            time.perf_counter() - started,
                            type(exc).__name__,
                        )
                    raise
                else:
                    status = "success"
                    elapsed = time.perf_counter() - started
                    if self._log_metadata:
                        logger.info(
                            "llm structured complete task=%s model=%s output=%s "
                            "status=success elapsed=%.3fs",
                            policy.task.value,
                            policy.model,
                            output_type.__name__,
                            elapsed,
                        )
                    self._complete_call(
                        call_id=call_id,
                        call_type="generate_structured",
                        policy=policy,
                        elapsed=elapsed,
                        output_type=output_type.__name__,
                        result=result,
                    )
                    terminal_emitted = True
                    return result
            finally:
                if not terminal_emitted and status != "success":
                    self._fail_call(
                        call_id=call_id,
                        call_type="generate_structured",
                        policy=policy,
                        status="abandoned",
                        started=started,
                        error_type="Abandoned",
                        output_type=output_type.__name__,
                    )

    def _begin_call(
        self,
        call_id: str | None,
        policy: ModelPolicy,
        call_type: str,
        messages: Sequence[ChatMessage],
        output_type: str | None = None,
    ) -> None:
        if self._recorder is not None and call_id is not None:
            role_sequence = ",".join(message.role.value for message in messages)
            self._recorder.record(
                "llm.call.start",
                {
                    "call_id": call_id,
                    "call_type": call_type,
                    "task": policy.task.value,
                    "model": policy.model,
                    "mode": policy.structured_output_mode.value,
                    "message_count": len(messages),
                    "roles": role_sequence,
                    "input_chars": sum(len(m.content) for m in messages),
                    "output_type": output_type,
                    "messages": [
                        {"role": m.role.value, "content": m.content} for m in messages
                    ],
                },
            )
        if self._log_metadata:
            role_sequence = ",".join(message.role.value for message in messages)
            char_counts = sum(len(message.content) for message in messages)
            logger.info(
                "llm call start type=%s task=%s model=%s mode=%s "
                "messages=%s roles=%s chars=%s output=%s",
                call_type,
                policy.task.value,
                policy.model,
                policy.structured_output_mode.value,
                len(messages),
                role_sequence,
                char_counts,
                output_type or "-",
            )

    def _complete_call(
        self,
        *,
        call_id: str | None,
        call_type: str,
        policy: ModelPolicy,
        elapsed: float,
        response_chars: int | None = None,
        chunk_count: int | None = None,
        ttfc_seconds: float | None = None,
        output_type: str | None = None,
        result: BaseModel | None = None,
    ) -> None:
        data: dict[str, object] = {
            "call_id": call_id,
            "call_type": call_type,
            "task": policy.task.value,
            "model": policy.model,
            "status": "success",
            "elapsed_seconds": elapsed,
        }
        if response_chars is not None:
            data["response_chars"] = response_chars
        if chunk_count is not None:
            data["chunk_count"] = chunk_count
        if ttfc_seconds is not None:
            data["ttfc_seconds"] = ttfc_seconds
        if output_type is not None:
            data["output_type"] = output_type
        if result is not None:
            data["result"] = result
        self._record_call("llm.call.complete", data)

    def _fail_call(
        self,
        *,
        call_id: str | None,
        call_type: str,
        policy: ModelPolicy,
        status: str,
        started: float,
        error_type: str,
        output_type: str | None = None,
    ) -> None:
        data: dict[str, object] = {
            "call_id": call_id,
            "call_type": call_type,
            "task": policy.task.value,
            "model": policy.model,
            "status": status,
            "elapsed_seconds": time.perf_counter() - started,
            "error_type": error_type,
        }
        if output_type is not None:
            data["output_type"] = output_type
        self._record_call("llm.call.error", data)

    def _record_call(self, kind: str, data: dict[str, object]) -> None:
        if self._recorder is None:
            return
        self._recorder.record(kind, data)
