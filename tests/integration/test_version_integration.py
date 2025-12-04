"""
Integration tests for version checking across clients.

Tests:
1. Version endpoint accessibility
2. Version compatibility checking
3. Console client version check integration
4. Frontend version check integration
5. Version update scenarios
"""

import pytest
import trio
import httpx
from src.version import API_VERSION, MIN_CLIENT_VERSION, Version


@pytest.fixture
async def test_server_url(test_server_websocket):
    """Get test server URL from the websocket fixture."""
    return test_server_websocket["url"]


@pytest.mark.trio
async def test_version_endpoint_no_auth_required(test_server_url):
    """Test that version endpoint is accessible without authentication."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{test_server_url}/api/version")

        assert response.status_code == 200
        data = response.json()

        assert "api_version" in data
        assert "min_client_version" in data
        assert "server_time" in data

        # Verify versions are valid semantic versions
        assert data["api_version"] == str(API_VERSION)
        assert data["min_client_version"] == str(MIN_CLIENT_VERSION)


@pytest.mark.trio
async def test_version_check_compatible_versions(test_server_url):
    """Test version check with compatible client version."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_url}/api/version/check",
            json={"client_version": str(API_VERSION), "client_type": "console"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["compatible"] is True
        assert data["api_version"] == str(API_VERSION)
        assert data["client_version"] == str(API_VERSION)
        assert data["upgrade_required"] is False
        assert "compatible" in data["message"].lower()


@pytest.mark.trio
async def test_version_check_outdated_but_compatible(test_server_url):
    """Test version check with outdated but still compatible version."""
    # Only run if API_VERSION has a minor version > 0
    if API_VERSION.minor > 0:
        outdated_version = f"{API_VERSION.major}.{API_VERSION.minor - 1}.0"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{test_server_url}/api/version/check",
                json={"client_version": outdated_version, "client_type": "web"},
            )

            assert response.status_code == 200
            data = response.json()

            assert data["compatible"] is True
            assert data["upgrade_required"] is False
            assert data["upgrade_recommended"] is True
            assert (
                "outdated" in data["message"].lower()
                or "consider" in data["message"].lower()
            )


@pytest.mark.trio
async def test_version_check_incompatible_major_version(test_server_url):
    """Test version check with incompatible major version."""
    incompatible_version = f"{API_VERSION.major + 1}.0.0"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_url}/api/version/check",
            json={"client_version": incompatible_version, "client_type": "console"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["compatible"] is False
        assert "not compatible" in data["message"].lower()


@pytest.mark.trio
async def test_version_check_below_minimum(test_server_url):
    """Test version check with version below minimum supported."""
    if MIN_CLIENT_VERSION.major > 0:
        old_version = f"{MIN_CLIENT_VERSION.major - 1}.9.9"
    else:
        old_version = "0.0.1"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_url}/api/version/check",
            json={"client_version": old_version, "client_type": "console"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["compatible"] is False
        assert data["upgrade_required"] is True
        assert "too old" in data["message"].lower() or "minimum" in data["message"].lower()


@pytest.mark.trio
async def test_version_check_invalid_format(test_server_url):
    """Test version check with invalid version format."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_url}/api/version/check",
            json={"client_version": "invalid.version", "client_type": "console"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data


@pytest.mark.trio
async def test_version_check_missing_fields(test_server_url):
    """Test version check with missing required fields."""
    async with httpx.AsyncClient() as client:
        # Missing client_version
        response1 = await client.post(
            f"{test_server_url}/api/version/check", json={"client_type": "console"}
        )
        assert response1.status_code == 400

        # Missing client_type
        response2 = await client.post(
            f"{test_server_url}/api/version/check", json={"client_version": "1.0.0"}
        )
        assert response2.status_code == 400


@pytest.mark.trio
async def test_version_check_invalid_client_type(test_server_url):
    """Test version check with invalid client type."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_url}/api/version/check",
            json={"client_version": "1.0.0", "client_type": "invalid_type"},
        )

        assert response.status_code == 400


@pytest.mark.trio
async def test_console_client_version_check_flow(test_server_url):
    """Test complete console client version check flow."""
    from console_ui.src.version_check import check_backend_version, CLIENT_VERSION

    # Simulate console client version check
    try:
        compatible, message = await check_backend_version(test_server_url)

        # Should be compatible since we're using current version
        assert compatible is True
        assert len(message) > 0
        assert "compatible" in message.lower()

    except Exception as e:
        pytest.fail(f"Console client version check failed: {e}")


@pytest.mark.trio
async def test_version_check_with_patch_difference(test_server_url):
    """Test that patch version differences don't affect compatibility."""
    different_patch = f"{API_VERSION.major}.{API_VERSION.minor}.{API_VERSION.patch + 1}"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_url}/api/version/check",
            json={"client_version": different_patch, "client_type": "web"},
        )

        assert response.status_code == 200
        data = response.json()

        # Patch differences should not affect compatibility
        assert data["compatible"] is True
        assert data["upgrade_required"] is False


@pytest.mark.trio
async def test_version_check_concurrent_requests(test_server_url):
    """Test multiple concurrent version check requests."""
    async with httpx.AsyncClient() as client:

        async def check_version():
            response = await client.post(
                f"{test_server_url}/api/version/check",
                json={"client_version": str(API_VERSION), "client_type": "console"},
            )
            return response

        # Send 10 concurrent requests
        async with trio.open_nursery() as nursery:
            responses = []

            async def make_request():
                response = await check_version()
                responses.append(response)

            for _ in range(10):
                nursery.start_soon(make_request)

        # All should succeed
        assert len(responses) == 10
        for response in responses:
            assert response.status_code == 200
            assert response.json()["compatible"] is True


@pytest.mark.trio
async def test_version_info_consistency(test_server_url):
    """Test that version info endpoint returns consistent data."""
    async with httpx.AsyncClient() as client:
        # Make multiple requests
        responses = []
        for _ in range(5):
            response = await client.get(f"{test_server_url}/api/version")
            responses.append(response.json())

        # All responses should have same version info
        api_versions = [r["api_version"] for r in responses]
        min_versions = [r["min_client_version"] for r in responses]

        assert len(set(api_versions)) == 1, "API version should be consistent"
        assert len(set(min_versions)) == 1, "Min client version should be consistent"

        # Server times should be different (progressing)
        server_times = [r["server_time"] for r in responses]
        assert len(set(server_times)) > 1, "Server times should progress"


@pytest.mark.trio
async def test_version_check_before_authentication(test_server_url):
    """Test that version check can be done before authentication."""
    # This test verifies that the version endpoints are truly public

    async with httpx.AsyncClient() as client:
        # Get version info without any authentication
        version_response = await client.get(f"{test_server_url}/api/version")
        assert version_response.status_code == 200

        # Check compatibility without authentication
        check_response = await client.post(
            f"{test_server_url}/api/version/check",
            json={"client_version": str(API_VERSION), "client_type": "console"},
        )
        assert check_response.status_code == 200

        # Verify we cannot access protected endpoint without auth
        # (When auth is enabled - behavior depends on REQUIRE_AUTHENTICATION)
        status_response = await client.get(f"{test_server_url}/api/user/status")
        # Should be either 200 (auth disabled) or 401 (auth enabled)
        assert status_response.status_code in [200, 401]
