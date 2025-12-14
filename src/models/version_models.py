"""
Pydantic models for version negotiation and compatibility checking.
"""

from typing import Literal

from pydantic import BaseModel, Field


class VersionInfo(BaseModel):
    """
    Backend version information response.

    This is returned by the /api/version endpoint and includes
    the current API version and minimum supported client version.
    """

    api_version: str = Field(
        ...,
        description="Current backend API version (semantic versioning: MAJOR.MINOR.PATCH)",
        example="1.0.0",
    )
    min_client_version: str = Field(
        ...,
        description="Minimum supported client version",
        example="1.0.0",
    )
    server_time: str = Field(
        ...,
        description="Current server timestamp (ISO 8601)",
        example="2025-12-03T10:00:00Z",
    )


class VersionCheckRequest(BaseModel):
    """
    Client version check request.

    Clients send this to verify compatibility with the backend.
    """

    client_version: str = Field(
        ...,
        description="Client's version (semantic versioning: MAJOR.MINOR.PATCH)",
        example="1.0.0",
    )
    client_type: Literal["console", "web"] = Field(
        ..., description="Type of client", example="console"
    )


class VersionCheckResponse(BaseModel):
    """
    Version compatibility check response.

    Indicates whether the client version is compatible with the backend.
    """

    compatible: bool = Field(..., description="Whether versions are compatible")
    api_version: str = Field(..., description="Current backend API version")
    client_version: str = Field(..., description="Client's reported version")
    message: str = Field(
        ...,
        description="Human-readable compatibility message",
        example="Versions are compatible",
    )
    upgrade_required: bool = Field(
        default=False, description="Whether client must upgrade to continue"
    )
    upgrade_recommended: bool = Field(
        default=False,
        description="Whether client upgrade is recommended (but not required)",
    )
