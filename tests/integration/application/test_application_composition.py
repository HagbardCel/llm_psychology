"""Composition-root smoke tests for TherapyApplication."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest

from jung.application import TherapyApplication
from jung.composition import application_context
from jung.domain.models import Stage
from jung.llm.gateway import AdapterConfig, LLMRole, LLMTask
from jung.llm.structured import UnsupportedStrictSchema
from jung.phases.intake.models import IntakeRecordPatch
from tests.support.fake_llm import FakeLLM
from tests.support.settings import make_test_settings

pytestmark = pytest.mark.asyncio


def _load_trace(run_dir: Path) -> list[dict[str, object]]:
    lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def failing_load_styles() -> None:
    raise RuntimeError("boom")


def _composition_settings(tmp_path: Path, **overrides: object):
    return make_test_settings(
        data_dir=tmp_path,
        model_name="fake",
        llm_base_url="http://fake.test",
        llm_api_key="fake",
        shutdown_timeout_seconds=2.0,
        **overrides,
    )


async def test_application_context_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed_count = 0

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal closed_count
            closed_count += 1

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    settings = _composition_settings(tmp_path)
    async with application_context(settings) as application:
        snapshot = await application.get_snapshot()
        assert snapshot.stage is Stage.SETUP
    assert application.is_shutdown is True
    assert closed_count == 2


async def test_application_context_rejects_unsupported_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @classmethod
    def unsupported_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "value": {"type": "string", "examples": ["bad"]},
            },
        }

    monkeypatch.setattr(
        IntakeRecordPatch,
        "model_json_schema",
        unsupported_schema,
    )
    monkeypatch.setattr(
        "jung.composition.OpenAICompatibleLLM",
        lambda *args, **kwargs: FakeLLM([]),
    )
    settings = _composition_settings(tmp_path)
    with pytest.raises(UnsupportedStrictSchema):
        async with application_context(settings):
            pass


async def test_application_context_closes_llm_when_load_styles_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_count = 0

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal closed_count
            closed_count += 1

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    monkeypatch.setattr("jung.composition.load_styles", failing_load_styles)
    settings = _composition_settings(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        async with application_context(settings):
            pass
    assert closed_count == 2


async def test_application_context_closes_llm_when_recover_on_startup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_count = 0

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal closed_count
            closed_count += 1

    async def failing_recover_on_startup(self) -> None:
        raise RuntimeError("recover failed")

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    monkeypatch.setattr(
        "jung.application.TherapyApplication.recover_on_startup",
        failing_recover_on_startup,
    )
    settings = _composition_settings(tmp_path)
    with pytest.raises(RuntimeError, match="recover failed"):
        async with application_context(settings):
            pass
    assert closed_count == 2


async def test_application_context_wires_loaded_llm_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_config: list[AdapterConfig] = []
    captured_llms: list[object] = []
    observed_calls: list[tuple[object, object | None, bool, object | None]] = []

    class RecordingObservedGateway:
        def __init__(
            self,
            llm: object,
            *,
            role: object | None = None,
            log_metadata: bool = False,
            recorder: object | None = None,
        ) -> None:
            observed_calls.append((llm, role, log_metadata, recorder))
            self._llm = llm

        def __getattr__(self, name: str) -> object:
            return getattr(self._llm, name)

    class CapturingLLM(FakeLLM):
        def __init__(self, config: AdapterConfig, **kwargs: object) -> None:
            captured_config.append(config)
            captured_llms.append(self)
            super().__init__([])

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", CapturingLLM)
    monkeypatch.setattr("jung.composition.ObservedLLMGateway", RecordingObservedGateway)

    settings = _composition_settings(
        tmp_path,
        enable_llm_tracing=True,
        llm_default_headers=json.dumps({"X-Test-Header": "value"}),
        llm_extra_body=json.dumps({"global_flag": True}),
        llm_task_config=json.dumps(
            {
                "therapy_response": {
                    "extra_body": {"task_flag": False},
                },
                "assessment": {
                    "extra_body": {"supervisor_flag": True},
                },
            }
        ),
    )

    async with application_context(settings) as application:
        snapshot = await application.get_snapshot()
        assert snapshot.stage is Stage.SETUP

    assert len(captured_config) == 2
    session_config, supervisor_config = captured_config
    assert session_config.default_headers == {"X-Test-Header": "value"}
    assert session_config.extra_body == {"global_flag": True}
    assert session_config.task_extra_body == {
        LLMTask.THERAPY_RESPONSE: {"task_flag": False}
    }
    assert supervisor_config.task_extra_body == {
        LLMTask.ASSESSMENT: {"supervisor_flag": True}
    }
    assert len(observed_calls) == 2
    assert observed_calls[0][0] is captured_llms[0]
    assert observed_calls[0][1] is LLMRole.SESSION
    assert observed_calls[0][2] is True
    assert observed_calls[1][0] is captured_llms[1]
    assert observed_calls[1][1] is LLMRole.SUPERVISOR


async def test_application_context_rejects_forbidden_extra_body_before_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_openai(*args: object, **kwargs: object) -> None:
        raise AssertionError("AsyncOpenAI must not be constructed")

    monkeypatch.setattr("jung.llm.openai_compatible.AsyncOpenAI", fail_openai)

    settings = _composition_settings(
        tmp_path,
        llm_extra_body=json.dumps({"model": "override"}),
    )

    with pytest.raises(
        ValueError, match="extra_body cannot override adapter-owned fields"
    ):
        async with application_context(settings):
            pass


async def test_primary_failure_wins_over_shutdown_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm_closed = 0
    shutdown_error = RuntimeError("shutdown-B")

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal llm_closed
            llm_closed += 1

    async def failing_shutdown(
        self: TherapyApplication, *, timeout_seconds: float
    ) -> None:
        del timeout_seconds
        raise shutdown_error

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    monkeypatch.setattr(TherapyApplication, "shutdown", failing_shutdown)

    settings = _composition_settings(tmp_path)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="body-A"):
            async with application_context(settings):
                raise RuntimeError("body-A")
    assert llm_closed == 2
    cleanup_messages = [
        record.getMessage()
        for record in caplog.records
        if "runtime cleanup failed" in record.getMessage()
    ]
    assert cleanup_messages
    assert any("application.shutdown" in message for message in cleanup_messages)
    assert all("shutdown-B" not in message for message in cleanup_messages)


async def test_shutdown_failure_propagates_and_marks_diagnostics_end_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_dir = tmp_path / "debug-run"
    shutdown_error = RuntimeError("shutdown-B")

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            return None

    async def failing_shutdown(
        self: TherapyApplication, *, timeout_seconds: float
    ) -> None:
        del timeout_seconds
        raise shutdown_error

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    monkeypatch.setattr(TherapyApplication, "shutdown", failing_shutdown)

    settings = _composition_settings(tmp_path, debug_run_dir=run_dir)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="shutdown-B"):
            async with application_context(settings) as application:
                snapshot = await application.get_snapshot()
                assert snapshot.stage is Stage.SETUP
    assert any(
        "runtime cleanup failed" in record.getMessage()
        and "application.shutdown" in record.getMessage()
        for record in caplog.records
    )
    cleanup_messages = [
        record.getMessage()
        for record in caplog.records
        if "runtime cleanup failed" in record.getMessage()
    ]
    assert cleanup_messages
    assert all("shutdown-B" not in message for message in cleanup_messages)
    events = _load_trace(run_dir)
    end = next(event for event in events if event["kind"] == "diagnostics.end")
    assert end["data"]["status"] == "failed"
    assert end["data"]["error_type"] == "RuntimeError"


async def test_llm_close_failure_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    close_error = RuntimeError("close-B")
    close_count = 0

    class FailingCloseLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal close_count
            close_count += 1
            raise close_error

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", FailingCloseLLM)

    settings = _composition_settings(tmp_path)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="close-B"):
            async with application_context(settings) as application:
                snapshot = await application.get_snapshot()
                assert snapshot.stage is Stage.SETUP
    assert close_count == 2
    cleanup_messages = [
        record.getMessage()
        for record in caplog.records
        if "runtime cleanup failed" in record.getMessage()
    ]
    assert cleanup_messages
    assert any("llm.aclose" in message for message in cleanup_messages)
    assert all("close-B" not in message for message in cleanup_messages)


async def test_first_close_failure_still_closes_second(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_results: list[str] = []
    constructed = 0

    class OrderedCloseLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            nonlocal constructed
            super().__init__([])
            self._index = constructed
            constructed += 1

        async def aclose(self) -> None:
            if self._index == 0:
                close_results.append("session")
                raise RuntimeError("session-close-failed")
            close_results.append("supervisor")

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", OrderedCloseLLM)
    settings = _composition_settings(tmp_path)
    with pytest.raises(RuntimeError, match="session-close-failed"):
        async with application_context(settings) as application:
            await application.get_snapshot()
    assert close_results == ["session", "supervisor"]


async def test_first_cleanup_failure_wins_when_both_cleanup_steps_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    shutdown_error = RuntimeError("shutdown-B")
    close_error = RuntimeError("close-C")

    class FailingCloseLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            raise close_error

    async def failing_shutdown(
        self: TherapyApplication, *, timeout_seconds: float
    ) -> None:
        del timeout_seconds
        raise shutdown_error

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", FailingCloseLLM)
    monkeypatch.setattr(TherapyApplication, "shutdown", failing_shutdown)

    settings = _composition_settings(tmp_path)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="shutdown-B"):
            async with application_context(settings) as application:
                snapshot = await application.get_snapshot()
                assert snapshot.stage is Stage.SETUP
    cleanup_logs = [
        record.getMessage()
        for record in caplog.records
        if "runtime cleanup failed" in record.getMessage()
    ]
    assert len(cleanup_logs) == 3
    assert all("shutdown-B" not in message for message in cleanup_logs)
    assert all("close-C" not in message for message in cleanup_logs)


async def test_context_cancellation_remains_primary_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    settings = _composition_settings(tmp_path)

    async def run_context() -> None:
        async with application_context(settings) as application:
            await application.get_snapshot()
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_context()


async def test_cancel_during_first_llm_close_still_closes_second(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "debug-run"
    first_close_entered = asyncio.Event()
    allow_first_close = asyncio.Event()
    close_order: list[str] = []
    constructed = 0

    class HoldingCloseLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            nonlocal constructed
            super().__init__([])
            self._index = constructed
            constructed += 1

        async def aclose(self) -> None:
            if self._index == 0:
                close_order.append("session-start")
                first_close_entered.set()
                await allow_first_close.wait()
                close_order.append("session-done")
            else:
                close_order.append("supervisor-done")

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", HoldingCloseLLM)
    settings = _composition_settings(tmp_path, debug_run_dir=run_dir)

    async def run_context() -> None:
        async with application_context(settings) as application:
            await application.get_snapshot()

    task = asyncio.create_task(run_context())
    await asyncio.wait_for(first_close_entered.wait(), timeout=2.0)
    task.cancel()
    await asyncio.sleep(0)

    assert not task.done()
    assert close_order == ["session-start"]

    allow_first_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert close_order == ["session-start", "session-done", "supervisor-done"]
    assert (run_dir / "db_snapshot.sqlite").exists()


async def test_cancel_during_blocked_llm_close_still_finishes_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_entered = asyncio.Event()
    allow_close = asyncio.Event()
    closed_count = 0

    class HoldingCloseLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal closed_count
            close_entered.set()
            await allow_close.wait()
            closed_count += 1

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", HoldingCloseLLM)
    settings = _composition_settings(tmp_path)

    async def run_context() -> None:
        async with application_context(settings) as application:
            await application.get_snapshot()

    task = asyncio.create_task(run_context())
    await asyncio.wait_for(close_entered.wait(), timeout=2.0)
    task.cancel()
    await asyncio.sleep(0)

    assert not task.done()
    assert closed_count == 0

    allow_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed_count == 2


async def test_drained_llm_close_failure_keeps_cancellation_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_dir = tmp_path / "debug-run"
    close_entered = asyncio.Event()
    allow_close = asyncio.Event()
    close_error = RuntimeError("close-while-draining")
    constructed = 0
    closed_indexes: list[int] = []

    class FailingHeldCloseLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            nonlocal constructed
            super().__init__([])
            self._index = constructed
            constructed += 1

        async def aclose(self) -> None:
            closed_indexes.append(self._index)
            if self._index == 0:
                close_entered.set()
                await allow_close.wait()
                raise close_error

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", FailingHeldCloseLLM)
    settings = _composition_settings(tmp_path, debug_run_dir=run_dir)

    async def run_context() -> None:
        async with application_context(settings) as application:
            await application.get_snapshot()

    task = asyncio.create_task(run_context())
    await asyncio.wait_for(close_entered.wait(), timeout=2.0)
    task.cancel()
    await asyncio.sleep(0)

    assert not task.done()

    with caplog.at_level(logging.WARNING):
        allow_close.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert closed_indexes == [0, 1]
    cleanup_messages = [
        record.getMessage()
        for record in caplog.records
        if "runtime cleanup failed" in record.getMessage()
    ]
    assert any("llm.aclose" in message for message in cleanup_messages)
    assert all("close-while-draining" not in message for message in cleanup_messages)

    events = _load_trace(run_dir)
    drained_errors = [
        event
        for event in events
        if event["kind"] == "runtime.error"
        and event["data"].get("phase") == "cleanup:session_llm.aclose"
        and event["data"].get("error_type") == "RuntimeError"
    ]
    assert drained_errors
    end = next(event for event in events if event["kind"] == "diagnostics.end")
    assert end["data"]["status"] == "failed"
    assert end["data"]["error_type"] == "CancelledError"


async def test_second_adapter_construction_failure_closes_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[object] = []
    closed: list[object] = []

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            if len(constructed) == 1:
                raise RuntimeError("supervisor construction failed")
            super().__init__([])
            constructed.append(self)

        async def aclose(self) -> None:
            closed.append(self)

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    settings = _composition_settings(tmp_path)
    with pytest.raises(RuntimeError, match="supervisor construction failed"):
        async with application_context(settings):
            pass
    assert len(constructed) == 1
    assert closed == constructed
