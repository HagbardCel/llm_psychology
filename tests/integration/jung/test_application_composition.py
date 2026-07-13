"""Composition-root smoke tests for TherapyApplication."""

from __future__ import annotations

from pathlib import Path

import pytest

from jung.composition import Settings, application_context
from jung.domain.models import Stage
from jung.llm.fake import FakeLLM
from jung.llm.gateway import LLMSettings
from jung.llm.structured import UnsupportedStrictSchema
from jung.phases.intake.models import IntakeRecordPatch

pytestmark = pytest.mark.asyncio


async def test_application_context_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed = False

    class TrackingFakeLLM(FakeLLM):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__([])

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr("jung.composition.OpenAICompatibleLLM", TrackingFakeLLM)
    settings = Settings(
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
    settings = Settings(
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
