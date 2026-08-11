"""HTTP error, correlation, and sanitization boundary tests for /api/v1."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient

from jung.api.app import create_app
from jung.domain.errors import InvariantViolation
from tests.support.api import application_factory


def _assert_safe_error_log(
    records: list[logging.LogRecord],
    *,
    message: str,
    request_id: str,
    exception_type: str,
) -> None:
    matching = [
        record
        for record in records
        if record.getMessage() == message
        and getattr(record, "request_id", None) == request_id
        and getattr(record, "exception_type", None) == exception_type
    ]

    assert len(matching) == 1
    assert matching[0].exc_info is None


@pytest.mark.asyncio
async def test_success_generates_request_id(started_api_client: AsyncClient) -> None:
    response = await started_api_client.get("/api/v1/state")
    assert response.status_code == 200
    assert UUID(response.headers["X-Request-ID"])


@pytest.mark.asyncio
async def test_success_preserves_valid_request_id(
    started_api_client: AsyncClient,
) -> None:
    request_id = str(uuid4())
    response = await started_api_client.get(
        "/api/v1/state",
        headers={"X-Request-ID": request_id},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


@pytest.mark.asyncio
async def test_invalid_request_body_returns_validation_error(
    started_api_client: AsyncClient,
) -> None:
    response = await started_api_client.put(
        "/api/v1/profile",
        json={
            "profile": {
                "name": "Alex",
                "primary_language": "English",
                "date_of_birth": None,
                "notes": None,
            },
            "unexpected_field": True,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "HTTPValidationError" not in response.text
    assert "detail" not in body


@pytest.mark.asyncio
async def test_malformed_request_id_logs_http_completion(
    started_api_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="jung.api.app"):
        response = await started_api_client.get(
            "/api/v1/state",
            headers={"X-Request-ID": "bad"},
        )

    assert response.status_code == 422
    matching = [
        record
        for record in caplog.records
        if record.message == "HTTP request completed"
        and getattr(record, "status", None) == 422
        and getattr(record, "path", None) == "/api/v1/state"
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_success_logs_http_completion(
    started_api_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="jung.api.app"):
        response = await started_api_client.get("/api/v1/state")

    assert response.status_code == 200
    matching = [
        record
        for record in caplog.records
        if record.message == "HTTP request completed"
        and getattr(record, "status", None) == 200
        and getattr(record, "path", None) == "/api/v1/state"
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_unexpected_exception_returns_sanitized_internal_error(
    store,
    fake_llm,
    api_settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "secret internal detail"
    app = create_app(
        api_settings,
        application_factory=application_factory(store, fake_llm),
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            application = app.state.api.application

            async def failing_get_snapshot():
                raise RuntimeError(secret)

            application.get_snapshot = failing_get_snapshot  # type: ignore[method-assign]
            with caplog.at_level(logging.ERROR, logger="jung.api.app"):
                response = await client.get("/api/v1/state")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert secret not in response.text
    _assert_safe_error_log(
        caplog.records,
        message="unhandled API error",
        request_id=str(body["request_id"]),
        exception_type="RuntimeError",
    )
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_internal_domain_error_is_logged_and_sanitized(
    store,
    fake_llm,
    api_settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "invariant secret detail"
    app = create_app(
        api_settings,
        application_factory=application_factory(store, fake_llm),
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            application = app.state.api.application

            async def failing_get_snapshot():
                raise InvariantViolation(secret)

            application.get_snapshot = failing_get_snapshot  # type: ignore[method-assign]
            with caplog.at_level(logging.ERROR, logger="jung.api.app"):
                response = await client.get("/api/v1/state")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert secret not in response.text
    _assert_safe_error_log(
        caplog.records,
        message="internal domain error",
        request_id=str(body["request_id"]),
        exception_type="InvariantViolation",
    )
    assert secret not in caplog.text
