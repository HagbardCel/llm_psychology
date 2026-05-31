from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from psychoanalyst_app.models.domain import UserProfile, UserStatus
from psychoanalyst_app.orchestration.profile_helpers import ensure_user_profile, merge_user_profile


@pytest.mark.trio
async def test_ensure_user_profile_applies_defaults():
    trio_db_service = AsyncMock()
    trio_db_service.get_user_profile.return_value = None
    trio_db_service.update_user_profile.return_value = True

    profile = await ensure_user_profile(
        trio_db_service,
        "user_123",
        {"name": "Guest"},
    )

    assert profile.user_id == "user_123"
    assert profile.name == "Guest"
    assert profile.status == UserStatus.PROFILE_ONLY
    assert isinstance(profile.updated_at, datetime)
    trio_db_service.update_user_profile.assert_called_once()


def test_merge_user_profile_allows_explicit_null_for_optional_fields():
    existing = UserProfile(
        user_id="user_123",
        name="Guest",
        alias="Alias",
        profession="Engineer",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    merged = merge_user_profile(
        existing_profile=existing,
        user_id="user_123",
        updates={
            "name": "Updated Name",
            "alias": None,
            "profession": None,
        },
    )

    assert merged.name == "Updated Name"
    assert merged.alias is None
    assert merged.profession is None
