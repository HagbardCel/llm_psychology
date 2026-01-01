"""Validation helpers for structured agent outputs."""

from __future__ import annotations

from typing import Any

from psychoanalyst_app.models.data_models import UserProfile
from psychoanalyst_app.models.structured_output_models import (
    StructuredTherapyPlanOutput,
    StructuredUserProfileOutput,
)
from psychoanalyst_app.orchestration.profile_helpers import parse_date_of_birth


def build_user_profile_output(payload: Any) -> StructuredUserProfileOutput:
    """Parse and normalize a structured user profile payload."""
    if isinstance(payload, StructuredUserProfileOutput):
        return payload

    if isinstance(payload, dict):
        normalized = dict(payload)
        data_of_birth = normalized.get("data_of_birth")
        if isinstance(data_of_birth, str) and data_of_birth:
            normalized["data_of_birth"] = parse_date_of_birth(data_of_birth)
        normalized.setdefault("primary_language", "English")
        return StructuredUserProfileOutput.model_validate(normalized)

    return StructuredUserProfileOutput.model_validate(payload)


def build_therapy_plan_output(payload: Any) -> StructuredTherapyPlanOutput:
    """Parse and normalize a structured therapy plan payload."""
    if isinstance(payload, StructuredTherapyPlanOutput):
        return payload
    return StructuredTherapyPlanOutput.model_validate(payload)


def is_profile_complete(profile: UserProfile) -> bool:
    """Check if required profile fields are present to advance workflow."""
    name = (profile.name or "").strip()
    if not name or name.lower() == "guest":
        return False
    if not profile.primary_language:
        return False
    return True
