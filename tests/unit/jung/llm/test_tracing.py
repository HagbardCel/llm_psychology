"""Tests for tracing gateway wrapper."""

from __future__ import annotations

import pytest

from jung.llm.fake import FakeLLM, StreamExpectation
from jung.llm.gateway import (
    ChatMessage,
    ChatRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.tracing import TracingLLMGateway


@pytest.mark.asyncio
async def test_tracing_gateway_passes_stream_through() -> None:
    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="local",
        temperature=0.7,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )
    gateway = TracingLLMGateway(
        FakeLLM(
            [
                StreamExpectation(
                    task=LLMTask.THERAPY_RESPONSE,
                    chunks=("hello", " world"),
                )
            ]
        )
    )
    chunks: list[str] = []
    async for chunk in gateway.stream_text(
        [ChatMessage(role=ChatRole.USER, content="hi")],
        policy,
    ):
        chunks.append(chunk)
    assert chunks == ["hello", " world"]
