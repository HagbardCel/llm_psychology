"""
Integration tests for session timer API endpoint.
"""

import pytest
import trio
import httpx
from datetime import datetime, timedelta


@pytest.fixture
def test_server_config(tmp_path):
    """Create test server configuration."""
    from psychoanalyst_app.config import Settings

    test_db_path = str(tmp_path / "timer_test_server.db")

    settings = Settings()
    return settings.model_copy(
        update={
            "DATABASE_PATH": test_db_path,
            "CORS_ALLOWED_ORIGINS": ["http://localhost", "http://127.0.0.1"],
        }
    )


@pytest.fixture
async def server_url(test_server_websocket):
    """Get server URL from test_server_websocket fixture."""
    return test_server_websocket["url"]


@pytest.fixture
async def active_session(test_server_websocket, server_url):
    """Create an active session for testing."""
    db_service = test_server_websocket["db_service"]

    # Create user profile
    from psychoanalyst_app.models.domain import UserProfile, UserStatus
    user_profile = UserProfile(
        user_id="test_user",
        name="Test User",
        status=UserStatus.PLAN_UPDATE_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await db_service.save_user_profile(user_profile)

    # Create therapy plan
    from psychoanalyst_app.models.domain import TherapyPlan
    therapy_plan = TherapyPlan(
        plan_id="plan_timer_test",
        user_id="test_user",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        selected_therapy_style="freud",
        plan_details={"focus": "test", "goals": "test goals"},
        initial_goals=["Stabilize presenting concerns"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        status="active",
        version=1,
    )
    await db_service.save_therapy_plan(therapy_plan)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/api/sessions",
            json={"user_id": "test_user"},
        )
        response.raise_for_status()
        session_payload = response.json()

    from psychoanalyst_app.models.domain import Session
    session = Session(
        session_id=session_payload["session_id"],
        user_id="test_user",
        timestamp=datetime.now() - timedelta(minutes=10),  # Started 10 minutes ago
        transcript=[],
        topics=[],
    )
    await db_service.save_session(session)

    return session


@pytest.mark.trio
async def test_get_session_timer_success(server_url, active_session):
    """Test GET /api/sessions/<session_id>/timer endpoint with valid session."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/sessions/{active_session.session_id}/timer",
            params={
                "user_id": active_session.user_id,
                "session_id": active_session.session_id,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "session_id" in data
        assert "elapsed_minutes" in data
        assert "remaining_minutes" in data
        assert "total_duration_minutes" in data
        assert "extensions_used" in data
        assert "max_extensions" in data
        assert "can_extend" in data
        assert "is_time_up" in data
        assert "timestamp" in data

        # Verify data values
        assert data["session_id"] == active_session.session_id
        assert data["elapsed_minutes"] >= 10  # At least 10 minutes elapsed
        assert data["elapsed_minutes"] <= 11  # Should be close to 10 minutes
        assert data["remaining_minutes"] >= 34  # Should have ~35 minutes left
        assert data["remaining_minutes"] <= 36
        assert data["total_duration_minutes"] == 45  # Default duration
        assert data["extensions_used"] == 0
        assert data["max_extensions"] == 2
        assert data["can_extend"] is True
        assert data["is_time_up"] is False


@pytest.mark.trio
async def test_get_session_timer_not_found(server_url):
    """Test GET /api/sessions/<session_id>/timer with non-existent session."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/sessions/nonexistent_session/timer",
            params={"user_id": "missing", "session_id": "missing"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data


@pytest.mark.trio
@pytest.mark.trio
async def test_get_session_timer_with_extensions(test_server_websocket, server_url):
    """Test timer endpoint with session extensions."""
    db_service = test_server_websocket["db_service"]

    # Create user profile
    from psychoanalyst_app.models.domain import UserProfile, UserStatus
    user_profile = UserProfile(
        user_id="test_user_ext",
        name="Test User",
        status=UserStatus.PLAN_UPDATE_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await db_service.save_user_profile(user_profile)

    # Create therapy plan
    from psychoanalyst_app.models.domain import TherapyPlan
    therapy_plan = TherapyPlan(
        plan_id="plan_timer_ext",
        user_id="test_user_ext",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        selected_therapy_style="freud",
        plan_details={"focus": "test", "goals": "test goals"},
        initial_goals=["Stabilize presenting concerns"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        status="active",
        version=1,
    )
    await db_service.save_therapy_plan(therapy_plan)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/api/sessions",
            json={"user_id": "test_user_ext"},
        )
        response.raise_for_status()
        session_payload = response.json()

    from psychoanalyst_app.models.domain import Session
    session = Session(
        session_id=session_payload["session_id"],
        user_id="test_user_ext",
        timestamp=datetime.now() - timedelta(minutes=40),
        transcript=[],
        topics=[],
    )
    await db_service.save_session(session)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/sessions/{session.session_id}/timer",
            params={
                "user_id": session.user_id,
                "session_id": session.session_id,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Session should be near time limit
        assert data["elapsed_minutes"] >= 40
        assert data["remaining_minutes"] <= 6  # Less than 6 minutes left
        assert data["can_extend"] is True  # Should be able to extend
        assert data["is_time_up"] is False  # Not quite time up yet


@pytest.mark.trio
async def test_get_session_timer_time_up(test_server_websocket, server_url):
    """Test timer endpoint when session time is up."""
    db_service = test_server_websocket["db_service"]

    # Create user profile
    from psychoanalyst_app.models.domain import UserProfile, UserStatus
    user_profile = UserProfile(
        user_id="test_user_timeup",
        name="Test User",
        status=UserStatus.PLAN_UPDATE_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await db_service.save_user_profile(user_profile)

    # Create therapy plan
    from psychoanalyst_app.models.domain import TherapyPlan
    therapy_plan = TherapyPlan(
        plan_id="plan_timer_timeup",
        user_id="test_user_timeup",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        selected_therapy_style="freud",
        plan_details={"focus": "test", "goals": "test goals"},
        initial_goals=["Stabilize presenting concerns"],
        current_progress="Baseline established",
        planned_interventions=["Supportive listening"],
        status="active",
        version=1,
    )
    await db_service.save_therapy_plan(therapy_plan)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/api/sessions",
            json={"user_id": "test_user_timeup"},
        )
        response.raise_for_status()
        session_payload = response.json()

    from psychoanalyst_app.models.domain import Session
    session = Session(
        session_id=session_payload["session_id"],
        user_id="test_user_timeup",
        timestamp=datetime.now() - timedelta(minutes=50),
        transcript=[],
        topics=[],
    )
    await db_service.save_session(session)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/sessions/{session.session_id}/timer",
            params={
                "user_id": session.user_id,
                "session_id": session.session_id,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Session time should be up
        assert data["elapsed_minutes"] >= 50
        assert data["remaining_minutes"] <= 0  # Time is up
        assert data["is_time_up"] is True
