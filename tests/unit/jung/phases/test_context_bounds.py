"""Unit tests for context bounding primitives."""

from __future__ import annotations

from jung.phases.context_bounds import (
    bounded_text,
    newest_lines_within_budget,
    newest_within_budget,
)


def test_bounded_text_zero_limit_returns_empty() -> None:
    assert bounded_text("hello world", 0) == ""


def test_bounded_text_negative_limit_returns_empty() -> None:
    assert bounded_text("hello world", -1) == ""


def test_bounded_text_short_text_unchanged() -> None:
    assert bounded_text("hello", 10) == "hello"


def test_newest_within_budget_zero_returns_empty() -> None:
    assert newest_within_budget(["a", "b"], 0) == []


def test_newest_lines_within_budget_counts_separators() -> None:
    lines = ["line-one", "line-two", "line-three"]
    selected = newest_lines_within_budget(lines, len("line-three"))
    assert selected == ["line-three"]

    budget = len("line-two") + 1 + len("line-three")
    selected = newest_lines_within_budget(lines, budget)
    assert selected == ["line-two", "line-three"]
    assert len("\n".join(selected)) <= budget


def test_newest_lines_within_budget_stops_at_first_nonfitting_older_line() -> None:
    lines = ["tiny", "middle-is-too-large-for-budget", "newest"]
    budget = len("newest")
    selected = newest_lines_within_budget(lines, budget)
    assert selected == ["newest"]

    budget = len("newest") + len("\n") + len("middle-is-too-large-for-budget") - 1
    selected = newest_lines_within_budget(lines, budget)
    assert selected == ["newest"]


def test_newest_lines_within_budget_bounds_oversized_newest_line() -> None:
    oversized = "x" * 50
    selected = newest_lines_within_budget([oversized], 20)
    assert selected == [bounded_text(oversized, 20)]
    assert len(selected[0]) <= 20
