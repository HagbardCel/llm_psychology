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
from jung.llm.fake import FakeLLM
from jung.llm.gateway import AdapterConfig, LLMTask
from jung.llm.structured import UnsupportedStrictSchema
from jung.phases.intake.models import IntakeRecordPatch
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
    closed = False

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    settings = _composition_settings(tmp_path)
    async with application_context(settings) as application:
        snapshot = await application.get_snapshot()
        assert snapshot.stage is Stage.SETUP
    assert closed is True


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
    closed = False

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    monkeypatch.setattr("jung.composition.load_styles", failing_load_styles)
    settings = _composition_settings(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        async with application_context(settings):
            pass
    assert closed is True


async def test_application_context_closes_llm_when_recover_on_startup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = False

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

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
    assert closed is True


async def test_application_context_wires_loaded_llm_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_config: list[AdapterConfig] = []
    captured_llms: list[object] = []
    observed_calls: list[tuple[object, bool, object | None]] = []

    class RecordingObservedGateway:
        def __init__(
            self,
            llm: object,
            *,
            log_metadata: bool = False,
            recorder: object | None = None,
        ) -> None:
            observed_calls.append((llm, log_metadata, recorder))
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
                }
            }
        ),
    )

    async with application_context(settings) as application:
        snapshot = await application.get_snapshot()
        assert snapshot.stage is Stage.SETUP

    assert len(captured_config) == 1
    config = captured_config[0]
    assert config.default_headers == {"X-Test-Header": "value"}
    assert config.extra_body == {"global_flag": True}
    assert config.task_extra_body == {LLMTask.THERAPY_RESPONSE: {"task_flag": False}}
    assert len(observed_calls) == 1
    assert observed_calls[0][0] is captured_llms[0]
    assert observed_calls[0][1] is True
    assert observed_calls[0][2] is None


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
    llm_closed = False
    shutdown_error = RuntimeError("shutdown-B")

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal llm_closed
            llm_closed = True

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
    assert llm_closed is True
    assert any(
        "runtime cleanup failed" in record.message
        and "application.shutdown" in record.message
        for record in caplog.records
    )


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
        "runtime cleanup failed" in record.message
        and "application.shutdown" in record.message
        for record in caplog.records
    )
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

    class FailingCloseLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            raise close_error

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", FailingCloseLLM)

    settings = _composition_settings(tmp_path)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="close-B"):
            async with application_context(settings) as application:
                snapshot = await application.get_snapshot()
                assert snapshot.stage is Stage.SETUP
    assert any(
        "runtime cleanup failed" in record.message and "llm.aclose" in record.message
        for record in caplog.records
    )


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
        record.message
        for record in caplog.records
        if "runtime cleanup failed" in record.message
    ]
    assert len(cleanup_logs) == 2


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
