"""Gateway observer for safe metadata logs and optional diagnostic capture."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from jung._async_cleanup import close_awaitable_safely
from jung.diagnostics import DiagnosticRecorder, diagnostic_context
from jung.llm.errors import LLMTimeout
from jung.llm.gateway import ChatMessage, LLMGateway, ModelPolicy

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class ObservedLLMGateway:
    """Optional safe metadata logging and/or lean diagnostic capture."""

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
        status = "started"

        with diagnostic_context(llm_call_id=call_id):
            self._log_call_start(policy, "stream_text", messages)
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
            finally:
                try:
                    close = getattr(inner_stream, "aclose", None)
                    if close is not None:

                        def _record_close_failure(exc: BaseException) -> None:
                            logger.warning(
                                "llm stream close failed task=%s close_method=%s "
                                "error_type=%s",
                                policy.task.value,
                                "aclose",
                                type(exc).__name__,
                            )

                        await close_awaitable_safely(
                            close,
                            record_failure=_record_close_failure,
                            preserve_existing_cancellation=status == "cancelled",
                        )
                finally:
                    pass

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: Callable[[T], T] | None = None,
    ) -> T:
        call_id = self._recorder.next_id("llm") if self._recorder is not None else None
        started = time.perf_counter()
        status = "started"

        with diagnostic_context(llm_call_id=call_id):
            self._log_call_start(
                policy,
                "generate_structured",
                messages,
                output_type.__name__,
            )
            try:
                result = await self._inner.generate_structured(
                    messages,
                    output_type,
                    policy,
                    validate_result=validate_result,
                )
            except asyncio.CancelledError as exc:
                status = "cancelled"
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
                if self._recorder is not None:
                    self._recorder.record(
                        "llm.accepted",
                        {
                            "output_type": output_type.__name__,
                            "result": result,
                        },
                    )
                return result

    def _log_call_start(
        self,
        policy: ModelPolicy,
        call_type: str,
        messages: Sequence[ChatMessage],
        output_type: str | None = None,
    ) -> None:
        if not self._log_metadata:
            return
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
