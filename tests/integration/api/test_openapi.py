"""Generated OpenAPI schema and route-surface contracts for /api/v1."""

from __future__ import annotations

from starlette.routing import Route

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


def _operation_label(method: str, path: str) -> str:
    return f"{method.upper()} {path}"


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

    paths = {route.path for route in api_app.routes if isinstance(route, Route)}
    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths


def test_openapi_common_operation_contract(api_app) -> None:
    schema = api_app.openapi()
    for method, path in sorted(EXPECTED_OPERATIONS):
        label = _operation_label(method, path)
        operation = schema["paths"][path][method]
        responses = operation.get("responses", {})
        assert "HTTPValidationError" not in str(responses), (
            f"{label} documents HTTPValidationError"
        )
        assert "422" in responses, f"{label} missing 422 response"
        response_schema = responses["422"]["content"]["application/json"]["schema"]
        assert response_schema["$ref"].endswith("ErrorResponse"), (
            f"{label} 422 schema is not ErrorResponse"
        )

        parameters = operation.get("parameters", [])
        assert any(
            parameter["in"] == "header"
            and parameter["name"].lower() == "x-request-id"
            and parameter.get("required") is False
            for parameter in parameters
        ), f"{label} missing optional X-Request-ID"


def test_openapi_snapshot_response_contract(api_app) -> None:
    schema = api_app.openapi()
    for method, path, status_code in SNAPSHOT_OPERATIONS:
        label = _operation_label(method, path)
        operation = schema["paths"][path][method]
        response_schema = operation["responses"][status_code]["content"][
            "application/json"
        ]["schema"]
        assert response_schema["$ref"].endswith("AppSnapshotResponse"), (
            f"{label} {status_code} schema is not AppSnapshotResponse"
        )
