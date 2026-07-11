#!/usr/bin/env python3
"""Produce reproducible, syntax-aware source metrics for the refactor baseline."""

from __future__ import annotations

import argparse
import ast
import io
import json
import tokenize
from collections import Counter
from pathlib import Path

EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "data", "schemas", ".pytest_cache"}


def _files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and not (set(path.relative_to(root).parts) & EXCLUDED_PARTS)
    )


def _python_files(root: Path) -> list[Path]:
    return _files(root, (".py",))


def _code_lines(path: Path) -> tuple[int, int]:
    """Return physical lines and distinct lines containing Python code tokens."""
    source = path.read_text(encoding="utf-8")
    code_lines: set[int] = set()
    for item in tokenize.generate_tokens(io.StringIO(source).readline):
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
    return len(source.splitlines()), len(code_lines)


def _loc(paths: list[Path]) -> tuple[int, int]:
    return tuple(
        sum(values[index] for values in map(_code_lines, paths)) for index in (0, 1)
    )


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _import_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _named_nodes(tree: ast.AST) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            counts[node.name] += 1
    return counts


def _pydantic_classes(tree: ast.AST) -> int:
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if any(
            (isinstance(base, ast.Name) and base.id == "BaseModel")
            or (isinstance(base, ast.Attribute) and base.attr == "BaseModel")
            for base in node.bases
        ):
            total += 1
    return total


def _route_count(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        if path.name.endswith("_routes.py"):
            tree = _tree(path)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "route"
                ):
                    total += 1
    return total


def _websocket_count(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        tree = _tree(path)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "websocket"
            ):
                total += 1
    return total


def _enum_members(paths: list[Path], names: set[str]) -> int:
    total = 0
    for path in paths:
        tree = _tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in names:
                total += sum(isinstance(item, ast.Assign) for item in node.body)
    return total


def _sqlite_tables(paths: list[Path]) -> int:
    import re

    pattern = re.compile(
        r"(?:CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|create_table)\s*[('`\"]*([A-Za-z_][A-Za-z0-9_]*)",
        re.I,
    )
    return len(
        {
            name.lower()
            for path in paths
            for name in pattern.findall(path.read_text(encoding="utf-8"))
        }
    )


def _requirements_count(root: Path) -> int:
    packages: set[str] = set()
    for path in (root / "requirements.in", root / "requirements-dev.in"):
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith(("#", "-")):
                packages.add(line.split("=")[0].split(">")[0].split("<")[0].strip())
    return len(packages)


def measure(root: Path) -> dict[str, int]:
    root = root.resolve()
    source = _python_files(root / "src")
    tests = _python_files(root / "tests")
    scripts = _python_files(root / "scripts")
    console = _python_files(root / "console-ui")
    source_physical, source_code = _loc(source)
    test_physical, test_code = _loc(tests)
    console_physical, console_code = _loc(console)
    script_physical, script_code = _loc(scripts)
    trees = {path: _tree(path) for path in source}
    imports = {path: _import_names(tree) for path, tree in trees.items()}
    module_imports = {path: _import_modules(tree) for path, tree in trees.items()}
    api_paths = [
        path
        for path in source
        if "/api/" in str(path)
        or path.name.endswith("_routes.py")
        or path.name == "ws_handler.py"
    ]
    return {
        "production_python_files": len(source),
        "production_python_physical_loc": source_physical,
        "production_python_code_loc": source_code,
        "test_python_files": len(tests),
        "test_python_physical_loc": test_physical,
        "test_python_code_loc": test_code,
        "console_python_files": len(console),
        "console_python_physical_loc": console_physical,
        "console_python_code_loc": console_code,
        "script_python_files": len(scripts),
        "script_python_physical_loc": script_physical,
        "script_python_code_loc": script_code,
        "executable_configuration_files": sum(
            1
            for path in root.rglob("*")
            if path.is_file()
            and path.stat().st_mode & 0o111
            and not (set(path.relative_to(root).parts) & EXCLUDED_PARTS)
        ),
        "direct_dependency_count": _requirements_count(root),
        "trio_importing_production_modules": sum(
            "trio" in value for value in imports.values()
        ),
        "service_container_importing_modules": sum(
            any(
                module == "psychoanalyst_app.container.service_container"
                or module.endswith(".service_container")
                for module in module_imports[path]
            )
            for path in source
        ),
        "persistence_related_modules": sum(
            1
            for path in source
            if "services/db" in path.as_posix()
            or any(
                module.startswith("psychoanalyst_app.services.db")
                for module in module_imports[path]
            )
        ),
        "pydantic_model_candidates": sum(
            _pydantic_classes(tree) for tree in trees.values()
        ),
        "api_route_count": _route_count(api_paths),
        "routes_in_user_named_modules": sum(
            "user" in path.name
            for path in api_paths
            for _ in range(_route_count([path]))
        ),
        "websocket_endpoint_count": _websocket_count(api_paths),
        "sqlite_table_count": _sqlite_tables(source),
        "workflow_state_member_count": _enum_members(source, {"WorkflowState"}),
        "workflow_action_member_count": _enum_members(
            source, {"WorkflowEvent", "RequiredWorkflowAction"}
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    metrics = measure(args.root)
    if args.format == "json":
        print(json.dumps(metrics, indent=2, sort_keys=True))
    else:
        print("# Baseline Metrics\n\n| Metric | Value |\n|---|---:|")
        for key, value in metrics.items():
            print(f"| {key} | {value} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
