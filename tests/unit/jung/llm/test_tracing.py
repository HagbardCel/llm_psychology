"""Tests for tracing gateway wrapper."""

from __future__ import annotations

import logging

import anyio
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


class _SlowStreamGateway:
    async def stream_text(self, messages, policy):
        await anyio.sleep(0.08)
        yield "done"

    async def generate_structured(self, messages, output_type, policy, validate_result=None):
        raise NotImplementedError


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
    assert "error_type=LLMTimeout" in caplog.text
    assert "elapsed=" in caplog.text
    assert "Traceback" not in caplog.text


def test_tracing_gateway_rejects_non_positive_heartbeat() -> None:
    with pytest.raises(ValueError, match="heartbeat_seconds must be positive"):
        TracingLLMGateway(FakeLLM([]), heartbeat_seconds=0)


@pytest.mark.asyncio
async def test_tracing_gateway_heartbeat_does_not_block_quick_stream() -> None:
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
                    chunks=("done",),
                )
            ]
        ),
        heartbeat_seconds=30,
    )
    chunks: list[str] = []
    async for chunk in gateway.stream_text(
        [ChatMessage(role=ChatRole.USER, content="hi")],
        policy,
    ):
        chunks.append(chunk)
    assert chunks == ["done"]


@pytest.mark.asyncio
async def test_tracing_gateway_emits_heartbeat_progress_event(
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
        _SlowStreamGateway(),
        heartbeat_seconds=0.02,
    )
    with caplog.at_level(logging.INFO, logger="jung.llm.tracing"):
        chunks: list[str] = []
        async for chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            policy,
        ):
            chunks.append(chunk)
    assert chunks == ["done"]
    assert any("llm call progress" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_tracing_gateway_heartbeat_does_not_block_quick_structured() -> None:
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
        heartbeat_seconds=30,
    )
    result = await gateway.generate_structured(
        [ChatMessage(role=ChatRole.USER, content="hi")],
        _Answer,
        policy,
    )
    assert result.value == "ok"
