"""Data models for therapeutic memory aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


class SessionContext:
    """Structured context from session analysis."""

    def __init__(
        self,
        session_id: str,
        key_themes: list[str],
        emotional_state: str,
        insights: list[str],
        progress_indicators: list[str],
    ):
        self.session_id = session_id
        self.key_themes = key_themes
        self.emotional_state = emotional_state
        self.insights = insights
        self.progress_indicators = progress_indicators
        self.timestamp = datetime.now()


class TherapeuticMemory:
    """Aggregated memory across multiple sessions."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.session_contexts: list[SessionContext] = []
        self.recurring_themes: dict[str, int] = defaultdict(int)
        self.emotional_patterns: list[str] = []
        self.progress_timeline: list[dict[str, Any]] = []
        self.relationship_quality: str = "building"

    def add_session_context(self, context: SessionContext) -> None:
        """Add new session context to memory."""
        self.session_contexts.append(context)

        for theme in context.key_themes:
            self.recurring_themes[theme] += 1

        if context.emotional_state:
            self.emotional_patterns.append(context.emotional_state)

        self.progress_timeline.append(
            {
                "session_id": context.session_id,
                "timestamp": context.timestamp.isoformat(),
                "indicators": context.progress_indicators,
            }
        )
