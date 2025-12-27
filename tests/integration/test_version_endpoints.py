"""Integration tests for version API endpoints."""

import importlib.util
from pathlib import Path

import httpx
import pytest
from psychoanalyst_app.version import API_VERSION, MIN_CLIENT_VERSION

pytestmark = pytest.mark.trio


def _load_console_version_check():
    module_path = Path(__file__).resolve().parents[2] / "console-ui" / "src" / "version_check.py"
    spec = importlib.util.spec_from_file_location(
        "console_version_check", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load console version checker at {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def server_url(test_server_websocket):
    """Get server URL from test_server_websocket fixture."""
    return test_server_websocket["url"]


async def test_get_version_info(server_url):
    """Test GET /api/version endpoint."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{server_url}/api/version")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "api_version" in data
        assert "min_client_version" in data
        assert "server_time" in data

        # Verify version values
        assert data["api_version"] == str(API_VERSION)
        assert data["min_client_version"] == str(MIN_CLIENT_VERSION)

        # Verify server_time is ISO 8601 format
        assert "T" in data["server_time"]
        assert "Z" in data["server_time"] or "+" in data["server_time"]


async def test_check_version_compatible(server_url):
    """Test POST /api/version/check with compatible version."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/api/version/check",
            json={"client_version": str(API_VERSION), "client_type": "console"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "compatible" in data
        assert "api_version" in data
        assert "client_version" in data
        assert "message" in data
        assert "upgrade_required" in data
        assert "upgrade_recommended" in data

        # Verify compatibility
        assert data["compatible"] is True
        assert data["upgrade_required"] is False
        assert data["api_version"] == str(API_VERSION)
        assert data["client_version"] == str(API_VERSION)


async def test_check_version_incompatible_major(server_url):
    """Test version check with incompatible major version."""
    async with httpx.AsyncClient() as client:
        # Try with a different major version
        incompatible_version = f"{API_VERSION.major + 1}.0.0"

        response = await client.post(
            f"{server_url}/api/version/check",
            json={"client_version": incompatible_version, "client_type": "web"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should be incompatible due to major version mismatch
        assert data["compatible"] is False
        assert "not compatible" in data["message"].lower()


async def test_check_version_too_old(server_url):
    """Test version check with client version below minimum."""
    async with httpx.AsyncClient() as client:
        # Use a version older than MIN_CLIENT_VERSION
        if MIN_CLIENT_VERSION.major > 0:
            old_version = f"{MIN_CLIENT_VERSION.major - 1}.9.9"
        else:
            old_version = "0.0.1"

        response = await client.post(
            f"{server_url}/api/version/check",
            json={"client_version": old_version, "client_type": "console"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should require upgrade
        assert data["compatible"] is False
        assert data["upgrade_required"] is True
        assert (
            "too old" in data["message"].lower() or "upgrade" in data["message"].lower()
        )


async def test_check_version_outdated_but_compatible(server_url):
    """Test version check with outdated but still compatible version."""
    async with httpx.AsyncClient() as client:
        if API_VERSION.minor == 0:
            pytest.skip("No older minor version to test against (API_VERSION.minor == 0)")

        outdated_version = f"{API_VERSION.major}.{API_VERSION.minor - 1}.0"

        response = await client.post(
            f"{server_url}/api/version/check",
            json={"client_version": outdated_version, "client_type": "web"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should be compatible but recommend upgrade
        assert data["compatible"] is True
        assert data["upgrade_required"] is False
        assert data["upgrade_recommended"] is True
        assert (
            "outdated" in data["message"].lower()
            or "consider" in data["message"].lower()
        )


async def test_check_version_invalid_format(server_url):
    """Test version check with invalid version format."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/api/version/check",
            json={"client_version": "invalid", "client_type": "console"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "invalid" in data["error"].lower()


async def test_check_version_missing_fields(server_url):
    """Test version check with missing required fields."""
    async with httpx.AsyncClient() as client:
        # Missing client_version
        response = await client.post(
            f"{server_url}/api/version/check", json={"client_type": "console"}
        )

        assert response.status_code == 400

        # Missing client_type
        response = await client.post(
            f"{server_url}/api/version/check", json={"client_version": "1.0.0"}
        )

        assert response.status_code == 400


async def test_check_version_invalid_client_type(server_url):
    """Test version check with invalid client type."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/api/version/check",
            json={"client_version": "1.0.0", "client_type": "invalid"},
        )

        # Should return 400 due to enum validation
        assert response.status_code == 400


async def test_version_endpoints_no_auth_required(server_url):
    """Test that version endpoints do not require authentication."""
    async with httpx.AsyncClient() as client:
        # GET /api/version should work without auth
        response = await client.get(f"{server_url}/api/version")
        assert response.status_code == 200

        # POST /api/version/check should work without auth
        response = await client.post(
            f"{server_url}/api/version/check",
            json={"client_version": "1.0.0", "client_type": "console"},
        )
        assert response.status_code == 200


async def test_version_check_patch_difference(server_url):
    """Test that patch version differences don't affect compatibility."""
    different_patch = f"{API_VERSION.major}.{API_VERSION.minor}.{API_VERSION.patch + 1}"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/api/version/check",
            json={"client_version": different_patch, "client_type": "web"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["compatible"] is True
        assert data["upgrade_required"] is False


async def test_console_client_version_check_flow(server_url):
    """Test the console client's version-check helper against the running backend."""
    version_check = _load_console_version_check()
    check_backend_version = getattr(version_check, "check_backend_version")
    compatible, message = await check_backend_version(server_url)
    assert compatible is True
    assert message
