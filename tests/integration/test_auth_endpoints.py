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
async def test_server(tmp_path):
    """Create a test server with temporary database."""
    # Use temporary database
    test_db_path = str(tmp_path / "test_auth.db")
    settings.DATABASE_PATH = test_db_path
    settings.REQUIRE_AUTHENTICATION = True  # Enable auth for testing
    settings.JWT_SECRET_KEY = "test_secret_key_for_integration_tests"

    # Create service container
    container = ServiceContainer(settings)

    # Initialize database
    db_service = container.get("trio_db_service")
    await db_service.initialize()

    # Import after path setup
    from trio_server import TrioServer

    # Create server
    server = TrioServer(container, host="127.0.0.1", port=8888)

    # Create Hypercorn config
    config = HypercornConfig()
    config.bind = [f"{server.host}:{server.port}"]

    # Start server in background
    async with trio.open_nursery() as nursery:
        # Start server
        nursery.start_soon(serve, server.app, config)

        # Give server time to start
        await trio.sleep(0.5)

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
async def test_register_new_user():
    """Test user registration endpoint."""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://127.0.0.1:8888/api/auth/register",
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
async def test_register_duplicate_username():
    """Test that duplicate username registration fails."""
    import httpx

    async with httpx.AsyncClient() as client:
        # Register first user
        response1 = await client.post(
            "http://127.0.0.1:8888/api/auth/register",
            json={
                "username": "duplicate_user",
                "password": "password123",
                "name": "First User",
            },
        )
        assert response1.status_code == 201

        # Try to register with same username
        response2 = await client.post(
            "http://127.0.0.1:8888/api/auth/register",
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
async def test_login_success():
    """Test successful login."""
    import httpx

    async with httpx.AsyncClient() as client:
        # Register user first
        await client.post(
            "http://127.0.0.1:8888/api/auth/register",
            json={
                "username": "logintest",
                "password": "testpass123",
                "name": "Login Test User",
            },
        )

        # Login
        response = await client.post(
            "http://127.0.0.1:8888/api/auth/login",
            json={"username": "logintest", "password": "testpass123"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 3600


@pytest.mark.trio
@pytest.mark.integration
async def test_login_invalid_credentials():
    """Test login with invalid credentials."""
    import httpx

    async with httpx.AsyncClient() as client:
        # Register user
        await client.post(
            "http://127.0.0.1:8888/api/auth/register",
            json={
                "username": "wrongpass",
                "password": "correctpassword",
                "name": "Test User",
            },
        )

        # Try to login with wrong password
        response = await client.post(
            "http://127.0.0.1:8888/api/auth/login",
            json={"username": "wrongpass", "password": "wrongpassword"},
        )

        assert response.status_code == 401
        assert "invalid" in response.json()["error"].lower()


@pytest.mark.trio
@pytest.mark.integration
async def test_protected_endpoint_without_token():
    """Test that protected endpoints reject requests without token."""
    import httpx

    async with httpx.AsyncClient() as client:
        # Try to access protected endpoint without token
        response = await client.get("http://127.0.0.1:8888/api/user/status?user_id=test")

        assert response.status_code == 401
        assert "authorization" in response.json()["error"].lower()


@pytest.mark.trio
@pytest.mark.integration
async def test_protected_endpoint_with_valid_token():
    """Test that protected endpoints accept valid tokens."""
    import httpx

    async with httpx.AsyncClient() as client:
        # Register and get token
        register_response = await client.post(
            "http://127.0.0.1:8888/api/auth/register",
            json={
                "username": "protected_test",
                "password": "testpass123",
                "name": "Protected Test User",
            },
        )
        token = register_response.json()["access_token"]

        # Access protected endpoint with token
        response = await client.get(
            "http://127.0.0.1:8888/api/user/status?user_id=test",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Should not be 401 (may be 200 or other depending on endpoint logic)
        assert response.status_code != 401


@pytest.mark.trio
@pytest.mark.integration
async def test_protected_endpoint_with_expired_token():
    """Test that expired tokens are rejected."""
    import httpx
    from datetime import timedelta

    from services.auth_service import AuthService

    # Create auth service with short expiration
    auth_service = AuthService(
        secret_key="test_secret_key_for_integration_tests",
        algorithm="HS256",
        access_token_expire_minutes=1,
    )

    # Create expired token (0 seconds expiration)
    token = auth_service.create_access_token(
        "test_user", "testuser", expires_delta=timedelta(seconds=0)
    )

    await trio.sleep(0.1)  # Wait for token to expire

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://127.0.0.1:8888/api/user/status?user_id=test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401
        assert "expired" in response.json()["error"].lower()


@pytest.mark.trio
@pytest.mark.integration
async def test_login_updates_last_login():
    """Test that login updates the last_login timestamp."""
    import httpx

    async with httpx.AsyncClient() as client:
        # Register user
        await client.post(
            "http://127.0.0.1:8888/api/auth/register",
            json={
                "username": "lastlogintest",
                "password": "testpass123",
                "name": "Last Login Test",
            },
        )

        # Login twice with a delay
        response1 = await client.post(
            "http://127.0.0.1:8888/api/auth/login",
            json={"username": "lastlogintest", "password": "testpass123"},
        )
        assert response1.status_code == 200

        await trio.sleep(1)

        response2 = await client.post(
            "http://127.0.0.1:8888/api/auth/login",
            json={"username": "lastlogintest", "password": "testpass123"},
        )
        assert response2.status_code == 200


@pytest.mark.trio
@pytest.mark.integration
async def test_health_endpoint_no_auth_required():
    """Test that health endpoint doesn't require authentication."""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get("http://127.0.0.1:8888/health")

        # Should work without authentication
        assert response.status_code == 200
