"""Required manual smoke for real local LLM processors before Phase 3 merge."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import Plan, Profile
from jung.llm.gateway import (
    AdapterConfig,
    LLMSettings,
    LLMTask,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.llm.policies import build_model_policies
from jung.phases.assessment.models import AssessmentInput, IntakeRecord
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.post_session.models import PostSessionInput
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.therapy.processor import TherapyProcessor
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles
from tests.smoke.jung.smoke_evidence import COLLECTOR, SmokePathResult


def _required_smoke_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} must be set for Phase 3 smoke")
    return value


def _structured_mode() -> StructuredOutputMode:
    raw = os.environ.get("PHASE3_SMOKE_STRUCTURED_MODE", "json_schema")
    return StructuredOutputMode(raw)


def _adapter_config() -> AdapterConfig:
    extra_body: dict[str, object] | None = None
    raw_extra = os.environ.get("PHASE3_SMOKE_EXTRA_BODY")
    if raw_extra:
        extra_body = json.loads(raw_extra)
    return AdapterConfig(
        base_url=_required_smoke_env("PHASE3_SMOKE_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
        extra_body=extra_body,
    )


def _policies() -> dict[LLMTask, object]:
    settings = LLMSettings(
        default_model=_required_smoke_env("PHASE3_SMOKE_MODEL"),
        base_url=_required_smoke_env("PHASE3_SMOKE_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
        task_structured_modes=dict.fromkeys(LLMTask, _structured_mode()),
        task_timeouts={
            task: float(os.environ.get("PHASE3_SMOKE_TIMEOUT", "120"))
            for task in LLMTask
        },
    )
    return build_model_policies(settings)


def _plan() -> Plan:
    now = datetime.now(UTC)
    return Plan(
        id=uuid4(),
        version=1,
        selected_style="cbt",
        focus="anxiety",
        themes=["worry"],
        goals=["sleep"],
        current_progress="baseline",
        planned_interventions=["grounding"],
        revision_recommendations=[],
        created_at=now,
    )


def _correction_count(caplog: pytest.LogCaptureFixture) -> int:
    return sum(
        1
        for record in caplog.records
        if record.message.startswith("llm structured correction")
    )


@pytest.fixture(scope="session", autouse=True)
def _configure_smoke_metadata() -> None:
    if not os.environ.get("PHASE3_SMOKE_BASE_URL"):
        return
    COLLECTOR.server = _required_smoke_env("PHASE3_SMOKE_SERVER")
    COLLECTOR.base_url = _required_smoke_env("PHASE3_SMOKE_BASE_URL")
    COLLECTOR.model = _required_smoke_env("PHASE3_SMOKE_MODEL")
    COLLECTOR.structured_mode = os.environ.get(
        "PHASE3_SMOKE_STRUCTURED_MODE",
        "json_schema",
    )
    raw_extra = os.environ.get("PHASE3_SMOKE_EXTRA_BODY")
    if raw_extra:
        COLLECTOR.request_extras = json.loads(raw_extra)


@pytest.fixture
async def gateway():
    _required_smoke_env("PHASE3_SMOKE_SERVER")
    _required_smoke_env("PHASE3_SMOKE_BASE_URL")
    _required_smoke_env("PHASE3_SMOKE_MODEL")
    llm = OpenAICompatibleLLM(_adapter_config())
    yield llm
    await llm.aclose()


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_therapy_stream(gateway: OpenAICompatibleLLM) -> None:
    policies = _policies()
    processor = TherapyProcessor(
        gateway,
        response_policy=policies[LLMTask.THERAPY_RESPONSE],
    )
    started = time.perf_counter()
    first_chunk_at: float | None = None
    chunks: list[str] = []
    try:
        async for chunk in processor.stream_response(
            TherapyTurnInput(
                profile=Profile(name="Alex", primary_language="English"),
                current_plan=_plan(),
                latest_user_message="I slept poorly again.",
                selected_style=load_styles()["cbt"],
            )
        ):
            if first_chunk_at is None:
                first_chunk_at = time.perf_counter()
            chunks.append(chunk)
        assert chunks
        assert first_chunk_at is not None
        COLLECTOR.therapy = SmokePathResult(
            success=True,
            latency_seconds=time.perf_counter() - started,
            ttfc_seconds=first_chunk_at - started,
        )
    except Exception as exc:
        COLLECTOR.therapy = SmokePathResult(
            success=False,
            latency_seconds=time.perf_counter() - started,
            error_type=type(exc).__name__,
        )
        raise


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_assessment_processor(
    gateway: OpenAICompatibleLLM,
    caplog: pytest.LogCaptureFixture,
) -> None:
    policies = _policies()
    processor = AssessmentProcessor(
        gateway,
        assessment_policy=policies[LLMTask.ASSESSMENT],
    )
    started = time.perf_counter()
    try:
        with caplog.at_level(logging.INFO, logger="jung.llm.openai_compatible"):
            result = await processor.assess(
                AssessmentInput(
                    intake_record=IntakeRecord(),
                    transcript=(),
                    profile=Profile(name="Alex", primary_language="English"),
                    available_styles=tuple(load_styles().values()),
                )
            )
        assert len(result.style_recommendations) == len(load_styles())
        COLLECTOR.assessment = SmokePathResult(
            success=True,
            latency_seconds=time.perf_counter() - started,
            correction_count=_correction_count(caplog),
        )
    except Exception as exc:
        COLLECTOR.assessment = SmokePathResult(
            success=False,
            latency_seconds=time.perf_counter() - started,
            error_type=type(exc).__name__,
        )
        raise


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_post_session_processor(
    gateway: OpenAICompatibleLLM,
    caplog: pytest.LogCaptureFixture,
) -> None:
    policies = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=policies[LLMTask.POST_SESSION_ANALYSIS],
        update_policy=policies[LLMTask.POST_SESSION_UPDATE],
    )
    started = time.perf_counter()
    try:
        with caplog.at_level(logging.INFO, logger="jung.llm.openai_compatible"):
            result = await processor.process(
                PostSessionInput(
                    transcript=(
                        TranscriptTurn(
                            message_id=uuid4(),
                            sequence=1,
                            role="user",
                            content="I slept badly.",
                        ),
                    ),
                    current_plan=_plan(),
                    profile=Profile(name="Alex", primary_language="English"),
                    selected_style=load_styles()["cbt"],
                )
            )
        assert result.session_summary
        COLLECTOR.post_session = SmokePathResult(
            success=True,
            latency_seconds=time.perf_counter() - started,
            correction_count=_correction_count(caplog),
        )
    except Exception as exc:
        COLLECTOR.post_session = SmokePathResult(
            success=False,
            latency_seconds=time.perf_counter() - started,
            error_type=type(exc).__name__,
        )
        raise
