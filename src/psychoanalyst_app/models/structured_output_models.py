from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from psychoanalyst_app.models.data_models import (
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
    data_of_birth: datetime | None = None
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
    status: Literal["active", "paused", "completed"] = "active"


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
    goals: str
    techniques: str
    themes: str
    timeline: str


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
    data_of_birth: datetime | None = None
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
    plan_details: dict[str, Any]
    initial_goals: list[str] = Field(..., min_length=1)
    current_progress: str = Field(..., min_length=1, max_length=2000)
    planned_interventions: list[str] = Field(..., min_length=1)
    status: Literal["active", "paused", "completed"] = "active"
