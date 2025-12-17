"""
Integration tests for session timer API endpoint.
"""

import pytest
import trio
import httpx
from datetime import datetime, timedelta


@pytest.fixture
def test_server_config(tmp_path):
    """Create test server configuration with authentication ENABLED."""
    from config import settings

    test_db_path = str(tmp_path / "timer_test_server.db")

    return settings.model_copy(
        update={
            "DATABASE_PATH": test_db_path,
            "REQUIRE_AUTHENTICATION": True,
            "JWT_SECRET_KEY": "test_secret_key_for_integration_tests",
            "CORS_ALLOWED_ORIGINS": ["http://localhost", "http://127.0.0.1"],
        }
    )


@pytest.fixture
async def server_url(test_server_websocket):
    """Get server URL from test_server_websocket fixture."""
    return test_server_websocket["url"]


@pytest.fixture
async def auth_headers(test_server_websocket):
    """Get authentication headers for API requests."""
    container = test_server_websocket["container"]
    from services.auth_service import AuthService

    auth_service = AuthService(
        secret_key=container.config.JWT_SECRET_KEY,
        algorithm=container.config.JWT_ALGORITHM,
        access_token_expire_minutes=container.config.ACCESS_TOKEN_EXPIRE_MINUTES,
    )

    # Create a test token for user "test_user"
    token = auth_service.create_access_token("test_user", "test_user")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def active_session(test_server_websocket, auth_headers):
    """Create an active session for testing."""
    db_service = test_server_websocket["db_service"]

    # Create user profile
    from models.data_models import UserProfile, UserStatus
    user_profile = UserProfile(
        user_id="test_user",
        name="Test User",
        status=UserStatus.PLAN_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await db_service.save_user_profile(user_profile)

    # Create therapy plan
    from models.data_models import TherapyPlan
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

    # Create session
    from models.data_models import Session
    session = Session(
        session_id="test_session_123",
        user_id="test_user",
        timestamp=datetime.now() - timedelta(minutes=10),  # Started 10 minutes ago
        transcript=[],
        topics=[],
    )
    await db_service.save_session(session)

    return session


@pytest.mark.trio
async def test_get_session_timer_success(server_url, auth_headers, active_session):
    """Test GET /api/sessions/<session_id>/timer endpoint with valid session."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/sessions/{active_session.session_id}/timer",
            headers=auth_headers,
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
async def test_get_session_timer_not_found(server_url, auth_headers):
    """Test GET /api/sessions/<session_id>/timer with non-existent session."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/sessions/nonexistent_session/timer",
            headers=auth_headers,
        )

        assert response.status_code == 404
        data = response.json()
        assert "error" in data


@pytest.mark.trio
async def test_get_session_timer_requires_auth(server_url, active_session):
    """Test that timer endpoint requires authentication."""
    async with httpx.AsyncClient() as client:
        # Request without auth headers
        response = await client.get(
            f"{server_url}/api/sessions/{active_session.session_id}/timer",
        )

        assert response.status_code == 401


@pytest.mark.trio
async def test_get_session_timer_with_extensions(test_server_websocket, server_url, auth_headers):
    """Test timer endpoint with session extensions."""
    db_service = test_server_websocket["db_service"]

    # Create user profile
    from models.data_models import UserProfile, UserStatus
    user_profile = UserProfile(
        user_id="test_user_ext",
        name="Test User",
        status=UserStatus.PLAN_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await db_service.save_user_profile(user_profile)

    # Create therapy plan
    from models.data_models import TherapyPlan
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

    # Create session that started 40 minutes ago (near end of base duration)
    from models.data_models import Session
    session = Session(
        session_id="test_session_ext",
        user_id="test_user_ext",
        timestamp=datetime.now() - timedelta(minutes=40),
        transcript=[],
        topics=[],
    )
    await db_service.save_session(session)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/sessions/{session.session_id}/timer",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Session should be near time limit
        assert data["elapsed_minutes"] >= 40
        assert data["remaining_minutes"] <= 6  # Less than 6 minutes left
        assert data["can_extend"] is True  # Should be able to extend
        assert data["is_time_up"] is False  # Not quite time up yet


@pytest.mark.trio
async def test_get_session_timer_time_up(test_server_websocket, server_url, auth_headers):
    """Test timer endpoint when session time is up."""
    db_service = test_server_websocket["db_service"]

    # Create user profile
    from models.data_models import UserProfile, UserStatus
    user_profile = UserProfile(
        user_id="test_user_timeup",
        name="Test User",
        status=UserStatus.PLAN_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await db_service.save_user_profile(user_profile)

    # Create therapy plan
    from models.data_models import TherapyPlan
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

    # Create session that started 50 minutes ago (past the 45 minute limit)
    from models.data_models import Session
    session = Session(
        session_id="test_session_timeup",
        user_id="test_user_timeup",
        timestamp=datetime.now() - timedelta(minutes=50),
        transcript=[],
        topics=[],
    )
    await db_service.save_session(session)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/sessions/{session.session_id}/timer",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Session time should be up
        assert data["elapsed_minutes"] >= 50
        assert data["remaining_minutes"] <= 0  # Time is up
        assert data["is_time_up"] is True
