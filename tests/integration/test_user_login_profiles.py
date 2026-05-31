"""Integration tests for profile listing and login endpoints."""

from datetime import datetime, timedelta

import httpx
import pytest

from psychoanalyst_app.models.domain import UserProfile, UserStatus


@pytest.mark.trio
async def test_user_profiles_endpoint_orders_by_updated_at(test_server_websocket):
    db_service = test_server_websocket["db_service"]
    now = datetime.now()

    older_profile = UserProfile(
        user_id="profile_old",
        name="Old Profile",
        primary_language="English",
        status=UserStatus.PROFILE_ONLY,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=1),
    )
    newer_profile = UserProfile(
        user_id="profile_new",
        name="New Profile",
        primary_language="English",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=now - timedelta(days=1),
        updated_at=now,
    )

    await db_service.save_user_profile(older_profile)
    await db_service.save_user_profile(newer_profile)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{test_server_websocket['url']}/api/user/profiles"
        )

    assert response.status_code == 200
    data = response.json()
    profiles = data.get("profiles") or []
    assert [profile["user_id"] for profile in profiles[:2]] == [
        "profile_new",
        "profile_old",
    ]


@pytest.mark.trio
async def test_user_login_returns_404_for_missing_profile(test_server_websocket):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_websocket['url']}/api/user/login",
            json={"user_id": "missing_user"},
        )

    assert response.status_code == 404


@pytest.mark.trio
async def test_user_login_returns_session_for_existing_profile(test_server_websocket):
    db_service = test_server_websocket["db_service"]
    now = datetime.now()

    profile = UserProfile(
        user_id="login_user",
        name="Login User",
        primary_language="English",
        status=UserStatus.PROFILE_ONLY,
        created_at=now,
        updated_at=now,
    )
    await db_service.save_user_profile(profile)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_websocket['url']}/api/user/login",
            json={"user_id": profile.user_id},
        )

    assert response.status_code == 200
    data = response.json()
    session = data.get("session") or {}
    assert session.get("user_id") == profile.user_id
    assert session.get("session_id")
    assert data.get("workflow_next_action")
