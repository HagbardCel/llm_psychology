"""Therapy phase models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    @model_validator(mode="after")
    def validate_turn_coherence(self) -> TherapyTurnInput:
        if self.is_opening_turn:
            if self.latest_user_message is not None:
                raise ValueError("opening turns must not include latest_user_message")
            if self.transcript:
                raise ValueError(
                    "opening turns must not include active-session transcript"
                )
        elif not (self.latest_user_message and self.latest_user_message.strip()):
            raise ValueError("continuation turns require latest_user_message")
        if self.selected_style.id != self.current_plan.selected_style:
            raise ValueError("selected_style must match current_plan.selected_style")
        return self
