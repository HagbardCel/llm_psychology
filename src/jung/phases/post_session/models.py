"""Post-session phase models."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from jung.domain.grounding import GroundedPatientTurn
from jung.domain.models import Plan, Profile
from jung.domain.session_artifacts import (
    InterventionEvidence,
    InterventionStatus,
    SessionBriefing,
)
from jung.phases.transcript import TranscriptTurn, normalize_transcript_content
from jung.styles import StyleDefinition

__all__ = [
    "DerivedProfilePatch",
    "InterventionCitation",
    "InterventionEvidence",
    "InterventionStatus",
    "PatientTurnCitation",
    "PlanPatch",
    "PostSessionInput",
    "PostSessionResult",
    "PostSessionUpdateResult",
    "ResolvedSessionAnalysis",
    "SessionAnalysisResult",
    "SessionBriefing",
    "SessionBriefingDraft",
]

_MAX_EVIDENCE_ITEMS = 20


def _non_empty_required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must be non-empty")
    return value


class InterventionCitation(BaseModel):
    """Model-facing sequence citation for an intervention.

    ``intervention_description`` is a model-generated interpretation. The
    backend resolves cited turn sequences to authoritative full-turn content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intervention_description: str = Field(max_length=500)
    therapist_sequence: int = Field(ge=1)
    patient_sequence: int | None = Field(default=None, ge=1)

    @field_validator("intervention_description")
    @classmethod
    def non_empty_description(cls, value: str) -> str:
        return _non_empty_required_text(value)


class PatientTurnCitation(BaseModel):
    """Model-facing citation of a patient turn by sequence only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    patient_sequence: int = Field(ge=1)


class SessionAnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str
    key_themes: tuple[str, ...]
    dominant_affects: tuple[str, ...] = ()
    important_moments: tuple[str, ...] = ()
    patient_insights: tuple[str, ...] = ()
    progress_indicators: tuple[str, ...] = ()
    unresolved_topics: tuple[str, ...] = ()
    intervention_citations: tuple[InterventionCitation, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE_ITEMS,
    )
    patient_turn_citations: tuple[PatientTurnCitation, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE_ITEMS,
    )
    safety_or_boundary_notes: tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def non_empty_summary(cls, value: str) -> str:
        return _non_empty_required_text(value)


@dataclass(frozen=True, slots=True)
class ResolvedSessionAnalysis:
    """Internal orchestration value after citation resolution."""

    analysis: SessionAnalysisResult
    intervention_evidence: tuple[InterventionEvidence, ...]
    grounded_patient_turns: tuple[GroundedPatientTurn, ...]


class SessionBriefingDraft(BaseModel):
    """Update-call briefing fields without intervention evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative_handoff: str
    continuity_points: tuple[str, ...] = ()
    unresolved_issues: tuple[str, ...] = ()
    recommended_opening_focus: str
    things_to_avoid: tuple[str, ...] = ()
    emotional_context: tuple[str, ...] = ()

    @field_validator("narrative_handoff", "recommended_opening_focus")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        return _non_empty_required_text(value)


class DerivedProfilePatch(BaseModel):
    """Processor-composed durable profile patch.

    Contains grounded patient turns only — not verified facts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    grounded_patient_turns: tuple[GroundedPatientTurn, ...] = ()


class PlanPatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    focus: str | None = None
    themes: tuple[str, ...] | None = None
    goals: tuple[str, ...] | None = None
    current_progress: str | None = None
    planned_interventions: tuple[str, ...] | None = None
    revision_recommendations: tuple[str, ...] | None = None


class PostSessionUpdateResult(BaseModel):
    """Update-call schema: briefing draft and plan patch only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_briefing: SessionBriefingDraft
    plan_patch: PlanPatch


class PostSessionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_summary: str
    session_briefing: SessionBriefing
    derived_profile_patch: DerivedProfilePatch
    plan_patch: PlanPatch

    @field_validator("session_summary")
    @classmethod
    def non_empty_session_summary(cls, value: str) -> str:
        return _non_empty_required_text(value)


class PostSessionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    transcript: tuple[TranscriptTurn, ...]
    current_plan: Plan
    profile: Profile
    derived_profile: dict[str, Any] | None = None
    prior_session_briefing: dict[str, Any] | None = None
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
        if any(
            not normalize_transcript_content(turn.content) for turn in self.transcript
        ):
            raise ValueError("transcript turn content must be non-empty")
        return self
