"""Core domain models for the psychoanalyst application.

These models describe the persistent business entities (users, sessions,
therapy plans, patient analysis) and the lifecycle/status enums that drive
workflow progression.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from psychoanalyst_app.models.intake_record import IntakeRecord


class UserStatus(str, Enum):
    """User status enum for workflow progression."""

    PROFILE_ONLY = "PROFILE_ONLY"
    INTAKE_IN_PROGRESS = "INTAKE_IN_PROGRESS"
    INTAKE_COMPLETE = "INTAKE_COMPLETE"
    ASSESSMENT_IN_PROGRESS = "ASSESSMENT_IN_PROGRESS"
    ASSESSMENT_COMPLETE = "ASSESSMENT_COMPLETE"
    INITIAL_PLAN_COMPLETE = "INITIAL_PLAN_COMPLETE"
    THERAPY_IN_PROGRESS = "THERAPY_IN_PROGRESS"
    PLAN_UPDATE_IN_PROGRESS = "PLAN_UPDATE_IN_PROGRESS"
    REFLECTION_IN_PROGRESS = "REFLECTION_IN_PROGRESS"
    PLAN_UPDATE_FAILED = "PLAN_UPDATE_FAILED"
    PLAN_UPDATE_COMPLETE = "PLAN_UPDATE_COMPLETE"


class BriefingStatus(Enum):
    """Status of a session briefing based on its age."""

    FRESH = "fresh"
    STALE = "stale"
    VERY_STALE = "very_stale"
    INVALID = "invalid"


class UserProfile(BaseModel):
    """Represents a user's personal information."""

    user_id: str
    name: str
    alias: str | None = None
    date_of_birth: datetime | None = None
    gender: str | None = None
    cultural_background: str | None = None
    primary_language: str = "English"
    profession: str | None = None
    status: UserStatus = UserStatus.PROFILE_ONLY
    plan_id: str | None = None

    parents: str | None = None
    siblings: str | None = None
    family_atmosphere: str | None = None
    significant_events: str | None = None

    education: str | None = None
    work_history: str | None = None
    relationship_to_work: str | None = None
    relationships: str | None = None
    social_context: str | None = None
    current_situation: str | None = None

    preferred_school: str | None = None
    boundary_notes: str | None = None
    frame_notes: str | None = None

    created_at: datetime
    updated_at: datetime


class UserProfileSummary(BaseModel):
    """Lightweight summary for profile listings."""

    user_id: str
    name: str
    status: UserStatus = UserStatus.PROFILE_ONLY
    primary_language: str = "English"
    plan_id: str | None = None
    updated_at: datetime


class Message(BaseModel):
    """Represents a single message in a conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    agent: str | None = None  # e.g., "IntakeAgent", "AssessmentAgent", "TherapistAgent"


class Topic(BaseModel):
    """Represents a topic to be discussed in a session."""

    name: str
    status: str = "pending"  # "pending", "covered", "partially_covered"


class Session(BaseModel):
    """Represents a complete therapy session."""

    session_id: str
    user_id: str
    session_type: Literal["intake", "therapy"] = "intake"
    plan_id: str | None = None
    timestamp: datetime
    transcript: list[Message]
    topics: list[Topic] = Field(default_factory=list)
    session_summary: str | None = Field(
        None,
        max_length=4000,
        description="Reflection summary persisted after the session completes",
    )
    session_briefing: dict[str, Any] | None = Field(
        None, description="Structured briefing generated for the next session"
    )
    intake_record: IntakeRecord | None = Field(
        default=None,
        description="Structured incremental intake record for intake sessions",
    )
    intake_record_updated_at: datetime | None = None

    # Tier 2 enrichment fields (added by Reflection Agent)
    psychological_summary: str | None = Field(
        None,
        max_length=3000,
        description="2-3 paragraph clinical summary of session content",
    )
    dominant_affects: list[str] = Field(
        default_factory=list,
        description="Primary emotional states observed (e.g., 'anxiety', 'sadness')",
    )
    key_themes: list[str] = Field(
        default_factory=list, description="Major themes and concerns discussed"
    )
    notable_interactions: str | None = Field(
        None,
        max_length=1500,
        description="Significant transference/countertransference moments",
    )
    interpretations: str | None = Field(
        None,
        max_length=1000,
        description="Interpretations offered during session",
    )
    patient_reactions: str | None = Field(
        None,
        max_length=1000,
        description="Patient responses to interventions",
    )
    enriched: bool = Field(
        default=False, description="Flag indicating Tier 2 data has been added"
    )


class TherapyPlan(BaseModel):
    """Unified therapy plan model (Tier 4 treatment trajectory)."""

    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    user_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    version: int = 1
    supersedes_plan_id: str | None = None
    superseded_by_plan_id: str | None = None
    selected_therapy_style: str | None = None  # e.g., "freud", "jung", "cbt"
    focus: str = Field(..., min_length=1, description="Current therapeutic focus")
    themes: list[str] = Field(
        default_factory=list,
        description="Themes currently tracked by the treatment plan",
    )
    timeline: str | None = Field(
        default=None,
        description="Optional planning horizon generated by the planning agent",
    )
    initial_goals: list[str] = Field(
        ...,
        min_length=1,
        description="Therapeutic goals identified during assessment",
    )
    current_progress: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Qualitative assessment of progress toward goals",
    )
    planned_interventions: list[str] = Field(
        ...,
        min_length=1,
        description="Planned therapeutic interventions or directions",
    )
    revision_recommendations: list[str] = Field(default_factory=list)
    status: str = Field(
        default="active",
        pattern="^(active|paused|completed|superseded)$",
        description="Treatment status",
    )
    session_briefing: dict[str, Any] | None = None  # Session briefing for resumption


# ============================================================================
# TIER 1: Static Background (Low Volatility)
# ============================================================================


class BasicPatientBackground(BaseModel):
    """Core demographic and identity information."""

    alias: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Patient pseudonym for confidentiality",
    )
    date_of_birth: datetime | None = Field(
        None,
        description="Date of birth for age calculation",
    )
    gender: str | None = Field(None, description="Gender identity")
    cultural_background: str | None = Field(
        None,
        max_length=500,
        description="Cultural, ethnic, or religious background",
    )
    primary_language: str = Field(
        default="English",
        max_length=50,
        description="Primary language spoken",
    )


class FamilyConstellation(BaseModel):
    """Family background and dynamics."""

    parents: str | None = Field(
        None,
        max_length=1000,
        description="Information about parents (alive, deceased, relationship quality)",
    )
    siblings: str | None = Field(
        None,
        max_length=500,
        description="Siblings and birth order",
    )
    family_atmosphere: str | None = Field(
        None,
        max_length=1000,
        description="Emotional climate of family of origin",
    )
    significant_events: str | None = Field(
        None,
        max_length=1000,
        description="Major family events (trauma, loss, disruptions)",
    )


class EducationalWorkHistory(BaseModel):
    """Educational and occupational background."""

    education: str | None = Field(
        None,
        max_length=500,
        description="Educational history and achievements",
    )
    work_history: str | None = Field(
        None,
        max_length=1000,
        description="Career history and major job transitions",
    )
    relationship_to_work: str | None = Field(
        None,
        max_length=500,
        description=(
            "Psychological relationship to work (identity, conflict, satisfaction)"
        ),
    )


class RelationalLifeContext(BaseModel):
    """Current relational and social context."""

    relationships: str | None = Field(
        None,
        max_length=1000,
        description="Romantic relationships, friendships, significant others",
    )
    social_context: str | None = Field(
        None,
        max_length=500,
        description="Social network, isolation, community involvement",
    )
    current_situation: str | None = Field(
        None,
        max_length=1000,
        description="Current life circumstances and stressors",
    )


class AnalyticFrame(BaseModel):
    """Therapeutic frame and preferences."""

    preferred_school: str | None = Field(
        None,
        description="Preferred therapeutic approach if specified",
    )
    boundary_notes: str | None = Field(
        None,
        max_length=500,
        description="Special boundary considerations",
    )
    frame_notes: str | None = Field(
        None,
        max_length=500,
        description="Other frame-related notes",
    )


# ============================================================================
# TIER 3: Dynamic Analysis (High Volatility, Versioned)
# ============================================================================


class CurrentFocus(BaseModel):
    """Current therapeutic focus and salience."""

    theme: str = Field(..., max_length=200, description="Central theme or concern")
    salience: str = Field(
        ...,
        max_length=500,
        description="Why this theme is salient now",
    )


class TransferenceImpressions(BaseModel):
    """Observations about transference patterns."""

    idealization: str | None = Field(
        None,
        max_length=500,
        description="Idealizing transference patterns",
    )
    devaluation: str | None = Field(
        None,
        max_length=500,
        description="Devaluing transference patterns",
    )
    boundaries: str | None = Field(
        None,
        max_length=500,
        description="Boundary testing or violations",
    )
    other_patterns: str | None = Field(
        None,
        max_length=1000,
        description="Other notable transference dynamics",
    )


class RecurringNarrative(BaseModel):
    """A recurring story or theme in patient's discourse."""

    title: str = Field(
        ...,
        max_length=100,
        description="Short label for this narrative",
    )
    description: str = Field(
        ...,
        max_length=1000,
        description="Description of the narrative and its significance",
    )
    first_appeared: str | None = Field(
        None,
        description="When this narrative first emerged (session ID or date)",
    )


class DefensiveOrganization(BaseModel):
    """Defensive patterns and coping mechanisms."""

    primary_defenses: list[str] = Field(
        default_factory=list,
        description=(
            "Main defense mechanisms (e.g., 'intellectualization', 'projection')"
        ),
    )
    defensive_style: str | None = Field(
        None,
        max_length=500,
        description="Overall defensive organization",
    )
    flexibility: str | None = Field(
        None,
        max_length=300,
        description="Rigidity vs flexibility of defenses",
    )


class AnalyticOrientation(BaseModel):
    """Therapeutic stance and approach recommendations."""

    pacing: str | None = Field(
        None,
        max_length=300,
        description="Recommended pace of intervention",
    )
    risk_areas: list[str] = Field(
        default_factory=list,
        description="Areas requiring caution",
    )
    key_questions: list[str] = Field(
        default_factory=list,
        description="Important questions to explore",
    )


class PatientAnalysis(BaseModel):
    """
    Tier 3: Dynamic clinical formulation.

    The analyst's evolving understanding of the patient.
    Versioned - new version created when understanding shifts.
    """

    current_focus: CurrentFocus
    transference: TransferenceImpressions
    narratives: list[RecurringNarrative] = Field(default_factory=list)
    defenses: DefensiveOrganization
    orientation: AnalyticOrientation


class PatientAnalysisVersion(BaseModel):
    """
    Versioned wrapper for PatientAnalysis.

    Tracks evolution of clinical understanding over time.
    """

    analysis_id: str = Field(
        default_factory=lambda: f"analysis_{uuid.uuid4().hex[:12]}",
    )
    user_id: str
    version: int = Field(..., ge=1, description="Version number (1, 2, 3, ...)")
    analysis_data: PatientAnalysis
    created_at: datetime = Field(default_factory=datetime.now)
    created_by_session: str | None = Field(
        None,
        description="Session ID that triggered this version",
    )
    change_summary: str | None = Field(
        None,
        max_length=1000,
        description="What changed from previous version",
    )
    superseded_by: str | None = Field(
        None,
        description="Analysis ID of next version (if superseded)",
    )
