import pytest
from pydantic import ValidationError

from psychoanalyst_app.models.intake_record import IntakeEvidence, IntakeRecord


def test_empty_intake_record_validates() -> None:
    record = IntakeRecord()

    assert record.schema_version == 1
    assert not record.presenting_problem.main_concern.is_present()


def test_evidence_presence_requires_value_and_quote() -> None:
    assert not IntakeEvidence(value="anxiety").is_present()
    assert not IntakeEvidence(evidence_quote="I feel anxious").is_present()
    assert IntakeEvidence(
        value="anxiety",
        evidence_quote="I feel anxious",
        source_role="user",
        source_message_index=1,
    ).is_present()


def test_evidence_presence_requires_patient_source() -> None:
    assert not IntakeEvidence(
        value="anxiety",
        evidence_quote="I feel anxious",
    ).is_present()


def test_unknown_evidence_is_addressed_but_not_informative() -> None:
    evidence = IntakeEvidence(
        value="unknown",
        evidence_quote="I do not know",
        source_role="user",
        source_message_index=2,
        response_status="unknown",
        direct_ask=True,
    )

    assert evidence.is_addressed()
    assert evidence.is_unable_or_unknown()
    assert not evidence.is_present()


def test_unknown_evidence_requires_direct_ask() -> None:
    with pytest.raises(ValidationError):
        IntakeEvidence(
            value="unknown",
            evidence_quote="I do not know",
            source_role="user",
            source_message_index=2,
            response_status="unknown",
            direct_ask=False,
        )


def test_time_course_requires_duration_or_frequency_not_trigger() -> None:
    record = IntakeRecord()
    record.presenting_problem.time_course.triggers = [
        IntakeEvidence(
            value="email",
            evidence_quote="when I open email",
            source_role="user",
            source_message_index=1,
        )
    ]

    assert not record.presenting_problem.time_course.has_required_time_course()
