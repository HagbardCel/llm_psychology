#!/usr/bin/env python3
"""Static architectural checks for Phase 4 target application core."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PHASE4_RUNTIME = (
    ROOT / "src/jung/application.py",
    ROOT / "src/jung/events.py",
    ROOT / "src/jung/supervisor.py",
    ROOT / "src/jung/composition.py",
)

FORBIDDEN_CLASS_NAMES = (
    "WorkflowEngine",
    "JobManager",
    "EventBus",
    "ServiceContainer",
    "AgentFactory",
    "RepositoryFactory",
    "AgentResponse",
    "UserContext",
)

FORBIDDEN_CREATE_TASK = "asyncio.create_task("


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _class_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]


def _contains_detached_create_task(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if FORBIDDEN_CREATE_TASK not in text:
        return False
    if path.name == "supervisor.py":
        return False
    if path.name == "application.py":
        total = text.count(FORBIDDEN_CREATE_TASK)
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_store":
                segment = ast.get_source_segment(text, node) or ""
                if FORBIDDEN_CREATE_TASK in segment:
                    return total != segment.count(FORBIDDEN_CREATE_TASK)
        return True
    return True


def validate() -> list[str]:
    errors: list[str] = []
    core_dirs = (
        ROOT / "src/jung/domain",
        ROOT / "src/jung/persistence",
        ROOT / "src/jung/phases",
        ROOT / "src/jung",
    )
    checked: set[Path] = set()
    for base in core_dirs:
        if not base.exists():
            continue
        for path in _python_files(base):
            if "api" in path.parts or "client" in path.parts:
                continue
            runtime_names = {
                "application.py",
                "events.py",
                "supervisor.py",
                "composition.py",
            }
            if path.name in runtime_names:
                checked.add(path)
            elif base.name in {"domain", "persistence", "phases"}:
                checked.add(path)
            elif path == ROOT / "src/jung/workflow.py":
                checked.add(path)

    for path in sorted(checked):
        rel = path.relative_to(ROOT)
        for module in _imports(path):
            root = module.split(".")[0]
            if root in {"psychoanalyst_app", "trio", "quart", "fastapi", "starlette"}:
                errors.append(f"{rel} imports forbidden module {module}")
            if module.startswith("psychoanalyst_app."):
                errors.append(f"{rel} imports legacy {module}")
        for name in _class_names(path):
            if name in FORBIDDEN_CLASS_NAMES:
                errors.append(f"{rel} defines forbidden class {name}")

    for path in PHASE4_RUNTIME:
        if not path.exists():
            errors.append(f"missing Phase 4 runtime file: {path.relative_to(ROOT)}")
            continue
        rel = path.relative_to(ROOT)
        if _contains_detached_create_task(path):
            errors.append(f"{rel} uses detached {FORBIDDEN_CREATE_TASK}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Phase 4 validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Phase 4 static validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
