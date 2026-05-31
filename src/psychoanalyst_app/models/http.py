"""HTTP-facing models: request/response DTOs, version negotiation, and workflow actions.

These models define the stable wire contract that all clients rely on.
They deliberately avoid leaking internal persistence models by exposing
only the fields that should travel over the network.
"""

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from psychoanalyst_app.models.domain import (
    Session,
    TherapyPlan,
    UserProfile,
    UserProfileSummary,
    UserStatus,
)
from psychoanalyst_app.orchestration.models import WorkflowState


# ============================================================================
# Version negotiation
# ============================================================================


class VersionInfo(BaseModel):
    """Backend version information response."""

    api_version: str = Field(
        ...,
        description="Current backend API version (semantic versioning: MAJOR.MINOR.PATCH)",
        json_schema_extra={"example": "1.0.0"},
    )
    min_client_version: str = Field(
        ...,
        description="Minimum supported client version",
        json_schema_extra={"example": "1.0.0"},
    )
    server_time: str = Field(
        ...,
        description="Current server timestamp (ISO 8601)",
        json_schema_extra={"example": "2025-12-03T10:00:00Z"},
    )


class VersionCheckRequest(BaseModel):
    """Client version check request."""

    client_version: str = Field(
        ...,
        description="Client's version (semantic versioning: MAJOR.MINOR.PATCH)",
        json_schema_extra={"example": "1.0.0"},
    )
    client_type: Literal["console", "web"] = Field(
        ..., description="Type of client", json_schema_extra={"example": "console"}
    )


class VersionCheckResponse(BaseModel):
    """Version compatibility check response."""

    compatible: bool = Field(..., description="Whether versions are compatible")
    api_version: str = Field(..., description="Current backend API version")
    client_version: str = Field(..., description="Client's reported version")
    message: str = Field(
        ...,
        description="Human-readable compatibility message",
        json_schema_extra={"example": "Versions are compatible"},
    )
    upgrade_required: bool = Field(
        default=False, description="Whether client must upgrade to continue"
    )
    upgrade_recommended: bool = Field(
        default=False,
        description="Whether client upgrade is recommended (but not required)",
    )


# ============================================================================
# Workflow next-action contract
# ============================================================================


class RequiredWorkflowAction(str, Enum):
    """Actions that clients must perform before the workflow can advance."""

    COMPLETE_PROFILE = "complete_profile"
    SELECT_THERAPY_STYLE = "select_therapy_style"
    START_INTAKE = "start_intake"
    START_THERAPY = "start_therapy"
    CONTINUE_THERAPY = "continue_therapy"
    RETRY_PLAN_UPDATE = "retry_plan_update"
    WAIT = "wait"


class WorkflowNextActionDTO(BaseModel):
    """Payload describing what the backend expects the client to do next."""

    user_id: str = Field(..., description="User identifier")
    workflow_state: WorkflowState = Field(
        ..., description="Current workflow state value"
    )
    required_action: RequiredWorkflowAction = Field(
        ..., description="Action the client is required to perform"
    )
    required_fields: list[str] = Field(
        default_factory=list, description="Fields that must be provided before advancing"
    )
    defaults: Mapping[str, str] | None = Field(
        None,
        description="Optional defaults usable to pre-fill the required fields",
    )
    prompt: Optional[str] = Field(
        None, description="Human-friendly prompt describing what should happen next"
    )
    blocking: bool = Field(
        True,
        description="Indicates whether the workflow must wait for this action before continuing",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this instruction was evaluated",
    )
    session_id: str | None = Field(
        None,
        description="Session receiving this workflow instruction, when available",
    )
    state_signature: str = Field(
        "",
        description="Stable identity for equivalent workflow instructions",
    )
    emission_source: str | None = Field(
        None,
        description="Backend path that emitted the workflow event, when applicable",
    )

    model_config = ConfigDict(use_enum_values=True)

    @model_validator(mode="after")
    def populate_state_signature(self) -> "WorkflowNextActionDTO":
        """Build an identity that is stable across repeated evaluations."""
        if self.state_signature:
            return self
        payload = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "workflow_state": self.workflow_state,
            "required_action": self.required_action,
            "required_fields": self.required_fields,
            "defaults": self.defaults,
            "prompt": self.prompt,
            "blocking": self.blocking,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.state_signature = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return self


# ============================================================================
# HTTP DTOs
# ============================================================================


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
    date_of_birth: datetime | None = None
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
    session_type: str
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
    supersedes_plan_id: str | None = None
    superseded_by_plan_id: str | None = None
    selected_therapy_style: str | None = None
    plan_details: dict[str, Any]
    initial_goals: list[str]
    current_progress: str
    planned_interventions: list[str]
    revision_recommendations: list[str] = Field(default_factory=list)
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
    date_of_birth: datetime | None = None
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
    date_of_birth: datetime | None = None
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
    date_of_birth: datetime | None = None
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


class EndSessionRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    reason: str | None = None


class EndSessionResponseDTO(BaseHTTPModel):
    session_id: str
    workflow_state: str
    reason: str


class WorkflowSelectTherapyStyleRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    selected_therapy_style: str = Field(..., min_length=1)


class WorkflowStartTherapyRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)


class WorkflowRetryPlanUpdateRequestDTO(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)


class WorkflowStartTherapyResponseDTO(BaseHTTPModel):
    session: SessionDTO
    workflow_next_action: WorkflowNextActionDTO


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
