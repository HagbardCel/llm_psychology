#!/usr/bin/env python3
"""Produce reproducible, Git-backed source metrics for the architecture refactor.

Uses only the Python standard library plus Git via subprocess. Run natively:

    python3 scripts/measure_codebase.py --root /path/to/worktree --format json
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import subprocess
import sys
import tokenize
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

GENERATED_PATHS = frozenset(
    {
        Path("uv.lock"),
        Path("requirements.txt"),
        Path("requirements-dev.txt"),
    }
)

HTTP_ROUTE_ATTRS = frozenset(
    {"get", "post", "put", "patch", "delete", "options", "head", "api_route"}
)
WEBSOCKET_ROUTE_ATTRS = frozenset({"websocket"})
LEGACY_ROUTE_ATTRS = frozenset({"route"})
LEGACY_WORKFLOW_TYPES = frozenset(
    {"WorkflowState", "WorkflowEvent", "RequiredWorkflowAction"}
)
LEGACY_NAMESPACE_ROOTS = frozenset(
    {
        "psychoanalyst_app",
        "trio",
        "quart",
        "quart_trio",
        "langchain",
        "langchain_core",
        "langchain_openai",
        "langchain_ollama",
        "langchain_google_genai",
    }
)
KNOWN_BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".sqlite",
        ".db",
        ".whl",
        ".egg",
    }
)


@dataclass(frozen=True)
class MeasurementLayout:
    name: str
    backend_roots: tuple[Path, ...]
    client_roots: tuple[Path, ...]
    backend_exclusions: tuple[Path, ...] = ()
    route_profile: str = "jung"


LEGACY_LAYOUT = MeasurementLayout(
    name="legacy",
    backend_roots=(Path("src/psychoanalyst_app"),),
    client_roots=(Path("console-ui"),),
    route_profile="legacy",
)

JUNG_LAYOUT = MeasurementLayout(
    name="jung",
    backend_roots=(Path("src/jung"),),
    backend_exclusions=(Path("src/jung/client"),),
    client_roots=(Path("src/jung/client"),),
    route_profile="jung",
)


class MeasurementError(RuntimeError):
    """Raised when a tree cannot be measured safely."""


def _run_git(root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise MeasurementError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or b"").decode("utf-8", errors="replace")
        raise MeasurementError(
            f"git {' '.join(args)} failed in {root}: {detail.strip()}"
        ) from exc
    return completed.stdout


def _ensure_git_worktree(root: Path) -> None:
    root = root.resolve()
    if not root.is_dir():
        raise MeasurementError(f"root is not a directory: {root}")
    try:
        _run_git(root, "rev-parse", "--is-inside-work-tree")
    except MeasurementError as exc:
        raise MeasurementError(
            f"root is not a Git worktree: {root}. "
            "measure_codebase.py must run natively against a Git checkout."
        ) from exc


def _tracked_paths(root: Path) -> list[Path]:
    raw = _run_git(root, "ls-files", "-z")
    if not raw:
        return []
    paths: list[Path] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        rel = Path(item.decode("utf-8"))
        absolute = root / rel
        if not absolute.exists():
            raise MeasurementError(
                f"tracked path missing from worktree: {rel} (under {root})"
            )
        if absolute.is_dir():
            continue
        paths.append(rel)
    return paths


def _detect_layout(root: Path, tracked: Sequence[Path]) -> MeasurementLayout:
    tracked_set = {path.as_posix() for path in tracked}
    has_jung = any(
        path == "src/jung" or path.startswith("src/jung/") for path in tracked_set
    )
    has_legacy = any(
        path == "src/psychoanalyst_app" or path.startswith("src/psychoanalyst_app/")
        for path in tracked_set
    )
    if has_jung and not has_legacy:
        return JUNG_LAYOUT
    if has_legacy and not has_jung:
        return LEGACY_LAYOUT
    if has_jung and has_legacy:
        # Prefer Jung when both exist (transitional trees).
        return JUNG_LAYOUT
    raise MeasurementError(
        f"unable to detect measurement layout under {root}: "
        "expected src/jung or src/psychoanalyst_app"
    )


def _under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _python_category_paths(
    tracked: Sequence[Path],
    *,
    roots: Sequence[Path],
    exclusions: Sequence[Path] = (),
) -> list[Path]:
    selected: list[Path] = []
    for path in tracked:
        if path.suffix != ".py":
            continue
        if not any(_under_root(path, root) for root in roots):
            continue
        if any(_under_root(path, excluded) for excluded in exclusions):
            continue
        selected.append(path)
    return selected


def _is_known_binary(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in KNOWN_BINARY_SUFFIXES:
        return True
    name = path.name.lower()
    return name.endswith(".tar.gz") or name.endswith(".tar.bz2")


def _is_authored_text(root: Path, rel: Path) -> bool:
    if rel in GENERATED_PATHS:
        return False
    if _is_known_binary(rel):
        return False
    absolute = root / rel
    data = absolute.read_bytes()
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _physical_lines(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _python_code_lines(text: str) -> int:
    code_lines: set[int] = set()
    for item in tokenize.generate_tokens(io.StringIO(text).readline):
        if item.type not in {
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENDMARKER,
            tokenize.ENCODING,
        }:
            code_lines.add(item.start[0])
    return len(code_lines)


def _read_text(root: Path, rel: Path) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _parse_tree(root: Path, rel: Path) -> ast.AST:
    return ast.parse(_read_text(root, rel), filename=str(rel))


def _import_roots(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _attr_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _call_constructor_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _assigned_router_symbols(tree: ast.AST, constructors: set[str]) -> set[str]:
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            ctor = _call_constructor_name(node.value)
            if ctor not in constructors:
                continue
            for target in node.targets:
                name = _attr_name(target)
                if name is not None:
                    symbols.add(name)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            ctor = _call_constructor_name(node.value)
            if ctor not in constructors:
                continue
            name = _attr_name(node.target)
            if name is not None:
                symbols.add(name)
    return symbols


def _decorator_route_attr(decorator: ast.AST) -> tuple[str | None, str | None]:
    """Return (owner_symbol, attr) for @owner.attr(...) style decorators."""
    call = decorator
    if isinstance(decorator, ast.Call):
        call = decorator.func
    if isinstance(call, ast.Attribute) and isinstance(call.value, ast.Name):
        return call.value.id, call.attr
    return None, None


def _count_jung_routes(tree: ast.AST) -> tuple[int, int]:
    routers = _assigned_router_symbols(tree, {"APIRouter", "FastAPI"})
    http = 0
    websocket = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            owner, attr = _decorator_route_attr(decorator)
            if owner is None or attr is None or owner not in routers:
                continue
            if attr in HTTP_ROUTE_ATTRS:
                http += 1
            elif attr in WEBSOCKET_ROUTE_ATTRS:
                websocket += 1
    return http, websocket


def _count_legacy_routes(tree: ast.AST) -> tuple[int, int]:
    blueprints = _assigned_router_symbols(tree, {"Blueprint"})
    # Quart also registers websockets on the app object created elsewhere;
    # count @<name>.websocket and @<name>.route when name is Blueprint or
    # when the decorator owner is a parameter/local commonly named app/bp.
    http = 0
    websocket = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            owner, attr = _decorator_route_attr(decorator)
            if owner is None or attr is None:
                continue
            if attr in LEGACY_ROUTE_ATTRS and (
                owner in blueprints or owner in {"bp", "blueprint"}
            ):
                http += 1
            elif attr in WEBSOCKET_ROUTE_ATTRS and owner in {
                "app",
                "application",
                *blueprints,
            }:
                websocket += 1
    return http, websocket


def _count_routes(
    root: Path, paths: Sequence[Path], *, profile: str
) -> tuple[int, int]:
    http_total = 0
    websocket_total = 0
    for rel in paths:
        tree = _parse_tree(root, rel)
        if profile == "jung":
            http, websocket = _count_jung_routes(tree)
        elif profile == "legacy":
            http, websocket = _count_legacy_routes(tree)
        else:
            raise MeasurementError(f"unknown route profile: {profile}")
        http_total += http
        websocket_total += websocket
    return http_total, websocket_total


def _enum_definition_and_member_counts(
    root: Path, paths: Sequence[Path], names: set[str]
) -> tuple[int, int]:
    definitions = 0
    members = 0
    for rel in paths:
        tree = _parse_tree(root, rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in names:
                definitions += 1
                members += sum(isinstance(item, ast.Assign) for item in node.body)
                members += sum(
                    isinstance(item, ast.AnnAssign) and item.value is not None
                    for item in node.body
                )
    return definitions, members


def _public_store_implementations(root: Path, paths: Sequence[Path]) -> int:
    total = 0
    for rel in paths:
        tree = _parse_tree(root, rel)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "SQLiteStore":
                if not node.name.startswith("_"):
                    total += 1
    return total


def _strip_requirement_name(line: str) -> str | None:
    text = line.strip()
    if not text or text.startswith(("#", "-")):
        return None
    for sep in ("===", "==", ">=", "<=", "~=", "!=", ">", "<"):
        if sep in text:
            text = text.split(sep, 1)[0]
            break
    text = text.split(";", 1)[0].strip()
    return text or None


def _parse_requirements_dev(root: Path) -> int:
    path = root / "requirements-dev.in"
    if not path.exists():
        return 0
    packages: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        name = _strip_requirement_name(raw)
        if name is not None:
            packages.add(name)
    return len(packages)


def _parse_pyproject_dependencies(root: Path) -> list[str]:
    path = root / "pyproject.toml"
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project") or {}
    deps = project.get("dependencies") or []
    if not isinstance(deps, list):
        raise MeasurementError("pyproject.toml [project].dependencies must be a list")
    return [str(item) for item in deps]


def _has_dependency_group_dev(root: Path) -> bool:
    path = root / "pyproject.toml"
    if not path.exists():
        return False
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    groups = data.get("dependency-groups")
    return isinstance(groups, dict) and "dev" in groups


def _parse_dependency_groups_dev(root: Path) -> int:
    path = root / "pyproject.toml"
    if not path.exists():
        return 0
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    groups = data.get("dependency-groups") or {}
    if not isinstance(groups, dict):
        return 0
    dev = groups.get("dev") or []
    if not isinstance(dev, list):
        raise MeasurementError("pyproject.toml [dependency-groups].dev must be a list")
    packages: set[str] = set()
    for item in dev:
        name = _strip_requirement_name(str(item))
        if name is not None:
            packages.add(name)
    return len(packages)


def _runtime_dependency_count(root: Path) -> int:
    packages: set[str] = set()
    for item in _parse_pyproject_dependencies(root):
        name = _strip_requirement_name(item)
        if name is not None:
            packages.add(name)
    return len(packages)


def _development_dependency_count(root: Path) -> int:
    if _has_dependency_group_dev(root):
        return _parse_dependency_groups_dev(root)
    return _parse_requirements_dev(root)


def _loc_for_python_files(root: Path, paths: Sequence[Path]) -> tuple[int, int, int]:
    physical = 0
    code = 0
    for rel in paths:
        text = _read_text(root, rel)
        physical += _physical_lines(text)
        code += _python_code_lines(text)
    return len(paths), physical, code


def measure(root: Path) -> dict[str, object]:
    root = root.resolve()
    _ensure_git_worktree(root)
    tracked = _tracked_paths(root)
    layout = _detect_layout(root, tracked)

    authored = [path for path in tracked if _is_authored_text(root, path)]
    authored_loc = sum(_physical_lines(_read_text(root, path)) for path in authored)

    backend_py = _python_category_paths(
        tracked,
        roots=layout.backend_roots,
        exclusions=layout.backend_exclusions,
    )
    client_py = _python_category_paths(tracked, roots=layout.client_roots)
    test_py = _python_category_paths(tracked, roots=(Path("tests"),))
    script_py = _python_category_paths(tracked, roots=(Path("scripts"),))

    backend_files, backend_physical, backend_code = _loc_for_python_files(
        root, backend_py
    )
    client_files, client_physical, _client_code = _loc_for_python_files(root, client_py)
    _test_files, test_physical, _test_code = _loc_for_python_files(root, test_py)
    _script_files, script_physical, _script_code = _loc_for_python_files(
        root, script_py
    )

    http_routes, websocket_routes = _count_routes(
        root, backend_py, profile=layout.route_profile
    )

    stage_defs, stage_members = _enum_definition_and_member_counts(
        root, backend_py, {"Stage"}
    )
    command_defs, command_members = _enum_definition_and_member_counts(
        root, backend_py, {"CommandName"}
    )
    legacy_workflow_defs, _legacy_members = _enum_definition_and_member_counts(
        root, backend_py, set(LEGACY_WORKFLOW_TYPES)
    )

    trio_imports = 0
    legacy_namespace_imports = 0
    for rel in backend_py:
        roots = _import_roots(_parse_tree(root, rel))
        if "trio" in roots:
            trio_imports += 1
        if roots & LEGACY_NAMESPACE_ROOTS:
            legacy_namespace_imports += 1

    return {
        "layout": layout.name,
        "backend_python_files": backend_files,
        "backend_python_physical_loc": backend_physical,
        "backend_python_code_loc": backend_code,
        "client_python_files": client_files,
        "client_python_physical_loc": client_physical,
        "test_python_physical_loc": test_physical,
        "script_python_physical_loc": script_physical,
        "tracked_authored_text_physical_loc": authored_loc,
        "tracked_authored_file_count": len(authored),
        "uv_lock_present": (root / "uv.lock").is_file()
        and Path("uv.lock") in set(tracked),
        "runtime_dependency_count": _runtime_dependency_count(root),
        "development_dependency_count": _development_dependency_count(root),
        "trio_importing_production_modules": trio_imports,
        "legacy_namespace_importing_modules": legacy_namespace_imports,
        "api_route_count": http_routes,
        "websocket_endpoint_count": websocket_routes,
        "stage_enum_definitions": stage_defs,
        "stage_member_count": stage_members,
        "command_name_definitions": command_defs,
        "command_name_member_count": command_members,
        "legacy_workflow_representation_definitions": legacy_workflow_defs,
        "public_concrete_store_implementations": _public_store_implementations(
            root, backend_py
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Git worktree root to measure",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    try:
        metrics = measure(args.root)
    except MeasurementError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(metrics, indent=2, sort_keys=True))
    else:
        print("# Measurement\n\n| Metric | Value |\n|---|---:|")
        for key, value in metrics.items():
            print(f"| {key} | {value} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
