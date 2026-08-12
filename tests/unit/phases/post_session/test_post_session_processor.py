"""Post-session processor orchestration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.models import Plan, Profile
from jung.llm.errors import InvalidLLMOutput
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.phases.post_session.models import (
    InterventionCitation,
    PatientTurnCitation,
    PlanPatch,
    PostSessionInput,
    PostSessionUpdateResult,
    SessionAnalysisResult,
    SessionBriefingDraft,
)
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.transcript import TranscriptTurn
from jung.styles import load_styles
from tests.support.fake_llm import FailureExpectation, FakeLLM, StructuredExpectation


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
    assert result.session_briefing.continuity_points == ()
    assert result.derived_profile_patch.grounded_patient_turns == ()
    assert result.plan_patch == PlanPatch()
    gateway.assert_exhausted()


async def test_user_only_transcript_uses_generic_summary_without_message_text() -> None:
    gateway = FakeLLM([])
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    latest = "Latest concern about sleep."
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
                    content=latest,
                ),
            )
        )
    )
    assert "before a therapist response occurred" in result.session_summary
    assert latest not in result.session_summary
    assert "Earlier concern." not in result.session_summary
    assert result.session_briefing.continuity_points == ()
    assert result.session_briefing.narrative_handoff == result.session_summary
    assert "Revisit the patient's final message" in (
        result.session_briefing.recommended_opening_focus
    )
    assert result.derived_profile_patch.grounded_patient_turns == ()
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
    assert result.session_briefing.continuity_points == ()
    assert result.plan_patch == PlanPatch()
    gateway.assert_exhausted()


def test_whitespace_only_transcript_is_rejected_by_input_model() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        _input(
            (
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=1,
                    role="user",
                    content="   ",
                ),
                TranscriptTurn(
                    message_id=uuid4(),
                    sequence=2,
                    role="assistant",
                    content="ok",
                ),
            )
        )


async def test_post_session_processor_makes_two_structured_calls() -> None:
    user_message_id = uuid4()
    therapist_content = "What feels unclear about your sleep?"
    patient_content = "I kept waking up."
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
            content=therapist_content,
        ),
        TranscriptTurn(
            message_id=uuid4(),
            sequence=3,
            role="user",
            content=patient_content,
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
                    intervention_citations=(
                        InterventionCitation(
                            intervention_description="Exploratory questioning",
                            therapist_sequence=2,
                            patient_sequence=3,
                        ),
                    ),
                    patient_turn_citations=(PatientTurnCitation(patient_sequence=1),),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionUpdateResult,
                response=PostSessionUpdateResult(
                    session_briefing=_briefing_draft(),
                    plan_patch=PlanPatch(current_progress="some progress"),
                ),
                message_fragments=(
                    therapist_content,
                    "I slept badly.",
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
    evidence = result.session_briefing.intervention_evidence[0]
    assert evidence.status == "response_cited"
    assert evidence.therapist_content == therapist_content
    assert evidence.patient_content == patient_content
    assert len(result.derived_profile_patch.grounded_patient_turns) == 1
    grounded = result.derived_profile_patch.grounded_patient_turns[0]
    assert grounded.source_message_id == user_message_id
    assert grounded.content == "I slept badly."
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


async def test_invalid_analysis_citations_raise_without_update_call() -> None:
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysisResult,
                response=SessionAnalysisResult(
                    summary="Patient explored sleep difficulties.",
                    key_themes=("sleep",),
                    intervention_citations=(
                        InterventionCitation(
                            intervention_description="Fabricated",
                            therapist_sequence=99,
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
