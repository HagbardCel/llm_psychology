"""
API request/response models for HTTP endpoints.

This module defines Pydantic models for API endpoints, separate from
internal workflow models to maintain clean separation of concerns.
"""

from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Optional, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from psychoanalyst_app.orchestration.models import WorkflowState


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
    """
    Payload describing what the backend expects the client to do next.

    Attributes:
        user_id: User identifier.
        workflow_state: Current workflow state.
        required_action: Action the client must perform.
        required_fields: Fields the client must collect for the action.
        defaults: Optional default values for the required fields.
        prompt: Optional copy describing the work to do.
        blocking: Whether this action must be completed before the client can continue other activities.
        timestamp: When the action was generated.
        session_id: Session receiving the instruction, when available.
        state_signature: Stable identity for suppressing duplicate state displays.
        emission_source: Backend path that emitted the event, when applicable.
    """

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
