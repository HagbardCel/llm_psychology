"""Lifespan and readiness integration tests for /api/v1."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_state_without_lifespan_returns_not_ready(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/state")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "not_ready"
    assert body["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_malformed_request_id_before_lifespan_returns_422(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get(
        "/api/v1/state",
        headers={"X-Request-ID": "bad"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_health_without_lifespan_returns_not_ready(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["code"] == "not_ready"


@pytest.mark.asyncio
async def test_health_inside_lifespan_returns_healthy(
    started_api_client: AsyncClient,
) -> None:
    response = await started_api_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_api_state_initialized_at_construction(api_app) -> None:
    assert api_app.state.api.ready is False
    assert api_app.state.api.runtime is None


@pytest.mark.asyncio
async def test_runtime_cleared_after_lifespan_exit(api_app) -> None:
    async with api_app.router.lifespan_context(api_app):
        assert api_app.state.api.ready is True
        assert api_app.state.api.runtime is not None
    assert api_app.state.api.ready is False
    assert api_app.state.api.runtime is None
