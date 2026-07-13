"""Intake processor tests with FakeLLM."""

from __future__ import annotations

from uuid import uuid4

from jung.domain.models import Profile
from jung.llm.fake import FakeLLM, StreamExpectation, StructuredExpectation
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.phases.intake.models import (
    IntakeEvidence,
    IntakeRecordPatch,
    IntakeTurnInput,
    PresentingProblemRecord,
)
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.transcript import TranscriptTurn


def _policies() -> tuple[ModelPolicy, ModelPolicy]:
    patch = ModelPolicy(
        task=LLMTask.INTAKE_PATCH,
        model="fake",
        temperature=0.0,
        timeout_seconds=30.0,
        structured_output_mode=StructuredOutputMode.PROMPT,
    )
    response = ModelPolicy(
        task=LLMTask.INTAKE_RESPONSE,
        model="fake",
        temperature=0.7,
        timeout_seconds=30.0,
    )
    return patch, response


async def test_prepare_turn_opening_skips_patch_extraction() -> None:
    patch_policy, response_policy = _policies()
    gateway = FakeLLM(
        [
            StreamExpectation(
                task=LLMTask.INTAKE_RESPONSE,
                chunks=("Welcome.",),
            )
        ]
    )
    processor = IntakeProcessor(
        gateway,
        patch_policy=patch_policy,
        response_policy=response_policy,
    )
    plan = await processor.prepare_turn(
        IntakeTurnInput(profile=Profile(name="Alex", primary_language="English"))
    )
    assert plan.record_changed is False
    assert plan.completeness_complete is False
    chunks = [chunk async for chunk in processor.stream_response(plan)]
    assert chunks == ["Welcome."]
    gateway.assert_exhausted()


async def test_prepare_turn_applies_patch_and_streams_response() -> None:
    patch_policy, response_policy = _policies()
    user_turn = TranscriptTurn(
        message_id=uuid4(),
        sequence=1,
        role="user",
        content="I feel anxious every morning",
    )
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeRecordPatch,
                response=IntakeRecordPatch(
                    presenting_problem=PresentingProblemRecord(
                        main_concern=IntakeEvidence(
                            value="anxiety",
                            evidence_quote="I feel anxious every morning",
                            source_message_sequence=1,
                            source_role="user",
                        )
                    )
                ),
            ),
            StreamExpectation(
                task=LLMTask.INTAKE_RESPONSE,
                chunks=("Tell me more.",),
            ),
        ]
    )
    processor = IntakeProcessor(
        gateway,
        patch_policy=patch_policy,
        response_policy=response_policy,
    )
    plan = await processor.prepare_turn(
        IntakeTurnInput(
            profile=Profile(name="Alex", primary_language="English"),
            transcript=(user_turn,),
            latest_user_message=user_turn.content,
            patient_turn_count=1,
        )
    )
    assert plan.record_changed is True
    assert plan.merged_record.presenting_problem.main_concern.value == "anxiety"
    chunks = [chunk async for chunk in processor.stream_response(plan)]
    assert chunks == ["Tell me more."]
    gateway.assert_exhausted()
