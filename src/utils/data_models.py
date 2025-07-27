from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class Message(BaseModel):
    """Represents a single message in a conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime

class Session(BaseModel):
    """Represents a complete therapy session."""
    session_id: str
    user_id: str
    timestamp: datetime
    transcript: List[Message]

class TherapyPlan(BaseModel):
    """Represents a therapy plan created by the Reflection Agent."""
    plan_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    plan_details: Dict[str, Any]  # Flexible structure for plan details
    version: int

class DomainKnowledgeChunk(BaseModel):
    """Represents a chunk of domain knowledge for RAG."""
    id: str
    content: str
    source: str  # e.g., "freud.txt", "jung.txt"
    embedding: Optional[List[float]] = None
