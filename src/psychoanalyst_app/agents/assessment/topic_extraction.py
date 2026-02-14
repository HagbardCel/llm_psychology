"""Topic extraction helpers for assessment recommendations."""

from __future__ import annotations

import re
from typing import Any


def extract_key_topics(recommendation: dict[str, Any]) -> list[str]:
    """Extract key topics from recommendation payload with safe fallbacks."""
    for key in ("key_topics", "topics"):
        value = recommendation.get(key)
        if isinstance(value, list):
            topics = [str(item).strip() for item in value if str(item).strip()]
            if topics:
                return topics[:5]

    assessment = recommendation.get("assessment")
    if not isinstance(assessment, str):
        return []

    extracted: list[str] = []
    for line in assessment.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        topic = re.sub(r"^[-*0-9.)\\s]+", "", stripped).strip()
        if not topic:
            continue
        if topic.endswith("."):
            topic = topic[:-1].strip()
        if not topic:
            continue
        extracted.append(topic)
        if len(extracted) == 3:
            break
    return extracted
