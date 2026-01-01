"""Unit tests for user profile repository utilities."""

from datetime import datetime, timedelta

import pytest

from psychoanalyst_app.models.data_models import UserProfile, UserStatus


@pytest.mark.trio
async def test_list_user_profiles_orders_by_updated_at(trio_db_service):
    now = datetime.now()
    older_profile = UserProfile(
        user_id="user_old",
        name="Older User",
        primary_language="English",
        status=UserStatus.PROFILE_ONLY,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=1),
    )
    newer_profile = UserProfile(
        user_id="user_new",
        name="Newer User",
        primary_language="English",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=now - timedelta(days=1),
        updated_at=now,
    )

    await trio_db_service.save_user_profile(older_profile)
    await trio_db_service.save_user_profile(newer_profile)

    profiles = await trio_db_service.list_user_profiles()

    assert [profile.user_id for profile in profiles] == [
        "user_new",
        "user_old",
    ]
