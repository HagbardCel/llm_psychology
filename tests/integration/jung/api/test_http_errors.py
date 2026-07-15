"""HTTP error, correlation, and OpenAPI contract tests for /api/v1."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient

from jung.api.app import create_app
from jung.domain.errors import InvariantViolation
from tests.integration.jung.conftest import _runtime_factory

EXPECTED_OPERATIONS = {
    ("get", "/api/v1/state"),
    ("get", "/api/v1/profile"),
    ("put", "/api/v1/profile"),
    ("get", "/api/v1/styles"),
    ("put", "/api/v1/style"),
    ("get", "/api/v1/sessions"),
    ("post", "/api/v1/sessions"),
    ("get", "/api/v1/sessions/{session_id}"),
    ("post", "/api/v1/sessions/{session_id}/end"),
    ("post", "/api/v1/operations/current/retry"),
    ("get", "/api/v1/health"),
}

SNAPSHOT_OPERATIONS = (
    ("get", "/api/v1/state", "200"),
    ("put", "/api/v1/profile", "200"),
    ("put", "/api/v1/style", "200"),
    ("post", "/api/v1/sessions/{session_id}/end", "202"),
    ("post", "/api/v1/operations/current/retry", "202"),
)


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
async def test_success_preserves_valid_request_id(started_api_client: AsyncClient) -> None:
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
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "HTTPValidationError" not in response.text
    assert "detail" not in body


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
        runtime_factory=_runtime_factory(store, fake_llm),
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            application = app.state.api.runtime.application

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
        runtime_factory=_runtime_factory(store, fake_llm),
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            application = app.state.api.runtime.application

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


@pytest.mark.asyncio
async def test_stale_revision_conflict_includes_snapshot(
    started_api_client: AsyncClient,
) -> None:
    revision = (await started_api_client.get("/api/v1/state")).json()["revision"]
    response = await started_api_client.put(
        "/api/v1/profile",
        json={
            "expected_revision": revision - 1,
            "profile": {
                "name": "Alex",
                "primary_language": "English",
                "date_of_birth": None,
                "notes": None,
            },
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "state_conflict"
    assert body["current_snapshot"] is not None
    assert body["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_revision_conflict_enrichment_failure_keeps_409(
    store,
    fake_llm,
    api_settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "secret enrichment detail"
    app = create_app(
        api_settings,
        runtime_factory=_runtime_factory(store, fake_llm),
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            revision = (await client.get("/api/v1/state")).json()["revision"]
            application = app.state.api.runtime.application

            async def failing_get_snapshot():
                raise RuntimeError(secret)

            application.get_snapshot = failing_get_snapshot  # type: ignore[method-assign]
            with caplog.at_level(logging.ERROR, logger="jung.api.app"):
                response = await client.put(
                    "/api/v1/profile",
                    json={
                        "expected_revision": revision - 1,
                        "profile": {
                            "name": "Alex",
                            "primary_language": "English",
                            "date_of_birth": None,
                            "notes": None,
                        },
                    },
                )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "state_conflict"
    assert body["current_snapshot"] is None
    assert body["request_id"] == response.headers["X-Request-ID"]
    _assert_safe_error_log(
        caplog.records,
        message="failed to enrich revision conflict snapshot",
        request_id=str(body["request_id"]),
        exception_type="RuntimeError",
    )
    assert secret not in caplog.text


def test_no_generic_exception_handler_registered(api_app) -> None:
    assert Exception not in api_app.exception_handlers


def test_openapi_operation_inventory(api_app) -> None:
    schema = api_app.openapi()
    operations = {
        (method, path)
        for path, methods in schema["paths"].items()
        for method in methods
        if method in {"get", "put", "post"}
    }
    assert operations == EXPECTED_OPERATIONS


def test_openapi_route_surface(api_app) -> None:
    assert api_app.docs_url is None
    assert api_app.redoc_url is None
    assert api_app.openapi_url == "/api/v1/openapi.json"
    from starlette.routing import Route

    paths = {
        route.path for route in api_app.routes if isinstance(route, Route)
    }
    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths


@pytest.mark.parametrize("method,path", sorted(EXPECTED_OPERATIONS))
def test_openapi_documents_error_response_not_http_validation(
    api_app,
    method: str,
    path: str,
) -> None:
    schema = api_app.openapi()
    operation = schema["paths"][path][method]
    responses = operation.get("responses", {})
    assert "HTTPValidationError" not in str(responses)
    assert "422" in responses
    response_schema = responses["422"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("ErrorResponse")


@pytest.mark.parametrize("method,path", sorted(EXPECTED_OPERATIONS))
def test_openapi_documents_optional_request_id_header(
    api_app,
    method: str,
    path: str,
) -> None:
    schema = api_app.openapi()
    operation = schema["paths"][path][method]
    parameters = operation.get("parameters", [])

    assert any(
        parameter["in"] == "header"
        and parameter["name"].lower() == "x-request-id"
        and parameter.get("required") is False
        for parameter in parameters
    )


@pytest.mark.parametrize("method,path,status_code", SNAPSHOT_OPERATIONS)
def test_openapi_snapshot_success_schema(
    api_app,
    method: str,
    path: str,
    status_code: str,
) -> None:
    schema = api_app.openapi()
    operation = schema["paths"][path][method]
    response_schema = operation["responses"][status_code]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["$ref"].endswith("AppSnapshotResponse")
