"""Therapy phase processor."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from jung._async_cleanup import close_awaitable_safely
from jung.llm.gateway import ChatMessage, LLMGateway, ModelPolicy
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.therapy.prompts import build_messages as build_therapy_messages

logger = logging.getLogger(__name__)


class TherapyProcessor:
    def __init__(
        self,
        gateway: LLMGateway,
        *,
        response_policy: ModelPolicy,
    ) -> None:
        self._gateway = gateway
        self._response_policy = response_policy

    def build_messages(self, input: TherapyTurnInput) -> list[ChatMessage]:
        return build_therapy_messages(input)

    async def stream_response(self, input: TherapyTurnInput) -> AsyncIterator[str]:
        messages = build_therapy_messages(input)
        preserve_close_cancellation = False
        inner = self._gateway.stream_text(messages, self._response_policy)
        try:
            async for chunk in inner:
                yield chunk
        except asyncio.CancelledError:
            preserve_close_cancellation = True
            raise
        finally:
            close = getattr(inner, "aclose", None)
            if close is not None:

                def _record_close_failure(exc: BaseException) -> None:
                    logger.debug(
                        "therapy gateway stream aclose failed error_type=%s",
                        type(exc).__name__,
                    )

                await close_awaitable_safely(
                    close,
                    record_failure=_record_close_failure,
                    preserve_existing_cancellation=preserve_close_cancellation,
                )
