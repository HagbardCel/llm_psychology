"""Therapy phase models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jung.domain.models import Plan, Profile
from jung.phases.transcript import TranscriptTurn
from jung.styles import StyleDefinition


class TherapyContextLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_transcript_turns: int = Field(default=12, ge=1)
    max_section_chars: int = Field(default=2000, ge=200)
    max_total_chars: int = Field(default=12000, ge=1000)


class TherapyTurnInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: Profile
    derived_profile: dict[str, Any] | None = None
    current_plan: Plan
    session_briefing: dict[str, Any] | None = None
    recent_session_summaries: tuple[str, ...] = ()
    transcript: tuple[TranscriptTurn, ...] = ()
    latest_user_message: str | None = None
    is_opening_turn: bool = False
    selected_style: StyleDefinition
    context_limits: TherapyContextLimits = Field(default_factory=TherapyContextLimits)
