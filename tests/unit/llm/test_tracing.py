"""Tests for ObservedLLMGateway metadata logging."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio
from pydantic import BaseModel

from jung.diagnostics import DiagnosticRun
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


async def test_observed_gateway_swallow_close_method_cancellederror_and_records_cleanup(
    tmp_path: Path,
) -> None:
    class CloseCancelledStream:
        def __init__(self) -> None:
            self._done = False

        def __aiter__(self) -> CloseCancelledStream:
            return self

        async def __anext__(self) -> str:
            if self._done:
                raise StopAsyncIteration
            self._done = True
            return "hello"

        async def aclose(self) -> None:
            raise asyncio.CancelledError()

    class Inner:
        def stream_text(self, messages, policy):  # type: ignore[no-untyped-def]
            return CloseCancelledStream()

    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="local",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )

    run_dir = tmp_path / "gateway-close-cancel"
    with DiagnosticRun(run_dir) as recorder:
        gateway = ObservedLLMGateway(Inner(), recorder=recorder)
        chunks: list[str] = []
        async for chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            policy,
        ):
            chunks.append(chunk)

        assert chunks == ["hello"]

    lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]  # type: ignore[name-defined]
    started = [e for e in events if e["kind"] == "llm.call.started"]
    terminals = [
        e
        for e in events
        if e["kind"] in {"llm.call.completed", "llm.call.failed", "llm.call.cancelled"}
    ]
    assert len(started) == 1
    assert len(terminals) == 1
    assert not any(e["kind"] == "llm.stream.cleanup.error" for e in events)


async def test_observed_gateway_ambient_cancel_during_close_drains_then_propagates(
    tmp_path: Path,
) -> None:
    close_started = asyncio.Event()
    close_release = asyncio.Event()

    class CloseBlockedStream:
        def __init__(self) -> None:
            self._done = False

        def __aiter__(self) -> CloseBlockedStream:
            return self

        async def __anext__(self) -> str:
            if self._done:
                raise StopAsyncIteration
            self._done = True
            return "hello"

        async def aclose(self) -> None:
            close_started.set()
            await close_release.wait()

    class Inner:
        def stream_text(self, messages, policy):  # type: ignore[no-untyped-def]
            return CloseBlockedStream()

    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="local",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )

    run_dir = tmp_path / "gateway-close-ambient-cancel"
    with DiagnosticRun(run_dir) as recorder:
        gateway = ObservedLLMGateway(Inner(), recorder=recorder)

        async def consume() -> None:
            async for _chunk in gateway.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                policy,
            ):
                pass

        task = asyncio.create_task(consume())
        await close_started.wait()
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Terminal was already determined before close was awaited.
        trace_path = run_dir / "trace.jsonl"
        assert trace_path.exists()

    lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]  # type: ignore[name-defined]
    started = [e for e in events if e["kind"] == "llm.call.started"]
    terminals = [
        e
        for e in events
        if e["kind"] in {"llm.call.completed", "llm.call.failed", "llm.call.cancelled"}
    ]
    assert len(started) == 1
    assert len(terminals) == 1
    assert not any(e["kind"] == "llm.stream.cleanup.error" for e in events)


async def test_observed_gateway_preserves_stream_cancel_message_over_close_cancel(
    tmp_path: Path,
) -> None:
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    close_finished = asyncio.Event()

    class CloseBlockedStream:
        def __init__(self) -> None:
            self._yielded = False

        def __aiter__(self) -> CloseBlockedStream:
            return self

        async def __anext__(self) -> str:
            if self._yielded:
                await asyncio.Event().wait()
            self._yielded = True
            return "hello"

        async def aclose(self) -> None:
            close_started.set()
            try:
                await close_release.wait()
            finally:
                close_finished.set()

    class Inner:
        def stream_text(self, messages, policy):  # type: ignore[no-untyped-def]
            return CloseBlockedStream()

    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="local",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )

    run_dir = tmp_path / "gateway-preserve-stream-cancel"
    with DiagnosticRun(run_dir) as recorder:
        gateway = ObservedLLMGateway(Inner(), recorder=recorder)

        async def consume() -> None:
            async for _chunk in gateway.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                policy,
            ):
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        task.cancel("stream-cancel")
        await close_started.wait()
        task.cancel("close-cancel")
        await asyncio.sleep(0.01)
        assert not task.done()
        close_release.set()
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task
        assert exc_info.value.args == ("stream-cancel",)
        assert close_finished.is_set() is True

    events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    started = [e for e in events if e["kind"] == "llm.call.started"]
    terminals = [
        e
        for e in events
        if e["kind"] in {"llm.call.completed", "llm.call.failed", "llm.call.cancelled"}
    ]
    assert len(started) == 1
    assert len(terminals) == 1
    assert not any(e["kind"] == "llm.stream.cleanup.error" for e in events)


async def test_observed_gateway_preserves_cancel_when_close_also_raises_cancelled(
    tmp_path: Path,
) -> None:
    class CloseCancelledStream:
        def __init__(self) -> None:
            self._yielded = False

        def __aiter__(self) -> CloseCancelledStream:
            return self

        async def __anext__(self) -> str:
            if self._yielded:
                await asyncio.Event().wait()
            self._yielded = True
            return "hello"

        async def aclose(self) -> None:
            raise asyncio.CancelledError("close-own-cancel")

    class Inner:
        def stream_text(self, messages, policy):  # type: ignore[no-untyped-def]
            return CloseCancelledStream()

    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="local",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )

    run_dir = tmp_path / "gateway-cancel-plus-close-cancel"
    with DiagnosticRun(run_dir) as recorder:
        gateway = ObservedLLMGateway(Inner(), recorder=recorder)

        async def consume() -> None:
            async for _chunk in gateway.stream_text(
                [ChatMessage(role=ChatRole.USER, content="hi")],
                policy,
            ):
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        task.cancel("stream-cancel")
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task
        assert exc_info.value.args == ("stream-cancel",)

    events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    started = [e for e in events if e["kind"] == "llm.call.started"]
    terminals = [
        e
        for e in events
        if e["kind"] in {"llm.call.completed", "llm.call.failed", "llm.call.cancelled"}
    ]
    assert len(started) == 1
    assert len(terminals) == 1
    assert not any(e["kind"] == "llm.stream.cleanup.error" for e in events)


async def test_observed_gateway_close_failure_without_recorder_logs_safe_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class CloseFailStream:
        def __init__(self) -> None:
            self._done = False

        def __aiter__(self) -> CloseFailStream:
            return self

        async def __anext__(self) -> str:
            if self._done:
                raise StopAsyncIteration
            self._done = True
            return "hello"

        async def aclose(self) -> None:
            raise RuntimeError("close boom with secret=sk-leak")

    class Inner:
        def stream_text(self, messages, policy):  # type: ignore[no-untyped-def]
            return CloseFailStream()

    policy = ModelPolicy(
        task=LLMTask.THERAPY_RESPONSE,
        model="local",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )
    gateway = ObservedLLMGateway(Inner(), recorder=None)

    with caplog.at_level(logging.WARNING, logger="jung.llm.tracing"):
        chunks: list[str] = []
        async for chunk in gateway.stream_text(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            policy,
        ):
            chunks.append(chunk)

    assert chunks == ["hello"]
    warnings = [
        record
        for record in caplog.records
        if "llm stream close failed" in record.getMessage()
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "error_type=RuntimeError" in message
    assert "close_method=aclose" in message
    assert "sk-leak" not in message
    assert "close boom" not in message
    assert "http" not in message.lower()
    assert "api_key" not in message.lower()
