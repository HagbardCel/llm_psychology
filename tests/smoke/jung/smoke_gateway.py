"""Smoke-only gateway wrapper for structured-call evidence."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from jung.llm.errors import LLMTimeout
from jung.llm.gateway import ChatMessage, LLMGateway, ModelPolicy
from tests.smoke.jung.smoke_context import current_smoke_call_id
from tests.smoke.jung.smoke_evidence import (
    SmokeEvidenceCollector,
    SmokeStructuredCallResult,
)

T = TypeVar("T", bound=BaseModel)


class SmokeObservingGateway:
    """Records structured-call evidence around an inner gateway."""

    def __init__(
        self,
        inner: LLMGateway,
        *,
        collector: SmokeEvidenceCollector,
    ) -> None:
        self._inner = inner
        self._collector = collector

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]:
        async for chunk in self._inner.stream_text(messages, policy):
            yield chunk

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: Callable[[T], T] | None = None,
    ) -> T:
        call_id = self._collector.next_call_id(policy.task.value)
        input_message_chars = tuple(len(message.content) for message in messages)
        input_chars = sum(input_message_chars)
        output_schema_chars = len(
            json.dumps(
                output_type.model_json_schema(),
                separators=(",", ":"),
            )
        )
        token = current_smoke_call_id.set(call_id)
        started = time.perf_counter()
        status = "error"
        error_type: str | None = None
        result_chars: int | None = None
        try:
            result = await self._inner.generate_structured(
                messages,
                output_type,
                policy,
                validate_result=validate_result,
            )
            status = "success"
            try:
                result_chars = len(result.model_dump_json())
            except Exception as exc:
                self._collector.instrumentation_errors.append(
                    f"structured result measurement failed: {type(exc).__name__}"
                )
            return result
        except asyncio.CancelledError as exc:
            status = "cancelled"
            error_type = type(exc).__name__
            raise
        except LLMTimeout:
            status = "timeout"
            error_type = "LLMTimeout"
            raise
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            raise
        finally:
            current_smoke_call_id.reset(token)
            try:
                self._collector.structured_calls.append(
                    SmokeStructuredCallResult(
                        call_id=call_id,
                        task=policy.task.value,
                        output_type=output_type.__name__,
                        status=status,
                        latency_seconds=time.perf_counter() - started,
                        input_chars=input_chars,
                        input_message_chars=input_message_chars,
                        output_schema_chars=output_schema_chars,
                        result_chars=result_chars,
                        error_type=error_type,
                    )
                )
            except Exception as exc:
                self._collector.instrumentation_errors.append(
                    f"structured call recorder failed: {type(exc).__name__}"
                )
