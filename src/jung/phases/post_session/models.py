"""Post-session phase models."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from jung.domain import session_artifacts as _artifacts
from jung.domain.models import Message, Plan, Profile
from jung.domain.text import normalize_content
from jung.phases.transcript import TranscriptTurn
from jung.styles import StyleDefinition

__all__ = [
    "InterventionEvidence",
    "PostSessionInput",
    "PostSessionResult",
    "PostSessionUpdateResult",
    "ResolvedSessionAnalysis",
]


def _non_empty_required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must be non-empty")
    return value


class InterventionEvidence(BaseModel):
    """Ephemeral resolved intervention evidence with full authoritative turns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intervention_description: str = Field(max_length=500)
    therapist_sequence: int = Field(ge=1)
    therapist_content: str
    patient_sequence: int | None = Field(default=None, ge=1)
    patient_content: str | None = None

    @field_validator("intervention_description")
    @classmethod
    def non_empty_description(cls, value: str) -> str:
        return _non_empty_required_text(value)

    @field_validator("therapist_content")
    @classmethod
    def normalize_therapist_content(cls, value: str) -> str:
        value = normalize_content(value)
        if not value:
            raise ValueError("must be non-empty")
        return value

    @field_validator("patient_content")
    @classmethod
    def normalize_patient_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = normalize_content(value)
        if not value:
            raise ValueError("must be non-empty when provided")
        return value

    @model_validator(mode="after")
    def validate_response_reference(self) -> InterventionEvidence:
        sequence_present = self.patient_sequence is not None
        content_present = self.patient_content is not None
        if sequence_present != content_present:
            raise ValueError(
                "patient_sequence and patient_content must both be "
                "present or both absent"
            )
        if (
            self.patient_sequence is not None
            and self.patient_sequence <= self.therapist_sequence
        ):
            raise ValueError("patient_sequence must follow therapist_sequence")
        return self


@dataclass(frozen=True, slots=True)
class ResolvedSessionAnalysis:
    """Internal orchestration value after citation resolution."""

    analysis: _artifacts.SessionAnalysis
    intervention_evidence: tuple[InterventionEvidence, ...]
    selected_patient_turns: tuple[TranscriptTurn, ...]


class PostSessionUpdateResult(BaseModel):
    """Update-call schema: briefing and plan patch only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_briefing: _artifacts.SessionBriefing
    plan_patch: _artifacts.PlanPatch


class PostSessionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review: _artifacts.SessionReview


class PostSessionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    transcript: tuple[TranscriptTurn, ...]
    current_plan: Plan
    profile: Profile
    grounded_patient_messages: tuple[Message, ...] = ()
    prior_session_briefing: _artifacts.SessionBriefing | None = None
    recent_session_summaries: tuple[str, ...] = ()
    selected_style: StyleDefinition

    @model_validator(mode="after")
    def validate_style_matches_plan(self) -> PostSessionInput:
        if self.selected_style.id != self.current_plan.selected_style:
            raise ValueError("selected_style must match current_plan.selected_style")
        return self

    @model_validator(mode="after")
    def validate_transcript(self) -> PostSessionInput:
        sequences = [turn.sequence for turn in self.transcript]
        if any(current >= following for current, following in pairwise(sequences)):
            raise ValueError(
                "transcript sequences must be unique and strictly increasing"
            )
        message_ids = [turn.message_id for turn in self.transcript]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("transcript message IDs must be unique")
        if any(not normalize_content(turn.content) for turn in self.transcript):
            raise ValueError("transcript turn content must be non-empty")
        return self
