"""Post-session processor and merge tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import Plan, Profile
from jung.llm.fake import FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.phases.post_session.merge import merge_plan_content, plan_patch_is_noop
from jung.phases.post_session.models import (
    DerivedProfilePatch,
    PlanPatch,
    PostSessionInput,
    PostSessionResult,
    SessionAnalysisResult,
    SessionBriefing,
)
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles


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


def _briefing() -> SessionBriefing:
    return SessionBriefing(
        narrative_handoff="Session focused on sleep.",
        recommended_opening_focus="sleep routine",
    )


@pytest.mark.asyncio
async def test_post_session_processor_makes_two_structured_calls() -> None:
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysisResult,
                response=SessionAnalysisResult(
                    summary="Patient explored sleep difficulties.",
                    key_themes=("sleep",),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionResult,
                response=PostSessionResult(
                    session_summary="Sleep remained difficult.",
                    session_briefing=_briefing(),
                    derived_profile_patch=DerivedProfilePatch(
                        observations=("reports poor sleep",)
                    ),
                    plan_patch=PlanPatch(current_progress="some progress"),
                ),
            ),
        ]
    )
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=ModelPolicy(
            task=LLMTask.POST_SESSION_ANALYSIS,
            model="fake",
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
        update_policy=ModelPolicy(
            task=LLMTask.POST_SESSION_UPDATE,
            model="fake",
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
    )
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
    assert result.session_summary == "Sleep remained difficult."
    gateway.assert_exhausted()


def test_plan_patch_noop_and_revision_merge() -> None:
    plan = _plan()
    noop_patch = PlanPatch()
    assert plan_patch_is_noop(plan, noop_patch) is True
    assert merge_plan_content(plan, noop_patch) is None

    changed = merge_plan_content(
        plan,
        PlanPatch(current_progress="improved sleep hygiene"),
    )
    assert changed is not None
    assert changed.current_progress == "improved sleep hygiene"
