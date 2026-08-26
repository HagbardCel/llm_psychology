"""Intake processor tests with FakeLLM."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.domain.models import Profile
from jung.llm.gateway import LLMTask, ModelPolicy, StructuredOutputMode
from jung.phases.intake.completion import MAX_INTAKE_PATIENT_TURNS
from jung.phases.intake.extraction import (
    ExtractedIntakeEvidence,
    IntakeEvidenceField,
    IntakeExtraction,
)
from jung.phases.intake.merge import IntakePatchMergeResult
from jung.phases.intake.models import (
    GoalsRecord,
    IntakeEvidence,
    IntakeRecord,
    IntakeTurnInput,
    PresentingProblemRecord,
    SafetyRecord,
    TimeCourseRecord,
)
from jung.phases.intake.processor import IntakeProcessor
from jung.phases.transcript import TranscriptTurn
from tests.support.fake_llm import FakeLLM, StreamExpectation, StructuredExpectation


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


def _user_turn(content: str, *, sequence: int = 1) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=sequence,
        role="user",
        content=content,
    )


def _addressed(value: str, quote: str, *, sequence: int = 1) -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=quote,
        source_role="user",
        source_message_sequence=sequence,
        direct_ask=True,
    )


def _hard_addressed_missing_soft() -> IntakeRecord:
    quote = "addressed earlier"
    return IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=_addressed("anxiety", quote),
            functional_impairment=_addressed("work", quote),
            time_course=TimeCourseRecord(
                duration_or_onset=_addressed("months", quote),
            ),
        ),
        safety=SafetyRecord(
            self_harm=_addressed("none", quote),
            harm_to_others=_addressed("none", quote),
            medical_urgency=_addressed("none", quote),
        ),
        goals=GoalsRecord(preferred_start=_addressed("sleep", quote)),
    )


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


async def test_prepare_turn_applies_extraction_and_streams_response() -> None:
    patch_policy, response_policy = _policies()
    user_turn = _user_turn("I feel anxious every morning")
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeExtraction,
                response=IntakeExtraction(
                    evidence=(
                        ExtractedIntakeEvidence(
                            field=IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                            value="anxiety",
                            evidence_quote="I feel anxious every morning",
                        ),
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
    assert plan.merge_diagnostics is not None
    assert plan.merge_diagnostics.status == "applied"
    chunks = [chunk async for chunk in processor.stream_response(plan)]
    assert chunks == ["Tell me more."]
    gateway.assert_exhausted()


async def test_empty_extraction_is_empty_patch() -> None:
    patch_policy, response_policy = _policies()
    user_turn = _user_turn("hello")
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeExtraction,
                response=IntakeExtraction(),
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
    assert plan.merge_diagnostics is not None
    assert plan.merge_diagnostics.status == "empty_patch"
    assert plan.merge_diagnostics.raw_evidence_count == 0
    assert plan.max_turn_completion_blocked is False


async def test_unasked_unknown_is_empty_after_validation() -> None:
    patch_policy, response_policy = _policies()
    user_turn = _user_turn("I'm not sure about harm")
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeExtraction,
                response=IntakeExtraction(
                    evidence=(
                        ExtractedIntakeEvidence(
                            field=IntakeEvidenceField.SAFETY_SELF_HARM,
                            evidence_quote="I'm not sure about harm",
                            response_status="unknown",
                        ),
                    )
                ),
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
    diagnostics = plan.merge_diagnostics
    assert diagnostics is not None
    assert diagnostics.status == "empty_after_validation"
    assert diagnostics.raw_evidence_count == 1
    assert diagnostics.retained_evidence_count == 0
    assert diagnostics.dropped_evidence_count == 1
    assert diagnostics.drop_reasons[0]["reason"] == "unasked_noninformative"
    assert diagnostics.applied is False


async def test_mixed_candidates_applied_with_combined_counts() -> None:
    patch_policy, response_policy = _policies()
    user_turn = _user_turn("anxious; not sure about harm")
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeExtraction,
                response=IntakeExtraction(
                    evidence=(
                        ExtractedIntakeEvidence(
                            field=IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                            value="anxiety",
                            evidence_quote="anxious",
                        ),
                        ExtractedIntakeEvidence(
                            field=IntakeEvidenceField.SAFETY_SELF_HARM,
                            evidence_quote="not sure about harm",
                            response_status="unknown",
                        ),
                    )
                ),
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
    diagnostics = plan.merge_diagnostics
    assert diagnostics is not None
    assert diagnostics.status == "applied"
    assert diagnostics.raw_evidence_count == 2
    assert diagnostics.retained_evidence_count == 1
    assert diagnostics.dropped_evidence_count == 1
    assert diagnostics.applied is True
    assert diagnostics.record_changed is True


async def test_quote_invalid_after_materialization_is_empty_after_validation() -> None:
    patch_policy, response_policy = _policies()
    user_turn = _user_turn("I feel anxious")
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeExtraction,
                response=IntakeExtraction(
                    evidence=(
                        ExtractedIntakeEvidence(
                            field=IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                            value="anxiety",
                            evidence_quote="not in the message",
                        ),
                    )
                ),
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
    diagnostics = plan.merge_diagnostics
    assert diagnostics is not None
    assert diagnostics.status == "empty_after_validation"
    assert diagnostics.drop_reasons[0]["reason"] == "quote_not_found_in_message"


async def test_all_dropped_at_max_turns_blocks_completion() -> None:
    patch_policy, response_policy = _policies()
    record = _hard_addressed_missing_soft()
    turns = tuple(
        _user_turn(f"turn {i}", sequence=i)
        for i in range(1, MAX_INTAKE_PATIENT_TURNS + 1)
    )
    latest = turns[-1]
    # next_required_item on this record is coping_attempts; sleep unknown is unasked.
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeExtraction,
                response=IntakeExtraction(
                    evidence=(
                        ExtractedIntakeEvidence(
                            field=IntakeEvidenceField.PRESENTING_PROBLEM_SLEEP_IMPACT,
                            evidence_quote=latest.content,
                            response_status="unknown",
                        ),
                    )
                ),
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
            current_record=record,
            transcript=turns,
            latest_user_message=latest.content,
            patient_turn_count=MAX_INTAKE_PATIENT_TURNS,
        )
    )
    assert plan.merge_diagnostics is not None
    assert plan.merge_diagnostics.status == "empty_after_validation"
    assert plan.max_turn_completion_blocked is True
    assert plan.completeness_complete is False


async def test_merge_failure_status_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_policy, response_policy = _policies()
    user_turn = _user_turn("I feel anxious")

    def fail_merge(*_args: object, **_kwargs: object) -> IntakePatchMergeResult:
        return IntakePatchMergeResult(
            record=IntakeRecord(),
            status="merge_failure",
            applied=False,
            raw_evidence_count=1,
            retained_evidence_count=0,
            dropped_evidence_count=1,
            record_changed=False,
            error_message="boom",
            error_code="RuntimeError",
        )

    monkeypatch.setattr(
        "jung.phases.intake.processor.merge_intake_record_patch_with_diagnostics",
        fail_merge,
    )
    gateway = FakeLLM(
        [
            StructuredExpectation(
                task=LLMTask.INTAKE_PATCH,
                output_type=IntakeExtraction,
                response=IntakeExtraction(
                    evidence=(
                        ExtractedIntakeEvidence(
                            field=IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                            value="anxiety",
                            evidence_quote="I feel anxious",
                        ),
                    )
                ),
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
    assert plan.merge_diagnostics is not None
    assert plan.merge_diagnostics.status == "merge_failure"
