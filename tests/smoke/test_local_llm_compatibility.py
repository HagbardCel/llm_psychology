"""Required manual smoke for real local LLM processors."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from jung.diagnostics import sanitize_url
from jung.domain.models import Plan, Profile
from jung.domain.text import normalize_content
from jung.llm.gateway import LLMTask
from jung.llm.tracing import ObservedLLMGateway
from jung.phases.assessment.models import AssessmentInput
from jung.phases.assessment.processor import AssessmentProcessor
from jung.phases.intake.models import IntakeRecord, IntakeTurnInput
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.post_session.models import PostSessionInput
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.therapy.processor import TherapyProcessor
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles
from tests.smoke.smoke_env import (
    effective_completion_cap_labels,
    parse_completion_caps,
    parse_smoke_extra_body,
    smoke_path_budget_seconds,
    smoke_request_timeout_seconds,
    smoke_strict_acceptance,
)
from tests.smoke.smoke_evidence import COLLECTOR, ProviderAttemptCollector
from tests.smoke.smoke_path import SmokeOperationResult, run_smoke_path
from tests.support.local_llm import (
    LocalModelClient,
    MissingLocalModelEnv,
    build_local_model_client,
    build_local_model_policies,
    resolve_local_model_environment,
)


@dataclass
class SmokeGatewayContext:
    gateway: ObservedLLMGateway
    attempts: ProviderAttemptCollector
    _client: LocalModelClient

    async def aclose(self) -> None:
        await self._client.aclose()


def _required_smoke_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} must be set for local-model smoke")
    return value


def _smoke_environment():
    try:
        return resolve_local_model_environment()
    except MissingLocalModelEnv as exc:
        pytest.fail(f"{exc.name} must be set for local-model smoke")


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
    return build_local_model_policies(
        _smoke_environment(),
        request_timeout_seconds=request_timeout,
        completion_caps=completion_caps,
    )


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
    COLLECTOR.server_version = os.environ.get("LOCAL_LLM_SMOKE_SERVER_VERSION") or None
    COLLECTOR.base_url = sanitize_url(_required_smoke_env("LOCAL_LLM_SMOKE_BASE_URL"))
    COLLECTOR.model = _required_smoke_env("LOCAL_LLM_SMOKE_MODEL")
    COLLECTOR.structured_mode = os.environ.get(
        "LOCAL_LLM_SMOKE_STRUCTURED_MODE",
        "json_schema",
    )
    COLLECTOR.request_extras_configured = bool(smoke_extra_body)
    COLLECTOR.strict_acceptance = smoke_strict_acceptance()
    COLLECTOR.path_budgets_seconds = {
        "therapy": smoke_path_budget_seconds("therapy"),
        "assessment": smoke_path_budget_seconds("assessment"),
        "post_session": smoke_path_budget_seconds("post_session"),
        "intake": smoke_path_budget_seconds("intake"),
    }


@pytest_asyncio.fixture
async def gateway(smoke_extra_body: dict[str, object] | None, diagnostic_run):
    _required_smoke_env("LOCAL_LLM_SMOKE_SERVER")
    attempts = ProviderAttemptCollector()
    client = build_local_model_client(
        _smoke_environment(),
        extra_body=smoke_extra_body,
        recorder=diagnostic_run,
        on_provider_attempt=attempts.observe,
    )
    context = SmokeGatewayContext(
        gateway=client.gateway,
        attempts=attempts,
        _client=client,
    )
    yield context
    await context.aclose()


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_therapy_stream(gateway: SmokeGatewayContext) -> None:
    policies = _policies()
    processor = TherapyProcessor(
        gateway.gateway,
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
        provider_attempts_snapshot=gateway.attempts.snapshot,
    )
    assert result


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_intake_patch(gateway: SmokeGatewayContext) -> None:
    policies = _policies()
    processor = IntakeProcessor(
        gateway.gateway,
        patch_policy=policies[LLMTask.INTAKE_PATCH],
        response_policy=policies[LLMTask.INTAKE_RESPONSE],
    )
    user_turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=1,
        role="user",
        content="I'm not sure how to describe what's wrong.",
    )

    async def operation() -> SmokeOperationResult[object]:
        plan = await processor.prepare_turn(
            IntakeTurnInput(
                profile=Profile(name="Alex", primary_language="English"),
                transcript=(user_turn,),
                latest_user_message=user_turn.content,
                patient_turn_count=1,
            )
        )
        assert plan.merge_diagnostics is not None
        assert plan.merge_diagnostics.status in {
            "applied",
            "empty_patch",
            "empty_after_validation",
        }
        assert plan.merge_diagnostics.raw_evidence_count >= 0
        assert plan.merge_diagnostics.retained_evidence_count >= 0
        assert (
            plan.merge_diagnostics.dropped_evidence_count
            == plan.merge_diagnostics.raw_evidence_count
            - plan.merge_diagnostics.retained_evidence_count
        )
        return SmokeOperationResult(value=plan)

    plan = await run_smoke_path(
        collector=COLLECTOR,
        name="intake",
        budget_seconds=smoke_path_budget_seconds("intake"),
        operation=operation,
        provider_attempts_snapshot=gateway.attempts.snapshot,
    )
    assert plan.merge_diagnostics is not None
    path = COLLECTOR.intake
    assert path is not None
    path.result_shape_valid = True


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_intake_clear_risk_denial(gateway: SmokeGatewayContext) -> None:
    """Category C smoke: clear dual safety denial must retain grounded evidence."""
    policies = _policies()
    processor = IntakeProcessor(
        gateway.gateway,
        patch_policy=policies[LLMTask.INTAKE_PATCH],
        response_policy=policies[LLMTask.INTAKE_RESPONSE],
    )
    fixture = "I am not thinking about harming myself or anyone else."
    user_turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=2,
        role="user",
        content=fixture,
    )

    async def operation() -> SmokeOperationResult[object]:
        plan = await processor.prepare_turn(
            IntakeTurnInput(
                profile=Profile(name="Alex", primary_language="English"),
                current_record=IntakeRecord(),
                transcript=(user_turn,),
                latest_user_message=user_turn.content,
                patient_turn_count=2,
            )
        )
        diagnostics = plan.merge_diagnostics
        assert diagnostics is not None
        assert diagnostics.status == "applied"
        assert diagnostics.retained_evidence_count >= 1
        assert plan.extraction_target == "risk_screen"
        assert plan.record_changed is True
        safety = plan.merged_record.safety
        assert safety.self_harm.is_present() or safety.harm_to_others.is_present()
        assert not safety.medical_urgency.is_present()
        for quote in (
            safety.self_harm.evidence_quote,
            safety.harm_to_others.evidence_quote,
        ):
            if quote:
                assert normalize_content(quote) in normalize_content(fixture)
        return SmokeOperationResult(value=plan)

    plan = await run_smoke_path(
        collector=COLLECTOR,
        name="intake_risk_denial",
        budget_seconds=smoke_path_budget_seconds("intake"),
        operation=operation,
        provider_attempts_snapshot=gateway.attempts.snapshot,
    )
    assert plan.merge_diagnostics is not None
    assert plan.merge_diagnostics.status == "applied"


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_assessment_processor(gateway: SmokeGatewayContext) -> None:
    policies = _policies()
    processor = AssessmentProcessor(
        gateway.gateway,
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
        provider_attempts_snapshot=gateway.attempts.snapshot,
    )


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_post_session_processor(gateway: SmokeGatewayContext) -> None:
    policies = _policies()
    processor = PostSessionProcessor(
        gateway.gateway,
        analysis_policy=policies[LLMTask.POST_SESSION_ANALYSIS],
        update_policy=policies[LLMTask.POST_SESSION_UPDATE],
    )
    transcript = (
        TranscriptTurn(
            message_id=uuid4(),
            sequence=1,
            role="assistant",
            content="What feels most important today?",
        ),
        TranscriptTurn(
            message_id=uuid4(),
            sequence=2,
            role="user",
            content="It is not true that everyone hates me.",
        ),
        TranscriptTurn(
            message_id=uuid4(),
            sequence=3,
            role="assistant",
            content="Thank you for saying that so clearly.",
        ),
        TranscriptTurn(
            message_id=uuid4(),
            sequence=4,
            role="user",
            content="I slept badly.",
        ),
    )

    async def operation() -> SmokeOperationResult[object]:
        result = await processor.process(
            PostSessionInput(
                transcript=transcript,
                current_plan=_plan(),
                selected_style=load_styles()["cbt"],
            )
        )
        assert result.review.analysis.summary
        return SmokeOperationResult(value=result)

    result = await run_smoke_path(
        collector=COLLECTOR,
        name="post_session",
        budget_seconds=smoke_path_budget_seconds("post_session"),
        operation=operation,
        provider_attempts_snapshot=gateway.attempts.snapshot,
    )

    # Grounding and negation behavior are owned by the hard evals
    # (`make evals`); smoke only proves the structured post-session result
    # parses against the supported schema.
    result_shape_valid = bool(
        result.review.analysis.summary and result.review.briefing.narrative_handoff
    )

    path = COLLECTOR.post_session
    assert path is not None
    path.result_shape_valid = result_shape_valid

    if smoke_strict_acceptance():
        if COLLECTOR.server_version is None:
            pytest.fail("LOCAL_LLM_SMOKE_SERVER_VERSION must be set under strict smoke")
        assert result_shape_valid
