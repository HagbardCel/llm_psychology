"""Post-session processor and merge tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jung.domain.models import Plan, Profile
from jung.llm.errors import InvalidLLMOutput
from jung.llm.fake import FailureExpectation, FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.phases.post_session.merge import merge_plan_content, plan_patch_is_noop
from jung.phases.post_session.models import (
    InterventionEvidence,
    PatientStatementCitation,
    PlanPatch,
    PostSessionInput,
    PostSessionUpdateResult,
    SessionAnalysisResult,
    SessionBriefingDraft,
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


def _policies() -> tuple[ModelPolicy, ModelPolicy]:
    return (
        ModelPolicy(
            task=LLMTask.POST_SESSION_ANALYSIS,
            model="fake",
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
        ModelPolicy(
            task=LLMTask.POST_SESSION_UPDATE,
            model="fake",
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
    )


def _briefing_draft() -> SessionBriefingDraft:
    return SessionBriefingDraft(
        narrative_handoff="Session focused on sleep.",
        recommended_opening_focus="sleep routine",
    )


def _conversational_transcript() -> tuple[TranscriptTurn, ...]:
    return (
        TranscriptTurn(
            message_id=uuid4(),
            sequence=1,
            role="user",
            content="I slept badly.",
        ),
        TranscriptTurn(
            message_id=uuid4(),
            sequence=2,
            role="assistant",
            content="What feels unclear about your sleep?",
        ),
        TranscriptTurn(
            message_id=uuid4(),
            sequence=3,
            role="user",
            content="I kept waking up.",
        ),
    )


def _input(
    transcript: tuple[TranscriptTurn, ...],
) -> PostSessionInput:
    return PostSessionInput(
        transcript=transcript,
        current_plan=_plan(),
        profile=Profile(name="Alex", primary_language="English"),
        selected_style=load_styles()["cbt"],
    )


async def test_empty_transcript_makes_zero_llm_calls() -> None:
    gateway = FakeLLM([])
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    result = await processor.process(_input(()))
    assert "without conversational content" in result.session_summary
    assert result.session_briefing.intervention_evidence == ()
    assert result.derived_profile_patch.grounded_patient_statements == ()
    assert result.plan_patch == PlanPatch()
    gateway.assert_exhausted()


async def test_user_only_transcript_selects_latest_message() -> None:
    gateway = FakeLLM([])
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    result = await processor.process(
        _input(
            (
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=1,
                    role="user",
                    content="Earlier concern.",
                ),
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=2,
                    role="user",
                    content="Latest concern about sleep.",
                ),
            )
        )
    )
    assert "Latest concern about sleep." in result.session_summary
    assert result.session_briefing.continuity_points == ("Latest concern about sleep.",)
    assert "Earlier concern." not in result.session_summary
    assert result.derived_profile_patch.grounded_patient_statements == ()
    gateway.assert_exhausted()


async def test_assistant_only_transcript_makes_zero_llm_calls() -> None:
    gateway = FakeLLM([])
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    result = await processor.process(
        _input(
            (
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=1,
                    role="assistant",
                    content="How are you today?",
                ),
            )
        )
    )
    assert "no patient response occurred" in result.session_summary
    assert result.plan_patch == PlanPatch()
    gateway.assert_exhausted()


async def test_post_session_processor_makes_two_structured_calls() -> None:
    user_message_id = uuid4()
    transcript = (
        TranscriptTurn(
            message_id=user_message_id,
            sequence=1,
            role="user",
            content="I slept badly.",
        ),
        TranscriptTurn(
            message_id=uuid4(),
            sequence=2,
            role="assistant",
            content="What feels unclear about your sleep?",
        ),
        TranscriptTurn(
            message_id=uuid4(),
            sequence=3,
            role="user",
            content="I kept waking up.",
        ),
    )
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysisResult,
                response=SessionAnalysisResult(
                    summary="Patient explored sleep difficulties.",
                    key_themes=("sleep",),
                    intervention_evidence=(
                        InterventionEvidence(
                            intervention_description="Exploratory questioning",
                            therapist_sequence=2,
                            therapist_quote="What feels unclear about your sleep?",
                            patient_sequence=3,
                            patient_quote="I kept waking up.",
                        ),
                    ),
                    patient_statements=(
                        PatientStatementCitation(
                            patient_sequence=1,
                            patient_quote="I slept badly.",
                        ),
                    ),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionUpdateResult,
                response=PostSessionUpdateResult(
                    session_briefing=_briefing_draft(),
                    plan_patch=PlanPatch(current_progress="some progress"),
                ),
            ),
        ]
    )
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    result = await processor.process(_input(transcript))
    assert result.session_summary == "Patient explored sleep difficulties."
    assert len(result.session_briefing.intervention_evidence) == 1
    assert result.session_briefing.intervention_evidence[0].status == "responded"
    assert len(result.derived_profile_patch.grounded_patient_statements) == 1
    grounded = result.derived_profile_patch.grounded_patient_statements[0]
    assert grounded.source_message_id == user_message_id
    assert grounded.quote == "I slept badly."
    assert result.plan_patch.current_progress == "some progress"
    gateway.assert_exhausted()


async def test_post_session_processor_rejects_invalid_plan_patch() -> None:
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
                output_type=PostSessionUpdateResult,
                response=PostSessionUpdateResult(
                    session_briefing=_briefing_draft(),
                    plan_patch=PlanPatch(goals=()),
                ),
            ),
        ]
    )
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    with pytest.raises(InvalidLLMOutput):
        await processor.process(_input(_conversational_transcript()))
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


async def test_post_session_processor_skips_update_when_analysis_fails() -> None:
    gateway = FakeLLM(
        [
            FailureExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                error=InvalidLLMOutput("analysis failed"),
            ),
        ]
    )
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    with pytest.raises(InvalidLLMOutput, match="analysis failed"):
        await processor.process(_input(_conversational_transcript()))
    gateway.assert_exhausted()


async def test_invalid_analysis_evidence_raises_without_update_call() -> None:
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysisResult,
                response=SessionAnalysisResult(
                    summary="Patient explored sleep difficulties.",
                    key_themes=("sleep",),
                    intervention_evidence=(
                        InterventionEvidence(
                            intervention_description="Fabricated",
                            therapist_sequence=99,
                            therapist_quote="not in transcript",
                        ),
                    ),
                ),
            ),
        ]
    )
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    with pytest.raises(InvalidLLMOutput):
        await processor.process(_input(_conversational_transcript()))
    gateway.assert_exhausted()


async def test_post_session_processor_raises_when_update_fails() -> None:
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
            FailureExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                error=InvalidLLMOutput("update failed"),
            ),
        ]
    )
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    with pytest.raises(InvalidLLMOutput, match="update failed"):
        await processor.process(_input(_conversational_transcript()))
    gateway.assert_exhausted()
