"""Formatting helpers for planning prompts."""

from __future__ import annotations

import re
from typing import Any

from psychoanalyst_app.models.domain import Session


def extract_session_text(session: Session) -> str:
    """Extract text content from session transcript."""
    return "\n".join(f"{msg.role}: {msg.content}" for msg in session.transcript)


def format_plan_details(plan_details: dict[str, Any]) -> str:
    """Format plan details for LLM context."""
    formatted = []
    for key, value in plan_details.items():
        if isinstance(value, (str, int, float)):
            formatted.append(f"{key.title()}: {value}")
    return "\n".join(formatted)


def split_bullets(value: Any) -> list[str]:
    """Extract a short list from an LLM-generated bullet/numbered string."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if not isinstance(value, str):
        return []

    text = value.replace("\r", "\n").strip()
    if not text:
        return []

    inline_numbered = [
        part.strip()
        for part in re.split(r"(?:^|\s+)\d+\s*[\).\:-]\s*", text)
        if part.strip()
    ]
    if len(inline_numbered) > 1:
        return inline_numbered[:5]

    items: list[str] = []
    for raw in text.split("\n"):
        raw = raw.strip()
        if not raw:
            continue
        raw = raw.lstrip("-•* ").strip()
        raw = re.sub(r"^\d+\s*[\).\:-]\s*", "", raw)
        if raw:
            items.append(raw)

    if not items:
        parts = [p.strip() for p in re.split(r"[;,]", text) if p.strip()]
        return parts[:5]
    return items[:5]
