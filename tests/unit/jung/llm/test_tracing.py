"""Tests for tracing gateway wrapper."""

from __future__ import annotations

import logging

import pytest
from pydantic import BaseModel

from jung.llm.errors import LLMTimeout
from jung.llm.fake import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from jung.llm.gateway import (
    ChatMessage,
    ChatRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.tracing import TracingLLMGateway


class _Answer(BaseModel):
    value: str


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


@pytest.mark.asyncio
async def test_tracing_gateway_does_not_log_prompt_previews_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
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
                    chunks=("secret prompt content",),
                )
            ]
        ),
        log_prompt_previews=False,
    )
    with caplog.at_level(logging.DEBUG, logger="jung.llm.tracing"):
        async for _chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="secret prompt content")],
            policy,
        ):
            pass
    assert "secret prompt content" not in caplog.text


@pytest.mark.asyncio
async def test_tracing_gateway_logs_structured_completion() -> None:
    policy = ModelPolicy(
        task=LLMTask.ASSESSMENT,
        model="local",
        temperature=0.7,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.JSON_OBJECT,
    )
    gateway = TracingLLMGateway(
        FakeLLM(
            [
                StructuredExpectation(
                    task=LLMTask.ASSESSMENT,
                    output_type=_Answer,
                    response=_Answer(value="ok"),
                )
            ]
        ),
    )
    result = await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="hi")],
        _Answer,
        policy,
    )
    assert result.value == "ok"


@pytest.mark.asyncio
async def test_tracing_gateway_logs_failure_metadata_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
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
                FailureExpectation(
                    task=LLMTask.THERAPY_RESPONSE,
                    error=LLMTimeout("provider stalled"),
                )
            ]
        )
    )
    with caplog.at_level(logging.ERROR, logger="jung.llm.tracing"):
        with pytest.raises(LLMTimeout):
            async for _chunk in gateway.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                policy,
            ):
                pass
    assert "llm stream failed" in caplog.text
    assert "status=error" in caplog.text
    assert "error_type=LLMTimeout" in caplog.text
    assert "Traceback" not in caplog.text
