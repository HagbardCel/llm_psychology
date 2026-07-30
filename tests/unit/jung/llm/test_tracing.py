"""Tests for ObservedLLMGateway metadata logging."""

from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.asyncio
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
from jung.llm.tracing import ObservedLLMGateway


class _Answer(BaseModel):
    value: str


async def test_observed_gateway_passes_stream_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="local",
        temperature=0.7,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )
    gateway = ObservedLLMGateway(
        FakeLLM(
            [
                StreamExpectation(
                    task=LLMTask.THERAPY_RESPONSE,
                    chunks=("hello", " world"),
                )
            ]
        ),
        log_metadata=True,
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


async def test_observed_gateway_does_not_log_when_metadata_disabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="local",
        temperature=0.7,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )
    gateway = ObservedLLMGateway(
        FakeLLM(
            [
                StreamExpectation(
                    task=LLMTask.THERAPY_RESPONSE,
                    chunks=("hello",),
                )
            ]
        ),
        log_metadata=False,
    )
    with caplog.at_level(logging.DEBUG, logger="jung.llm.tracing"):
        async for _chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            policy,
        ):
            pass
    assert "llm call start" not in caplog.text
    assert "llm stream complete" not in caplog.text


async def test_observed_gateway_logs_structured_completion(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = ModelPolicy(
        task=LLMTask.ASSESSMENT,
        model="local",
        temperature=0.7,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.JSON_OBJECT,
    )
    gateway = ObservedLLMGateway(
        FakeLLM(
            [
                StructuredExpectation(
                    task=LLMTask.ASSESSMENT,
                    output_type=_Answer,
                    response=_Answer(value="ok"),
                )
            ]
        ),
        log_metadata=True,
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


async def test_observed_gateway_logs_failure_metadata_without_traceback(
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
    gateway = ObservedLLMGateway(
        FakeLLM(
            [
                FailureExpectation(
                    task=LLMTask.THERAPY_RESPONSE,
                    error=original_error,
                )
            ]
        ),
        log_metadata=True,
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
    assert "status=timeout" in caplog.text
    assert "error_type=LLMTimeout" in caplog.text
    assert "Traceback" not in caplog.text


async def test_observed_gateway_logs_structured_failure_metadata(
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
    gateway = ObservedLLMGateway(
        FakeLLM(
            [
                FailureExpectation(
                    task=LLMTask.ASSESSMENT,
                    error=original_error,
                )
            ]
        ),
        log_metadata=True,
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
    assert "status=timeout" in message
    assert "error_type=LLMTimeout" in message
    assert "Traceback" not in caplog.text
