"""
Data models for the orchestration layer.

This module defines the core data structures used by the orchestration
layer to coordinate agents, manage workflow state, and maintain
conversation context.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from models.data_models import Message, TherapyPlan, UserProfile


class WorkflowState(Enum):
    """
    Workflow states for user progression through therapy.

    The workflow progresses through these states:
    NEW → INTAKE_IN_PROGRESS → INTAKE_COMPLETE → ASSESSMENT_IN_PROGRESS →
    ASSESSMENT_COMPLETE → THERAPY_IN_PROGRESS → REFLECTION_IN_PROGRESS →
    PLAN_COMPLETE → (loop back to THERAPY_IN_PROGRESS)
    """

    NEW = "new"
    INTAKE_IN_PROGRESS = "intake_in_progress"
    INTAKE_COMPLETE = "intake_complete"
    ASSESSMENT_IN_PROGRESS = "assessment_in_progress"
    ASSESSMENT_COMPLETE = "assessment_complete"
    THERAPY_IN_PROGRESS = "therapy_in_progress"
    REFLECTION_IN_PROGRESS = "reflection_in_progress"
    PLAN_COMPLETE = "plan_complete"


class WorkflowEvent(Enum):
    """Events that trigger workflow state transitions."""

    START_INTAKE = "start_intake"
    COMPLETE_INTAKE = "complete_intake"
    START_ASSESSMENT = "start_assessment"
    COMPLETE_ASSESSMENT = "complete_assessment"
    START_THERAPY = "start_therapy"
    COMPLETE_SESSION = "complete_session"
    START_REFLECTION = "start_reflection"
    COMPLETE_REFLECTION = "complete_reflection"
    RESUME_THERAPY = "resume_therapy"


@dataclass
class AgentResponse:
    """
    Response from an agent after processing a message.

    Attributes:
        content: The content to send to LLM or return to user
        next_action: What should happen next ("continue", "transition", "complete")
        next_state: Next workflow state (if transitioning)
        metadata: Additional information for orchestrator
    """

    content: str
    next_action: str  # "continue", "transition", "complete"
    next_state: WorkflowState | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationContext:
    """
    Context for a conversation session.

    This contains all information needed for an agent to process
    messages and for the conversation manager to stream responses.

    Attributes:
        session_id: Unique identifier for this session
        user_profile: User's profile information
        therapy_plan: Current therapy plan (if exists)
        message_history: List of messages in this session
        topics_covered: Topics discussed (for intake)
        session_start_time: When this session started
        duration_minutes: Target duration for this session
        extensions_used: Number of time extensions used
        max_extensions: Maximum extensions allowed
    """

    session_id: str
    user_profile: UserProfile
    therapy_plan: TherapyPlan | None
    message_history: list[Message]
    topics_covered: list[str]
    session_start_time: datetime
    duration_minutes: int
    extensions_used: int = 0
    max_extensions: int = 2

    @property
    def time_elapsed_minutes(self) -> float:
        """Calculate minutes elapsed since session start."""
        elapsed = datetime.now() - self.session_start_time
        return elapsed.total_seconds() / 60

    @property
    def time_remaining_minutes(self) -> float:
        """Calculate minutes remaining in session."""
        total_duration = self.duration_minutes + (self.extensions_used * 5)
        return total_duration - self.time_elapsed_minutes

    @property
    def can_extend(self) -> bool:
        """Check if session can be extended."""
        return self.extensions_used < self.max_extensions

    @property
    def is_time_up(self) -> bool:
        """Check if session time is up."""
        return self.time_remaining_minutes <= 0


@dataclass
class SessionInfo:
    """
    Information about a therapy session.

    Attributes:
        session_id: Unique identifier
        agent_type: Type of agent conducting this session
        workflow_state: Current workflow state
        created_at: When session was created
        user_id: User this session belongs to
        has_initial_message: Whether an initial message is being sent from the agent
    """

    session_id: str
    agent_type: str  # AgentType value
    workflow_state: WorkflowState
    created_at: datetime
    user_id: str
    has_initial_message: bool = False

    def to_dict(self):
        """Convert dataclass to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "agent_type": self.agent_type,
            "workflow_state": self.workflow_state.value,
            "created_at": self.created_at.isoformat(),
            "user_id": self.user_id,
            "has_initial_message": self.has_initial_message,
        }


@dataclass
class TherapyStyleRecommendation:
    """
    Recommendation for a therapy style.

    Attributes:
        style_name: Name of the therapy style
        score: Confidence score (0-1)
        explanation: Why this style is recommended
        key_topics: Topics from intake that align with this style
    """

    style_name: str
    score: float
    explanation: str
    key_topics: list[str]
