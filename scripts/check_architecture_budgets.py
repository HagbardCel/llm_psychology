#!/usr/bin/env python3
"""Enforce architecture size budgets and basic layer boundary rules."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BUDGETS: dict[str, int] = {
    "src/psychoanalyst_app/agents/trio_reflection_agent.py": 760,
    "src/psychoanalyst_app/agents/trio_assessment_agent.py": 500,
    "src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py": 620,
    "src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py": 560,
    "src/psychoanalyst_app/orchestration/trio_conversation_manager.py": 580,
    "src/psychoanalyst_app/orchestration/helpers/session_lifecycle.py": 430,
    "src/psychoanalyst_app/orchestration/helpers/response_handler.py": 500,
    "src/psychoanalyst_app/container/service_container.py": 500,
    "src/psychoanalyst_app/agents/reflection/insights_pipeline.py": 260,
    "src/psychoanalyst_app/agents/psychoanalyst/prompt_context.py": 340,
}

METHOD_LENGTH_BUDGETS: dict[str, int] = {
    "src/psychoanalyst_app/agents/trio_reflection_agent.py": 120,
    "src/psychoanalyst_app/agents/trio_assessment_agent.py": 130,
    "src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py": 120,
    "src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py": 120,
    "src/psychoanalyst_app/orchestration/trio_conversation_manager.py": 120,
    "src/psychoanalyst_app/orchestration/helpers/session_lifecycle.py": 180,
    "src/psychoanalyst_app/orchestration/helpers/response_handler.py": 180,
}

FORBIDDEN_IMPORTS_BY_LAYER: dict[str, set[str]] = {
    "services": {"api", "orchestration", "agents"},
    "agents": {"api"},
    "orchestration": {"api"},
    "api": {"agents"},
}


def _line_count(path: Path) -> int:
    return sum(1 for _ in path.read_text(encoding="utf-8").splitlines())


def _layer_from_path(path: Path) -> str | None:
    parts = path.parts
    marker = ("src", "psychoanalyst_app")
    for idx in range(len(parts) - 2):
        if parts[idx : idx + 2] == marker:
            return parts[idx + 2]
    return None


def _iter_py_files() -> list[Path]:
    return sorted((ROOT / "src" / "psychoanalyst_app").rglob("*.py"))


def _imported_top_layers(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if not name.startswith("psychoanalyst_app."):
                    continue
                parts = name.split(".")
                if len(parts) >= 2:
                    imported.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if not module.startswith("psychoanalyst_app."):
                continue
            parts = module.split(".")
            if len(parts) >= 2:
                imported.add(parts[1])

    return imported


def _iter_named_functions(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    named: list[tuple[str, ast.AST]] = []

    def walk(nodes: list[ast.stmt], prefix: str = "") -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                walk(node.body, prefix=f"{prefix}{node.name}.")
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                named.append((f"{prefix}{node.name}", node))

    if isinstance(tree, ast.Module):
        walk(tree.body)
    return named


def _function_length(node: ast.AST) -> int:
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    if not lineno or not end_lineno:
        return 0
    return end_lineno - lineno + 1


def check_budgets(errors: list[str]) -> None:
    for rel_path, max_lines in BUDGETS.items():
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f"Budget target missing: {rel_path}")
            continue
        count = _line_count(path)
        if count > max_lines:
            errors.append(
                f"Budget exceeded: {rel_path} has {count} lines (max {max_lines})"
            )


def check_method_lengths(errors: list[str]) -> None:
    for rel_path, max_lines in METHOD_LENGTH_BUDGETS.items():
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f"Method budget target missing: {rel_path}")
            continue

        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for name, node in _iter_named_functions(tree):
            length = _function_length(node)
            if length > max_lines:
                errors.append(
                    "Method budget exceeded: "
                    f"{rel_path}:{name} has {length} lines (max {max_lines})"
                )


def check_layer_boundaries(errors: list[str]) -> None:
    for path in _iter_py_files():
        layer = _layer_from_path(path)
        if not layer or layer not in FORBIDDEN_IMPORTS_BY_LAYER:
            continue

        forbidden = FORBIDDEN_IMPORTS_BY_LAYER[layer]
        imported_layers = _imported_top_layers(path)
        bad = sorted(imported_layers.intersection(forbidden))
        if bad:
            rel = path.relative_to(ROOT)
            errors.append(
                f"Layer violation: {rel} ({layer}) imports forbidden layers {bad}"
            )


def main() -> int:
    errors: list[str] = []
    check_budgets(errors)
    check_method_lengths(errors)
    check_layer_boundaries(errors)

    if errors:
        print("Architecture checks failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Architecture checks passed.")
    print(f"Validated budgets: {len(BUDGETS)}")
    print(f"Validated method budgets: {len(METHOD_LENGTH_BUDGETS)}")
    print(f"Validated python files: {len(_iter_py_files())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
