"""Gateway contract and FakeLLM tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio
from pydantic import BaseModel

from jung.llm import (
    ChatMessage,
    ChatRole,
    FakeLLM,
    LLMTask,
    ModelPolicy,
    StreamExpectation,
    StructuredExpectation,
    StructuredOutputMode,
)


class _SampleOutput(BaseModel):
    value: str


async def test_fake_llm_streams_scripted_chunks() -> None:
    gateway = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("a", "b"),
            )
        ]
    )
    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="fake",
        temperature=0.7,
        timeout_seconds=30.0,
    )
    chunks = [
        chunk
        async for chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hello")],
            policy,
        )
    ]
    assert chunks == ["a", "b"]
    gateway.assert_exhausted()


async def test_fake_llm_returns_structured_models() -> None:
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=_SampleOutput,
                response=_SampleOutput(value="ok"),
            )
        ]
    )
    policy = ModelPolicy(
        task=LLMTask.ASSESSMENT,
        model="fake",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )
    result = await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="hello")],
        _SampleOutput,
        policy,
    )
    assert result.value == "ok"
    gateway.assert_exhausted()


async def test_fake_llm_raises_mid_stream_error() -> None:
    from jung.llm.errors import LLMUnavailable

    gateway = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.THERAPY_RESPONSE,
                chunks=("partial",),
                error_after_chunks=LLMUnavailable("stream failed"),
            )
        ]
    )
    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="fake",
        temperature=0.7,
        timeout_seconds=30.0,
    )
    chunks: list[str] = []
    with pytest.raises(LLMUnavailable):
        async for chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hello")],
            policy,
        ):
            chunks.append(chunk)
    assert chunks == ["partial"]
    gateway.assert_exhausted()
