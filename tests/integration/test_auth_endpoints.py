"""
Integration tests for authentication endpoints.

Tests the complete authentication flow including register, login, and protected endpoints.
"""

import json
from datetime import datetime

import pytest
import trio
from hypercorn.config import Config as HypercornConfig
from hypercorn.trio import serve

from config import settings
from container.service_container import ServiceContainer


@pytest.fixture
async def test_server(tmp_path, mock_llm_service, mock_rag_service):
    """Create a test server with authentication enabled."""
    from trio_server import TrioServer
    import socket

    # Use temporary database
    test_db_path = str(tmp_path / "test_auth.db")

    # Create test config with auth enabled
    test_config = settings.model_copy(
        update={
            "DATABASE_PATH": test_db_path,
            "REQUIRE_AUTHENTICATION": True,  # Enable auth for these tests
            "JWT_SECRET_KEY": "test_secret_key_for_integration_tests",
        }
    )

    # Create service container with mocked services
    container = ServiceContainer(test_config)
    container.register("llm_service", mock_llm_service)
    container.register("rag_service", mock_rag_service)

    # Initialize database
    db_service = container.get("trio_db_service")
    await db_service.initialize()

    # Create server
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = TrioServer(container, host="127.0.0.1", port=port)

    # Start server in background
    async with trio.open_nursery() as nursery:
        await nursery.start(server.run)

        # Verify server is actually accepting connections via health check
        import httpx

        async with httpx.AsyncClient() as client:
            for _ in range(20):  # 2 seconds max (20 * 0.1s)
                try:
                    response = await client.get(
                        f"http://127.0.0.1:{port}/health", timeout=1.0
                    )
                    if response.status_code == 200:
                        break
                except Exception:
                    pass
                await trio.sleep(0.1)
            else:
                raise RuntimeError("Server failed to respond to health checks")

        # Provide server info to test
        yield {
            "base_url": f"http://{server.host}:{server.port}",
            "db_service": db_service,
            "auth_service": server.auth_service,
        }

        # Cleanup
        nursery.cancel_scope.cancel()


@pytest.mark.trio
@pytest.mark.integration
async def test_register_new_user(test_server):
    """Test user registration endpoint."""
    import httpx

    base_url = test_server["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}/api/auth/register",
            json={
                "username": "testuser123",
                "password": "securepassword123",
                "name": "Test User",
            },
        )

        assert response.status_code == 201
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 3600  # 60 minutes in seconds


@pytest.mark.trio
@pytest.mark.integration
async def test_register_duplicate_username(test_server):
    """Test that duplicate username registration fails."""
    import httpx

    base_url = test_server["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Register first user
        response1 = await client.post(
            f"{base_url}/api/auth/register",
            json={
                "username": "duplicate_user",
                "password": "password123",
                "name": "First User",
            },
        )
        assert response1.status_code == 201

        # Try to register with same username
        response2 = await client.post(
            f"{base_url}/api/auth/register",
            json={
                "username": "duplicate_user",
                "password": "different_password",
                "name": "Second User",
            },
        )
        assert response2.status_code == 400
        assert "already exists" in response2.json()["error"].lower()


@pytest.mark.trio
@pytest.mark.integration
async def test_login_success(test_server):
    """Test successful login."""
    import httpx

    base_url = test_server["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Register user first
        await client.post(
            f"{base_url}/api/auth/register",
            json={
                "username": "logintest",
                "password": "testpass123",
                "name": "Login Test User",
            },
        )

        # Login
        response = await client.post(
            f"{base_url}/api/auth/login",
            json={"username": "logintest", "password": "testpass123"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 3600


@pytest.mark.trio
@pytest.mark.integration
async def test_login_invalid_credentials(test_server):
    """Test login with invalid credentials."""
    import httpx

    base_url = test_server["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Register user
        await client.post(
            f"{base_url}/api/auth/register",
            json={
                "username": "wrongpass",
                "password": "correctpassword",
                "name": "Test User",
            },
        )

        # Try to login with wrong password
        response = await client.post(
            f"{base_url}/api/auth/login",
            json={"username": "wrongpass", "password": "wrongpassword"},
        )

        assert response.status_code == 401
        assert "invalid" in response.json()["error"].lower()


@pytest.mark.trio
@pytest.mark.integration
async def test_protected_endpoint_without_token(test_server):
    """Test that protected endpoints reject requests without token."""
    import httpx

    base_url = test_server["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try to access protected endpoint without token
        response = await client.get(f"{base_url}/api/user/status?user_id=test")

        assert response.status_code == 401
        assert "authorization" in response.json()["error"].lower()


@pytest.mark.trio
@pytest.mark.integration
async def test_protected_endpoint_with_valid_token(test_server):
    """Test that protected endpoints accept valid tokens."""
    import httpx

    base_url = test_server["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Register and get token
        register_response = await client.post(
            f"{base_url}/api/auth/register",
            json={
                "username": "protected_test",
                "password": "testpass123",
                "name": "Protected Test User",
            },
        )
        token = register_response.json()["access_token"]

        # Access protected endpoint with token
        response = await client.get(
            f"{base_url}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "protected_test"


@pytest.mark.trio
@pytest.mark.integration
async def test_protected_endpoint_with_expired_token(test_server):
    """Test that expired tokens are rejected."""
    from datetime import timedelta

    import httpx

    from services.auth_service import AuthService

    base_url = test_server["base_url"]

    # Create auth service with short expiration
    auth_service = AuthService(
        secret_key="test_secret_key_for_integration_tests",
        algorithm="HS256",
        access_token_expire_minutes=1,
    )

    # Create an already-expired token (avoid time-based sleeps in tests).
    token = auth_service.create_access_token(
        "test_user", "testuser", expires_delta=timedelta(seconds=-1)
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/api/user/status?user_id=test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401
        assert "expired" in response.json()["error"].lower()


@pytest.mark.trio
@pytest.mark.integration
async def test_login_updates_last_login(test_server):
    """Test that login updates the last_login timestamp."""
    import httpx

    base_url = test_server["base_url"]
    db_service = test_server["db_service"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Register user
        await client.post(
            f"{base_url}/api/auth/register",
            json={
                "username": "lastlogintest",
                "password": "testpass123",
                "name": "Last Login Test",
            },
        )

        # Login twice with a delay
        response1 = await client.post(
            f"{base_url}/api/auth/login",
            json={"username": "lastlogintest", "password": "testpass123"},
        )
        assert response1.status_code == 200

        creds1 = await db_service.get_user_credentials("lastlogintest")
        assert creds1 is not None
        assert creds1.last_login is not None

        response2 = await client.post(
            f"{base_url}/api/auth/login",
            json={"username": "lastlogintest", "password": "testpass123"},
        )
        assert response2.status_code == 200

        creds2 = await db_service.get_user_credentials("lastlogintest")
        assert creds2 is not None
        assert creds2.last_login is not None
        assert creds2.last_login != creds1.last_login


@pytest.mark.trio
@pytest.mark.integration
async def test_health_endpoint_no_auth_required(test_server):
    """Test that health endpoint doesn't require authentication."""
    import httpx

    base_url = test_server["base_url"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{base_url}/health")

        # Should work without authentication
        assert response.status_code == 200
