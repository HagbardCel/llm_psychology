"""Composition-root smoke tests for TherapyApplication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jung.composition import application_context
from jung.config import ApplicationSettings, load_application_settings
from jung.domain.models import Stage
from jung.llm.fake import FakeLLM
from jung.llm.gateway import AdapterConfig, LLMSettings, LLMTask
from jung.llm.structured import UnsupportedStrictSchema
from jung.phases.intake.models import IntakeRecordPatch

pytestmark = pytest.mark.asyncio


def failing_load_styles() -> None:
    raise RuntimeError("boom")


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
    settings = ApplicationSettings(
        database_path=tmp_path / "composition.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        shutdown_timeout_seconds=2.0,
    )
    async with application_context(settings) as runtime:
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.stage is Stage.SETUP
        assert runtime.events is not None
        assert runtime.supervisor is not None
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
    settings = ApplicationSettings(
        database_path=tmp_path / "composition-invalid.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        shutdown_timeout_seconds=2.0,
    )
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
    settings = ApplicationSettings(
        database_path=tmp_path / "composition-load-styles.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        shutdown_timeout_seconds=2.0,
    )
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
    settings = ApplicationSettings(
        database_path=tmp_path / "composition-recover.db",
        llm=LLMSettings(
            default_model="fake",
            base_url="http://fake.test",
            api_key="fake",
        ),
        shutdown_timeout_seconds=2.0,
    )
    with pytest.raises(ExceptionGroup) as exc_info:
        async with application_context(settings):
            pass
    assert closed is True
    assert len(exc_info.value.exceptions) == 1
    assert isinstance(exc_info.value.exceptions[0], RuntimeError)
    assert str(exc_info.value.exceptions[0]) == "recover failed"


async def test_application_context_wires_loaded_llm_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_config: list[AdapterConfig] = []
    tracing_calls: list[tuple[object, bool]] = []

    class RecordingTracingGateway:
        def __init__(self, llm: object, *, log_prompt_previews: bool) -> None:
            tracing_calls.append((llm, log_prompt_previews))
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
    monkeypatch.setattr("jung.composition.TracingLLMGateway", RecordingTracingGateway)

    settings = load_application_settings(
        {
            "JUNG_ENABLE_LLM_TRACING": "true",
            "JUNG_LOG_PROMPT_PREVIEWS": "true",
            "JUNG_LLM_DEFAULT_HEADERS_JSON": json.dumps(
                {"X-Test-Header": "value"},
            ),
            "JUNG_LLM_EXTRA_BODY_JSON": json.dumps({"global_flag": True}),
            "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                {
                    "therapy_response": {
                        "extra_body": {"task_flag": False},
                    }
                }
            ),
        },
        database_path=tmp_path / "wired.db",
    )

    async with application_context(settings) as runtime:
        raw_llm = runtime.llm
        snapshot = await runtime.application.get_snapshot()
        assert snapshot.stage is Stage.SETUP

    assert len(captured_config) == 1
    config = captured_config[0]
    assert config.default_headers == {"X-Test-Header": "value"}
    assert config.extra_body == {"global_flag": True}
    assert config.task_extra_body == {LLMTask.THERAPY_RESPONSE: {"task_flag": False}}
    assert len(tracing_calls) == 1
    assert tracing_calls[0][0] is raw_llm
    assert tracing_calls[0][1] is True


async def test_application_context_rejects_forbidden_extra_body_before_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_openai(*args: object, **kwargs: object) -> None:
        raise AssertionError("AsyncOpenAI must not be constructed")

    monkeypatch.setattr("jung.llm.openai_compatible.AsyncOpenAI", fail_openai)

    settings = load_application_settings(
        {
            "JUNG_LLM_EXTRA_BODY_JSON": json.dumps({"model": "override"}),
        },
        database_path=tmp_path / "forbidden.db",
    )

    with pytest.raises(
        ValueError, match="extra_body cannot override adapter-owned fields"
    ):
        async with application_context(settings):
            pass
