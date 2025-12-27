"""Data models for planning helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PlanEvolution:
    """Tracks the evolution of a therapy plan over time."""

    plan_id: str
    version: int
    changes: list[str]
    rationale: str
    effectiveness_score: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PlanningStrategy:
    """Defines a strategy for therapy planning based on style and context."""

    therapy_style: str
    focus_areas: list[str]
    techniques: list[str]
    assessment_criteria: list[str]
    created_at: datetime = field(default_factory=datetime.now)

