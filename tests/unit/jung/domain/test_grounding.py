"""Grounded patient-turn domain contract tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.grounding import GroundedPatientTurn, parse_grounded_patient_turns


def test_parse_missing_key_yields_empty_tuple() -> None:
    assert parse_grounded_patient_turns({}) == ()
    assert parse_grounded_patient_turns({"other": []}) == ()


def test_parse_null_key_raises() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        parse_grounded_patient_turns({"grounded_patient_turns": None})


def test_parse_non_list_raises() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        parse_grounded_patient_turns({"grounded_patient_turns": {}})


def test_parse_valid_turns() -> None:
    message_id = uuid4()
    turns = parse_grounded_patient_turns(
        {
            "grounded_patient_turns": [
                {
                    "source_message_id": str(message_id),
                    "source_sequence": 2,
                    "content": "I   slept\nbadly.",
                }
            ]
        }
    )
    assert len(turns) == 1
    assert turns[0].source_message_id == message_id
    assert turns[0].source_sequence == 2
    assert turns[0].content == "I slept badly."


def test_grounded_patient_turn_normalizes_content() -> None:
    turn = GroundedPatientTurn(
        source_message_id=uuid4(),
        source_sequence=1,
        content="  hello\n\tworld  ",
    )
    assert turn.content == "hello world"


def test_grounded_patient_turn_rejects_whitespace_only() -> None:
    with pytest.raises(ValidationError):
        GroundedPatientTurn(
            source_message_id=uuid4(),
            source_sequence=1,
            content="   \n\t  ",
        )


def test_grounded_patient_turn_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        GroundedPatientTurn(
            source_message_id=uuid4(),
            source_sequence=1,
            content="",
        )


def test_parse_malformed_item_raises() -> None:
    with pytest.raises(ValidationError):
        parse_grounded_patient_turns({"grounded_patient_turns": ["not-an-object"]})
