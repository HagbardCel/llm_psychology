"""Unit tests for context bounding primitives."""

from __future__ import annotations

from jung.phases.context_bounds import bounded_text, newest_within_budget


def test_bounded_text_zero_limit_returns_empty() -> None:
    assert bounded_text("hello world", 0) == ""


def test_bounded_text_negative_limit_returns_empty() -> None:
    assert bounded_text("hello world", -1) == ""


def test_bounded_text_short_text_unchanged() -> None:
    assert bounded_text("hello", 10) == "hello"


def test_newest_within_budget_zero_returns_empty() -> None:
    assert newest_within_budget(["a", "b"], 0) == []
