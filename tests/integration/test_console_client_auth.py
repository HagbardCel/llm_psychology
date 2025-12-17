"""
Integration tests for console client authentication flow.

Tests:
1. User registration flow
2. User login flow
3. Authentication failure scenarios
4. Token-based API access
5. Token expiration handling
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import trio


@pytest.fixture
def test_server_config(tmp_path):
    """Create test server configuration with authentication ENABLED."""
    from config import settings

    test_db_path = str(tmp_path / "auth_test_server.db")

    return settings.model_copy(
        update={
            "DATABASE_PATH": test_db_path,
            "REQUIRE_AUTHENTICATION": True,  # Enable auth for this test file
            "JWT_SECRET_KEY": "test_secret_key_for_integration_tests",
            "CORS_ALLOWED_ORIGINS": ["http://localhost", "http://127.0.0.1"],
        }
    )


@pytest.fixture
async def test_server_url(test_server_websocket):
    """Get test server URL from the websocket fixture."""
    return test_server_websocket["url"]


@pytest.mark.trio
async def test_user_registration_flow(test_server_url):
    """Test complete user registration flow."""
    # ... code below ...
    """Test complete user registration flow."""
    # Generate unique test credentials
    username = f"testuser_{uuid.uuid4().hex[:8]}"
    password = "secure_test_password_123"
    name = "Test User"

    async with httpx.AsyncClient() as client:
        # Register new user
        response = await client.post(
            f"{test_server_url}/api/auth/register",
            json={"username": username, "password": password, "name": name},
        )

        assert response.status_code == 201, f"Registration failed: {response.text}"

        data = response.json()
        assert "access_token" in data
        assert "token_type" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data

        # Verify token is valid JWT
        token = data["access_token"]
        assert len(token.split(".")) == 3, "Token should be valid JWT"

        # Verify we can access protected endpoint with token
        me_response = await client.get(
            f"{test_server_url}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data["username"] == username
        assert me_data["name"] == name


@pytest.mark.trio
async def test_user_login_flow(test_server_url):
    """Test user login with existing credentials."""
    # First, register a user
    username = f"loginuser_{uuid.uuid4().hex[:8]}"
    password = "test_password_456"
    name = "Login Test User"

    async with httpx.AsyncClient() as client:
        # Register
        reg_response = await client.post(
            f"{test_server_url}/api/auth/register",
            json={"username": username, "password": password, "name": name},
        )
        assert reg_response.status_code == 201

        # Now login
        login_response = await client.post(
            f"{test_server_url}/api/auth/login",
            json={"username": username, "password": password},
        )

        assert login_response.status_code == 200, f"Login failed: {login_response.text}"

        data = login_response.json()
        assert "access_token" in data
        assert "token_type" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data

        # Verify token works
        token = data["access_token"]
        me_response = await client.get(
            f"{test_server_url}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert me_response.status_code == 200
        assert me_response.json()["username"] == username


@pytest.mark.trio
async def test_registration_duplicate_username(test_server_url):
    """Test that duplicate usernames are rejected."""
    username = f"duplicate_{uuid.uuid4().hex[:8]}"
    password = "password123"
    name = "Duplicate User"

    async with httpx.AsyncClient() as client:
        # Register first time
        response1 = await client.post(
            f"{test_server_url}/api/auth/register",
            json={"username": username, "password": password, "name": name},
        )
        assert response1.status_code == 201

        # Try to register again with same username
        response2 = await client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "username": username,
                "password": "different_password",
                "name": "Different Name",
            },
        )

        assert response2.status_code == 400
        data = response2.json()
        assert "error" in data
        assert (
            "already exists" in data["error"].lower()
            or "duplicate" in data["error"].lower()
        )


@pytest.mark.trio
async def test_login_invalid_credentials(test_server_url):
    """Test login with invalid credentials."""
    async with httpx.AsyncClient() as client:
        # Try to login with non-existent user
        response = await client.post(
            f"{test_server_url}/api/auth/login",
            json={"username": "nonexistent_user", "password": "wrong_password"},
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data


@pytest.mark.trio
async def test_login_wrong_password(test_server_url):
    """Test login with correct username but wrong password."""
    username = f"wrongpass_{uuid.uuid4().hex[:8]}"
    correct_password = "correct_password_789"
    name = "Wrong Pass User"

    async with httpx.AsyncClient() as client:
        # Register user
        reg_response = await client.post(
            f"{test_server_url}/api/auth/register",
            json={"username": username, "password": correct_password, "name": name},
        )
        assert reg_response.status_code == 201

        # Try to login with wrong password
        login_response = await client.post(
            f"{test_server_url}/api/auth/login",
            json={"username": username, "password": "wrong_password"},
        )

        assert login_response.status_code == 401
        data = login_response.json()
        assert "error" in data
        assert (
            "invalid" in data["error"].lower() or "incorrect" in data["error"].lower()
        )


@pytest.mark.trio
async def test_protected_endpoint_without_token(test_server_url):
    """Test that protected endpoints require authentication."""
    async with httpx.AsyncClient() as client:
        # Try to access protected endpoint without token
        response = await client.get(f"{test_server_url}/api/user/status")

        assert response.status_code == 401


@pytest.mark.trio
async def test_protected_endpoint_with_invalid_token(test_server_url):
    """Test that invalid tokens are rejected."""
    async with httpx.AsyncClient() as client:
        # Try to access protected endpoint with invalid token
        response = await client.get(
            f"{test_server_url}/api/user/status",
            headers={"Authorization": "Bearer invalid_token_here"},
        )

        assert response.status_code == 401


@pytest.mark.trio
async def test_token_based_api_access(test_server_url):
    """Test using token to access multiple protected endpoints."""
    username = f"apiuser_{uuid.uuid4().hex[:8]}"
    password = "api_test_password"
    name = "API Test User"

    async with httpx.AsyncClient() as client:
        # Register and get token
        reg_response = await client.post(
            f"{test_server_url}/api/auth/register",
            json={"username": username, "password": password, "name": name},
        )
        assert reg_response.status_code == 201

        token = reg_response.json()["access_token"]

        # Use token to access various endpoints
        headers = {"Authorization": f"Bearer {token}"}

        # Access /api/auth/me to get user details
        me_response = await client.get(
            f"{test_server_url}/api/auth/me", headers=headers
        )
        assert me_response.status_code == 200
        assert me_response.json()["username"] == username
        user_id = me_response.json()["user_id"]

        # Access /api/user/status
        status_response = await client.get(
            f"{test_server_url}/api/user/status",
            params={"user_id": user_id},
            headers=headers,
        )
        assert status_response.status_code == 200

        # Access /api/sessions
        sessions_response = await client.get(
            f"{test_server_url}/api/sessions",
            params={"user_id": user_id},
            headers=headers,
        )
        assert sessions_response.status_code == 200


@pytest.mark.trio
async def test_registration_validation(test_server_url):
    """Test input validation for registration."""
    async with httpx.AsyncClient() as client:
        # Test missing username
        response = await client.post(
            f"{test_server_url}/api/auth/register",
            json={"password": "password123", "name": "Test User"},
        )
        assert response.status_code == 400

        # Test missing password
        response = await client.post(
            f"{test_server_url}/api/auth/register",
            json={"username": "testuser", "name": "Test User"},
        )
        assert response.status_code == 400

        # Test missing name
        response = await client.post(
            f"{test_server_url}/api/auth/register",
            json={"username": "testuser", "password": "password123"},
        )
        assert response.status_code == 400


@pytest.mark.trio
async def test_login_validation(test_server_url):
    """Test input validation for login."""
    async with httpx.AsyncClient() as client:
        # Test missing username
        response = await client.post(
            f"{test_server_url}/api/auth/login", json={"password": "password123"}
        )
        assert response.status_code == 400

        # Test missing password
        response = await client.post(
            f"{test_server_url}/api/auth/login", json={"username": "testuser"}
        )
        assert response.status_code == 400
