from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class UserStatus(str, Enum):
    """User status enum for workflow progression."""
    PROFILE_ONLY = "PROFILE_ONLY"
    INTAKE_COMPLETE = "INTAKE_COMPLETE"
    PLAN_COMPLETE = "PLAN_COMPLETE"

class UserProfile(BaseModel):
    """Represents a user's personal information."""
    user_id: str
    name: str
    birthdate: Optional[datetime] = None
    profession: Optional[str] = None
    status: UserStatus = UserStatus.PROFILE_ONLY
    created_at: datetime
    updated_at: datetime

class Message(BaseModel):
    """Represents a single message in a conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime

class Topic(BaseModel):
    """Represents a topic to be discussed in a session."""
    name: str
    status: str = "pending"  # "pending", "covered", "partially_covered"

class Session(BaseModel):
    """Represents a complete therapy session."""
    session_id: str
    user_id: str
    timestamp: datetime
    transcript: List[Message]
    topics: List[Topic] = []

class TherapyPlan(BaseModel):
    """Represents a therapy plan created by the Reflection Agent."""
    plan_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    plan_details: Dict[str, Any]  # Flexible structure for plan details
    version: int
    selected_therapy_style: Optional[str] = None  # e.g., "freud", "jung", "cbt"

class DomainKnowledgeChunk(BaseModel):
    """Represents a chunk of domain knowledge for RAG."""
    id: str
    content: str
    source: str  # e.g., "freud.md", "jung.md"
    embedding: Optional[List[float]] = None
