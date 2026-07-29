"""Gateway observer for safe metadata logs and optional diagnostic capture."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from jung.diagnostics import DiagnosticRecorder, diagnostic_context
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
        call_id = self._begin_call(policy, "stream_text", messages)
        started = time.perf_counter()
        first_chunk_at: float | None = None
        chunk_count = 0
        char_count = 0
        provider_attempt_ids: list[str] = []
        status = "error"
        error_type: str | None = None
        with diagnostic_context(llm_call_id=call_id):
            try:
                async for chunk in self._inner.stream_text(messages, policy):
                    if first_chunk_at is None:
                        first_chunk_at = time.perf_counter()
                    chunk_count += 1
                    char_count += len(chunk)
                    yield chunk
            except Exception as exc:
                error_type = type(exc).__name__
                if self._log_metadata:
                    logger.error(
                        "llm stream failed task=%s model=%s status=error "
                        "elapsed=%.3fs error_type=%s",
                        policy.task.value,
                        policy.model,
                        time.perf_counter() - started,
                        error_type,
                    )
                self._record_call(
                    "llm.call.error",
                    {
                        "call_id": call_id,
                        "call_type": "stream_text",
                        "task": policy.task.value,
                        "model": policy.model,
                        "status": "error",
                        "elapsed_seconds": time.perf_counter() - started,
                        "error_type": error_type,
                        "provider_attempt_ids": provider_attempt_ids,
                        "messages": [
                            {"role": m.role.value, "content": m.content}
                            for m in messages
                        ],
                    },
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
                self._record_call(
                    "llm.call.complete",
                    {
                        "call_id": call_id,
                        "call_type": "stream_text",
                        "task": policy.task.value,
                        "model": policy.model,
                        "status": status,
                        "elapsed_seconds": elapsed,
                        "response_chars": char_count,
                        "chunk_count": chunk_count,
                        "ttfc_seconds": ttfc,
                        "provider_attempt_ids": provider_attempt_ids,
                    },
                )

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: Callable[[T], T] | None = None,
    ) -> T:
        call_id = self._begin_call(
            policy,
            "generate_structured",
            messages,
            output_type.__name__,
        )
        started = time.perf_counter()
        with diagnostic_context(llm_call_id=call_id):
            try:
                result = await self._inner.generate_structured(
                    messages,
                    output_type,
                    policy,
                    validate_result=validate_result,
                )
            except Exception as exc:
                if self._log_metadata:
                    logger.error(
                        "llm structured failed task=%s model=%s output=%s "
                        "status=error elapsed=%.3fs error_type=%s",
                        policy.task.value,
                        policy.model,
                        output_type.__name__,
                        time.perf_counter() - started,
                        type(exc).__name__,
                    )
                self._record_call(
                    "llm.call.error",
                    {
                        "call_id": call_id,
                        "call_type": "generate_structured",
                        "task": policy.task.value,
                        "model": policy.model,
                        "output_type": output_type.__name__,
                        "status": "error",
                        "elapsed_seconds": time.perf_counter() - started,
                        "error_type": type(exc).__name__,
                        "messages": [
                            {"role": m.role.value, "content": m.content}
                            for m in messages
                        ],
                    },
                )
                raise
            else:
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
                self._record_call(
                    "llm.call.complete",
                    {
                        "call_id": call_id,
                        "call_type": "generate_structured",
                        "task": policy.task.value,
                        "model": policy.model,
                        "output_type": output_type.__name__,
                        "status": "success",
                        "elapsed_seconds": elapsed,
                        "result": result,
                    },
                )
                return result

    def _begin_call(
        self,
        policy: ModelPolicy,
        call_type: str,
        messages: Sequence[ChatMessage],
        output_type: str | None = None,
    ) -> str | None:
        call_id: str | None = None
        if self._recorder is not None:
            call_id = self._recorder.next_id("llm")
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
        return call_id

    def _record_call(self, kind: str, data: dict[str, object]) -> None:
        if self._recorder is None:
            return
        self._recorder.record(kind, data)


# Backward-compatible alias during migration of imports.
TracingLLMGateway = ObservedLLMGateway
