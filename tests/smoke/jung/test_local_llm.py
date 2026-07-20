"""Required manual smoke for real local LLM processors."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from jung.domain.models import Plan, Profile
from jung.llm.gateway import (
    AdapterConfig,
    LLMSettings,
    LLMTask,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.llm.policies import build_model_policies
from jung.llm.tracing import TracingLLMGateway
from jung.phases.assessment.models import AssessmentInput, IntakeRecord
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.post_session.models import PostSessionInput
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.therapy.processor import TherapyProcessor
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles
from tests.smoke.jung.smoke_env import (
    effective_completion_cap_labels,
    parse_completion_caps,
    parse_smoke_extra_body,
    smoke_log_prompt_previews,
    smoke_path_budget_seconds,
    smoke_request_timeout_seconds,
    smoke_strict_acceptance,
)
from tests.smoke.jung.smoke_evidence import COLLECTOR
from tests.smoke.jung.smoke_gateway import SmokeObservingGateway
from tests.smoke.jung.smoke_path import SmokeOperationResult, run_smoke_path
from tests.smoke.jung.smoke_recorder import SmokeAttemptRecorder


def _required_smoke_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} must be set for local-model smoke")
    return value


def _structured_mode() -> StructuredOutputMode:
    raw = os.environ.get("LOCAL_LLM_SMOKE_STRUCTURED_MODE", "json_schema")
    return StructuredOutputMode(raw)


@pytest.fixture(scope="session")
def smoke_extra_body() -> dict[str, object] | None:
    return parse_smoke_extra_body(os.environ.get("LOCAL_LLM_SMOKE_EXTRA_BODY"))


def _policies() -> dict[LLMTask, object]:
    completion_caps = parse_completion_caps(
        os.environ.get("LOCAL_LLM_SMOKE_MAX_COMPLETION_TOKENS")
    )
    COLLECTOR.effective_completion_caps = effective_completion_cap_labels(
        completion_caps
    )
    request_timeout = smoke_request_timeout_seconds()
    COLLECTOR.request_timeout_seconds = request_timeout
    settings = LLMSettings(
        default_model=_required_smoke_env("LOCAL_LLM_SMOKE_MODEL"),
        base_url=_required_smoke_env("LOCAL_LLM_SMOKE_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
        task_structured_modes=dict.fromkeys(LLMTask, _structured_mode()),
        task_timeouts=dict.fromkeys(LLMTask, request_timeout),
        task_max_completion_tokens=completion_caps or None,
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


@pytest.fixture(scope="session", autouse=True)
def configure_smoke_metadata(
    smoke_extra_body: dict[str, object] | None,
) -> None:
    if not os.environ.get("LOCAL_LLM_SMOKE_BASE_URL"):
        return
    COLLECTOR.server = _required_smoke_env("LOCAL_LLM_SMOKE_SERVER")
    COLLECTOR.base_url = _required_smoke_env("LOCAL_LLM_SMOKE_BASE_URL")
    COLLECTOR.model = _required_smoke_env("LOCAL_LLM_SMOKE_MODEL")
    COLLECTOR.structured_mode = os.environ.get(
        "LOCAL_LLM_SMOKE_STRUCTURED_MODE",
        "json_schema",
    )
    COLLECTOR.request_extras = smoke_extra_body or {}
    COLLECTOR.strict_acceptance = smoke_strict_acceptance()
    COLLECTOR.path_budgets_seconds = {
        "therapy": smoke_path_budget_seconds("therapy"),
        "assessment": smoke_path_budget_seconds("assessment"),
        "post_session": smoke_path_budget_seconds("post_session"),
    }


@pytest_asyncio.fixture
async def gateway(smoke_extra_body: dict[str, object] | None):
    _required_smoke_env("LOCAL_LLM_SMOKE_SERVER")
    _required_smoke_env("LOCAL_LLM_SMOKE_BASE_URL")
    _required_smoke_env("LOCAL_LLM_SMOKE_MODEL")
    attempt_recorder = SmokeAttemptRecorder(COLLECTOR)
    config = AdapterConfig(
        base_url=_required_smoke_env("LOCAL_LLM_SMOKE_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
        extra_body=smoke_extra_body,
    )
    raw = OpenAICompatibleLLM(
        config,
        on_provider_attempt=attempt_recorder.record,
    )
    traced = TracingLLMGateway(
        raw,
        log_prompt_previews=smoke_log_prompt_previews(),
        preview_chars=300,
    )
    observed = SmokeObservingGateway(
        traced,
        collector=COLLECTOR,
    )
    yield observed
    await raw.aclose()


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_therapy_stream(gateway: SmokeObservingGateway) -> None:
    policies = _policies()
    processor = TherapyProcessor(
        gateway,
        response_policy=policies[LLMTask.THERAPY_RESPONSE],
    )

    async def operation() -> SmokeOperationResult[str]:
        started = time.perf_counter()
        first_chunk_at: float | None = None
        chunks: list[str] = []
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
        return SmokeOperationResult(
            value="".join(chunks),
            ttfc_seconds=first_chunk_at - started,
        )

    result = await run_smoke_path(
        collector=COLLECTOR,
        name="therapy",
        budget_seconds=smoke_path_budget_seconds("therapy"),
        operation=operation,
    )
    assert result


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_assessment_processor(gateway: SmokeObservingGateway) -> None:
    policies = _policies()
    processor = AssessmentProcessor(
        gateway,
        assessment_policy=policies[LLMTask.ASSESSMENT],
    )

    async def operation() -> SmokeOperationResult[object]:
        result = await processor.assess(
            AssessmentInput(
                intake_record=IntakeRecord(),
                transcript=(),
                profile=Profile(name="Alex", primary_language="English"),
                available_styles=tuple(load_styles().values()),
            )
        )
        assert len(result.style_recommendations) == len(load_styles())
        return SmokeOperationResult(value=result)

    await run_smoke_path(
        collector=COLLECTOR,
        name="assessment",
        budget_seconds=smoke_path_budget_seconds("assessment"),
        operation=operation,
    )


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_post_session_processor(gateway: SmokeObservingGateway) -> None:
    policies = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=policies[LLMTask.POST_SESSION_ANALYSIS],
        update_policy=policies[LLMTask.POST_SESSION_UPDATE],
    )

    async def operation() -> SmokeOperationResult[object]:
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
        return SmokeOperationResult(value=result)

    await run_smoke_path(
        collector=COLLECTOR,
        name="post_session",
        budget_seconds=smoke_path_budget_seconds("post_session"),
        operation=operation,
    )
