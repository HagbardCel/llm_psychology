"""Tests for the immutable therapy style catalog."""

from __future__ import annotations

import pytest

from jung.styles import StyleDefinition, load_styles


def test_load_styles_returns_all_known_styles_in_order() -> None:
    styles = load_styles()
    assert tuple(styles.keys()) == ("jung", "cbt", "freud")
    for style_id, definition in styles.items():
        assert isinstance(definition, StyleDefinition)
        assert definition.id == style_id
        assert definition.description
        assert definition.assessment_instructions
        assert definition.therapist_instructions
        assert definition.post_session_instructions


def test_style_definitions_are_immutable() -> None:
    from dataclasses import FrozenInstanceError

    styles = load_styles()
    jung = styles["jung"]
    with pytest.raises(FrozenInstanceError):
        jung.name = "changed"  # type: ignore[misc]


def test_load_styles_is_deterministic() -> None:
    first = load_styles()
    second = load_styles()
    assert tuple(first.keys()) == tuple(second.keys())
    assert first["cbt"].therapist_instructions == second["cbt"].therapist_instructions
