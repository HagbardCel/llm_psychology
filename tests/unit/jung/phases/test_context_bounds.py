"""Unit tests for context bounding primitives."""

from __future__ import annotations

import json

from jung.phases.context_bounds import (
    bounded_lines,
    bounded_text,
    newest_lines_within_budget,
    pack_complete_json_items,
)
from jung.phases.therapy.models import TherapyContextLimits
from jung.styles import load_styles


def _render_items(items: list[str] | tuple[str, ...], omitted: int) -> str:
    return json.dumps(
        {"items": list(items), "omitted": omitted},
        ensure_ascii=True,
        separators=(",", ":"),
    )


def test_pack_complete_json_items_returns_none_when_minimal_cannot_fit() -> None:
    packed = pack_complete_json_items(
        ["a", "b"],
        limit=5,
        render_document=_render_items,
    )
    assert packed is None


def test_pack_complete_json_items_oversized_newest_does_not_block_older() -> None:
    items = ("tiny", "x" * 200, "also-tiny")
    packed = pack_complete_json_items(
        items,
        limit=80,
        render_document=_render_items,
    )
    assert packed is not None
    assert packed.items == ("tiny", "also-tiny")
    assert packed.omitted == 1
    assert len(_render_items(packed.items, packed.omitted)) <= 80


def test_pack_complete_json_items_omitted_count_is_exact() -> None:
    items = ("one", "two", "three", "four")
    packed = pack_complete_json_items(
        items,
        limit=len(_render_items(("three", "four"), 2)),
        render_document=_render_items,
    )
    assert packed is not None
    assert packed.items == ("three", "four")
    assert packed.omitted == len(items) - len(packed.items)
    assert packed.omitted == 2
    assert len(_render_items(packed.items, packed.omitted)) <= len(
        _render_items(("three", "four"), 2)
    )


def test_bounded_text_zero_limit_returns_empty() -> None:
    assert bounded_text("hello world", 0) == ""


def test_bounded_text_negative_limit_returns_empty() -> None:
    assert bounded_text("hello world", -1) == ""


def test_bounded_text_short_text_unchanged() -> None:
    assert bounded_text("hello", 10) == "hello"


def test_bounded_lines_returns_complete_prefix_without_ellipsis() -> None:
    text = "line one\nline two\nline three"
    result = bounded_lines(text, len("line one\nline two"))
    assert result == "line one\nline two"
    assert "..." not in result


def test_bounded_lines_unchanged_when_fit() -> None:
    text = "line one\nline two"
    assert bounded_lines(text, 100) == text


def test_bounded_lines_empty_when_no_complete_line_fits() -> None:
    assert bounded_lines("a very long single line", 5) == ""


def test_newest_lines_within_budget_zero_returns_empty() -> None:
    assert newest_lines_within_budget(["a", "b"], 0) == []


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


def test_all_post_session_style_instructions_fit_reserved_budget() -> None:
    for style in load_styles().values():
        instructions = style.post_session_instructions or ""
        assert len(instructions) <= 2000
        rendered = bounded_lines(instructions, 2000)
        assert rendered in {instructions, instructions.rstrip("\n")}


def test_all_therapy_style_instructions_fit_minimum_production_budget() -> None:
    limits = TherapyContextLimits()
    # Style and plan share the core body budget; style gets half.
    min_style_budget = min(limits.max_section_chars, limits.max_total_chars // 2)
    for style in load_styles().values():
        instructions = style.therapist_instructions
        assert len(instructions) <= min_style_budget
        rendered = bounded_lines(instructions, min_style_budget)
        assert rendered in {instructions, instructions.rstrip("\n")}
