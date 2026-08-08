"""Table-driven tests for intake completion policy."""

from __future__ import annotations

import pytest

from jung.phases.intake.completion import (
    MAX_INTAKE_PATIENT_TURNS,
    MIN_INTAKE_PATIENT_TURNS,
    intake_record_completion_decision,
)
from jung.phases.intake.models import (
    CopingRecord,
    GoalsRecord,
    IntakeEvidence,
    IntakeRecord,
    PresentingProblemRecord,
    SafetyRecord,
    TimeCourseRecord,
)


def _informative(value: str, quote: str) -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=quote,
        source_message_sequence=1,
        source_role="user",
    )


def _complete_record() -> IntakeRecord:
    return IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=_informative("anxiety", "anxious"),
            time_course=TimeCourseRecord(
                duration_or_onset=_informative("3 months", "3 months"),
            ),
            functional_impairment=_informative("work", "work"),
            sleep_impact=_informative("poor sleep", "sleep"),
        ),
        safety=SafetyRecord(
            self_harm=_informative("denies", "denies"),
            harm_to_others=_informative("denies", "denies"),
            medical_urgency=_informative("none", "none"),
        ),
        coping=CopingRecord(
            attempted_strategies=(_informative("journaling", "journal"),),
        ),
        goals=GoalsRecord(
            therapy_goals=(_informative("sleep better", "sleep"),),
        ),
    )


@pytest.mark.parametrize(
    ("patient_turn_count", "expected_complete"),
    [
        (MIN_INTAKE_PATIENT_TURNS - 1, False),
        (MIN_INTAKE_PATIENT_TURNS, True),
    ],
)
def test_completion_requires_minimum_turns(
    patient_turn_count: int,
    expected_complete: bool,
) -> None:
    result = intake_record_completion_decision(
        _complete_record(),
        patient_turn_count,
    )
    assert result.complete is expected_complete


def test_max_turn_completion_blocked_when_extraction_failed() -> None:
    hard_complete_missing_soft = IntakeRecord(
        presenting_problem=PresentingProblemRecord(
            main_concern=_informative("anxiety", "anxious"),
            time_course=TimeCourseRecord(
                duration_or_onset=_informative("3 months", "3 months"),
            ),
            functional_impairment=_informative("work", "work"),
        ),
        safety=SafetyRecord(
            self_harm=_informative("denies", "denies"),
            harm_to_others=_informative("denies", "denies"),
            medical_urgency=_informative("none", "none"),
        ),
        goals=GoalsRecord(
            therapy_goals=(_informative("sleep better", "sleep"),),
        ),
    )
    result = intake_record_completion_decision(
        hard_complete_missing_soft,
        MAX_INTAKE_PATIENT_TURNS,
        extraction_failed=True,
    )
    assert result.max_turn_completion is True
    assert result.complete is False
