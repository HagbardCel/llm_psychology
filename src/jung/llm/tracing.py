"""Tracing decorator for the LLM gateway boundary."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import TypeVar

from pydantic import BaseModel

from jung.llm.gateway import ChatMessage, LLMGateway, ModelPolicy

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class TracingLLMGateway:
    """Records task, latency, and redacted diagnostics around a gateway."""

    def __init__(
        self,
        inner: LLMGateway,
        *,
        log_prompt_previews: bool = False,
        preview_chars: int = 200,
    ) -> None:
        self._inner = inner
        self._log_prompt_previews = log_prompt_previews
        self._preview_chars = preview_chars

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]:
        started = time.perf_counter()
        first_chunk_at: float | None = None
        chunk_count = 0
        char_count = 0
        self._log_start(policy, "stream_text", messages)
        try:
            async for chunk in self._inner.stream_text(messages, policy):
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()
                chunk_count += 1
                char_count += len(chunk)
                yield chunk
        except Exception as exc:
            logger.error(
                "llm stream failed task=%s model=%s status=error "
                "elapsed=%.3fs error_type=%s",
                policy.task.value,
                policy.model,
                time.perf_counter() - started,
                type(exc).__name__,
            )
            raise
        else:
            elapsed = time.perf_counter() - started
            ttfc = (first_chunk_at - started) if first_chunk_at is not None else None
            logger.info(
                "llm stream complete task=%s model=%s elapsed=%.3fs "
                "ttfc=%s chunks=%s chars=%s",
                policy.task.value,
                policy.model,
                elapsed,
                f"{ttfc:.3f}s" if ttfc is not None else "n/a",
                chunk_count,
                char_count,
            )

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result=None,
    ) -> T:
        started = time.perf_counter()
        self._log_start(policy, "generate_structured", messages, output_type.__name__)
        try:
            result = await self._inner.generate_structured(
                messages,
                output_type,
                policy,
                validate_result=validate_result,
            )
        except Exception as exc:
            logger.error(
                "llm structured failed task=%s model=%s output=%s "
                "status=error elapsed=%.3fs error_type=%s",
                policy.task.value,
                policy.model,
                output_type.__name__,
                time.perf_counter() - started,
                type(exc).__name__,
            )
            raise
        else:
            elapsed = time.perf_counter() - started
            logger.info(
                "llm structured complete task=%s model=%s output=%s elapsed=%.3fs",
                policy.task.value,
                policy.model,
                output_type.__name__,
                elapsed,
            )
            return result

    def _log_start(
        self,
        policy: ModelPolicy,
        call_type: str,
        messages: Sequence[ChatMessage],
        output_type: str | None = None,
    ) -> None:
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
        if self._log_prompt_previews:
            for index, message in enumerate(messages):
                preview = message.content[: self._preview_chars]
                logger.debug(
                    "llm preview message[%s] role=%s preview=%r",
                    index,
                    message.role.value,
                    preview,
                )
