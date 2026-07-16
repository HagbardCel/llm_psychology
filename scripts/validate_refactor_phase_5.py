#!/usr/bin/env python3
"""Static and runtime contract checks for Phase 5 API/client handoff."""

from __future__ import annotations

import ast
import tempfile
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import get_args, get_origin

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PUBLIC_FILES = (
    Path("src/jung/api/app.py"),
    Path("src/jung/api/routes.py"),
    Path("src/jung/api/websocket.py"),
    Path("src/jung/api/contracts.py"),
    Path("src/jung/api/errors.py"),
    Path("src/jung/client/api_client.py"),
    Path("src/jung/client/console.py"),
)

REQUIRED_PHASE_5_TEST_FILES = (
    Path("tests/integration/jung/api/test_api_resilience.py"),
    Path("tests/integration/jung/client/test_api_resilience.py"),
    Path("tests/unit/test_validate_refactor_phase_5.py"),
)

REQUIRED_MAKE_TARGETS = (
    "phase-5-test",
    "validate-refactor-phase-5",
    "probe-console-v1-deterministic",
)

EXPECTED_HTTP_OPERATIONS = frozenset(
    {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/profile"),
        ("GET", "/api/v1/sessions"),
        ("GET", "/api/v1/sessions/{session_id}"),
        ("GET", "/api/v1/state"),
        ("GET", "/api/v1/styles"),
        ("POST", "/api/v1/operations/current/retry"),
        ("POST", "/api/v1/sessions"),
        ("POST", "/api/v1/sessions/{session_id}/end"),
        ("PUT", "/api/v1/profile"),
        ("PUT", "/api/v1/style"),
    }
)

EXPECTED_WEBSOCKET_PATHS = ("/api/v1/chat",)

EXPECTED_COMMAND_DISCRIMINATORS = frozenset({"send_message"})

EXPECTED_EVENT_DISCRIMINATORS = frozenset(
    {
        "error",
        "message_completed",
        "message_in_progress",
        "operation_changed",
        "snapshot_changed",
        "token",
    }
)

LEGACY_WS_EVENT_NAMES = frozenset(
    {
        "assessment_recommendations",
        "chat_message",
        "chat_response_chunk",
        "connected",
        "job_status",
        "session_ended",
        "session_started",
        "typing_start",
        "typing_stop",
        "workflow_next_action",
    }
)

USER_ID = "user_id"


@dataclass(frozen=True, slots=True)
class Violation:
    message: str


@dataclass(frozen=True, slots=True)
class RuntimeContract:
    http_operations: frozenset[tuple[str, str]]
    websocket_paths: tuple[str, ...]
    command_discriminators: frozenset[str]
    event_discriminators: frozenset[str]
    openapi_schemas: dict[str, object]
    ws_schemas: dict[str, object]


def _python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*.py") if path.is_file())


def _read_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _terminal_component(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _ref_terminal(ref: str) -> str:
    return ref.rstrip("/").rsplit("/", 1)[-1]


def _extract_http_operations(app: object) -> frozenset[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    openapi = app.openapi()
    for path, path_item in openapi.get("paths", {}).items():
        for method in path_item:
            upper = method.upper()
            if upper in {"GET", "PUT", "POST", "DELETE", "PATCH"}:
                operations.add((upper, path))
    return frozenset(operations)


def _extract_websocket_paths(app: object) -> tuple[str, ...]:
    paths: set[str] = set()

    def collect(routes: Iterable[object]) -> None:
        for route in routes:
            if type(route).__name__ == "APIWebSocketRoute":
                paths.add(route.path)

            included = getattr(route, "original_router", None)
            included_routes = getattr(included, "routes", ())
            collect(included_routes)

    collect(getattr(app, "routes", ()))
    return tuple(sorted(paths))


def _schema_names(model: type[object]) -> dict[str, object]:
    if hasattr(model, "model_json_schema"):
        return model.model_json_schema(ref_template="#/components/schemas/{model}")
    return {}


def _collect_schema_semantics(
    schema: object,
    *,
    path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], str]]:
    """Flag user_id only in semantic schema positions, not prose fields."""
    hits: list[tuple[tuple[str, ...], str]] = []
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict) and USER_ID in properties:
            hits.append(
                (
                    (*path, "properties", USER_ID),
                    "property name user_id",
                )
            )

        required = schema.get("required")
        if isinstance(required, list):
            for index, item in enumerate(required):
                if item == USER_ID:
                    hits.append(
                        (
                            (*path, "required", str(index)),
                            "required entry user_id",
                        )
                    )

        discriminator = schema.get("discriminator")
        if isinstance(discriminator, dict):
            property_name = discriminator.get("propertyName")
            if property_name == USER_ID:
                hits.append(
                    (
                        (*path, "discriminator", "propertyName"),
                        "discriminator propertyName user_id",
                    )
                )
            mapping = discriminator.get("mapping")
            if isinstance(mapping, dict):
                for map_key, map_value in mapping.items():
                    if map_key == USER_ID:
                        hits.append(
                            (
                                (*path, "discriminator", "mapping", map_key),
                                "discriminator mapping key user_id",
                            )
                        )
                    if isinstance(map_value, str) and (
                        _ref_terminal(map_value) == USER_ID
                        or _terminal_component(map_value) == USER_ID
                    ):
                        hits.append(
                            (
                                (*path, "discriminator", "mapping", str(map_key)),
                                "discriminator mapping value terminal user_id",
                            )
                        )

        ref = schema.get("$ref")
        if isinstance(ref, str) and _ref_terminal(ref) == USER_ID:
            hits.append(((*path, "$ref"), "$ref terminal user_id"))

        for key, value in schema.items():
            hits.extend(
                _collect_schema_semantics(value, path=(*path, str(key)))
            )
    elif isinstance(schema, list):
        for index, item in enumerate(schema):
            hits.extend(_collect_schema_semantics(item, path=(*path, str(index))))
    return hits


def _literal_discriminators(
    model: type[object],
    field_name: str = "type",
) -> frozenset[str]:
    field = getattr(model, "model_fields", {}).get(field_name)
    if field is None:
        return frozenset()
    annotation = field.annotation
    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        if args:
            annotation = args[0]
    if hasattr(annotation, "__args__"):
        return frozenset(str(item) for item in get_args(annotation))
    if isinstance(annotation, str):
        return frozenset({annotation})
    return frozenset()


def _extract_contract_from_app(app: object) -> RuntimeContract:
    from jung.api.contracts import (
        ErrorEvent,
        MessageCompletedEvent,
        MessageInProgressEvent,
        OperationChangedEvent,
        SendMessageCommand,
        ServerEvent,
        SnapshotChangedEvent,
        TokenEvent,
    )

    openapi = app.openapi()
    event_models = (
        TokenEvent,
        MessageInProgressEvent,
        MessageCompletedEvent,
        SnapshotChangedEvent,
        OperationChangedEvent,
        ErrorEvent,
    )
    command_discriminators = _literal_discriminators(SendMessageCommand)
    event_discriminators: set[str] = set()
    for model in event_models:
        event_discriminators.update(_literal_discriminators(model))
    if hasattr(ServerEvent, "__args__"):
        for model in get_args(ServerEvent):
            if isinstance(model, type):
                event_discriminators.update(_literal_discriminators(model))

    return RuntimeContract(
        http_operations=_extract_http_operations(app),
        websocket_paths=_extract_websocket_paths(app),
        command_discriminators=frozenset(command_discriminators),
        event_discriminators=frozenset(event_discriminators),
        openapi_schemas=openapi.get("components", {}).get("schemas", {}),
        ws_schemas={
            model.__name__: _schema_names(model)
            for model in (*event_models, SendMessageCommand)
        },
    )


def _deterministic_settings(database_path: Path) -> object:
    from jung.api.settings import ApiSettings
    from jung.composition import build_settings

    return ApiSettings(
        application=build_settings(
            database_path=database_path,
            llm_base_url="http://fake.test/v1",
            llm_api_key="fake",
            default_model="fake",
        ),
        allowed_origins=("http://frontend.test",),
    )


def extract_runtime_contract() -> RuntimeContract:
    from jung.api.app import create_app

    runtime_factory_called = False

    def inert_runtime_factory(_settings: object) -> object:
        nonlocal runtime_factory_called
        runtime_factory_called = True
        raise AssertionError(
            "Runtime factory must not be called during contract extraction"
        )

    with tempfile.TemporaryDirectory(prefix="jung-phase5-contract-") as temporary:
        temporary_directory = Path(temporary)
        database_path = temporary_directory / "contract-extract.sqlite"
        try:
            database_path.relative_to(temporary_directory)
        except ValueError as exc:
            raise AssertionError(
                "contract extraction database path escaped tempfile"
            ) from exc

        app = create_app(
            _deterministic_settings(database_path),
            runtime_factory=inert_runtime_factory,
        )
        contract = _extract_contract_from_app(app)
        assert runtime_factory_called is False
        return contract


def _legacy_event_ast_hits(path: Path, root: Path) -> list[str]:
    tree = _read_ast(path)
    display = _display_path(path, root)
    hits: set[str] = set()
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        location = f"{display}:{lineno}" if lineno is not None else display
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in LEGACY_WS_EVENT_NAMES:
                hits.add(f"{location}: legacy event {node.value!r}")
        elif isinstance(node, ast.Name) and node.id in LEGACY_WS_EVENT_NAMES:
            hits.add(f"{location}: legacy identifier {node.id!r}")
        elif isinstance(node, ast.Attribute) and node.attr in LEGACY_WS_EVENT_NAMES:
            hits.add(f"{location}: legacy attribute {node.attr!r}")
    return sorted(hits)


def _user_id_source_hits(path: Path, root: Path) -> list[str]:
    tree = _read_ast(path)
    display = _display_path(path, root)
    hits: set[str] = set()

    def _record(node: ast.AST, kind: str) -> None:
        lineno = getattr(node, "lineno", None)
        location = f"{display}:{lineno}" if lineno is not None else display
        hits.add(f"{location}: user_id {kind}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == USER_ID:
            _record(node, "name")
        elif isinstance(node, ast.Attribute) and node.attr == USER_ID:
            _record(node, "attribute")
        elif isinstance(node, ast.arg) and node.arg == USER_ID:
            _record(node, "argument")
        elif isinstance(node, ast.keyword) and node.arg == USER_ID:
            _record(node, "keyword")
        elif isinstance(node, ast.alias):
            if node.asname == USER_ID:
                _record(node, "import alias")
            elif _terminal_component(node.name) == USER_ID:
                _record(node, "import name")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _terminal_component(node.module) == USER_ID:
                _record(node, "import module")
    return sorted(hits)


def _read_pyproject_scripts(
    root: Path,
) -> tuple[dict[str, str] | None, Violation | None]:
    pyproject_path = root / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as file:
            pyproject = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        return None, Violation(f"invalid pyproject.toml: {exc}")

    project = pyproject.get("project", {})
    if not isinstance(project, dict):
        project = {}
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict):
        scripts = {}

    normalized: dict[str, str] = {}
    for key, value in scripts.items():
        if isinstance(key, str) and isinstance(value, str):
            normalized[key] = value
    return normalized, None


def _makefile_targets(root: Path) -> set[str]:
    text = (root / "Makefile").read_text(encoding="utf-8")
    targets: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("\t"):
            continue
        if any(token in line for token in (":=", "+=", "?=")):
            continue
        if ":" not in line:
            continue
        target = line.split(":", 1)[0].strip()
        if target and not target.startswith("."):
            targets.add(target)
    return targets


def validate_static_repository(root: Path) -> list[Violation]:
    violations: list[Violation] = []

    for relative in REQUIRED_PUBLIC_FILES:
        if not (root / relative).is_file():
            violations.append(Violation(f"missing public file: {relative}"))

    for relative in REQUIRED_PHASE_5_TEST_FILES:
        if not (root / relative).is_file():
            violations.append(Violation(f"missing required test file: {relative}"))

    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        violations.append(Violation("missing required file: pyproject.toml"))
    else:
        scripts, error = _read_pyproject_scripts(root)
        if error is not None:
            violations.append(error)
        elif scripts is not None:
            for entry, target in (
                ("jung-api", "jung.api.app:cli"),
                ("jung-console", "jung.client.console:cli"),
            ):
                if scripts.get(entry) != target:
                    violations.append(
                        Violation(
                            f"pyproject script {entry!r} must map to {target!r}"
                        )
                    )

    makefile_path = root / "Makefile"
    if not makefile_path.is_file():
        violations.append(Violation("missing required file: Makefile"))
    else:
        makefile_targets = _makefile_targets(root)
        for target in REQUIRED_MAKE_TARGETS:
            if target not in makefile_targets:
                violations.append(Violation(f"Makefile missing target: {target}"))

    for package in ("api", "client"):
        package_root = root / "src/jung" / package
        if not package_root.exists():
            continue
        for path in _python_files(package_root):
            for hit in _legacy_event_ast_hits(path, root):
                violations.append(Violation(hit))
            for hit in _user_id_source_hits(path, root):
                violations.append(Violation(hit))

    return violations


def validate_runtime_contract(contract: RuntimeContract) -> list[Violation]:
    violations: list[Violation] = []

    missing_http = sorted(EXPECTED_HTTP_OPERATIONS - contract.http_operations)
    unexpected_http = sorted(contract.http_operations - EXPECTED_HTTP_OPERATIONS)
    for method, path in missing_http:
        violations.append(Violation(f"missing HTTP operation: {method} {path}"))
    for method, path in unexpected_http:
        violations.append(Violation(f"unexpected HTTP operation: {method} {path}"))

    if contract.websocket_paths != EXPECTED_WEBSOCKET_PATHS:
        violations.append(
            Violation(
                "unexpected websocket paths: "
                f"expected {EXPECTED_WEBSOCKET_PATHS}, got {contract.websocket_paths}"
            )
        )

    missing_commands = sorted(
        EXPECTED_COMMAND_DISCRIMINATORS - contract.command_discriminators
    )
    unexpected_commands = sorted(
        contract.command_discriminators - EXPECTED_COMMAND_DISCRIMINATORS
    )
    for item in missing_commands:
        violations.append(Violation(f"missing command discriminator: {item}"))
    for item in unexpected_commands:
        violations.append(Violation(f"unexpected command discriminator: {item}"))

    missing_events = sorted(
        EXPECTED_EVENT_DISCRIMINATORS - contract.event_discriminators
    )
    unexpected_events = sorted(
        contract.event_discriminators - EXPECTED_EVENT_DISCRIMINATORS
    )
    for item in missing_events:
        violations.append(Violation(f"missing event discriminator: {item}"))
    for item in unexpected_events:
        violations.append(Violation(f"unexpected event discriminator: {item}"))

    for path, reason in _collect_schema_semantics(contract.openapi_schemas):
        violations.append(
            Violation(
                "OpenAPI schema semantics include user_id at "
                f"{'.'.join(path)} ({reason})"
            )
        )
    for model_name, schema in contract.ws_schemas.items():
        for path, reason in _collect_schema_semantics(schema):
            violations.append(
                Violation(
                    f"WebSocket schema {model_name} includes user_id at "
                    f"{'.'.join(path)} ({reason})"
                )
            )

    return violations


def validate_repository(root: Path | None = None) -> list[Violation]:
    resolved_root = (root or REPO_ROOT).resolve()
    violations = validate_static_repository(resolved_root)
    if resolved_root == REPO_ROOT.resolve():
        violations.extend(validate_runtime_contract(extract_runtime_contract()))
    return violations


def main() -> int:
    violations = validate_repository()
    if violations:
        print("Phase 5 validation failed:")
        for violation in violations:
            print(f"  - {violation.message}")
        return 1
    print("Phase 5 validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
