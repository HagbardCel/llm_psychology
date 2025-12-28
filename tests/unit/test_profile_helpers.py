from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from psychoanalyst_app.models.data_models import UserStatus
from psychoanalyst_app.orchestration.profile_helpers import ensure_user_profile


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
