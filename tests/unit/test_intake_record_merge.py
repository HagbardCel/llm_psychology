from datetime import datetime

import pytest

from psychoanalyst_app.agents.intake.record_merge import (
    merge_intake_record_patch,
    merge_intake_record_patch_with_diagnostics,
)
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import (
    CopingRecord,
    GoalsRecord,
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
    PresentingProblemRecord,
    SafetyRecord,
    TimeCourseRecord,
)


def _message(content: str = "I feel anxious at work.") -> Message:
    return Message(role="user", content=content, timestamp=datetime.now())


def _evidence(value: str, quote: str = "I feel anxious at work.") -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=quote,
        source_role="user",
        source_message_index=0,
        confidence="medium",
    )


def test_rejects_wrong_source_role() -> None:
    evidence = IntakeEvidence.model_construct(
        value="anxiety",
        evidence_quote="I feel anxious at work.",
        source_role="assistant",
        source_message_index=0,
        confidence="medium",
        response_status="informative",
        direct_ask=False,
    )
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(main_concern=evidence)
    )

    merged = merge_intake_record_patch(
        IntakeRecord(),
        patch,
        latest_user_message=_message(),
        source_message_index=0,
    )

    assert not merged.presenting_problem.main_concern.is_present()


def test_rejects_wrong_source_message_index() -> None:
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=_evidence("anxiety")
        )
    )

    merged = merge_intake_record_patch(
        IntakeRecord(),
        patch,
        latest_user_message=_message(),
        source_message_index=1,
    )

    assert not merged.presenting_problem.main_concern.is_present()


def test_rejects_patch_evidence_without_quote() -> None:
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                value="anxiety",
                source_role="user",
                source_message_index=0,
            )
        )
    )

    merged = merge_intake_record_patch(
        IntakeRecord(),
        patch,
        latest_user_message=_message(),
        source_message_index=0,
    )

    assert not merged.presenting_problem.main_concern.is_present()


def test_rejects_quote_not_in_latest_user_message() -> None:
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=_evidence("anxiety", quote="not in message")
        )
    )

    merged = merge_intake_record_patch(
        IntakeRecord(),
        patch,
        latest_user_message=_message(),
        source_message_index=0,
    )

    assert not merged.presenting_problem.main_concern.is_present()


def test_diagnostics_report_empty_after_validation_for_bad_quote() -> None:
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=_evidence("anxiety", quote="not in message")
        )
    )

    result = merge_intake_record_patch_with_diagnostics(
        IntakeRecord(),
        patch,
        latest_user_message=_message(),
        source_message_index=0,
    )

    assert result.status == "empty_after_validation"
    assert result.applied is False
    assert result.raw_evidence_count == 1
    assert result.retained_evidence_count == 0
    assert result.dropped_evidence_count == 1


def test_diagnostics_report_empty_patch_for_no_evidence() -> None:
    result = merge_intake_record_patch_with_diagnostics(
        IntakeRecord(),
        IntakeRecordPatch(),
        latest_user_message=_message(),
        source_message_index=0,
    )

    assert result.status == "empty_patch"
    assert result.applied is False
    assert result.record_changed is False
    assert result.raw_evidence_count == 0
    assert result.retained_evidence_count == 0
    assert result.dropped_evidence_count == 0


def test_accepts_normalized_quote_match() -> None:
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=_evidence("anxiety", quote="i feel   anxious at work")
        )
    )

    merged = merge_intake_record_patch(
        IntakeRecord(),
        patch,
        latest_user_message=_message("I feel anxious at work."),
        source_message_index=0,
    )

    assert merged.presenting_problem.main_concern.is_present()


def test_diagnostics_report_applied_for_valid_evidence() -> None:
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=_evidence("anxiety", quote="i feel   anxious at work")
        )
    )

    result = merge_intake_record_patch_with_diagnostics(
        IntakeRecord(),
        patch,
        latest_user_message=_message("I feel anxious at work."),
        source_message_index=0,
    )

    assert result.status == "applied"
    assert result.applied is True
    assert result.record_changed is True
    assert result.raw_evidence_count == 1
    assert result.retained_evidence_count == 1
    assert result.dropped_evidence_count == 0
    assert result.record.presenting_problem.main_concern.is_present()


def test_diagnostics_report_no_record_change_for_duplicate_evidence() -> None:
    current = IntakeRecord()
    current.presenting_problem.symptoms = [_evidence("racing thoughts")]
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            symptoms=[_evidence("racing thoughts")]
        )
    )

    result = merge_intake_record_patch_with_diagnostics(
        current,
        patch,
        latest_user_message=_message(),
        source_message_index=0,
    )

    assert result.status == "applied"
    assert result.applied is True
    assert result.record_changed is False
    assert result.raw_evidence_count == 1
    assert result.retained_evidence_count == 1
    assert result.dropped_evidence_count == 0
    assert result.record == current


def test_non_strict_quote_validation_keeps_role_and_index_checks() -> None:
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=_evidence("anxiety", quote="paraphrased anxiety")
        )
    )

    merged = merge_intake_record_patch(
        IntakeRecord(),
        patch,
        latest_user_message=_message(),
        source_message_index=0,
        strict_quote_validation=False,
    )

    assert merged.presenting_problem.main_concern.is_present()


def test_appends_unique_list_evidence() -> None:
    current = IntakeRecord()
    current.presenting_problem.symptoms = [_evidence("racing thoughts")]
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            symptoms=[
                _evidence("racing thoughts"),
                _evidence("sleep disruption"),
            ]
        )
    )

    merged = merge_intake_record_patch(
        current,
        patch,
        latest_user_message=_message(),
        source_message_index=0,
    )

    assert [item.value for item in merged.presenting_problem.symptoms] == [
        "racing thoughts",
        "sleep disruption",
    ]


def test_retains_unknown_direct_ask_without_value() -> None:
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=IntakeEvidence(
                evidence_quote="I don't know",
                source_role="user",
                source_message_index=0,
                response_status="unknown",
                direct_ask=True,
            )
        )
    )

    merged = merge_intake_record_patch(
        IntakeRecord(),
        patch,
        latest_user_message=_message("I don't know"),
        source_message_index=0,
    )

    evidence = merged.presenting_problem.main_concern
    assert evidence.is_addressed()
    assert evidence.is_unable_or_unknown()
    assert not evidence.is_present()



def _unknown_evidence(
    quote: str = "I don't know",
    *,
    confidence: str = "medium",
) -> IntakeEvidence:
    return IntakeEvidence(
        value="I don't know",
        evidence_quote=quote,
        source_role="user",
        source_message_index=0,
        confidence=confidence,  # type: ignore[arg-type]
        response_status="unknown",
        direct_ask=True,
    )


def test_informative_existing_not_overwritten_by_unknown_patch() -> None:
    current = IntakeRecord()
    current.presenting_problem.time_course.duration_or_onset = IntakeEvidence(
        value="three months",
        evidence_quote="about three months",
        source_role="user",
        source_message_index=0,
        confidence="low",
    )
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            time_course=TimeCourseRecord(
                duration_or_onset=_unknown_evidence(confidence="medium"),
            )
        )
    )

    merged = merge_intake_record_patch(
        current,
        patch,
        latest_user_message=_message("I don't know"),
        source_message_index=0,
    )

    evidence = merged.presenting_problem.time_course.duration_or_onset
    assert evidence.value == "three months"
    assert evidence.is_present()


def test_unknown_existing_replaced_by_informative_patch() -> None:
    current = IntakeRecord()
    current.presenting_problem.time_course.duration_or_onset = _unknown_evidence()
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            time_course=TimeCourseRecord(
                duration_or_onset=_evidence("three months", quote="about three months"),
            )
        )
    )

    merged = merge_intake_record_patch(
        current,
        patch,
        latest_user_message=_message("about three months"),
        source_message_index=0,
    )

    evidence = merged.presenting_problem.time_course.duration_or_onset
    assert evidence.value == "three months"
    assert evidence.is_present()


@pytest.mark.parametrize(
    "patch, accessor",
    [
        pytest.param(
            IntakeRecordPatch(
                presenting_problem=PresentingProblemRecord(
                    time_course=TimeCourseRecord(duration_or_onset=_evidence("months"))
                )
            ),
            lambda record: record.presenting_problem.time_course.duration_or_onset,
            id="time_course_duration",
        ),
        pytest.param(
            IntakeRecordPatch(safety=SafetyRecord(self_harm=_evidence("no self harm"))),
            lambda record: record.safety.self_harm,
            id="safety_self_harm",
        ),
        pytest.param(
            IntakeRecordPatch(
                safety=SafetyRecord(harm_to_others=_evidence("no harm to others"))
            ),
            lambda record: record.safety.harm_to_others,
            id="safety_harm_to_others",
        ),
        pytest.param(
            IntakeRecordPatch(
                safety=SafetyRecord(medical_urgency=_evidence("not medically urgent"))
            ),
            lambda record: record.safety.medical_urgency,
            id="safety_medical_urgency",
        ),
        pytest.param(
            IntakeRecordPatch(
                coping=CopingRecord(
                    attempted_strategies=[_evidence("breathing exercises")]
                )
            ),
            lambda record: record.coping.attempted_strategies[0],
            id="coping_attempted_strategies",
        ),
        pytest.param(
            IntakeRecordPatch(
                goals=GoalsRecord(therapy_goals=[_evidence("sleep better")])
            ),
            lambda record: record.goals.therapy_goals[0],
            id="goals_therapy_goals",
        ),
    ],
)
def test_valid_patch_merges_into_empty_record(patch, accessor) -> None:
    merged = merge_intake_record_patch(
        IntakeRecord(),
        patch,
        latest_user_message=_message("I feel anxious at work."),
        source_message_index=0,
    )

    assert accessor(merged).is_present()


@pytest.mark.parametrize(
    "attach, build_patch, accessor, cap",
    [
        pytest.param(
            lambda record, items: setattr(
                record.presenting_problem, "symptoms", items
            ),
            lambda items: IntakeRecordPatch(
                presenting_problem=PresentingProblemRecord(symptoms=items)
            ),
            lambda record: record.presenting_problem.symptoms,
            20,
            id="symptoms_cap_20",
        ),
        pytest.param(
            lambda record, items: setattr(
                record.presenting_problem.time_course, "triggers", items
            ),
            lambda items: IntakeRecordPatch(
                presenting_problem=PresentingProblemRecord(
                    time_course=TimeCourseRecord(triggers=items)
                )
            ),
            lambda record: record.presenting_problem.time_course.triggers,
            10,
            id="triggers_cap_10",
        ),
        pytest.param(
            lambda record, items: setattr(
                record.coping, "attempted_strategies", items
            ),
            lambda items: IntakeRecordPatch(
                coping=CopingRecord(attempted_strategies=items)
            ),
            lambda record: record.coping.attempted_strategies,
            20,
            id="coping_cap_20",
        ),
        pytest.param(
            lambda record, items: setattr(record.goals, "therapy_goals", items),
            lambda items: IntakeRecordPatch(goals=GoalsRecord(therapy_goals=items)),
            lambda record: record.goals.therapy_goals,
            10,
            id="goals_cap_10",
        ),
    ],
)
def test_merge_evidence_list_respects_cap(attach, build_patch, accessor, cap) -> None:
    current = IntakeRecord()
    attach(current, [_evidence(f"existing {i}") for i in range(cap - 2)])
    patch = build_patch([_evidence(f"new {i}") for i in range(5)])

    merged = merge_intake_record_patch(
        current,
        patch,
        latest_user_message=_message("I feel anxious at work."),
        source_message_index=0,
    )

    merged_list = accessor(merged)
    assert len(merged_list) == cap
    assert all(item.is_present() for item in merged_list)
