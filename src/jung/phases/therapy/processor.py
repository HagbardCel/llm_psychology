"""Therapy phase processor."""

from __future__ import annotations

from collections.abc import AsyncIterator

from jung.llm.gateway import ChatMessage, LLMGateway, ModelPolicy
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.therapy.prompts import build_messages as build_therapy_messages


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
        async for chunk in self._gateway.stream_text(messages, self._response_policy):
            yield chunk
