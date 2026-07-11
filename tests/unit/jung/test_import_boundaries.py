"""Import boundary checks for the jung package."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "psychoanalyst_app",
    "trio",
    "quart",
    "quart_trio",
    "langchain",
    "openai",
    "fastapi",
    "console_ui",
    "console-ui",
)

ROOT = Path(__file__).resolve().parents[3]
JUNG_SRC = ROOT / "src" / "jung"


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_jung_package_has_no_forbidden_imports() -> None:
    violations: list[str] = []
    for path in sorted(JUNG_SRC.rglob("*.py")):
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root in FORBIDDEN_PREFIXES or module.startswith("psychoanalyst_app."):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []
