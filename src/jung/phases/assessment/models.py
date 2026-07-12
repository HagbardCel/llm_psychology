"""Assessment phase models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jung.domain.models import PlanContent, Profile
from jung.phases.transcript import TranscriptTurn
from jung.styles import StyleDefinition


class StyleRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    style_id: str
    score: float = Field(ge=0.0, le=1.0)
    rationale: str
    key_topics: tuple[str, ...]
    initial_plan: PlanContent

    @field_validator("rationale")
    @classmethod
    def non_empty_rationale(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("rationale must be non-empty")
        return value

    @field_validator("key_topics")
    @classmethod
    def non_empty_topics(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("key_topics must be non-empty")
        return value


class AssessmentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    formulation: str
    presenting_concerns: tuple[str, ...]
    strengths_and_resources: tuple[str, ...]
    risk_or_boundary_notes: tuple[str, ...] = ()
    style_recommendations: tuple[StyleRecommendation, ...]

    @field_validator("formulation")
    @classmethod
    def non_empty_formulation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("formulation must be non-empty")
        return value


class AssessmentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    intake_record: dict[str, Any]
    transcript: tuple[TranscriptTurn, ...]
    profile: Profile
    available_styles: tuple[StyleDefinition, ...]
