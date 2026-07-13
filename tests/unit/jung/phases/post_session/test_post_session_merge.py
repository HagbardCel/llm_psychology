"""Post-session merge policy tests."""

from __future__ import annotations

from jung.phases.post_session.merge import merge_derived_profile
from jung.phases.post_session.models import DerivedProfilePatch


def test_empty_patch_preserves_none_derived_profile() -> None:
    assert merge_derived_profile(None, DerivedProfilePatch()) is None


def test_empty_patch_preserves_sparse_derived_profile() -> None:
    current = {"custom_observation": "existing"}
    assert merge_derived_profile(current, DerivedProfilePatch()) == current


def test_nonempty_patch_merges_into_sparse_profile() -> None:
    current = {"custom_observation": "existing"}
    merged = merge_derived_profile(
        current,
        DerivedProfilePatch(observations=("new fact",)),
    )
    assert merged == {
        "custom_observation": "existing",
        "observations": ["new fact"],
    }
