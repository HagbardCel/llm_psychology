"""Shared mechanical context-bounding primitives."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence


def bounded_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def bounded_json(document: Mapping[str, object], limit: int) -> str:
    return bounded_text(json.dumps(document, ensure_ascii=True), limit)


def newest_within_budget(items: Sequence[str], budget: int) -> list[str]:
    if budget <= 0 or not items:
        return []
    selected: list[str] = []
    used = 0
    for item in reversed(items):
        if not item.strip():
            continue
        addition = len(item) if not selected else len(item) + 1
        if used + addition > budget:
            break
        selected.insert(0, item)
        used += addition
    return selected
