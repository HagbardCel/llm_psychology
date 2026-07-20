#!/usr/bin/env python3
"""Semantic cutover checks for Phase 6 legacy deletion.

Lean architectural guardrail for the Jung cutover.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("docs/refactor/deletion-manifest.toml")
WORKFLOW_EDIT_PATH = ".github/workflows/release-candidate-validation.yml"
KIND_ACTIONS: dict[str, frozenset[str]] = {
    "filesystem": frozenset(
        {"delete", "port_then_delete", "reimplement_then_delete", "retain"}
    ),
    "make_target": frozenset({"delete", "retain"}),
    "workflow": frozenset({"delete", "retain"}),
    "workflow_edit": frozenset({"edit"}),
}
FORBIDDEN_IMPORT_ROOTS = (
    "psychoanalyst_app",
    "trio",
    "pytest_trio",
    "quart",
    "quart_trio",
    "quart_cors",
    "trio_websocket",
    "hypercorn",
)
FORBIDDEN_DEP_PREFIXES = FORBIDDEN_IMPORT_ROOTS + ("langchain",)
ENTRY_POINT_TARGETS = {
    "psychoanalyst-server": "psychoanalyst_app.server:cli",
    "jung-api": "jung.api.app:cli",
    "jung-console": "jung.client.terminal:cli",
}
TARGET_REQUIRED_ENTRY_POINTS = frozenset({"jung-api", "jung-console"})
POST_CUTOVER_FORBIDDEN_ENTRY_POINTS = frozenset(
    {"psychoanalyst-server", "psychoanalyst-db", "jung-db"}
)
MAKE_TARGET_RE = re.compile(
    r"^([A-Za-z0-9_.-]+)\s*:(?!=)",
    re.MULTILINE,
)
MAKE_TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
SELECTED_DOCKER_STAGE = "development"
REQUIRED_CMD = 'CMD ["jung-api"]'
HEALTH_PATH = "/api/v1/health"
FORBIDDEN_CONSOLE_SERVICES = frozenset({"console-ui", "console-ui-usertest"})
REQUIRED_TEST_COMMAND = [
    "pytest",
    "-o",
    "trio_mode=false",
    "-o",
    "asyncio_mode=auto",
    "-m",
    "not real_llm",
    "tests/unit/jung",
    "tests/integration/jung",
]
SERVICE_SPECS = {
    "api": {
        "profiles": None,
        "data_dir": "/app/data/local",
        "published": "8000",
    },
    "api-usertest": {
        "profiles": ["usertest-console"],
        "data_dir": "/app/data/usertest",
        "published": "8001",
    },
}
STAGE_MANIFEST_STATUS = {
    "cutover": "active",
    "final": "completed",
}
STAGE_OWNER_PRS = {
    "cutover": frozenset({"6A", "6B", "6C"}),
    "final": frozenset({"6A", "6B", "6C", "6D"}),
}

SUPPORTED_TEST_ROOTS = (
    Path("tests/unit/jung"),
    Path("tests/integration/jung"),
    Path("tests/smoke/jung"),
)
SUPPORTED_TEST_FILES = (
    Path("tests/conftest.py"),
    Path("tests/e2e/test_console_v1_workflow.py"),
    Path("tests/jung_api_fixtures.py"),
    Path("tests/console_probe_support.py"),
    Path("tests/unit/test_validate_refactor_phase_5.py"),
    Path("tests/unit/test_validate_refactor_phase_6.py"),
    Path("tests/unit/test_validate_docs_metadata.py"),
    Path("tests/unit/test_recording_fake_llm.py"),
    Path("tests/unit/test_measure_codebase.py"),
)


def _strip_nonempty(value: Any, field_name: str) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-empty")
    return stripped


def _norm_pkg_name(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def normalize_repo_path(value: str, field_name: str) -> str:
    stripped = value.strip()
    is_directory = stripped.endswith(("/", "\\"))
    normalized = re.sub(r"/+", "/", stripped.replace("\\", "/")).rstrip("/")

    if (
        not normalized
        or normalized == "."
        or normalized.startswith("/")
        or _WINDOWS_DRIVE_RE.match(normalized)
        or ".." in normalized.split("/")
    ):
        raise ValueError(f"{field_name} must be a repository-relative path")

    return f"{normalized}/" if is_directory else normalized


def path_exists(root: Path, value: str) -> bool:
    path = root / value
    return path.is_dir() if value.endswith("/") else path.exists()


def _format_validation_errors(exc: ValidationError) -> list[str]:
    errors: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = err.get("msg", "invalid")
        errors.append(f"manifest {loc}: {msg}" if loc else f"manifest: {msg}")
    return errors


class ManifestItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["filesystem", "make_target", "workflow", "workflow_edit"]
    path: StrictStr
    action: Literal[
        "delete", "port_then_delete", "reimplement_then_delete", "retain", "edit"
    ]
    owner_pr: Literal["6A", "6B", "6C", "6D"]
    status: Literal["planned", "in_progress", "complete"]
    confidence: Literal["confirmed", "likely", "discovery-needed"]
    responsibility: StrictStr
    blocker: StrictStr | None = None
    replacements: tuple[StrictStr, ...] = ()
    evidence: tuple[StrictStr, ...] = ()
    aggregate: StrictBool | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_item_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for field in ("path", "responsibility", "blocker"):
            if field in normalized and normalized[field] is not None:
                normalized[field] = _strip_nonempty(normalized[field], field)
        kind = normalized.get("kind")
        if isinstance(normalized.get("path"), str) and kind != "make_target":
            try:
                normalized["path"] = normalize_repo_path(normalized["path"], "path")
            except ValueError:
                pass
        return normalized

    @field_validator("replacements", "evidence")
    @classmethod
    def validate_path_entries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        normalized: list[str] = []
        for entry in value:
            norm = normalize_repo_path(entry, "path")
            if norm in seen:
                raise ValueError(f"duplicate path entry {norm!r}")
            seen.add(norm)
            normalized.append(norm)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_item_rules(self) -> Self:
        if self.action not in KIND_ACTIONS[self.kind]:
            raise ValueError(f"action {self.action!r} invalid for kind {self.kind!r}")
        if self.aggregate is not None:
            if self.aggregate is not True:
                raise ValueError("aggregate must be omitted or true")
            if self.kind != "filesystem" or self.action != "delete":
                raise ValueError("aggregate rows require filesystem delete")
        replacement_optional = (
            self.action in {"port_then_delete", "reimplement_then_delete"}
            and self.status == "planned"
            and self.confidence == "discovery-needed"
        )
        if (
            self.action in {"port_then_delete", "reimplement_then_delete"}
            and not replacement_optional
            and not self.replacements
        ):
            raise ValueError(f"{self.action} requires replacements")
        if self.kind == "workflow_edit" and self.path != WORKFLOW_EDIT_PATH:
            raise ValueError(f"workflow_edit path must be {WORKFLOW_EDIT_PATH!r}")
        if self.status == "complete" and self.confidence != "confirmed":
            raise ValueError("complete items must have confidence = confirmed")
        if self.kind == "make_target":
            if not MAKE_TARGET_NAME_RE.match(self.path):
                raise ValueError(f"invalid make target name: {self.path!r}")
        else:
            try:
                normalize_repo_path(self.path, "path")
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            if self.kind in {"workflow", "workflow_edit"} and not self.path.startswith(
                ".github/workflows/"
            ):
                raise ValueError("workflow path must be under .github/workflows/")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: StrictInt
    status: Literal["active", "completed"]
    items: tuple[ManifestItem, ...]

    @field_validator("schema_version")
    @classmethod
    def require_schema_version_one(cls, value: int) -> int:
        if value != 1:
            raise ValueError("must be 1")
        return value

    @model_validator(mode="after")
    def reject_duplicate_items(self) -> Self:
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(self.items):
            key = (item.kind, item.path)
            if key in seen:
                raise ValueError(
                    f"item {index}: duplicate kind/path {item.kind} {item.path!r}"
                )
            seen.add(key)
        return self


def parse_manifest(root: Path) -> tuple[Manifest | None, list[str]]:
    path = root / MANIFEST_PATH
    if not path.is_file():
        return None, [f"missing manifest: {MANIFEST_PATH}"]
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        return Manifest.model_validate(raw), []
    except ValidationError as exc:
        return None, _format_validation_errors(exc)
    except Exception as exc:  # noqa: BLE001 — surface parse failures
        return None, [f"manifest parse error: {exc}"]


def make_targets(text: str) -> set[str]:
    return set(MAKE_TARGET_RE.findall(text))


def _healthcheck_has_path(service: dict[str, Any], path: str) -> bool:
    health = service.get("healthcheck") or {}
    test = health.get("test")
    if not isinstance(test, list):
        return False
    return any(isinstance(part, str) and path in part for part in test)


def _validate_published_port(
    service: dict[str, Any],
    *,
    label: str,
    host_ip: str,
    published: str,
    target: str,
) -> list[str]:
    ports = service.get("ports")
    if not isinstance(ports, list) or not ports:
        return [f"{label} must declare ports"]
    for entry in ports:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("host_ip") == host_ip
            and str(entry.get("published")) == published
            and str(entry.get("target")) == target
        ):
            return []
    return [
        f"{label} must publish {host_ip}:{published}->{target} "
        f"(got {ports!r})"
    ]


def _validate_test_service(services: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    test_service = services.get("test")
    if not isinstance(test_service, dict):
        return ["compose model missing services.test"]

    if test_service.get("env_file"):
        errors.append("services.test must not declare env_file")

    environment = test_service.get("environment")
    environment = environment if isinstance(environment, dict) else {}
    legacy_keys = sorted(
        {"APP_ENV", "GOOGLE_API_KEY", "DATABASE_PATH"} & environment.keys()
    )
    if legacy_keys:
        errors.append(
            f"services.test declares legacy environment keys: {legacy_keys}"
        )

    if test_service.get("command") != REQUIRED_TEST_COMMAND:
        errors.append(
            "services.test.command must run the core supported Jung test trees "
            f"(got {test_service.get('command')!r})"
        )

    volumes = test_service.get("volumes")
    if isinstance(volumes, list):
        for volume in volumes:
            text = volume if isinstance(volume, str) else str(volume)
            if "/app/schemas" in text or ":./schemas" in text or "schemas:" in text:
                errors.append("services.test must not mount ./schemas")
                break

    return errors


def validate_compose_model(model: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    services = model.get("services")
    if not isinstance(services, dict):
        return ["compose model missing services mapping"]

    for forbidden in FORBIDDEN_CONSOLE_SERVICES:
        if forbidden in services:
            errors.append(f"compose must not define services.{forbidden}")

    resolved: dict[str, dict[str, Any]] = {}
    for name, spec in SERVICE_SPECS.items():
        service = services.get(name)
        if not isinstance(service, dict):
            errors.append(f"compose model missing services.{name}")
            continue
        resolved[name] = service

        expected_profiles = spec["profiles"]
        if expected_profiles is None:
            if service.get("profiles"):
                errors.append(f"services.{name} must not declare profiles")
        elif service.get("profiles") != expected_profiles:
            errors.append(
                f"services.{name}.profiles must be {expected_profiles!r} "
                f"(got {service.get('profiles')!r})"
            )

        if service.get("command") != ["jung-api"]:
            errors.append(
                f"services.{name}.command must be ['jung-api'] "
                f"(got {service.get('command')!r})"
            )
        if service.get("entrypoint") not in (None, [], ""):
            errors.append(f"services.{name} must not declare entrypoint")

        env = (
            service.get("environment")
            if isinstance(service.get("environment"), dict)
            else {}
        )
        data_dir = spec["data_dir"]
        if env.get("JUNG_DATA_DIR") != data_dir:
            errors.append(
                f"services.{name} JUNG_DATA_DIR must be {data_dir!r} "
                f"(got {env.get('JUNG_DATA_DIR')!r})"
            )

        errors.extend(
            _validate_published_port(
                service,
                label=f"services.{name}",
                host_ip="127.0.0.1",
                published=str(spec["published"]),
                target="8000",
            )
        )
        if not _healthcheck_has_path(service, HEALTH_PATH):
            errors.append(f"services.{name} healthcheck must target {HEALTH_PATH}")

    api = resolved.get("api")
    usertest = resolved.get("api-usertest")
    if api is not None and usertest is not None:
        if api.get("build") != usertest.get("build"):
            errors.append("services.api.build must equal services.api-usertest.build")
        api_env = (
            api.get("environment")
            if isinstance(api.get("environment"), dict)
            else {}
        )
        usertest_env = (
            usertest.get("environment")
            if isinstance(usertest.get("environment"), dict)
            else {}
        )
        if api_env.get("JUNG_DATA_DIR") == usertest_env.get("JUNG_DATA_DIR"):
            errors.append("api and api-usertest JUNG_DATA_DIR values must differ")

    errors.extend(_validate_test_service(services))
    return errors


def validate_compose_config_file(path: Path) -> list[str]:
    if not path.is_file():
        return [f"missing compose config: {path}"]
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"malformed compose config JSON: {exc}"]
    if not isinstance(model, dict):
        return ["compose config must be a JSON object"]
    return validate_compose_model(model)


def _dockerfile_stage_cmd(text: str, stage: str) -> str | None:
    lines = text.splitlines()
    current: str | None = None
    cmd: str | None = None
    for raw in lines:
        line = raw.strip()
        if line.upper().startswith("FROM "):
            parts = line.split()
            if "AS" in parts:
                current = parts[parts.index("AS") + 1]
            elif "as" in parts:
                current = parts[parts.index("as") + 1]
            else:
                current = None
            if current == stage:
                cmd = None
        elif current == stage and line.upper().startswith("CMD "):
            cmd = line
    return cmd


def validate_dockerfile(root: Path) -> list[str]:
    path = root / "Dockerfile"
    if not path.is_file():
        return ["missing Dockerfile"]
    cmd = _dockerfile_stage_cmd(path.read_text(encoding="utf-8"), SELECTED_DOCKER_STAGE)
    if cmd != REQUIRED_CMD:
        return [
            f"Dockerfile {SELECTED_DOCKER_STAGE} stage CMD must be {REQUIRED_CMD!r} "
            f"(got {cmd!r})"
        ]
    return []


def validate_item_complete(
    root: Path, makefile_targets: set[str], item: ManifestItem
) -> list[str]:
    errors: list[str] = []
    if item.kind == "make_target":
        present = item.path in makefile_targets
        if item.action == "delete" and present:
            errors.append(f"complete delete make target still present: {item.path}")
        if item.action == "retain" and not present:
            errors.append(f"complete retain make target missing: {item.path}")
        return errors

    if item.kind in {"filesystem", "workflow"}:
        present = path_exists(root, item.path)
        if item.action in {"delete", "port_then_delete", "reimplement_then_delete"}:
            if present:
                errors.append(f"complete {item.action} path still present: {item.path}")
        elif item.action == "retain" and not present:
            errors.append(f"complete retain path missing: {item.path}")
        for replacement in item.replacements:
            if not path_exists(root, replacement):
                errors.append(
                    f"replacement missing for {item.path}: {replacement}"
                )
        for evidence in item.evidence:
            if not path_exists(root, evidence):
                errors.append(f"evidence missing for {item.path}: {evidence}")
    elif item.kind == "workflow_edit":
        if not (root / item.path).is_file():
            errors.append(f"workflow_edit path missing: {item.path}")
    return errors


def validate_entry_points(root: Path) -> list[str]:
    errors: list[str] = []
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        return ["missing pyproject.toml"]
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return ["pyproject.toml project.scripts must be a mapping"]
    for name in TARGET_REQUIRED_ENTRY_POINTS:
        expected = ENTRY_POINT_TARGETS[name]
        actual = scripts.get(name)
        if actual != expected:
            errors.append(
                f"entry point {name!r} must map to {expected!r} (got {actual!r})"
            )
    for name in POST_CUTOVER_FORBIDDEN_ENTRY_POINTS:
        if name in scripts:
            errors.append(f"forbidden entry point still present: {name}")
    return errors


def validate_required_owner_closure(
    manifest: Manifest, owners: frozenset[str]
) -> list[str]:
    errors: list[str] = []
    for owner in owners:
        incomplete = [
            item.path
            for item in manifest.items
            if item.owner_pr == owner and item.status != "complete"
        ]
        if incomplete:
            errors.append(
                f"owner_pr {owner} has incomplete items: {', '.join(incomplete)}"
            )
    return errors


def supported_python_files(root: Path) -> tuple[list[Path], list[str]]:
    """Return Python files in the explicitly enumerated supported test tree.

    This is a direct scan of declared roots and files, not a recursive
    local-import dependency graph.
    """
    files: list[Path] = []
    errors: list[str] = []

    for relative in SUPPORTED_TEST_FILES:
        path = root / relative
        if not path.is_file():
            errors.append(f"missing supported test file: {relative}")
        else:
            files.append(path)

    for relative in SUPPORTED_TEST_ROOTS:
        path = root / relative
        if not path.is_dir():
            errors.append(f"missing supported test root: {relative}")
        else:
            python_files = sorted(path.rglob("*.py"))
            if not python_files:
                errors.append(
                    f"supported test root contains no Python files: {relative}"
                )
            else:
                files.extend(python_files)

    return list(dict.fromkeys(files)), errors


def _imports_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def validate_supported_imports(root: Path) -> list[str]:
    """Direct import scan of the enumerated supported test tree."""
    files, errors = supported_python_files(root)
    for path in files:
        try:
            modules = _imports_in_file(path)
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(root)}: syntax error: {exc}")
            continue
        for module in modules:
            root_name = module.split(".")[0]
            if root_name in FORBIDDEN_IMPORT_ROOTS or root_name.startswith("langchain"):
                rel = path.relative_to(root)
                errors.append(f"{rel} imports forbidden module {module}")
    return errors


def validate_dependency_closure(root: Path) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject.get("project", {}).get("dependencies", [])
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str):
                names.add(_norm_pkg_name(dep.split(";")[0].strip()))
    for req_name in ("requirements.txt", "requirements-dev.txt"):
        req_path = root / req_name
        if req_path.is_file():
            for line in req_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    token = re.split(r"[<>=!~\[]", stripped, maxsplit=1)[0].strip()
                    if token:
                        names.add(_norm_pkg_name(token))
    for forbidden in FORBIDDEN_DEP_PREFIXES:
        if any(name == forbidden or name.startswith(forbidden + "_") for name in names):
            errors.append(f"forbidden dependency present: {forbidden}")
    package_data = pyproject.get("tool", {}).get("setuptools", {}).get("package-data")
    if isinstance(package_data, dict) and "psychoanalyst_app" in package_data:
        errors.append("pyproject package-data still references psychoanalyst_app")
    return errors


def validate_final_confidence_closure(manifest: Manifest) -> list[str]:
    incomplete = [
        item.path
        for item in manifest.items
        if item.status != "complete" or item.confidence != "confirmed"
    ]
    if incomplete:
        joined = ", ".join(incomplete)
        return [
            f"final stage requires all items complete/confirmed: {joined}"
        ]
    return []


def validate_workflow(root: Path) -> list[str]:
    path = root / WORKFLOW_EDIT_PATH
    if not path.is_file():
        return [f"missing workflow: {WORKFLOW_EDIT_PATH}"]
    text = path.read_text(encoding="utf-8")
    if "make finalization-check" not in text:
        return [f"{WORKFLOW_EDIT_PATH} must invoke make finalization-check"]
    return []


def validate(
    root: Path | None = None,
    *,
    stage: str = "cutover",
    compose_config: Path | None = None,
) -> list[str]:
    resolved = (root or REPO_ROOT).resolve()
    if stage not in STAGE_MANIFEST_STATUS:
        return [f"unknown stage: {stage}"]
    is_final = stage == "final"
    manifest, errors = parse_manifest(resolved)
    if manifest is None:
        return errors
    expected_status = STAGE_MANIFEST_STATUS[stage]
    if manifest.status != expected_status:
        errors.append(
            f"manifest status must be {expected_status!r} for stage {stage!r}, "
            f"got {manifest.status!r}"
        )

    makefile_text = (resolved / "Makefile").read_text(encoding="utf-8")
    targets = make_targets(makefile_text)

    errors.extend(validate_entry_points(resolved))
    errors.extend(
        validate_required_owner_closure(manifest, STAGE_OWNER_PRS[stage])
    )
    errors.extend(validate_dockerfile(resolved))
    errors.extend(validate_workflow(resolved))

    compose_path = compose_config or (
        resolved / "logs" / "compose-config.resolved.json"
    )
    errors.extend(validate_compose_config_file(compose_path))

    for item in manifest.items:
        if item.status == "complete":
            errors.extend(validate_item_complete(resolved, targets, item))

    errors.extend(validate_supported_imports(resolved))
    if is_final:
        errors.extend(validate_final_confidence_closure(manifest))
        errors.extend(validate_dependency_closure(resolved))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=tuple(STAGE_MANIFEST_STATUS), required=True
    )
    parser.add_argument(
        "--compose-config",
        type=Path,
        default=None,
        help="Path to docker compose config --format json output",
    )
    args = parser.parse_args()
    errors = validate(stage=args.stage, compose_config=args.compose_config)
    if errors:
        print(f"Phase 6 refactor validation failed ({args.stage}):")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"Phase 6 refactor validation passed ({args.stage}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
