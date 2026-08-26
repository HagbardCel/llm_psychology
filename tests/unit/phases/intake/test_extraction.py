"""Unit tests for intake extraction materialization."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.phases.intake.extraction import (
    FIELD_TO_INTAKE_ITEM,
    ExtractedIntakeEvidence,
    IntakeEvidenceField,
    IntakeExtraction,
    materialize_extraction,
    prompted_item_for_extraction,
)
from jung.phases.intake.merge import merge_intake_record_patch_with_diagnostics
from jung.phases.intake.models import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
    PresentingProblemRecord,
)
from jung.phases.transcript import TranscriptTurn

EXPECTED_DESTINATIONS = {
    "presenting_problem.main_concern": "presenting_problem",
    "presenting_problem.symptoms": None,
    "presenting_problem.time_course.duration_or_onset": "duration",
    "presenting_problem.time_course.frequency": "duration",
    "presenting_problem.time_course.trajectory": None,
    "presenting_problem.time_course.triggers": None,
    "presenting_problem.sleep_impact": "sleep_impact",
    "presenting_problem.functional_impairment": "functional_impairment",
    "safety.self_harm": "risk_screen",
    "safety.harm_to_others": "risk_screen",
    "safety.medical_urgency": "risk_screen",
    "coping.attempted_strategies": "coping_attempts",
    "coping.substances_or_medication": "coping_attempts",
    "goals.therapy_goals": "goal_preference",
    "goals.preferred_start": "goal_preference",
}


def _user_turn(content: str, *, sequence: int = 1) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=sequence,
        role="user",
        content=content,
    )


def _candidate(
    field: IntakeEvidenceField,
    *,
    quote: str,
    value: str | None = None,
    response_status: str = "informative",
) -> ExtractedIntakeEvidence:
    return ExtractedIntakeEvidence(
        field=field,
        value=value,
        evidence_quote=quote,
        response_status=response_status,  # type: ignore[arg-type]
    )


def test_field_enum_matches_expected_destination_set() -> None:
    assert {member.value for member in IntakeEvidenceField} == set(
        EXPECTED_DESTINATIONS
    )
    for field in IntakeEvidenceField:
        assert FIELD_TO_INTAKE_ITEM[field] == EXPECTED_DESTINATIONS[field.value]


def test_prompted_item_first_turn_is_presenting_problem() -> None:
    assert (
        prompted_item_for_extraction(IntakeRecord(), patient_turn_count=1)
        == "presenting_problem"
    )


def test_prompted_item_later_turn_uses_next_required() -> None:
    record = IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="anxiety",
                evidence_quote="anxious",
                source_role="user",
                source_message_sequence=1,
            )
        )
    )
    assert prompted_item_for_extraction(record, patient_turn_count=2) == "risk_screen"


def test_materialize_informative_prompted_and_volunteered() -> None:
    turn = _user_turn("I feel anxious and can't sleep")
    result = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    value="anxiety",
                    quote="I feel anxious",
                ),
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_SLEEP_IMPACT,
                    value="poor sleep",
                    quote="can't sleep",
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.raw_candidate_count == 2
    assert result.materialized_candidate_count == 2
    assert result.drop_reasons == ()
    assert result.patch.presenting_problem is not None
    main = result.patch.presenting_problem.main_concern
    assert main.direct_ask is True
    assert main.source_role == "user"
    assert main.source_message_sequence == turn.sequence
    sleep = result.patch.presenting_problem.sleep_impact
    assert sleep.direct_ask is False
    assert sleep.value == "poor sleep"


def test_materialize_unknown_for_prompted_item() -> None:
    turn = _user_turn("I'm not sure")
    result = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    quote="I'm not sure",
                    response_status="unknown",
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.materialized_candidate_count == 1
    evidence = result.patch.presenting_problem.main_concern  # type: ignore[union-attr]
    assert evidence.response_status == "unknown"
    assert evidence.direct_ask is True


def test_materialize_drops_unasked_noninformative() -> None:
    turn = _user_turn("I'm not sure about risk")
    result = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.SAFETY_SELF_HARM,
                    quote="I'm not sure about risk",
                    response_status="unknown",
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.raw_candidate_count == 1
    assert result.materialized_candidate_count == 0
    assert result.drop_reasons == (
        {"field_path": "evidence[0]", "reason": "unasked_noninformative"},
    )
    assert result.patch == IntakeRecordPatch()


def test_materialize_drops_unknown_for_informative_only_field() -> None:
    turn = _user_turn("I don't know my symptoms")
    result = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_SYMPTOMS,
                    quote="I don't know my symptoms",
                    response_status="unable_to_answer",
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.drop_reasons[0]["reason"] == "unasked_noninformative"
    assert result.materialized_candidate_count == 0


def test_materialize_keeps_list_duplicates_drops_scalar_duplicates() -> None:
    turn = _user_turn("racing heart and sweating; worry is the concern; worry again")
    result = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_SYMPTOMS,
                    value="racing heart",
                    quote="racing heart",
                ),
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_SYMPTOMS,
                    value="sweating",
                    quote="sweating",
                ),
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    value="worry",
                    quote="worry is the concern",
                ),
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    value="anxiety",
                    quote="worry again",
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.raw_candidate_count == 4
    assert result.materialized_candidate_count == 3
    assert result.drop_reasons == (
        {"field_path": "evidence[3]", "reason": "duplicate_scalar_field"},
    )
    assert result.patch.presenting_problem is not None
    assert len(result.patch.presenting_problem.symptoms) == 2
    assert result.patch.presenting_problem.main_concern.value == "worry"


def test_materialize_whitespace_only_quote() -> None:
    turn = _user_turn("hello")
    result = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    value="x",
                    quote="   ",
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.drop_reasons == (
        {"field_path": "evidence[0]", "reason": "missing_evidence_quote"},
    )
    assert result.materialized_candidate_count == 0


def test_informative_whitespace_value_dropped_by_merge() -> None:
    turn = _user_turn("I feel anxious")
    materialized = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    value="   ",
                    quote="I feel anxious",
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert materialized.materialized_candidate_count == 1
    assert materialized.patch.presenting_problem is not None
    assert materialized.patch.presenting_problem.main_concern.value is None
    merge = merge_intake_record_patch_with_diagnostics(
        IntakeRecord(),
        materialized.patch,
        latest_user_message=turn,
        source_message_sequence=turn.sequence,
    )
    assert merge.status == "empty_after_validation"
    assert merge.drop_reasons[0]["reason"] == "missing_value"


def test_count_invariant_on_mixed_drops() -> None:
    turn = _user_turn("anxious; not sure about harm")
    result = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    value="anxiety",
                    quote="anxious",
                ),
                _candidate(
                    IntakeEvidenceField.SAFETY_SELF_HARM,
                    quote="not sure about harm",
                    response_status="unknown",
                ),
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    value="worry",
                    quote="anxious",
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.raw_candidate_count == (
        result.materialized_candidate_count + len(result.drop_reasons)
    )
    assert result.materialized_candidate_count == 1
    assert {reason["reason"] for reason in result.drop_reasons} == {
        "unasked_noninformative",
        "duplicate_scalar_field",
    }


@pytest.mark.parametrize(
    "status",
    ["unknown", "unable_to_answer"],
)
def test_prompted_noninformative_with_valid_quote_accepted(status: str) -> None:
    turn = _user_turn("I cannot say")
    result = materialize_extraction(
        IntakeExtraction(
            evidence=(
                _candidate(
                    IntakeEvidenceField.PRESENTING_PROBLEM_MAIN_CONCERN,
                    quote="I cannot say",
                    response_status=status,
                ),
            )
        ),
        latest_user_turn=turn,
        prompted_item="presenting_problem",
    )
    assert result.materialized_candidate_count == 1
    evidence = result.patch.presenting_problem.main_concern  # type: ignore[union-attr]
    assert evidence.direct_ask is True
    assert evidence.response_status == status
