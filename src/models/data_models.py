from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class UserStatus(str, Enum):
    """User status enum for workflow progression."""

    PROFILE_ONLY = "PROFILE_ONLY"
    INTAKE_IN_PROGRESS = "INTAKE_IN_PROGRESS"
    INTAKE_COMPLETE = "INTAKE_COMPLETE"
    ASSESSMENT_IN_PROGRESS = "ASSESSMENT_IN_PROGRESS"
    ASSESSMENT_COMPLETE = "ASSESSMENT_COMPLETE"
    THERAPY_IN_PROGRESS = "THERAPY_IN_PROGRESS"
    REFLECTION_IN_PROGRESS = "REFLECTION_IN_PROGRESS"
    PLAN_COMPLETE = "PLAN_COMPLETE"


class UserProfile(BaseModel):
    """Represents a user's personal information."""

    user_id: str
    name: str
    birthdate: datetime | None = None
    profession: str | None = None
    status: UserStatus = UserStatus.PROFILE_ONLY
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    """Represents a single message in a conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    agent: str | None = None  # e.g., "IntakeAgent", "AssessmentAgent", "PsychoanalystAgent"


class Topic(BaseModel):
    """Represents a topic to be discussed in a session."""

    name: str
    status: str = "pending"  # "pending", "covered", "partially_covered"


class Session(BaseModel):
    """Represents a complete therapy session."""

    session_id: str
    user_id: str
    timestamp: datetime
    transcript: list[Message]
    topics: list[Topic] = []


class TherapyPlan(BaseModel):
    """Represents a therapy plan created by the Reflection Agent."""

    plan_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    plan_details: dict[str, Any]  # Flexible structure for plan details
    version: int
    selected_therapy_style: str | None = None  # e.g., "freud", "jung", "cbt"
    session_briefing: dict[str, Any] | None = None  # Session briefing for resumption


class DomainKnowledgeChunk(BaseModel):
    """Represents a chunk of domain knowledge for RAG."""

    id: str
    content: str
    source: str  # e.g., "freud.md", "jung.md"
    embedding: list[float] | None = None
