"""Authentication result models."""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class AuthResult:
    """Result of an authentication operation."""
    success: bool
    message: str
    token: Optional[str] = None
    user_info: Optional[Dict[str, Any]] = None
    

@dataclass  
class CreateUserResult:
    """Result of user creation operation."""
    success: bool
    message: str
    user_id: Optional[str] = None


@dataclass
class PasswordChangeResult:
    """Result of password change operation."""
    success: bool
    message: str


@dataclass
class TokenValidationResult:
    """Result of token validation."""
    valid: bool
    expired: bool = False
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class SessionInfo:
    """Information about an active session."""
    username: str
    token: str
    created_at: str
    expires_at: str
    last_activity: str
