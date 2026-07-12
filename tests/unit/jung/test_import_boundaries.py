"""Import boundary checks for the jung package."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JUNG_SRC = ROOT / "src" / "jung"
LLM_SRC = JUNG_SRC / "llm"
PHASES_SRC = JUNG_SRC / "phases"
STYLES_SRC = JUNG_SRC / "styles"

PHASE2_FORBIDDEN_PREFIXES = (
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

def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _collect_violations(
    paths: list[Path],
    *,
    forbidden_prefixes: tuple[str, ...],
    extra_rules: list[tuple[Path, tuple[str, ...]]] | None = None,
) -> list[str]:
    violations: list[str] = []
    for path in paths:
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root in forbidden_prefixes or module.startswith("psychoanalyst_app."):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
        if extra_rules:
            for check_path, forbidden in extra_rules:
                if path == check_path or str(path).startswith(str(check_path)):
                    for module in _imported_modules(path):
                        root = module.split(".")[0]
                        if root in forbidden:
                            violations.append(
                                f"{path.relative_to(ROOT)} imports {module}"
                            )
    return violations


def _phase2_paths() -> list[Path]:
    paths: list[Path] = []
    for root in (JUNG_SRC / "domain", JUNG_SRC / "persistence"):
        paths.extend(sorted(root.rglob("*.py")))
    workflow = JUNG_SRC / "workflow.py"
    if workflow.exists():
        paths.append(workflow)
    return paths


def test_phase2_packages_have_no_forbidden_imports() -> None:
    violations = _collect_violations(
        _phase2_paths(),
        forbidden_prefixes=PHASE2_FORBIDDEN_PREFIXES,
    )
    assert violations == []


def test_phase3_packages_respect_llm_and_processor_boundaries() -> None:
    phase3_paths: list[Path] = []
    for root in (LLM_SRC, PHASES_SRC, STYLES_SRC):
        if root.exists():
            phase3_paths.extend(sorted(root.rglob("*.py")))

    violations: list[str] = []
    for path in phase3_paths:
        rel = path.relative_to(ROOT)
        for module in _imported_modules(path):
            root_name = module.split(".")[0]
            if root_name in PHASE2_FORBIDDEN_PREFIXES and root_name != "openai":
                violations.append(f"{rel} imports {module}")
            if module.startswith("psychoanalyst_app."):
                violations.append(f"{rel} imports {module}")
            if module.startswith("jung.persistence"):
                violations.append(f"{rel} imports {module}")

        if LLM_SRC in path.parents or path == LLM_SRC:
            continue
        if "openai" in _imported_modules(path) or any(
            m.startswith("openai.") for m in _imported_modules(path)
        ):
            violations.append(f"{rel} imports openai outside jung.llm")

    phase_processor_dirs = {
        p.name for p in PHASES_SRC.iterdir() if p.is_dir()
    } if PHASES_SRC.exists() else set()
    for path in phase3_paths:
        if PHASES_SRC not in path.parents:
            continue
        parts = path.relative_to(PHASES_SRC).parts
        if not parts:
            continue
        phase_name = parts[0]
        for module in _imported_modules(path):
            for other in phase_processor_dirs:
                if other != phase_name and module.startswith(f"jung.phases.{other}"):
                    violations.append(
                        f"{path.relative_to(ROOT)} imports cross-phase {module}"
                    )

    assert violations == []
