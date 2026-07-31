"""Post-session merge policy tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.grounding import GroundedPatientTurn
from jung.phases.post_session.merge import (
    derived_profile_patch_is_empty,
    merge_derived_profile,
)
from jung.phases.post_session.models import DerivedProfilePatch


def test_empty_patch_preserves_none_derived_profile() -> None:
    assert merge_derived_profile(None, DerivedProfilePatch()) is None
    assert derived_profile_patch_is_empty(DerivedProfilePatch()) is True


def test_empty_patch_preserves_sparse_derived_profile() -> None:
    current = {"custom_observation": "existing"}
    assert merge_derived_profile(current, DerivedProfilePatch()) == current


def test_empty_patch_validates_existing_grounded_turns() -> None:
    with pytest.raises(ValidationError):
        merge_derived_profile(
            {"grounded_patient_turns": ["not-an-object"]},
            DerivedProfilePatch(),
        )


def test_empty_patch_rejects_null_grounded_turns() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        merge_derived_profile(
            {"grounded_patient_turns": None},
            DerivedProfilePatch(),
        )


def test_empty_patch_rejects_duplicate_stored_message_ids() -> None:
    message_id = uuid4()
    with pytest.raises(ValueError, match="duplicate grounded patient source message"):
        merge_derived_profile(
            {
                "grounded_patient_turns": [
                    {
                        "source_message_id": str(message_id),
                        "source_sequence": 1,
                        "content": "first",
                    },
                    {
                        "source_message_id": str(message_id),
                        "source_sequence": 2,
                        "content": "duplicate id",
                    },
                ]
            },
            DerivedProfilePatch(),
        )


def test_merge_dedups_by_source_message_id_with_stable_order() -> None:
    first_id = uuid4()
    second_id = uuid4()
    current = {
        "grounded_patient_turns": [
            GroundedPatientTurn(
                source_message_id=first_id,
                source_sequence=1,
                content="first content",
            ).model_dump(mode="json"),
        ]
    }
    merged = merge_derived_profile(
        current,
        DerivedProfilePatch(
            grounded_patient_turns=(
                GroundedPatientTurn(
                    source_message_id=first_id,
                    source_sequence=1,
                    content="updated content ignored",
                ),
                GroundedPatientTurn(
                    source_message_id=second_id,
                    source_sequence=3,
                    content="second content",
                ),
            )
        ),
    )
    assert merged is not None
    turns = merged["grounded_patient_turns"]
    assert len(turns) == 2
    assert turns[0]["source_message_id"] == str(first_id)
    assert turns[0]["content"] == "first content"
    assert turns[1]["source_message_id"] == str(second_id)
    assert turns[1]["content"] == "second content"


def test_same_content_from_different_messages_retained() -> None:
    first_id = uuid4()
    second_id = uuid4()
    merged = merge_derived_profile(
        None,
        DerivedProfilePatch(
            grounded_patient_turns=(
                GroundedPatientTurn(
                    source_message_id=first_id,
                    source_sequence=1,
                    content="I slept badly.",
                ),
                GroundedPatientTurn(
                    source_message_id=second_id,
                    source_sequence=4,
                    content="I slept badly.",
                ),
            )
        ),
    )
    assert merged is not None
    assert len(merged["grounded_patient_turns"]) == 2


def test_malformed_stored_entries_raise_visibly() -> None:
    with pytest.raises(ValidationError):
        merge_derived_profile(
            {"grounded_patient_turns": ["not-an-object"]},
            DerivedProfilePatch(
                grounded_patient_turns=(
                    GroundedPatientTurn(
                        source_message_id=uuid4(),
                        source_sequence=1,
                        content="content",
                    ),
                )
            ),
        )


def test_merge_preserves_unrelated_keys() -> None:
    message_id = uuid4()
    current = {
        "custom_observation": "keep me",
        "grounded_patient_turns": [],
    }
    merged = merge_derived_profile(
        current,
        DerivedProfilePatch(
            grounded_patient_turns=(
                GroundedPatientTurn(
                    source_message_id=message_id,
                    source_sequence=1,
                    content="new turn",
                ),
            )
        ),
    )
    assert merged is not None
    assert merged["custom_observation"] == "keep me"
    assert len(merged["grounded_patient_turns"]) == 1
