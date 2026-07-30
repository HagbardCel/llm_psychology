"""Shared mechanical context-bounding primitives."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PackedItems(Generic[T]):
    """Complete items retained by budget packing, plus how many were omitted."""

    items: tuple[T, ...]
    omitted: int


def pack_complete_json_items(
    items: Sequence[T],
    *,
    limit: int,
    render_document: Callable[[Sequence[T], int], str],
) -> PackedItems[T] | None:
    """Select complete items newest-first so the rendered document fits.

    Returns ``None`` when even the empty selection (omission-only document)
    exceeds ``limit``. Never modifies items. Continues after oversized items so
    a smaller older item may still fit. Selected items are returned oldest-first.
    """
    source = tuple(items)
    total = len(source)
    if len(render_document((), total)) > limit:
        return None

    selected_reverse: list[T] = []
    for item in reversed(source):
        candidate = tuple(reversed([*selected_reverse, item]))
        omitted = total - len(candidate)
        if len(render_document(candidate, omitted)) <= limit:
            selected_reverse.append(item)

    selected = tuple(reversed(selected_reverse))
    omitted = total - len(selected)
    rendered = render_document(selected, omitted)
    if len(rendered) > limit:
        raise ValueError("packed document exceeded limit after successful selection")
    return PackedItems(items=selected, omitted=omitted)


def bounded_text(text: str, limit: int) -> str:
    """Return bounded display text. May truncate text."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def bounded_lines(text: str, limit: int) -> str:
    """Return the longest complete prefix of lines fitting within limit.

    Never appends an ellipsis and never emits a partial line. Returns the
    original text unchanged when it fits, or ``""`` when no complete non-empty
    line fits.
    """
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    selected: list[str] = []
    for line in lines:
        if not line.strip():
            if not selected:
                continue
            candidate = "\n".join([*selected, line])
            if len(candidate) > limit:
                break
            selected.append(line)
            continue
        candidate = "\n".join([*selected, line]) if selected else line
        if len(candidate) > limit:
            break
        selected.append(line)
    if not any(line.strip() for line in selected):
        return ""
    return "\n".join(selected)


def newest_lines_within_budget(
    lines: Sequence[str],
    budget: int,
    *,
    separator: str = "\n",
) -> list[str]:
    """Return a contiguous newest suffix in chronological order."""
    if budget <= 0:
        return []
    selected: list[str] = []
    used = 0
    for line in reversed(lines):
        if not line.strip():
            continue
        if not selected:
            if len(line) <= budget:
                selected = [line]
                used = len(line)
            else:
                return [bounded_text(line, budget)]
            continue
        addition = len(separator) + len(line)
        if used + addition > budget:
            break
        selected.insert(0, line)
        used += addition
    if selected and len(separator.join(selected)) > budget:
        return [bounded_text(selected[-1], budget)]
    return selected
