"""Therapy phase processor."""

from __future__ import annotations

from collections.abc import AsyncGenerator

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

    def stream_response(self, input: TherapyTurnInput) -> AsyncGenerator[str, None]:
        return self._gateway.stream_text(
            build_therapy_messages(input),
            self._response_policy,
        )
