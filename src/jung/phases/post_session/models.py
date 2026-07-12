"""Post-session phase models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jung.domain.models import Plan, Profile
from jung.phases.transcript import TranscriptTurn
from jung.styles import StyleDefinition

InterventionStatus = Literal["proposed", "accepted", "completed"]


class InterventionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    intervention: str
    status: InterventionStatus
    patient_quote: str | None = Field(default=None, max_length=500)


class SessionAnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str
    key_themes: tuple[str, ...]
    dominant_affects: tuple[str, ...] = ()
    important_moments: tuple[str, ...] = ()
    patient_insights: tuple[str, ...] = ()
    progress_indicators: tuple[str, ...] = ()
    unresolved_topics: tuple[str, ...] = ()
    interventions_and_responses: tuple[InterventionEvidence, ...] = ()
    safety_or_boundary_notes: tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def non_empty_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary must be non-empty")
        return value


class SessionBriefing(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative_handoff: str
    continuity_points: tuple[str, ...] = ()
    unresolved_issues: tuple[str, ...] = ()
    recommended_opening_focus: str
    things_to_avoid: tuple[str, ...] = ()
    emotional_context: tuple[str, ...] = ()
    intervention_evidence: tuple[InterventionEvidence, ...] = ()


class DerivedProfilePatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observations: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    patient_stated_facts: tuple[str, ...] = ()


class PlanPatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    focus: str | None = None
    themes: tuple[str, ...] | None = None
    goals: tuple[str, ...] | None = None
    current_progress: str | None = None
    planned_interventions: tuple[str, ...] | None = None
    revision_recommendations: tuple[str, ...] | None = None


class PostSessionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_summary: str
    session_briefing: SessionBriefing
    derived_profile_patch: DerivedProfilePatch
    plan_patch: PlanPatch


class PostSessionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    transcript: tuple[TranscriptTurn, ...]
    current_plan: Plan
    profile: Profile
    derived_profile: dict[str, Any] | None = None
    prior_session_briefing: dict[str, Any] | None = None
    recent_session_summaries: tuple[str, ...] = ()
    selected_style: StyleDefinition
