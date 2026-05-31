"""Helpers for merging and persisting user profile updates."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from psychoanalyst_app.models.domain import UserProfile, UserStatus
from psychoanalyst_app.models.llm_outputs import StructuredUserProfileOutput
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


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
        if field in updates:
            return updates[field]
        return getattr(existing_profile, field) if existing_profile else default

    if "date_of_birth" in updates:
        raw_date_of_birth = updates.get("date_of_birth")
        date_of_birth = parse_date_of_birth(raw_date_of_birth)
        if (
            raw_date_of_birth not in (None, "")
            and date_of_birth is None
            and existing_profile
        ):
            date_of_birth = existing_profile.date_of_birth
    else:
        date_of_birth = existing_profile.date_of_birth if existing_profile else None

    name_value = updates.get("name") if "name" in updates else None
    if isinstance(name_value, str) and name_value.strip():
        name = name_value
    else:
        name = existing_profile.name if existing_profile else user_id

    profession = pick_optional("profession")
    primary_language = pick_optional("primary_language", "English")
    if not primary_language:
        primary_language = (
            existing_profile.primary_language if existing_profile else "English"
        )

    return UserProfile(
        user_id=user_id,
        name=name,
        date_of_birth=date_of_birth,
        profession=profession,
        alias=pick_optional("alias"),
        gender=pick_optional("gender"),
        cultural_background=pick_optional("cultural_background"),
        primary_language=primary_language,
        plan_id=pick_optional("plan_id"),
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
        boundary_notes=pick_optional("boundary_notes"),
        frame_notes=pick_optional("frame_notes"),
        status=status,
        created_at=created_at,
        updated_at=datetime.now(),
    )


async def ensure_user_profile(
    trio_db_service: TrioDatabaseService,
    user_id: str,
    defaults: dict[str, Any] | None = None,
) -> UserProfile:
    """Ensure a user profile exists, applying defaults without transitions."""
    existing_profile = await trio_db_service.get_user_profile(user_id)
    updates = dict(defaults or {})
    date_of_birth = updates.get("date_of_birth")
    if isinstance(date_of_birth, str) and date_of_birth:
        updates["date_of_birth"] = parse_date_of_birth(date_of_birth)

    user_profile = merge_user_profile(
        existing_profile=existing_profile,
        user_id=user_id,
        updates=updates,
    )

    success = await trio_db_service.update_user_profile(user_profile)
    if not success:
        raise ValueError("Failed to save user profile to database")

    return user_profile


async def persist_structured_user_profile_output(
    *,
    trio_db_service,
    user_id: str,
    session_id: str | None,
    user_profile_output: StructuredUserProfileOutput | dict | None,
    change_summary: str,
) -> bool:
    """Persist a structured user profile payload to DB."""
    if isinstance(user_profile_output, dict):
        user_profile_output = StructuredUserProfileOutput.model_validate(
            user_profile_output
        )
    if not isinstance(user_profile_output, StructuredUserProfileOutput):
        return False

    updates = user_profile_output.model_dump(exclude_none=True, exclude_unset=True)
    existing = await trio_db_service.get_user_profile(user_id)
    merged = merge_user_profile(
        existing_profile=existing,
        user_id=user_id,
        updates=updates,
    )
    saved = await trio_db_service.update_user_profile(
        merged,
        change_summary=change_summary,
        created_by_session=session_id,
    )
    if not saved:
        logger.error("Failed to persist structured profile update for user %s", user_id)
    return saved
