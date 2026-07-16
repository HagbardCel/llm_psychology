"""Lifespan and readiness integration tests for /api/v1."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient

from jung.api.app import create_app
from tests.jung_api_fixtures import runtime_factory


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
async def test_lifespan_logs_ready_and_shutdown_complete(
    store,
    fake_llm,
    api_settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(
        api_settings,
        runtime_factory=runtime_factory(store, fake_llm),
    )

    with caplog.at_level(logging.INFO, logger="jung.api.app"):
        async with app.router.lifespan_context(app):
            assert any(
                record.message == "api_ready"
                for record in caplog.records
            )

    assert any(
        record.message == "api_shutdown_complete"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_failed_runtime_exit_does_not_log_shutdown_complete(
    store,
    fake_llm,
    api_settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    base_factory = runtime_factory(store, fake_llm)

    @asynccontextmanager
    async def failing_exit_factory(settings):
        async with base_factory(settings) as runtime:
            try:
                yield runtime
            finally:
                raise RuntimeError("shutdown failed")

    app = create_app(api_settings, runtime_factory=failing_exit_factory)

    with caplog.at_level(logging.INFO, logger="jung.api.app"):
        with pytest.raises(ExceptionGroup) as exc_info:
            async with app.router.lifespan_context(app):
                pass

    assert any(
        isinstance(exc, RuntimeError) and str(exc) == "shutdown failed"
        for exc in exc_info.value.exceptions
    )

    assert not any(
        record.message == "api_shutdown_complete"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_runtime_cleared_after_lifespan_exit(api_app) -> None:
    async with api_app.router.lifespan_context(api_app):
        assert api_app.state.api.ready is True
        assert api_app.state.api.runtime is not None
    assert api_app.state.api.ready is False
    assert api_app.state.api.runtime is None
