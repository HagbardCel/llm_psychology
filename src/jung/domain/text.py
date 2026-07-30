"""Neutral text normalization primitives."""

from __future__ import annotations


def normalize_content(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip ends."""
    return " ".join(text.split())
