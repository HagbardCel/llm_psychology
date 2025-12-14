"""
Integration tests for the Trio-native server flow.

Tests the complete flow from HTTP endpoint through database using pure Trio.
"""

from datetime import datetime

import pytest
import trio

from config import settings
from container.service_container import ServiceContainer
from models.data_models import UserProfile, UserStatus
from trio_server import TrioServer


@pytest.fixture
def app_config(tmp_path):
    """Create test configuration."""

    # Use temporary file database (in-memory doesn't work with Trio threading)
    test_db_path = str(tmp_path / "test_trio_flow.db")

    # Create a modified copy of settings
    mock_settings = settings.model_copy(
        update={
            "DATABASE_PATH": test_db_path,
            "REQUIRE_AUTHENTICATION": False,  # Disable auth for internal flow tests
        }
    )
    return mock_settings


@pytest.fixture
async def service_container(app_config, mock_llm_service, mock_rag_service):
    """Create service container with test configuration."""
    container = ServiceContainer(app_config)

    # Mock services BEFORE getting trio_db_service to prevent llm_service creation
    container.register("llm_service", mock_llm_service)
    container.register("rag_service", mock_rag_service)

    # Initialize trio database service
    trio_db_service = container.get("trio_db_service")
    await trio_db_service.initialize()

    yield container

    # Cleanup
    await trio_db_service.clear_all_data()


@pytest.fixture
async def trio_server(service_container):
    """Create Trio server instance for testing."""
    async with trio.open_nursery() as nursery:
        server = TrioServer(service_container, host="127.0.0.1", port=8001)
        server.nursery = nursery
        server._initialize_orchestration(nursery)
        yield server
        nursery.cancel_scope.cancel()


@pytest.fixture
async def test_user(service_container):
    """Create a test user profile."""
    trio_db_service = service_container.get("trio_db_service")

    user_profile = UserProfile(
        user_id="test_user_123",
        name="Test User",
        birthdate=None,
        profession="Software Engineer",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    await trio_db_service.save_user_profile(user_profile)
    return user_profile


@pytest.mark.trio
@pytest.mark.integration
async def test_trio_database_service_health_check(service_container):
    """Test that the Trio database service health check works."""
    trio_db_service = service_container.get("trio_db_service")

    # Perform health check
    is_healthy = await trio_db_service.health_check()

    assert is_healthy is True


@pytest.mark.trio
@pytest.mark.integration
async def test_trio_database_service_save_and_retrieve_user(service_container):
    """Test saving and retrieving a user profile with Trio database service."""
    trio_db_service = service_container.get("trio_db_service")

    # Create user profile
    user_profile = UserProfile(
        user_id="test_user_456",
        name="Jane Doe",
        birthdate=None,
        profession="Doctor",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # Save user profile
    success = await trio_db_service.save_user_profile(user_profile)
    assert success is True

    # Retrieve user profile
    retrieved_profile = await trio_db_service.get_user_profile("test_user_456")
    assert retrieved_profile is not None
    assert retrieved_profile.user_id == "test_user_456"
    assert retrieved_profile.name == "Jane Doe"
    assert retrieved_profile.profession == "Doctor"
    assert retrieved_profile.status == UserStatus.PROFILE_ONLY


@pytest.mark.trio
@pytest.mark.integration
async def test_health_endpoint(trio_server):
    """Test the /health endpoint returns correct status."""
    app = trio_server.app

    async with app.test_client() as client:
        response = await client.get("/health")

        assert response.status_code == 200

        data = await response.get_json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["service"] == "therapy-backend-trio"
        assert "database" in data


@pytest.mark.trio
@pytest.mark.integration
async def test_create_session_endpoint_success(trio_server, test_user):
    """Test creating a session via POST /api/sessions."""
    app = trio_server.app

    async with app.test_client() as client:
        # Create session request
        response = await client.post(
            "/api/sessions", json={"user_id": test_user.user_id, "type": "therapy"}
        )

        assert response.status_code == 201

        data = await response.get_json()
        assert "session_id" in data
        assert data["user_id"] == test_user.user_id
        assert data["type"] == "therapy"
        assert data["status"] == "created"
        assert "timestamp" in data


@pytest.mark.trio
@pytest.mark.integration
async def test_create_session_endpoint_missing_user_id(trio_server):
    """Test creating a session without user_id returns 400."""
    app = trio_server.app

    async with app.test_client() as client:
        response = await client.post("/api/sessions", json={"type": "therapy"})

        assert response.status_code == 400

        data = await response.get_json()
        assert "error" in data
        assert "User ID is required" in data["error"]


@pytest.mark.trio
@pytest.mark.integration
async def test_create_session_endpoint_nonexistent_user(trio_server):
    """Test creating a session for nonexistent user returns 404."""
    app = trio_server.app

    async with app.test_client() as client:
        response = await client.post(
            "/api/sessions", json={"user_id": "nonexistent_user_999", "type": "therapy"}
        )

        assert response.status_code == 404

        data = await response.get_json()
        assert "error" in data
        assert "User profile not found" in data["error"]


@pytest.mark.trio
@pytest.mark.integration
async def test_create_session_and_verify_in_database(trio_server, test_user):
    """Test that created session is actually saved to database."""
    app = trio_server.app
    trio_db_service = trio_server.db_service

    async with app.test_client() as client:
        # Create session
        response = await client.post(
            "/api/sessions", json={"user_id": test_user.user_id, "type": "therapy"}
        )

        assert response.status_code == 201
        data = await response.get_json()
        session_id = data["session_id"]

        # Verify session exists in database
        session = await trio_db_service.get_session(session_id)
        assert session is not None
        assert session.session_id == session_id
        assert session.user_id == test_user.user_id
        assert len(session.transcript) == 1
        assert session.transcript[0].role == "system"
        assert "Session started" in session.transcript[0].content


@pytest.mark.trio
@pytest.mark.integration
async def test_structured_concurrency_with_nursery(service_container):
    """Test that Trio structured concurrency works with database operations."""
    trio_db_service = service_container.get("trio_db_service")

    results = []

    async def create_user(user_id: str):
        """Create a user profile."""
        user_profile = UserProfile(
            user_id=user_id,
            name=f"User {user_id}",
            birthdate=None,
            profession="Test",
            status=UserStatus.PROFILE_ONLY,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        success = await trio_db_service.save_user_profile(user_profile)
        results.append((user_id, success))

    # Run multiple user creations concurrently using nursery
    async with trio.open_nursery() as nursery:
        for i in range(5):
            nursery.start_soon(create_user, f"concurrent_user_{i}")

    # Verify all users were created
    assert len(results) == 5
    assert all(success for _, success in results)

    # Verify all users exist in database
    for i in range(5):
        profile = await trio_db_service.get_user_profile(f"concurrent_user_{i}")
        assert profile is not None
        assert profile.user_id == f"concurrent_user_{i}"


@pytest.mark.trio
@pytest.mark.integration
async def test_get_user_status_endpoint(trio_server, test_user):
    """Test the /api/user/status endpoint."""
    app = trio_server.app

    async with app.test_client() as client:
        response = await client.get(f"/api/user/status?user_id={test_user.user_id}")

        assert response.status_code == 200

        data = await response.get_json()
        assert data["user_id"] == test_user.user_id
        assert "workflow_state" in data
        assert "timestamp" in data
