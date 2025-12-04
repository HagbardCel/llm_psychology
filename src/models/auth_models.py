"""Authentication models for JWT-based authentication system."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Request model for user login."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class RegisterRequest(BaseModel):
    """Request model for user registration."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=1, max_length=100)


class LoginResponse(BaseModel):
    """Response model for successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class TokenPayload(BaseModel):
    """JWT token payload structure."""

    user_id: str
    username: str
    exp: int  # Expiration timestamp
    iat: int  # Issued at timestamp


class UserCredentials(BaseModel):
    """User credentials stored in database."""

    user_id: str
    username: str
    password_hash: str
    created_at: datetime
    last_login: Optional[datetime] = None


class UserInfo(BaseModel):
    """Public user information (no sensitive data)."""

    user_id: str
    username: str
    created_at: datetime
    last_login: Optional[datetime] = None
