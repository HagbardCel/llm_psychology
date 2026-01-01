"""
HTTP-facing Data Transfer Objects (DTOs) for the REST API.

These models define the stable wire contract that all clients rely on.
They deliberately avoid leaking internal persistence models by exposing
only the fields that should travel over the network.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from psychoanalyst_app.models.api_models import WorkflowNextActionDTO
from psychoanalyst_app.models.data_models import (
    Session,
    TherapyPlan,
    UserProfile,
    UserProfileSummary,
    UserStatus,
)
from psychoanalyst_app.orchestration.models import WorkflowState


class BaseHTTPModel(BaseModel):
    """Base class that allows validation directly from ORM/model instances."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class MessageDTO(BaseHTTPModel):
    role: str
    content: str
    timestamp: datetime
    agent: str | None = None


class TopicDTO(BaseHTTPModel):
    name: str
    status: str = "pending"


class UserProfileDTO(BaseHTTPModel):
    user_id: str
    name: str
    alias: str | None = None
    data_of_birth: datetime | None = None
    gender: str | None = None
    cultural_background: str | None = None
    primary_language: str = "English"
    profession: str | None = None
    status: UserStatus
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


class UserProfileSummaryDTO(BaseHTTPModel):
    user_id: str
    name: str
    status: UserStatus
    primary_language: str = "English"
    plan_id: str | None = None
    updated_at: datetime


class UserProfileListResponseDTO(BaseHTTPModel):
    profiles: list[UserProfileSummaryDTO]


class SessionDTO(BaseHTTPModel):
    session_id: str
    user_id: str
    plan_id: str | None = None
    timestamp: datetime
    transcript: list[MessageDTO] = Field(default_factory=list)
    topics: list[TopicDTO] = Field(default_factory=list)

    session_summary: str | None = None
    session_briefing: dict[str, Any] | None = None
    psychological_summary: str | None = None
    dominant_affects: list[str] = Field(default_factory=list)
    key_themes: list[str] = Field(default_factory=list)
    notable_interactions: str | None = None
    interpretations: str | None = None
    patient_reactions: str | None = None
    enriched: bool = False


class TherapyPlanDTO(BaseHTTPModel):
    plan_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    version: int
    selected_therapy_style: str | None = None
    plan_details: dict[str, Any]
    initial_goals: list[str]
    current_progress: str
    planned_interventions: list[str]
    status: str = "active"
    session_briefing: dict[str, Any] | None = None


class SessionTimerResponseDTO(BaseHTTPModel):
    session_id: str
    elapsed_minutes: float
    remaining_minutes: float
    total_duration_minutes: float
    extensions_used: int
    max_extensions: int
    can_extend: bool
    is_time_up: bool
    timestamp: datetime


class UserStatusResponseDTO(BaseHTTPModel):
    user_id: str
    workflow_state: WorkflowState
    timestamp: datetime


class TherapyStyleDTO(BaseHTTPModel):
    style: str
    name: str
    description: str


class StatusMessageResponseDTO(BaseHTTPModel):
    message: str
    session_id: str | None = None


class HealthCheckResponseDTO(BaseHTTPModel):
    status: str
    service: str
    database: str
    timestamp: datetime


class UserRegisterResponseDTO(BaseHTTPModel):
    session: SessionDTO
    workflow_next_action: WorkflowNextActionDTO


class CreateUserProfileRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    alias: str | None = None
    data_of_birth: datetime | None = None
    gender: str | None = None
    cultural_background: str | None = None
    primary_language: str = Field(..., min_length=1)
    profession: str | None = None
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


class UserLoginRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)


class WorkflowCompleteProfileRequestDTO(CreateUserProfileRequestDTO):
    session_id: str = Field(..., min_length=1)


class UpdateUserProfileRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    alias: str | None = None
    data_of_birth: datetime | None = None
    gender: str | None = None
    cultural_background: str | None = None
    primary_language: str | None = None
    profession: str | None = None
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


class PatchUserProfileRequestDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    name: str | None = None
    alias: str | None = None
    data_of_birth: datetime | None = None
    gender: str | None = None
    cultural_background: str | None = None
    primary_language: str | None = None
    profession: str | None = None
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


class CreateSessionRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)


class WorkflowSelectTherapyStyleRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    selected_therapy_style: str = Field(..., min_length=1)


def user_profile_to_dto(profile: UserProfile) -> UserProfileDTO:
    """Convert internal user profile model to wire DTO."""
    return UserProfileDTO.model_validate(profile)


def user_profile_summary_to_dto(
    profile: UserProfileSummary,
) -> UserProfileSummaryDTO:
    """Convert internal profile summary model to wire DTO."""
    return UserProfileSummaryDTO.model_validate(profile)


def session_to_dto(session: Session) -> SessionDTO:
    """Convert internal session model to wire DTO."""
    return SessionDTO.model_validate(session)


def therapy_plan_to_dto(plan: TherapyPlan) -> TherapyPlanDTO:
    """Convert internal therapy plan model to wire DTO."""
    return TherapyPlanDTO.model_validate(plan)
