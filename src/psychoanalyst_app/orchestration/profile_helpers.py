"""Helpers for merging user profile updates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psychoanalyst_app.models.data_models import UserProfile, UserStatus


def parse_date_of_birth(value: str | datetime | None) -> datetime | None:
    """Normalize date-of-birth values into datetime when possible."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def merge_user_profile(
    *,
    existing_profile: UserProfile | None,
    user_id: str,
    updates: dict[str, Any],
) -> UserProfile:
    """Merge incoming user profile fields with an existing profile."""
    created_at = existing_profile.created_at if existing_profile else datetime.now()
    status = existing_profile.status if existing_profile else UserStatus.PROFILE_ONLY

    def pick_optional(field: str, default: Any = None) -> Any:
        value = updates.get(field)
        if value is None:
            return getattr(existing_profile, field) if existing_profile else default
        return value

    data_of_birth = parse_date_of_birth(updates.get("data_of_birth"))
    if data_of_birth is None and existing_profile:
        data_of_birth = existing_profile.data_of_birth

    name = updates.get("name") or (
        existing_profile.name if existing_profile else user_id
    )
    profession = updates.get("profession") or (
        existing_profile.profession if existing_profile else None
    )
    primary_language = updates.get("primary_language") or (
        existing_profile.primary_language if existing_profile else "English"
    )
    session_mode = updates.get("session_mode") or (
        existing_profile.session_mode if existing_profile else "virtual"
    )

    return UserProfile(
        user_id=user_id,
        name=name,
        data_of_birth=data_of_birth,
        profession=profession,
        alias=pick_optional("alias"),
        gender=pick_optional("gender"),
        cultural_background=pick_optional("cultural_background"),
        primary_language=primary_language,
        parents=pick_optional("parents"),
        siblings=pick_optional("siblings"),
        family_atmosphere=pick_optional("family_atmosphere"),
        significant_events=pick_optional("significant_events"),
        education=pick_optional("education"),
        work_history=pick_optional("work_history"),
        relationship_to_work=pick_optional("relationship_to_work"),
        relationships=pick_optional("relationships"),
        social_context=pick_optional("social_context"),
        current_situation=pick_optional("current_situation"),
        preferred_school=pick_optional("preferred_school"),
        session_mode=session_mode,
        boundary_notes=pick_optional("boundary_notes"),
        frame_notes=pick_optional("frame_notes"),
        status=status,
        created_at=created_at,
        updated_at=datetime.now(),
    )
