"""Post-session processor orchestration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.models import Plan
from jung.domain.session_artifacts import (
    InterventionCitation,
    PatientTurnCitation,
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
)
from jung.llm.errors import InvalidLLMOutput
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.phases.post_session.models import (
    PostSessionInput,
    PostSessionUpdateResult,
)
from jung.phases.post_session.processor import PostSessionProcessor
from jung.phases.post_session.prompts import (
    ANALYSIS_PROMPT_VERSION,
    UPDATE_PROMPT_VERSION,
)
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


def _policies(
    *,
    analysis_model: str = "fake-analysis",
    update_model: str = "fake-update",
) -> tuple[ModelPolicy, ModelPolicy]:
    return (
        ModelPolicy(
            task=LLMTask.POST_SESSION_ANALYSIS,
            model=analysis_model,
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
        ModelPolicy(
            task=LLMTask.POST_SESSION_UPDATE,
            model=update_model,
            temperature=0.0,
            timeout_seconds=60.0,
            structured_output_mode=StructuredOutputMode.PROMPT,
        ),
    )


def _briefing() -> SessionBriefing:
    return SessionBriefing(
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
        selected_style=load_styles()["cbt"],
    )


def test_llm_schemas_omit_generation_provenance() -> None:
    analysis_schema = SessionAnalysis.model_json_schema()
    update_schema = PostSessionUpdateResult.model_json_schema()
    assert "generation" not in analysis_schema.get("properties", {})
    assert "generation" not in update_schema.get("properties", {})
    assert "analysis_model" not in update_schema.get("properties", {})
    assert "update_model" not in update_schema.get("properties", {})


async def test_empty_transcript_makes_zero_llm_calls() -> None:
    gateway = FakeLLM([])
    analysis_policy, update_policy = _policies()
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    result = await processor.process(_input(()))
    assert "without conversational content" in result.review.analysis.summary
    assert result.review.briefing.continuity_points == ()
    assert result.review.plan_recommendation == PlanPatch()
    assert result.review.generation is None
    assert result.review.analysis.patient_turn_citations == ()
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
    summary = result.review.analysis.summary
    assert "before a therapist response occurred" in summary
    assert latest not in summary
    assert "Earlier concern." not in summary
    assert result.review.briefing.continuity_points == ()
    assert result.review.briefing.narrative_handoff == summary
    assert "Revisit the patient's final message" in (
        result.review.briefing.recommended_opening_focus
    )
    assert result.review.generation is None
    assert result.review.analysis.patient_turn_citations == ()
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
    assert "no patient response occurred" in result.review.analysis.summary
    assert result.review.briefing.continuity_points == ()
    assert result.review.plan_recommendation == PlanPatch()
    assert result.review.generation is None
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
                output_type=SessionAnalysis,
                response=SessionAnalysis(
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
                    session_briefing=_briefing(),
                    plan_patch=PlanPatch(current_progress="some progress"),
                ),
                message_fragments=(
                    therapist_content,
                    "I slept badly.",
                ),
            ),
        ]
    )
    analysis_policy, update_policy = _policies(
        analysis_model="analysis-model-a",
        update_model="update-model-b",
    )
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    result = await processor.process(_input(transcript))
    assert result.review.analysis.summary == "Patient explored sleep difficulties."
    assert result.review.briefing.narrative_handoff == "Session focused on sleep."
    assert result.review.plan_recommendation.current_progress == "some progress"
    assert tuple(
        citation.patient_sequence
        for citation in result.review.analysis.patient_turn_citations
    ) == (1,)
    generation = result.review.generation
    assert generation is not None
    assert generation.analysis_model == "analysis-model-a"
    assert generation.update_model == "update-model-b"
    assert generation.analysis_prompt_version == ANALYSIS_PROMPT_VERSION
    assert generation.update_prompt_version == UPDATE_PROMPT_VERSION
    gateway.assert_exhausted()


async def test_post_session_processor_records_differing_analysis_and_update_models() -> (
    None
):
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysis,
                response=SessionAnalysis(
                    summary="Patient explored sleep difficulties.",
                    key_themes=("sleep",),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionUpdateResult,
                response=PostSessionUpdateResult(
                    session_briefing=_briefing(),
                    plan_patch=PlanPatch(),
                ),
            ),
        ]
    )
    analysis_policy, update_policy = _policies(
        analysis_model="model-analysis",
        update_model="model-update",
    )
    processor = PostSessionProcessor(
        gateway,
        analysis_policy=analysis_policy,
        update_policy=update_policy,
    )
    result = await processor.process(_input(_conversational_transcript()))
    generation = result.review.generation
    assert generation is not None
    assert generation.analysis_model == "model-analysis"
    assert generation.update_model == "model-update"
    assert generation.analysis_model != generation.update_model
    gateway.assert_exhausted()


async def test_post_session_processor_rejects_invalid_plan_patch() -> None:
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.POST_SESSION_ANALYSIS,
                output_type=SessionAnalysis,
                response=SessionAnalysis(
                    summary="Patient explored sleep difficulties.",
                    key_themes=("sleep",),
                ),
            ),
            StructuredExpectation(
                task=LLMTask.POST_SESSION_UPDATE,
                output_type=PostSessionUpdateResult,
                response=PostSessionUpdateResult(
                    session_briefing=_briefing(),
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
                output_type=SessionAnalysis,
                response=SessionAnalysis(
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
                output_type=SessionAnalysis,
                response=SessionAnalysis(
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
