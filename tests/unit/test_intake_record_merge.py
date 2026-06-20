from datetime import datetime

from psychoanalyst_app.agents.intake.record_merge import (
    merge_intake_record_patch,
    merge_intake_record_patch_with_diagnostics,
)
from psychoanalyst_app.models.domain import Message
from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
    PresentingProblemRecord,
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

