"""Unit tests for user route validations."""

from datetime import datetime

import pytest
import trio

from psychoanalyst_app.models.data_models import UserProfile, UserStatus
from psychoanalyst_app.trio_server import TrioServer


@pytest.fixture
async def trio_server(mock_service_container):
    """Create Trio server instance for user route tests."""
    async with trio.open_nursery() as nursery:
        server = TrioServer(mock_service_container, host="127.0.0.1", port=8003)
        server.nursery = nursery
        server._initialize_orchestration(nursery)
        yield server
        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_register_user_returns_session_and_action(trio_server):
    app = trio_server.app

    async with app.test_client() as client:
        response = await client.post(
            "/api/user/register",
            json={
                "user_id": "register_user",
                "name": "Register User",
                "primary_language": "English",
                "session_mode": "virtual",
            },
        )

        assert response.status_code == 201
        data = await response.get_json()
        assert "session" in data
        assert "workflow_next_action" in data
        assert data["session"]["user_id"] == "register_user"
        assert data["session"]["session_id"]
        assert data["workflow_next_action"]["user_id"] == "register_user"


@pytest.mark.trio
async def test_profile_patch_rejects_status_update(trio_server):
    app = trio_server.app
    trio_db_service = trio_server.db_service

    user_profile = UserProfile(
        user_id="status_patch_user",
        name="Status Patch User",
        data_of_birth=None,
        profession="Tester",
        status=UserStatus.INTAKE_IN_PROGRESS,
        primary_language="English",
        session_mode="virtual",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(user_profile)

    session_info = await trio_server.orchestrator.start_session(
        user_profile.user_id,
        session_type="intake",
        send_initial_message=False,
    )

    async with app.test_client() as client:
        response = await client.patch(
            "/api/user/profile",
            json={
                "user_id": user_profile.user_id,
                "session_id": session_info.session_id,
                "status": "plan_complete",
            },
        )

        assert response.status_code == 400
        data = await response.get_json()
        assert "status" in data.get("error", "").lower()
