"""Shared profile persistence helpers for orchestration flows."""

from __future__ import annotations

import logging

from psychoanalyst_app.models.structured_output_models import StructuredUserProfileOutput
from psychoanalyst_app.orchestration.profile_helpers import merge_user_profile

logger = logging.getLogger(__name__)


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
        logger.error(
            "Failed to persist structured profile update for user %s", user_id
        )
    return saved
