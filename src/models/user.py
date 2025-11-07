"""User model for authentication system."""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any
import json


@dataclass
class User:
    """User model with authentication information."""
    username: str
    password_hash: str
    full_name: str
    email: Optional[str] = None
    created_at: datetime = None
    last_login: Optional[datetime] = None
    is_active: bool = True
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    
    def __post_init__(self):
        """Initialize created_at if not provided."""
        if self.created_at is None:
            self.created_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert user to dictionary for storage."""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        if data['created_at']:
            data['created_at'] = data['created_at'].isoformat()
        if data['last_login']:
            data['last_login'] = data['last_login'].isoformat()
        if data['locked_until']:
            data['locked_until'] = data['locked_until'].isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """Create user from dictionary data."""
        # Convert ISO strings back to datetime objects
        if data.get('created_at'):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('last_login'):
            data['last_login'] = datetime.fromisoformat(data['last_login'])
        if data.get('locked_until'):
            data['locked_until'] = datetime.fromisoformat(data['locked_until'])
        
        return cls(**data)
    
    def to_safe_dict(self) -> Dict[str, Any]:
        """Convert user to safe dictionary (no password hash)."""
        safe_data = self.to_dict()
        safe_data.pop('password_hash', None)
        return safe_data
    
    def is_locked(self) -> bool:
        """Check if account is currently locked."""
        if not self.locked_until:
            return False
        return datetime.now() < self.locked_until
    
    def can_login(self) -> bool:
        """Check if user can attempt login."""
        return self.is_active and not self.is_locked()


@dataclass
class CreateUserRequest:
    """Request model for user creation."""
    username: str
    password: str
    full_name: str
    email: Optional[str] = None


@dataclass
class LoginRequest:
    """Request model for user login."""
    username: str
    password: str


@dataclass
class ChangePasswordRequest:
    """Request model for password change."""
    current_password: str
    new_password: str
