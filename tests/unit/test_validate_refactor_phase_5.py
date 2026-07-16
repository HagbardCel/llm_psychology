"""Unit tests for Phase 5 refactor validation."""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "validate_refactor_phase_5.py"
)
_SPEC = importlib.util.spec_from_file_location("validate_refactor_phase_5", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

REQUIRED_PUBLIC_FILES = _MODULE.REQUIRED_PUBLIC_FILES
REQUIRED_PHASE_5_TEST_FILES = _MODULE.REQUIRED_PHASE_5_TEST_FILES
RuntimeContract = _MODULE.RuntimeContract
_collect_schema_semantics = _MODULE._collect_schema_semantics
_collect_openapi_user_id_hits = _MODULE.collect_openapi_user_id_hits
_extract_websocket_paths = _MODULE._extract_websocket_paths
extract_runtime_contract = _MODULE.extract_runtime_contract
validate_repository = _MODULE.validate_repository
validate_runtime_contract = _MODULE.validate_runtime_contract
validate_static_repository = _MODULE.validate_static_repository


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_valid_static_tree(root: Path) -> None:
    for relative in REQUIRED_PUBLIC_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    for relative in REQUIRED_PHASE_5_TEST_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project.scripts]
            jung-api = "jung.api.app:cli"
            jung-console = "jung.client.terminal:cli"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    (root / "Makefile").write_text(
        textwrap.dedent(
            """
            phase-5-test:
            validate-refactor-phase-5:
            probe-console-v1-deterministic:
            """
        ).lstrip(),
        encoding="utf-8",
    )


def _messages(root: Path) -> list[str]:
    return [item.message for item in validate_static_repository(root)]


def test_validate_current_repository_passes() -> None:
    violations = validate_repository(_repo_root())
    assert violations == []


def test_extract_runtime_contract_does_not_invoke_runtime_factory() -> None:
    contract = extract_runtime_contract()
    assert contract.http_operations
    assert contract.websocket_paths == ("/api/v1/chat",)
    assert "send_message" in contract.command_discriminators
    assert "token" in contract.event_discriminators


def test_extract_websocket_paths_retains_direct_and_nested_routes() -> None:
    from fastapi import APIRouter, FastAPI, WebSocket

    app = FastAPI()

    outer = APIRouter(prefix="/api/v1")
    inner = APIRouter()

    @inner.websocket("/chat")
    async def included_chat(_websocket: WebSocket) -> None:
        pass

    outer.include_router(inner)
    app.include_router(outer)

    async def direct_extra(_websocket: WebSocket) -> None:
        pass

    app.router.add_websocket_route("/extra", direct_extra)

    assert _extract_websocket_paths(app) == (
        "/api/v1/chat",
        "/extra",
    )


def test_extract_websocket_paths_returns_both_prefixes_for_reused_router() -> None:
    from fastapi import APIRouter, FastAPI, WebSocket

    app = FastAPI()
    shared = APIRouter()

    @shared.websocket("/chat")
    async def chat(_websocket: WebSocket) -> None:
        pass

    app.include_router(shared, prefix="/api/v1")
    app.include_router(shared, prefix="/debug")

    assert _extract_websocket_paths(app) == (
        "/api/v1/chat",
        "/debug/chat",
    )


def test_valid_static_tree_passes(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    assert validate_static_repository(tmp_path) == []


def test_missing_required_public_file_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    (tmp_path / "src/jung/api/app.py").unlink()

    assert _messages(tmp_path) == [
        "missing public file: src/jung/api/app.py",
    ]


def test_missing_required_test_file_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    (
        tmp_path / "tests/integration/jung/api/test_api_resilience.py"
    ).unlink()

    assert _messages(tmp_path) == [
        "missing required test file: "
        "tests/integration/jung/api/test_api_resilience.py",
    ]


def test_missing_pyproject_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    (tmp_path / "pyproject.toml").unlink()

    assert _messages(tmp_path) == [
        "missing required file: pyproject.toml",
    ]


def test_missing_makefile_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    (tmp_path / "Makefile").unlink()

    assert _messages(tmp_path) == [
        "missing required file: Makefile",
    ]


def test_wrong_cli_script_mapping_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project.scripts]
            jung-api = "jung.api.app:wrong"
            jung-console = "jung.client.terminal:cli"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    assert _messages(tmp_path) == [
        "pyproject script 'jung-api' must map to 'jung.api.app:cli'",
    ]


def test_missing_make_target_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    (tmp_path / "Makefile").write_text(
        textwrap.dedent(
            """
            phase-5-test:
            probe-console-v1-deterministic:
            """
        ).lstrip(),
        encoding="utf-8",
    )

    assert _messages(tmp_path) == [
        "Makefile missing target: validate-refactor-phase-5",
    ]


def test_source_user_id_attribute_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    target = tmp_path / "src/jung/api/routes.py"
    target.write_text("value = request.user_id\n", encoding="utf-8")

    messages = _messages(tmp_path)
    assert messages == [
        "src/jung/api/routes.py:1: user_id attribute",
    ]


def test_source_user_id_keyword_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    target = tmp_path / "src/jung/api/routes.py"
    target.write_text("connect(user_id=value)\n", encoding="utf-8")

    assert _messages(tmp_path) == [
        "src/jung/api/routes.py:1: user_id keyword",
    ]


def test_source_user_id_import_alias_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    target = tmp_path / "src/jung/client/api_client.py"
    target.write_text("import package as user_id\n", encoding="utf-8")

    assert _messages(tmp_path) == [
        "src/jung/client/api_client.py:1: user_id import alias",
    ]


def test_source_user_id_import_module_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    target = tmp_path / "src/jung/api/routes.py"
    target.write_text(
        "from package.user_id import SomeType\n",
        encoding="utf-8",
    )

    assert _messages(tmp_path) == [
        "src/jung/api/routes.py:1: user_id import module",
    ]


def test_source_user_identity_module_is_allowed(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    target = tmp_path / "src/jung/api/routes.py"
    target.write_text(
        "from package.user_identity import SomeType\n",
        encoding="utf-8",
    )

    assert validate_static_repository(tmp_path) == []


def test_legacy_ws_event_fails(tmp_path: Path) -> None:
    build_valid_static_tree(tmp_path)
    target = tmp_path / "src/jung/api/routes.py"
    target.write_text('EVENT = "workflow_next_action"\n', encoding="utf-8")

    assert _messages(tmp_path) == [
        "src/jung/api/routes.py:1: legacy event 'workflow_next_action'",
    ]


def test_schema_user_id_in_descriptive_text_is_allowed() -> None:
    schema = {
        "title": "User ID migration note",
        "description": "The legacy user_id field was removed.",
        "examples": [{"note": "user_id is not accepted"}],
    }
    assert _collect_schema_semantics(schema) == []


def test_schema_user_id_property_is_flagged() -> None:
    schema = {"properties": {"user_id": {"type": "string"}}}
    hits = _collect_schema_semantics(schema)
    assert hits
    assert hits[0][1] == "property name user_id"


def test_schema_user_id_required_is_flagged() -> None:
    schema = {"required": ["user_id"]}
    hits = _collect_schema_semantics(schema)
    assert hits
    assert hits[0][1] == "required entry user_id"


def test_schema_user_id_discriminator_property_name_is_flagged() -> None:
    schema = {"discriminator": {"propertyName": "user_id"}}
    hits = _collect_schema_semantics(schema)
    assert hits
    assert hits[0][1] == "discriminator propertyName user_id"


def test_schema_user_id_discriminator_mapping_key_is_flagged() -> None:
    schema = {
        "discriminator": {
            "propertyName": "type",
            "mapping": {"user_id": "#/components/schemas/Profile"},
        }
    }
    hits = _collect_schema_semantics(schema)
    assert any(reason == "discriminator mapping key user_id" for _, reason in hits)


def test_schema_user_id_mapping_value_is_flagged() -> None:
    schema = {
        "discriminator": {
            "propertyName": "type",
            "mapping": {"profile": "#/components/schemas/user_id"},
        },
    }
    hits = _collect_schema_semantics(schema)
    assert any(
        reason == "discriminator mapping value terminal user_id"
        for _, reason in hits
    )


def test_schema_user_id_ref_terminal_is_flagged() -> None:
    schema = {"$ref": "#/components/schemas/user_id"}
    hits = _collect_schema_semantics(schema)
    assert hits
    assert hits[0][1] == "$ref terminal user_id"


def test_validate_runtime_contract_reports_missing_http_operation() -> None:
    contract = RuntimeContract(
        http_operations=frozenset(),
        websocket_paths=("/api/v1/chat",),
        command_discriminators=frozenset({"send_message"}),
        event_discriminators=_MODULE.EXPECTED_EVENT_DISCRIMINATORS,
        openapi_document={},
        ws_schemas={},
    )
    violations = validate_runtime_contract(contract)
    assert any("missing HTTP operation" in item.message for item in violations)


def test_validate_runtime_contract_reports_unexpected_websocket_path() -> None:
    contract = RuntimeContract(
        http_operations=_MODULE.EXPECTED_HTTP_OPERATIONS,
        websocket_paths=("/api/v1/chat", "/api/v1/extra"),
        command_discriminators=frozenset({"send_message"}),
        event_discriminators=_MODULE.EXPECTED_EVENT_DISCRIMINATORS,
        openapi_document={},
        ws_schemas={},
    )
    messages = [item.message for item in validate_runtime_contract(contract)]
    assert any("unexpected websocket paths" in message for message in messages)


def test_validate_runtime_contract_reports_discriminator_mismatch() -> None:
    contract = RuntimeContract(
        http_operations=_MODULE.EXPECTED_HTTP_OPERATIONS,
        websocket_paths=("/api/v1/chat",),
        command_discriminators=frozenset({"other_command"}),
        event_discriminators=_MODULE.EXPECTED_EVENT_DISCRIMINATORS,
        openapi_document={},
        ws_schemas={},
    )
    messages = [item.message for item in validate_runtime_contract(contract)]
    assert any(
        "missing command discriminator: send_message" in message
        for message in messages
    )
    assert any(
        "unexpected command discriminator: other_command" in message
        for message in messages
    )


def test_validate_runtime_contract_reports_event_discriminator_mismatch() -> None:
    contract = RuntimeContract(
        http_operations=_MODULE.EXPECTED_HTTP_OPERATIONS,
        websocket_paths=("/api/v1/chat",),
        command_discriminators=frozenset({"send_message"}),
        event_discriminators=(
            _MODULE.EXPECTED_EVENT_DISCRIMINATORS - {"token"}
        ) | {"unexpected_event"},
        openapi_document={},
        ws_schemas={},
    )
    messages = [item.message for item in validate_runtime_contract(contract)]
    assert "missing event discriminator: token" in messages
    assert "unexpected event discriminator: unexpected_event" in messages


def test_openapi_query_alias_user_id_is_flagged() -> None:
    from fastapi import FastAPI, Query

    app = FastAPI()

    @app.get("/probe")
    def probe(legacy_user: str = Query(alias="user_id")) -> dict[str, str]:
        return {"legacy_user": legacy_user}

    hits = _collect_openapi_user_id_hits(app.openapi())
    assert any(reason == "parameter name user_id" for _, reason in hits)


def test_openapi_header_alias_user_id_is_flagged() -> None:
    from fastapi import FastAPI, Header

    app = FastAPI()

    @app.get("/probe")
    def probe(legacy_user: str = Header(alias="user_id")) -> dict[str, str]:
        return {"legacy_user": legacy_user}

    hits = _collect_openapi_user_id_hits(app.openapi())
    assert any(reason == "parameter name user_id" for _, reason in hits)


def test_openapi_nested_parameter_schema_user_id_is_flagged() -> None:
    document = {
        "paths": {
            "/probe": {
                "get": {
                    "parameters": [
                        {
                            "name": "filter",
                            "in": "query",
                            "schema": {
                                "type": "object",
                                "properties": {"user_id": {"type": "string"}},
                            },
                        }
                    ]
                }
            }
        }
    }
    hits = _collect_openapi_user_id_hits(document)
    assert any(reason == "property name user_id" for _, reason in hits)


def test_openapi_request_body_user_id_property_is_flagged() -> None:
    document = {
        "paths": {
            "/probe": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"user_id": {"type": "string"}},
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    hits = _collect_openapi_user_id_hits(document)
    assert any(reason == "property name user_id" for _, reason in hits)


def test_openapi_parameter_ref_user_id_is_flagged() -> None:
    document = {
        "components": {
            "parameters": {
                "LegacyUser": {
                    "name": "user_id",
                    "in": "query",
                    "schema": {"type": "string"},
                }
            }
        },
        "paths": {
            "/probe": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/LegacyUser"}]
                }
            }
        },
    }
    hits = _collect_openapi_user_id_hits(document)
    assert any(reason == "parameter name user_id" for _, reason in hits)


def test_openapi_request_body_ref_user_id_is_flagged() -> None:
    document = {
        "components": {
            "requestBodies": {
                "LegacyBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"user_id": {"type": "string"}},
                            }
                        }
                    }
                }
            }
        },
        "paths": {
            "/probe": {
                "post": {
                    "requestBody": {
                        "$ref": "#/components/requestBodies/LegacyBody"
                    }
                }
            }
        },
    }
    hits = _collect_openapi_user_id_hits(document)
    assert any(reason == "property name user_id" for _, reason in hits)


def test_openapi_descriptive_user_id_text_is_allowed() -> None:
    document = {
        "components": {
            "schemas": {
                "Profile": {
                    "type": "object",
                    "description": "Profile without user_id field",
                    "properties": {"name": {"type": "string"}},
                }
            }
        }
    }
    assert _collect_openapi_user_id_hits(document) == []


def test_openapi_outer_parameter_ref_cycle_terminates() -> None:
    document = {
        "components": {
            "parameters": {
                "A": {"$ref": "#/components/parameters/B"},
                "B": {"$ref": "#/components/parameters/A"},
            }
        },
        "paths": {
            "/probe": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/A"}]
                }
            }
        },
    }
    assert _collect_openapi_user_id_hits(document) == []


def test_openapi_outer_request_body_ref_cycle_terminates() -> None:
    document = {
        "components": {
            "requestBodies": {
                "A": {"$ref": "#/components/requestBodies/B"},
                "B": {"$ref": "#/components/requestBodies/A"},
            }
        },
        "paths": {
            "/probe": {
                "post": {
                    "requestBody": {"$ref": "#/components/requestBodies/A"}
                }
            }
        },
    }
    assert _collect_openapi_user_id_hits(document) == []


def test_validate_runtime_contract_reports_openapi_parameter_user_id() -> None:
    contract = RuntimeContract(
        http_operations=_MODULE.EXPECTED_HTTP_OPERATIONS,
        websocket_paths=("/api/v1/chat",),
        command_discriminators=frozenset({"send_message"}),
        event_discriminators=_MODULE.EXPECTED_EVENT_DISCRIMINATORS,
        openapi_document={
            "paths": {
                "/probe": {
                    "get": {
                        "parameters": [
                            {
                                "name": "user_id",
                                "in": "query",
                                "schema": {"type": "string"},
                            }
                        ]
                    }
                }
            }
        },
        ws_schemas={},
    )
    messages = [item.message for item in validate_runtime_contract(contract)]
    assert any(
        "OpenAPI public surface includes user_id" in message
        for message in messages
    )
