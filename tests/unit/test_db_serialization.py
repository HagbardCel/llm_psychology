import json

import pytest
from pydantic import ValidationError

from psychoanalyst_app.models.intake_record import (
    IntakeEvidence,
    IntakeRecord,
    PresentingProblemRecord,
)
from psychoanalyst_app.services.db_serialization import load_intake_record

pytestmark = pytest.mark.unit

INVALID_INTAKE_RECORD_JSON = json.dumps(
    {
        "presenting_problem": {
            "main_concern": {
                "source_message_index": -1,
            }
        }
    }
)


def test_load_intake_record_none_returns_none() -> None:
    assert load_intake_record(None) is None


def test_load_intake_record_empty_string_raises_json_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        load_intake_record("")


def test_load_intake_record_malformed_json_raises_json_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        load_intake_record("{not json")


def test_load_intake_record_schema_invalid_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        load_intake_record(INVALID_INTAKE_RECORD_JSON)


def test_load_intake_record_valid_json_returns_typed_record() -> None:
    payload = json.dumps(
        IntakeRecord(
            presenting_problem=PresentingProblemRecord(
                main_concern=IntakeEvidence(
                    value="work anxiety",
                    evidence_quote="I feel anxious at work",
                    source_message_index=0,
                    source_role="user",
                    confidence="high",
                )
            )
        ).model_dump(mode="json")
    )

    record = load_intake_record(payload)

    assert record is not None
    assert record.presenting_problem.main_concern.value == "work anxiety"
