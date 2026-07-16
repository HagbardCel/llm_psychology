#!/usr/bin/env python3
"""Static and runtime contract checks for Phase 5 API/client handoff."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import get_args, get_origin

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PUBLIC_FILES = (
    REPO_ROOT / "src/jung/api/app.py",
    REPO_ROOT / "src/jung/api/routes.py",
    REPO_ROOT / "src/jung/api/websocket.py",
    REPO_ROOT / "src/jung/api/contracts.py",
    REPO_ROOT / "src/jung/api/errors.py",
    REPO_ROOT / "src/jung/client/api_client.py",
    REPO_ROOT / "src/jung/client/console.py",
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

API_FORBIDDEN_IMPORT_PREFIXES = (
    "jung.llm",
    "jung.persistence",
    "jung.phases",
    "psychoanalyst_app",
    "quart",
    "trio",
)

CLIENT_ALLOWED_EXTERNAL_ROOTS = frozenset({"httpx", "pydantic", "websockets"})

CORE_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "fastapi",
        "httpx",
        "starlette",
        "uvicorn",
        "websockets",
    }
)


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
    database_path: Path | None = None


def _python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*.py") if path.is_file())


def _read_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(path: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(_read_ast(path)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


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
    for route in getattr(app, "routes", ()):
        router = getattr(route, "original_router", None)
        if router is None:
            continue
        for subroute in router.routes:
            if type(subroute).__name__ == "APIWebSocketRoute":
                paths.add(subroute.path)
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
    hits: list[tuple[tuple[str, ...], str]] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            next_path = (*path, key)
            if key == "user_id":
                hits.append((next_path, "property name user_id"))
            if key in {"properties", "required", "discriminator", "mapping"}:
                if isinstance(value, dict):
                    for child_key in value:
                        if child_key == "user_id":
                            hits.append(
                                (
                                    (*next_path, child_key),
                                    f"schema semantics reference user_id in {key}",
                                )
                            )
            hits.extend(_collect_schema_semantics(value, path=next_path))
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


def _extract_contract_from_app(
    app: object,
    *,
    database_path: Path | None,
) -> RuntimeContract:
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
        database_path=database_path,
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
    import tempfile

    from jung.api.app import create_app

    runtime_factory_called = False

    def inert_runtime_factory(_settings: object) -> object:
        nonlocal runtime_factory_called
        runtime_factory_called = True
        raise AssertionError(
            "Runtime factory must not be called during contract extraction"
        )

    with tempfile.TemporaryDirectory(prefix="jung-phase5-contract-") as tmp:
        database_path = Path(tmp) / "contract-extract.sqlite"
        app = create_app(
            _deterministic_settings(database_path),
            runtime_factory=inert_runtime_factory,
        )
        contract = _extract_contract_from_app(app, database_path=database_path)
        if runtime_factory_called:
            raise AssertionError("runtime factory was invoked during extraction")
        if not str(contract.database_path).startswith(tmp):
            raise AssertionError("contract extraction database path escaped tempfile")
        return contract


def _legacy_event_ast_hits(path: Path, root: Path) -> list[str]:
    tree = _read_ast(path)
    hits: list[str] = []
    try:
        display = str(path.relative_to(root))
    except ValueError:
        display = str(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in LEGACY_WS_EVENT_NAMES:
                hits.append(f"{display}: legacy event {node.value!r}")
        elif isinstance(node, ast.Name) and node.id in LEGACY_WS_EVENT_NAMES:
            hits.append(f"{display}: legacy identifier {node.id!r}")
        elif isinstance(node, ast.Attribute) and node.attr in LEGACY_WS_EVENT_NAMES:
            hits.append(f"{display}: legacy attribute {node.attr!r}")
    return hits


def _identifier_hits(path: Path, name: str) -> list[str]:
    tree = _read_ast(path)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            hits.append(str(path.relative_to(REPO_ROOT)))
        elif isinstance(node, ast.arg) and node.arg == name:
            hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


def _client_import_violations(modules: list[str]) -> list[str]:
    violations: list[str] = []
    for module in modules:
        root = module.split(".")[0]
        if root == "__future__" or root in sys.stdlib_module_names:
            continue
        if root in CLIENT_ALLOWED_EXTERNAL_ROOTS:
            continue
        if module == "jung.api.contracts" or module.startswith("jung.api.contracts."):
            continue
        if module == "jung.client" or module.startswith("jung.client."):
            continue
        violations.append(module)
    return violations


def _read_pyproject_scripts(root: Path) -> dict[str, str]:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    scripts: dict[str, str] = {}
    in_scripts = False
    for line in text.splitlines():
        if line.strip() == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts:
            if line.startswith("[") and line.endswith("]"):
                break
            match = re.match(r'^(\S+)\s*=\s*"([^"]+)"\s*$', line.strip())
            if match:
                scripts[match.group(1)] = match.group(2)
    return scripts


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

    for path in REQUIRED_PUBLIC_FILES:
        if not path.exists():
            violations.append(
                Violation(
                    f"missing public file: {path.relative_to(root)}"
                )
            )

    for relative in REQUIRED_PHASE_5_TEST_FILES:
        if not (root / relative).is_file():
            violations.append(Violation(f"missing required test file: {relative}"))

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        scripts = _read_pyproject_scripts(root)
        for entry, target in (
            ("jung-api", "jung.api.app:cli"),
            ("jung-console", "jung.client.console:cli"),
        ):
            if scripts.get(entry) != target:
                violations.append(
                    Violation(f"pyproject script {entry!r} must map to {target!r}")
                )

    makefile_path = root / "Makefile"
    if makefile_path.is_file():
        makefile_targets = _makefile_targets(root)
        for target in REQUIRED_MAKE_TARGETS:
            if target not in makefile_targets:
                violations.append(Violation(f"Makefile missing target: {target}"))

    api_root = root / "src/jung/api"
    if api_root.exists():
        for path in _python_files(api_root):
            for module in _imported_modules(path):
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in API_FORBIDDEN_IMPORT_PREFIXES
                ):
                    violations.append(
                        Violation(
                            f"{path.relative_to(root)} imports forbidden {module}"
                        )
                    )
            violations.extend(
                Violation(hit) for hit in _legacy_event_ast_hits(path, root)
            )
            for hit in _identifier_hits(path, "user_id"):
                violations.append(Violation(f"user_id identifier in {hit}"))

    client_root = root / "src/jung/client"
    if client_root.exists():
        for path in _python_files(client_root):
            for module in _client_import_violations(_imported_modules(path)):
                violations.append(
                    Violation(f"{path.relative_to(root)} imports unsupported {module}")
                )
            violations.extend(
                Violation(hit) for hit in _legacy_event_ast_hits(path, root)
            )
            for hit in _identifier_hits(path, "user_id"):
                violations.append(Violation(f"user_id identifier in {hit}"))

    jung_root = root / "src/jung"
    if jung_root.exists():
        for path in _python_files(jung_root):
            rel = path.relative_to(jung_root)
            if rel.parts and rel.parts[0] in {"api", "client"}:
                continue
            for module in _imported_modules(path):
                root_name = module.split(".")[0]
                if root_name in CORE_FORBIDDEN_IMPORT_ROOTS:
                    violations.append(
                        Violation(
                            f"{path.relative_to(root)} imports framework {module}"
                        )
                    )

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

    artifact = REPO_ROOT / "data" / "contract-extract.sqlite"
    if artifact.exists():
        violations.append(
            Violation(
                "contract extraction artifact must not persist under repository data/"
            )
        )

    return violations


def validate_repository(root: Path | None = None) -> list[Violation]:
    root = (root or REPO_ROOT).resolve()
    violations = validate_static_repository(root)
    if root.resolve() == REPO_ROOT.resolve():
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
