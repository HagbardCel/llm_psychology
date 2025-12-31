"""
API request/response models for HTTP endpoints.

This module defines Pydantic models for API endpoints, separate from
internal workflow models to maintain clean separation of concerns.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Mapping

from pydantic import BaseModel, ConfigDict, Field

from psychoanalyst_app.orchestration.models import WorkflowState


class RequiredWorkflowAction(str, Enum):
    """Actions that clients must perform before the workflow can advance."""

    COMPLETE_PROFILE = "complete_profile"
    SELECT_THERAPY_STYLE = "select_therapy_style"
    START_INTAKE = "start_intake"
    CONTINUE_THERAPY = "continue_therapy"
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

    model_config = ConfigDict(use_enum_values=True)
