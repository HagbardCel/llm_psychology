"""Import boundary checks for the jung package."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

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

ALLOWED_CROSS_PHASE_MODULES = frozenset(
    {
        "jung.phases.transcript",
        "jung.phases.context_bounds",
    }
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


def _module_package_for_path(path: Path) -> str:
    relative = path.relative_to(JUNG_SRC.parent).with_suffix("")
    return ".".join(relative.parts[:-1])


def _resolve_import_from(
    package: str,
    node: ast.ImportFrom,
) -> list[str]:
    if node.level:
        relative_name = "." * node.level + (node.module or "")
        base = resolve_name(relative_name, package)
    elif node.module is not None:
        base = node.module
    else:
        return []

    modules = [base]
    modules.extend(
        f"{base}.{alias.name}"
        for alias in node.names
        if alias.name != "*"
    )
    return modules


def _resolved_imported_modules(path: Path) -> list[str]:
    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )
    package = _module_package_for_path(path)
    modules: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.extend(_resolve_import_from(package, node))

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


def _cross_phase_import_allowed(module: str, other: str) -> bool:
    if module in ALLOWED_CROSS_PHASE_MODULES:
        return True
    if module == f"jung.phases.{other}.models":
        return True
    return module.startswith(f"jung.phases.{other}.models.")


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
                    if not _cross_phase_import_allowed(module, other):
                        violations.append(
                            f"{path.relative_to(ROOT)} imports cross-phase {module}"
                        )

    assert violations == []


PHASE4_RUNTIME_FILES = (
    JUNG_SRC / "application.py",
    JUNG_SRC / "events.py",
    JUNG_SRC / "supervisor.py",
    JUNG_SRC / "composition.py",
)


def test_phase4_runtime_respects_import_boundaries() -> None:
    violations = _collect_violations(
        [path for path in PHASE4_RUNTIME_FILES if path.exists()],
        forbidden_prefixes=PHASE2_FORBIDDEN_PREFIXES,
    )
    assert violations == []


def test_domain_does_not_import_phase_or_application_packages() -> None:
    forbidden = ("jung.phases", "jung.application")
    violations: list[str] = []

    for path in sorted((JUNG_SRC / "domain").rglob("*.py")):
        for module in _resolved_imported_modules(path):
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in forbidden
            ):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert violations == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from ..phases.assessment.models import AssessmentResult",
            "jung.phases.assessment.models",
        ),
        (
            "from .. import application",
            "jung.application",
        ),
        (
            "from jung import application",
            "jung.application",
        ),
        (
            "from jung import phases",
            "jung.phases",
        ),
    ],
)
def test_import_resolution_handles_forbidden_absolute_and_relative_forms(
    source: str,
    expected: str,
) -> None:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ImportFrom)

    modules = _resolve_import_from("jung.domain", node)

    assert expected in modules


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            JUNG_SRC / "domain" / "fake.py",
            "jung.domain",
        ),
        (
            JUNG_SRC / "domain" / "nested" / "fake.py",
            "jung.domain.nested",
        ),
        (
            JUNG_SRC / "domain" / "nested" / "__init__.py",
            "jung.domain.nested",
        ),
    ],
)
def test_module_package_for_path(
    path: Path,
    expected: str,
) -> None:
    assert _module_package_for_path(path) == expected
