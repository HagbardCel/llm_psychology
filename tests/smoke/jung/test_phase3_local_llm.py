"""Optional manual smoke for real local LLM schemas."""

from __future__ import annotations

import os

import pytest

from jung.llm.gateway import (
    AdapterConfig,
    ChatMessage,
    ChatRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.phases.assessment.models import AssessmentResult
from jung.phases.post_session.models import PostSessionResult
from jung.styles import load_styles


def _policy(task: LLMTask) -> ModelPolicy:
    return ModelPolicy(
        task=task,
        model=os.environ.get("PHASE3_SMOKE_MODEL", "local-model"),
        temperature=0.1,
        timeout_seconds=float(os.environ.get("PHASE3_SMOKE_TIMEOUT", "120")),
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
    )


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_assessment_schema() -> None:
    base_url = os.environ.get("PHASE3_SMOKE_BASE_URL")
    if not base_url:
        pytest.skip("PHASE3_SMOKE_BASE_URL not set")
    gateway = OpenAICompatibleLLM(
        AdapterConfig(base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "not-needed"))
    )
    styles = load_styles()
    result = await gateway.generate_structured(
        [
            ChatMessage(role=ChatRole.SYSTEM, content="Return assessment JSON only."),
            ChatMessage(
                role=ChatRole.USER,
                content=f"Styles: {', '.join(styles)}. Intake summary: mild anxiety.",
            ),
        ],
        AssessmentResult,
        _policy(LLMTask.ASSESSMENT),
    )
    assert result.style_recommendations


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_smoke_post_session_schema() -> None:
    base_url = os.environ.get("PHASE3_SMOKE_BASE_URL")
    if not base_url:
        pytest.skip("PHASE3_SMOKE_BASE_URL not set")
    gateway = OpenAICompatibleLLM(
        AdapterConfig(base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "not-needed"))
    )
    result = await gateway.generate_structured(
        [
            ChatMessage(role=ChatRole.SYSTEM, content="Return post-session JSON only."),
            ChatMessage(role=ChatRole.USER, content="Transcript: patient discussed worry."),
        ],
        PostSessionResult,
        _policy(LLMTask.POST_SESSION_UPDATE),
    )
    assert result.session_summary
