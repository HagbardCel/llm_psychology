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


async def test_tracing_gateway_passes_stream_through(
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
                    chunks=("hello", " world"),
                )
            ]
        )
    )
    with caplog.at_level(logging.INFO, logger="jung.llm.tracing"):
        chunks: list[str] = []
        async for chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            policy,
        ):
            chunks.append(chunk)
    assert chunks == ["hello", " world"]
    completion_records = [
        record
        for record in caplog.records
        if "llm stream complete" in record.getMessage()
    ]
    assert len(completion_records) == 1
    assert "status=success" in completion_records[0].getMessage()


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


async def test_tracing_gateway_logs_structured_completion(
    caplog: pytest.LogCaptureFixture,
) -> None:
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
    with caplog.at_level(logging.INFO, logger="jung.llm.tracing"):
        result = await gateway.generate_structured(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            _Answer,
            policy,
        )
    assert result.value == "ok"
    completion_records = [
        record
        for record in caplog.records
        if "llm structured complete" in record.getMessage()
    ]
    assert len(completion_records) == 1
    assert "status=success" in completion_records[0].getMessage()


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
    original_error = LLMTimeout("provider stalled")
    gateway = TracingLLMGateway(
        FakeLLM(
            [
                FailureExpectation(
                    task=LLMTask.THERAPY_RESPONSE,
                    error=original_error,
                )
            ]
        )
    )
    with caplog.at_level(logging.ERROR, logger="jung.llm.tracing"):
        with pytest.raises(LLMTimeout) as exc_info:
            async for _chunk in gateway.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                policy,
            ):
                pass
    assert exc_info.value is original_error
    assert "llm stream failed" in caplog.text
    assert "status=error" in caplog.text
    assert "error_type=LLMTimeout" in caplog.text
    assert "Traceback" not in caplog.text


async def test_tracing_gateway_logs_structured_failure_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = ModelPolicy(
        task=LLMTask.ASSESSMENT,
        model="local",
        temperature=0.7,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.JSON_OBJECT,
    )
    original_error = LLMTimeout("provider stalled")
    gateway = TracingLLMGateway(
        FakeLLM(
            [
                FailureExpectation(
                    task=LLMTask.ASSESSMENT,
                    error=original_error,
                )
            ]
        ),
    )
    with caplog.at_level(logging.ERROR, logger="jung.llm.tracing"):
        with pytest.raises(LLMTimeout) as exc_info:
            await gateway.generate_structured(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                _Answer,
                policy,
            )
    assert exc_info.value is original_error
    failure_records = [
        record
        for record in caplog.records
        if "llm structured failed" in record.getMessage()
    ]
    assert len(failure_records) == 1
    message = failure_records[0].getMessage()
    assert "status=error" in message
    assert "error_type=LLMTimeout" in message
    assert "Traceback" not in caplog.text
