"""Generated OpenAPI schema and route-surface contracts for /api/v1."""

from __future__ import annotations

from starlette.routing import Route

OPENAPI_OPERATION_METHODS = frozenset(
    {
        "get",
        "put",
        "post",
        "delete",
        "patch",
        "options",
        "head",
        "trace",
    }
)

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
    ("post", "/api/v1/chat"),
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
        if method in OPENAPI_OPERATION_METHODS
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


def test_openapi_schema_property_inventories(api_app) -> None:
    schema = api_app.openapi()
    components = schema["components"]["schemas"]

    snapshot = components["AppSnapshotResponse"]
    assert set(snapshot["properties"]) == {
        "stage",
        "profile_complete",
        "selected_style",
        "active_session",
        "operation",
        "available_commands",
    }

    profile_update = components["ProfileUpdateRequest"]
    assert set(profile_update["properties"]) == {"profile"}

    profile_wire = components["ProfileWire"]
    assert set(profile_wire["properties"]) == {
        "name",
        "primary_language",
        "date_of_birth",
        "notes",
    }

    select_style = components["SelectStyleRequest"]
    assert set(select_style["properties"]) == {"style_id"}

    chat_request = components["ChatRequest"]
    assert set(chat_request["properties"]) == {
        "session_id",
        "client_message_id",
        "content",
    }

    assert set(components["StyleOptionsResponse"]["properties"]) == {
        "styles",
        "recommendations",
    }
    assert set(components["StyleSummaryResponse"]["properties"]) == {
        "id",
        "name",
        "description",
    }
    assert set(components["StyleRecommendationSummaryResponse"]["properties"]) == {
        "style_id",
        "score",
        "rationale",
        "key_topics",
    }


def test_openapi_chat_stream_response_media_type(api_app) -> None:
    schema = api_app.openapi()
    operation = schema["paths"]["/api/v1/chat"]["post"]
    assert "requestBody" in operation
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("ChatRequest")

    content = operation["responses"]["200"]["content"]
    assert "application/x-ndjson" in content
    assert "application/json" not in content


def test_openapi_bodyless_post_commands_have_no_request_body(api_app) -> None:
    schema = api_app.openapi()
    bodyless = (
        ("post", "/api/v1/sessions"),
        ("post", "/api/v1/sessions/{session_id}/end"),
        ("post", "/api/v1/operations/current/retry"),
    )
    for method, path in bodyless:
        label = _operation_label(method, path)
        operation = schema["paths"][path][method]
        assert "requestBody" not in operation, f"{label} must not declare requestBody"
