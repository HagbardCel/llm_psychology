"""Shared mechanical context-bounding primitives."""

from __future__ import annotations

from collections.abc import Sequence


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
