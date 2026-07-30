"""Post-session merge policy tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.phases.post_session.merge import (
    derived_profile_patch_is_empty,
    merge_derived_profile,
)
from jung.phases.post_session.models import (
    DerivedProfilePatch,
    GroundedPatientStatement,
)


def test_empty_patch_preserves_none_derived_profile() -> None:
    assert merge_derived_profile(None, DerivedProfilePatch()) is None
    assert derived_profile_patch_is_empty(DerivedProfilePatch()) is True


def test_empty_patch_preserves_sparse_derived_profile() -> None:
    current = {"custom_observation": "existing"}
    assert merge_derived_profile(current, DerivedProfilePatch()) == current


def test_merge_dedups_by_source_message_id_with_stable_order() -> None:
    first_id = uuid4()
    second_id = uuid4()
    current = {
        "grounded_patient_statements": [
            GroundedPatientStatement(
                source_message_id=first_id,
                source_sequence=1,
                quote="first quote",
            ).model_dump(mode="json"),
        ]
    }
    merged = merge_derived_profile(
        current,
        DerivedProfilePatch(
            grounded_patient_statements=(
                GroundedPatientStatement(
                    source_message_id=first_id,
                    source_sequence=1,
                    quote="updated quote ignored",
                ),
                GroundedPatientStatement(
                    source_message_id=second_id,
                    source_sequence=3,
                    quote="second quote",
                ),
            )
        ),
    )
    assert merged is not None
    statements = merged["grounded_patient_statements"]
    assert len(statements) == 2
    assert statements[0]["source_message_id"] == str(first_id)
    assert statements[0]["quote"] == "first quote"
    assert statements[1]["source_message_id"] == str(second_id)
    assert statements[1]["quote"] == "second quote"


def test_same_quote_from_different_messages_retained() -> None:
    first_id = uuid4()
    second_id = uuid4()
    merged = merge_derived_profile(
        None,
        DerivedProfilePatch(
            grounded_patient_statements=(
                GroundedPatientStatement(
                    source_message_id=first_id,
                    source_sequence=1,
                    quote="I slept badly.",
                ),
                GroundedPatientStatement(
                    source_message_id=second_id,
                    source_sequence=4,
                    quote="I slept badly.",
                ),
            )
        ),
    )
    assert merged is not None
    assert len(merged["grounded_patient_statements"]) == 2


def test_malformed_stored_entries_raise_visibly() -> None:
    with pytest.raises(ValidationError):
        merge_derived_profile(
            {"grounded_patient_statements": ["not-an-object"]},
            DerivedProfilePatch(
                grounded_patient_statements=(
                    GroundedPatientStatement(
                        source_message_id=uuid4(),
                        source_sequence=1,
                        quote="quote",
                    ),
                )
            ),
        )
