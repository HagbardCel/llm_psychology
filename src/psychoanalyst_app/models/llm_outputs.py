"""Structured output and briefing models produced by LLM agents."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from psychoanalyst_app.models.domain import (
    AnalyticFrame,
    BasicPatientBackground,
    EducationalWorkHistory,
    FamilyConstellation,
    RelationalLifeContext,
)


class Tier2Enrichment(BaseModel):
    psychological_summary: str = Field(..., min_length=1, max_length=3000)
    dominant_affects: list[str] = Field(..., min_length=1)
    key_themes: list[str] = Field(..., min_length=1)
    notable_interactions: str | None = Field(None, max_length=1500)
    interpretations: str | None = Field(None, max_length=1000)
    patient_reactions: str | None = Field(None, max_length=1000)


class ChangeDetectionDecision(BaseModel):
    update_needed: bool = False
    change_summary: str | None = Field(default=None, max_length=1000)
    confidence: Literal["high", "medium", "low"] | None = None


class BasicPatientBackgroundPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alias: str | None = Field(default=None, max_length=100)
    date_of_birth: datetime | None = None
    gender: str | None = None
    cultural_background: str | None = Field(default=None, max_length=500)
    primary_language: str = Field(default="English", max_length=50)


class FamilyConstellationPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    parents: str | None = Field(default=None, max_length=1000)
    siblings: str | None = Field(default=None, max_length=500)
    family_atmosphere: str | None = Field(default=None, max_length=1000)
    significant_events: str | None = Field(default=None, max_length=1000)


class EducationalWorkHistoryPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    education: str | None = Field(default=None, max_length=500)
    work_history: str | None = Field(default=None, max_length=1000)
    relationship_to_work: str | None = Field(default=None, max_length=500)


class RelationalLifeContextPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    relationships: str | None = Field(default=None, max_length=1000)
    social_context: str | None = Field(default=None, max_length=500)
    current_situation: str | None = Field(default=None, max_length=1000)


class AnalyticFramePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preferred_school: str | None = None
    boundary_notes: str | None = Field(default=None, max_length=500)
    frame_notes: str | None = Field(default=None, max_length=500)


class Tier1ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    basic_info: BasicPatientBackgroundPatch | None = None
    family: FamilyConstellationPatch | None = None
    history: EducationalWorkHistoryPatch | None = None
    context: RelationalLifeContextPatch | None = None
    frame: AnalyticFramePatch | None = None


class Tier4Extract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    initial_goals: list[str] = Field(..., min_length=1)
    current_progress: str = Field(..., min_length=1, max_length=2000)
    planned_interventions: list[str] = Field(..., min_length=1)
    revision_recommendations: list[str] = Field(default_factory=list)
    status: Literal["active", "paused", "completed", "superseded"] = "active"


class PatientProfileExtract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    basic_info: BasicPatientBackground
    family: FamilyConstellation
    history: EducationalWorkHistory
    context: RelationalLifeContext
    frame: AnalyticFrame


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    focus: str
    goals: list[str] = Field(..., min_length=1)
    techniques: list[str] = Field(..., min_length=1)
    themes: list[str] = Field(default_factory=list)
    timeline: str | None = None


class SessionAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key_themes: list[str] = Field(..., min_length=1)
    emotional_state: str = Field(..., min_length=1)
    insights: list[str] = Field(default_factory=list)
    progress_indicators: list[str] = Field(default_factory=list)


class StructuredUserProfileOutput(BaseModel):
    """Structured profile payload aligned with UserProfile fields."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    alias: str | None = Field(default=None, max_length=100)
    date_of_birth: datetime | None = None
    gender: str | None = None
    cultural_background: str | None = Field(default=None, max_length=500)
    primary_language: str | None = Field(default=None, max_length=50)
    profession: str | None = None
    parents: str | None = Field(default=None, max_length=1000)
    siblings: str | None = Field(default=None, max_length=500)
    family_atmosphere: str | None = Field(default=None, max_length=1000)
    significant_events: str | None = Field(default=None, max_length=1000)
    education: str | None = Field(default=None, max_length=500)
    work_history: str | None = Field(default=None, max_length=1000)
    relationship_to_work: str | None = Field(default=None, max_length=500)
    relationships: str | None = Field(default=None, max_length=1000)
    social_context: str | None = Field(default=None, max_length=500)
    current_situation: str | None = Field(default=None, max_length=1000)
    preferred_school: str | None = None
    boundary_notes: str | None = Field(default=None, max_length=500)
    frame_notes: str | None = Field(default=None, max_length=500)


class StructuredTherapyPlanOutput(BaseModel):
    """Structured plan payload aligned with TherapyPlan content fields."""

    model_config = ConfigDict(extra="ignore")

    selected_therapy_style: str | None = None
    focus: str = Field(..., min_length=1)
    themes: list[str] = Field(default_factory=list)
    timeline: str | None = None
    initial_goals: list[str] = Field(..., min_length=1)
    current_progress: str = Field(..., min_length=1, max_length=2000)
    planned_interventions: list[str] = Field(..., min_length=1)
    revision_recommendations: list[str] = Field(default_factory=list)
    status: Literal["active", "paused", "completed", "superseded"] = "active"


class StyleAssessmentOutput(BaseModel):
    """Structured assessment output for a single therapy style recommendation."""

    model_config = ConfigDict(extra="ignore")

    assessment: str = Field(..., min_length=1, max_length=2000)
    score: float = Field(..., ge=0.0, le=1.0)
    key_topics: list[str] = Field(default_factory=list, max_length=5)


class DeepTopicSignalOutput(BaseModel):
    """Signal for whether the conversation is in a deep/sensitive topic."""

    model_config = ConfigDict(extra="ignore")

    in_deep_topic: bool = False
    confidence: Literal["high", "medium", "low"] | None = None
    rationale: str | None = Field(default=None, max_length=500)


# ============================================================================
# Session Briefing structures
# ============================================================================


class EmotionalSummary(BaseModel):
    """Emotional state tracking across sessions."""

    last_session: str = Field(..., description="Emotional state during last session")
    trend: str = Field(
        ...,
        description="Overall trend: 'improving', 'stable', 'declining', 'fluctuating'",
    )
    note: str = Field(
        ..., max_length=500, description="Contextual note about emotional progression"
    )

    @field_validator("trend")
    @classmethod
    def validate_trend(cls, v: str) -> str:
        allowed_trends = ["improving", "stable", "declining", "fluctuating"]
        if v not in allowed_trends:
            raise ValueError(f"Trend must be one of {allowed_trends}")
        return v


class KeyTheme(BaseModel):
    """Individual therapy theme tracking."""

    theme: str = Field(..., min_length=3, max_length=100)
    status: str = Field(
        ...,
        description="ongoing | newly introduced | underlying | emerging | resolved",
    )
    priority: str = Field(..., description="'high', 'medium', 'low'")
    frequency: int = Field(..., ge=1, description="Number of sessions where discussed")
    first_appearance: str = Field(..., description="Session ID where first discussed")
    last_discussed: str = Field(..., description="Session ID where last discussed")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed_statuses = [
            "ongoing",
            "newly introduced",
            "underlying",
            "emerging",
            "resolved",
        ]
        if v not in allowed_statuses:
            raise ValueError(f"Status must be one of {allowed_statuses}")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        allowed_priorities = ["high", "medium", "low"]
        if v not in allowed_priorities:
            raise ValueError(f"Priority must be one of {allowed_priorities}")
        return v


class RecommendedApproach(BaseModel):
    """Enhanced guidance for the next session."""

    opening_tone: str
    opening_focus: str
    things_to_avoid: str

    suggested_questions: list[str] = Field(max_length=3)
    therapeutic_goals_for_session: list[str] = Field(max_length=3)


class InterventionEvidence(BaseModel):
    """Patient-grounded support for intervention claims."""

    intervention: str
    evidence_level: Literal["proposed", "accepted", "completed"]
    patient_turn_index: int | None = None
    patient_evidence: str | None = None


class SessionBriefing(BaseModel):
    """Complete session briefing for therapy resumption."""

    briefing_type: str = "resumption"
    generated_at: str  # ISO format datetime string
    session_count: int
    last_session_id: str
    last_session_date: str

    narrative_handoff: str = Field(..., min_length=50, max_length=1500)
    patient_observations: str = Field(..., max_length=1000)
    plan_progression_notes: str = Field(..., max_length=1000)

    relationship_quality: str
    continuity_points: list[str] = Field(max_length=10)
    emotional_summary: EmotionalSummary
    key_themes: list[KeyTheme] = Field(max_length=10)
    progress_highlights: list[str] = Field(max_length=10)
    unresolved_issues: list[str] = Field(max_length=10)
    recommended_approach: RecommendedApproach
    intervention_evidence: list[InterventionEvidence]

    @field_validator("continuity_points")
    @classmethod
    def validate_continuity_points(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one continuity point required")
        return v

    @field_validator("key_themes")
    @classmethod
    def validate_key_themes(cls, v: list[KeyTheme]) -> list[KeyTheme]:
        if not v:
            raise ValueError("At least one key theme required")
        return v

    @field_validator("narrative_handoff")
    @classmethod
    def validate_narrative_handoff(cls, v: str) -> str:
        if len(v.strip()) < 50:
            raise ValueError("Narrative handoff too short - needs substantial summary")
        return v
