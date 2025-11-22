"""Pydantic models for session briefing validation and type safety."""

from enum import Enum

from pydantic import BaseModel, Field, validator


class BriefingStatus(Enum):
    """Status of a session briefing based on its age."""

    FRESH = "fresh"
    STALE = "stale"
    VERY_STALE = "very_stale"
    INVALID = "invalid"


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

    @validator("trend")
    def validate_trend(cls, v):
        allowed_trends = ["improving", "stable", "declining", "fluctuating"]
        if v not in allowed_trends:
            raise ValueError(f"Trend must be one of {allowed_trends}")
        return v


class KeyTheme(BaseModel):
    """Individual therapy theme tracking."""

    theme: str = Field(..., min_length=3, max_length=100)
    status: str = Field(
        ...,
        description="'ongoing', 'newly introduced', 'underlying', 'emerging', 'resolved'",
    )
    priority: str = Field(..., description="'high', 'medium', 'low'")
    frequency: int = Field(..., ge=1, description="Number of sessions where discussed")
    first_appearance: str = Field(..., description="Session ID where first discussed")
    last_discussed: str = Field(..., description="Session ID where last discussed")

    @validator("status")
    def validate_status(cls, v):
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

    @validator("priority")
    def validate_priority(cls, v):
        allowed_priorities = ["high", "medium", "low"]
        if v not in allowed_priorities:
            raise ValueError(f"Priority must be one of {allowed_priorities}")
        return v


class RecommendedApproach(BaseModel):
    """Enhanced guidance for the next session."""

    opening_tone: str
    opening_focus: str
    things_to_avoid: str

    # More explicit guidance
    suggested_questions: list[str] = Field(max_items=3)
    therapeutic_goals_for_session: list[str] = Field(max_items=3)


class SessionBriefing(BaseModel):
    """Complete session briefing for therapy resumption."""

    briefing_type: str = "resumption"
    generated_at: str  # ISO format datetime string
    session_count: int
    last_session_id: str
    last_session_date: str

    # Rich analytical fields
    narrative_handoff: str = Field(..., min_length=50, max_length=1500)
    patient_observations: str = Field(..., max_length=1000)
    plan_progression_notes: str = Field(..., max_length=1000)

    relationship_quality: str
    continuity_points: list[str] = Field(max_items=10)
    emotional_summary: EmotionalSummary
    key_themes: list[KeyTheme] = Field(max_items=10)
    progress_highlights: list[str] = Field(max_items=10)
    unresolved_issues: list[str] = Field(max_items=10)
    recommended_approach: RecommendedApproach

    @validator("continuity_points")
    def validate_continuity_points(cls, v):
        if not v:
            raise ValueError("At least one continuity point required")
        return v

    @validator("key_themes")
    def validate_key_themes(cls, v):
        if not v:
            raise ValueError("At least one key theme required")
        return v

    @validator("narrative_handoff")
    def validate_narrative_handoff(cls, v):
        if len(v.strip()) < 50:
            raise ValueError("Narrative handoff too short - needs substantial summary")
        return v
