"""Composition-root smoke tests for TherapyApplication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jung.composition import application_context
from jung.domain.models import Stage
from jung.llm.fake import FakeLLM
from jung.llm.gateway import AdapterConfig, LLMTask
from jung.llm.structured import UnsupportedStrictSchema
from jung.phases.intake.models import IntakeRecordPatch
from tests.support.settings import make_test_settings

pytestmark = pytest.mark.asyncio


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
    async with application_context(settings) as runtime:
        snapshot = await runtime.application.get_snapshot()
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

    async with application_context(settings) as runtime:
        raw_llm = runtime.llm
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.stage is Stage.SETUP
        assert not hasattr(runtime, "recorder")

    assert len(captured_config) == 1
    config = captured_config[0]
    assert config.default_headers == {"X-Test-Header": "value"}
    assert config.extra_body == {"global_flag": True}
    assert config.task_extra_body == {LLMTask.THERAPY_RESPONSE: {"task_flag": False}}
    assert len(observed_calls) == 1
    assert observed_calls[0][0] is raw_llm
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
