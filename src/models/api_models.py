"""
API request/response models for HTTP endpoints.

This module defines Pydantic models for API endpoints, separate from
internal workflow models to maintain clean separation of concerns.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class WorkflowNextActionRequest(BaseModel):
    """
    Request for determining the next action in the workflow.

    Attributes:
        user_id: The user's identifier
        current_route: Optional current frontend route for context
    """
    user_id: str = Field(..., description="User identifier")
    current_route: Optional[str] = Field(None, description="Current frontend route")


class WorkflowDisplayAction(BaseModel):
    """
    Display information for a non-navigation action.

    Attributes:
        title: Title to display to user
        description: Optional description text
        primary_action: Optional primary action button configuration
    """
    title: str = Field(..., description="Display title")
    description: Optional[str] = Field(None, description="Display description")
    primary_action: Optional[dict] = Field(None, description="Primary action button config")


class WorkflowNextActionResponse(BaseModel):
    """
    Response indicating what the frontend should do next.

    Attributes:
        action: Type of action ('navigate', 'wait', 'display', 'error')
        route: Optional route to navigate to (for 'navigate' action)
        reason: Optional reason for the action
        display: Optional display information (for 'display' action)
        error: Optional error message (for 'error' action)
    """
    action: Literal['navigate', 'wait', 'display', 'error'] = Field(
        ...,
        description="Action type to perform"
    )
    route: Optional[str] = Field(None, description="Route to navigate to")
    reason: Optional[str] = Field(None, description="Reason for this action")
    display: Optional[WorkflowDisplayAction] = Field(None, description="Display information")
    error: Optional[str] = Field(None, description="Error message")

    class Config:
        """Pydantic configuration."""
        json_schema_extra = {
            "examples": [
                {
                    "action": "navigate",
                    "route": "/intake",
                    "reason": "User needs to complete intake assessment"
                },
                {
                    "action": "wait",
                    "reason": "Session in progress"
                },
                {
                    "action": "display",
                    "display": {
                        "title": "Complete Your Profile",
                        "description": "Please fill in your profile information to continue"
                    }
                },
                {
                    "action": "error",
                    "error": "User not found"
                }
            ]
        }
