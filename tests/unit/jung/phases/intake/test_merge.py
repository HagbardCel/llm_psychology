"""Table-driven tests for intake merge policy."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jung.phases.intake.merge import merge_intake_record_patch_with_diagnostics
from jung.phases.intake.models import (
    IntakeEvidence,
    IntakeRecord,
    IntakeRecordPatch,
    PresentingProblemRecord,
)
from jung.phases.transcript import TranscriptTurn


def _user_turn(content: str, *, sequence: int = 1) -> TranscriptTurn:
    return TranscriptTurn(
        message_id=uuid4(),
        sequence=sequence,
        role="user",
        content=content,
    )


def _valid_evidence(
    *,
    value: str,
    quote: str,
    sequence: int = 1,
) -> IntakeEvidence:
    return IntakeEvidence(
        value=value,
        evidence_quote=quote,
        source_message_sequence=sequence,
        source_role="user",
        confidence="high",
    )


@pytest.mark.parametrize(
    ("patch", "expected_status", "record_changed"),
    [
        (
            IntakeRecordPatch(),
            "empty_patch",
            False,
        ),
        (
            IntakeRecordPatch(
                presenting_problem=PresentingProblemRecord(
                    main_concern=_valid_evidence(
                        value="anxiety",
                        quote="I feel anxious every morning",
                    )
                )
            ),
            "applied",
            True,
        ),
        (
            IntakeRecordPatch(
                presenting_problem=PresentingProblemRecord(
                    main_concern=IntakeEvidence(
                        value="anxiety",
                        evidence_quote="not in message",
                        source_message_sequence=1,
                        source_role="user",
                    )
                )
            ),
            "empty_after_validation",
            False,
        ),
    ],
)
def test_merge_intake_record_patch_with_diagnostics(
    patch: IntakeRecordPatch,
    expected_status: str,
    record_changed: bool,
) -> None:
    current = IntakeRecord()
    latest = _user_turn("I feel anxious every morning")
    result = merge_intake_record_patch_with_diagnostics(
        current,
        patch,
        latest_user_message=latest,
        source_message_sequence=latest.sequence,
    )
    assert result.status == expected_status
    assert result.record_changed is record_changed


def test_merge_is_idempotent_for_same_patch() -> None:
    current = IntakeRecord()
    latest = _user_turn("I feel anxious every morning")
    patch = IntakeRecordPatch(
        presenting_problem=PresentingProblemRecord(
            main_concern=_valid_evidence(
                value="anxiety",
                quote="I feel anxious every morning",
            )
        )
    )
    first = merge_intake_record_patch_with_diagnostics(
        current,
        patch,
        latest_user_message=latest,
        source_message_sequence=latest.sequence,
    )
    second = merge_intake_record_patch_with_diagnostics(
        first.record,
        patch,
        latest_user_message=latest,
        source_message_sequence=latest.sequence,
    )
    assert second.record == first.record
    assert second.record_changed is False
