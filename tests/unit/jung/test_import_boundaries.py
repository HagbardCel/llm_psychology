"""Import boundary checks for the jung package.

These checks walk the `src/jung` directory tree directly rather than
enumerating fixed file lists, so they stay correct as files are added,
renamed, or moved between packages. Boundaries are grouped by the
architectural layer they protect: global legacy/SDK isolation, domain
purity, phase processor isolation, the API surface, the client surface,
and core transport independence.
"""

from __future__ import annotations

import ast
import re
import sys
from importlib.util import resolve_name
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
JUNG_SRC = ROOT / "src" / "jung"
DOMAIN_SRC = JUNG_SRC / "domain"
PHASES_SRC = JUNG_SRC / "phases"
LLM_SRC = JUNG_SRC / "llm"
API_SRC = JUNG_SRC / "api"
CLIENT_SRC = JUNG_SRC / "client"

# ---------------------------------------------------------------------------
# AST helpers shared by every boundary check below.
# ---------------------------------------------------------------------------


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


def _resolve_import_from(package: str, node: ast.ImportFrom) -> list[str]:
    if node.level:
        relative_name = "." * node.level + (node.module or "")
        base = resolve_name(relative_name, package)
    elif node.module is not None:
        base = node.module
    else:
        return []

    modules = [base]
    modules.extend(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return modules


def _resolved_imported_modules_from_source(
    source: str,
    *,
    package: str,
    filename: str = "<test>",
) -> list[str]:
    tree = ast.parse(source, filename=filename)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.extend(_resolve_import_from(package, node))
    return modules


def _resolved_imported_modules(path: Path) -> list[str]:
    return _resolved_imported_modules_from_source(
        path.read_text(encoding="utf-8"),
        package=_module_package_for_path(path),
        filename=str(path),
    )


def _matches_any_prefix(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes
    )


def _python_files(*roots: Path) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(sorted(root.rglob("*.py")))
    return paths


# ---------------------------------------------------------------------------
# Rule 1: global legacy/framework absence, and OpenAI SDK confinement.
# ---------------------------------------------------------------------------

# Forbidden anywhere under src/jung, matched as an exact module or a dotted
# submodule (e.g. "trio" or "trio.lowlevel", but not "trio_util").
GLOBAL_FORBIDDEN_EXACT_OR_DOTTED = (
    "psychoanalyst_app",
    "trio",
    "quart",
    "quart_trio",
    "console_ui",
    "console-ui",
)

# Forbidden anywhere under src/jung, matched as a bare string prefix so that
# the whole `langchain*` family (langchain, langchain_core, langchain_openai,
# ...) is caught.
GLOBAL_FORBIDDEN_WILDCARD_PREFIXES = ("langchain",)


def _global_forbidden_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        under_llm = LLM_SRC in path.parents or path == LLM_SRC
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root == "openai":
                if under_llm:
                    continue
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
                continue
            if _matches_any_prefix(module, GLOBAL_FORBIDDEN_EXACT_OR_DOTTED) or any(
                module.startswith(prefix)
                for prefix in GLOBAL_FORBIDDEN_WILDCARD_PREFIXES
            ):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    return violations


def test_no_legacy_or_forbidden_global_imports() -> None:
    violations = _global_forbidden_violations(_python_files(JUNG_SRC))
    assert violations == []


def test_only_llm_package_imports_openai_sdk() -> None:
    violations: list[str] = []
    for path in _python_files(JUNG_SRC):
        if LLM_SRC in path.parents or path == LLM_SRC:
            continue
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root == "openai":
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


# ---------------------------------------------------------------------------
# Rule 2: domain purity.
# ---------------------------------------------------------------------------

DOMAIN_FORBIDDEN_MODULES = (
    "jung.application",
    "jung.persistence",
    "jung.phases",
    "jung.api",
    "jung.client",
)

TRANSPORT_FRAMEWORK_ROOTS = ("fastapi", "starlette", "httpx", "websockets", "uvicorn")


def test_domain_has_no_forbidden_dependencies() -> None:
    violations: list[str] = []
    for path in _python_files(DOMAIN_SRC):
        for module in _resolved_imported_modules(path):
            root = module.split(".")[0]
            if root in TRANSPORT_FRAMEWORK_ROOTS:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
            elif _matches_any_prefix(module, DOMAIN_FORBIDDEN_MODULES):
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
        (DOMAIN_SRC / "fake.py", "jung.domain"),
        (DOMAIN_SRC / "nested" / "fake.py", "jung.domain.nested"),
        (DOMAIN_SRC / "nested" / "__init__.py", "jung.domain.nested"),
    ],
)
def test_module_package_for_path(path: Path, expected: str) -> None:
    assert _module_package_for_path(path) == expected


# ---------------------------------------------------------------------------
# Rule 3: phase isolation.
# ---------------------------------------------------------------------------

PHASE_LEVEL_FORBIDDEN_MODULES = (
    "jung.persistence",
    "jung.api",
    "jung.client",
    "jung.application",
)

ALLOWED_CROSS_PHASE_MODULES = frozenset(
    {
        "jung.phases.transcript",
        "jung.phases.context_bounds",
    }
)


def _phase_package_names() -> frozenset[str]:
    if not PHASES_SRC.exists():
        return frozenset()
    return frozenset(
        entry.name
        for entry in PHASES_SRC.iterdir()
        if entry.is_dir() and (entry / "__init__.py").exists()
    )


def _own_phase(path: Path) -> str | None:
    relative_parts = path.relative_to(PHASES_SRC).parts
    if len(relative_parts) <= 1:
        return None
    return relative_parts[0]


def _cross_phase_import_allowed(module: str, other_phase: str) -> bool:
    if module in ALLOWED_CROSS_PHASE_MODULES:
        return True
    if module == f"jung.phases.{other_phase}.models":
        return True
    return module.startswith(f"jung.phases.{other_phase}.models.")


def test_phases_do_not_import_persistence_api_client_or_application() -> None:
    violations: list[str] = []
    for path in _python_files(PHASES_SRC):
        for module in _resolved_imported_modules(path):
            if _matches_any_prefix(module, PHASE_LEVEL_FORBIDDEN_MODULES):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_phases_do_not_cross_import_other_phase_implementations() -> None:
    phase_names = _phase_package_names()
    violations: list[str] = []

    for path in _python_files(PHASES_SRC):
        own_phase = _own_phase(path)
        for module in _resolved_imported_modules(path):
            if not module.startswith("jung.phases."):
                continue
            remainder = module[len("jung.phases.") :]
            other_phase = remainder.split(".", 1)[0]
            if other_phase not in phase_names or other_phase == own_phase:
                continue
            if not _cross_phase_import_allowed(module, other_phase):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert violations == []


def test_phase_processors_do_not_import_other_phase_processor_modules() -> None:
    phase_names = _phase_package_names()
    processor_pattern = re.compile(r"^jung\.phases\.([^.]+)\.processor(\.|$)")
    violations: list[str] = []

    for path in _python_files(PHASES_SRC):
        own_phase = _own_phase(path)
        for module in _resolved_imported_modules(path):
            match = processor_pattern.match(module)
            if not match:
                continue
            other_phase = match.group(1)
            if other_phase in phase_names and other_phase != own_phase:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert violations == []


# ---------------------------------------------------------------------------
# Rule 4: API surface boundaries.
# ---------------------------------------------------------------------------

_PHASE_PROCESSOR_PATTERN = re.compile(r"^jung\.phases\.[^.]+\.processor(\.|$)")


def _is_phase_processor_import(module: str) -> bool:
    return bool(_PHASE_PROCESSOR_PATTERN.match(module))


# Concrete-infrastructure imports each API surface file must never reach for.
# `jung.api.settings` builds its environment-backed configuration from
# `jung.config` only; it must not reach into the composition root.
API_SURFACE_FORBIDDEN_MODULES: dict[str, tuple[str, ...]] = {
    "app.py": ("jung.persistence", "jung.llm.openai_compatible"),
    "settings.py": (
        "jung.composition",
        "jung.persistence",
        "jung.llm.openai_compatible",
    ),
    "routes.py": ("jung.composition", "jung.persistence", "jung.llm.openai_compatible"),
    "websocket.py": (
        "jung.composition",
        "jung.persistence",
        "jung.llm.openai_compatible",
    ),
    "contracts.py": ("jung.composition", "jung.persistence", "jung.llm", "jung.phases"),
}

# Files where a phase-processor import (jung.phases.<phase>.processor) is
# additionally forbidden. contracts.py is excluded because it already bans
# all of jung.phases above.
API_SURFACE_FORBID_PHASE_PROCESSORS = frozenset(
    {"app.py", "settings.py", "routes.py", "websocket.py"}
)


@pytest.mark.parametrize(
    "filename",
    sorted(API_SURFACE_FORBIDDEN_MODULES),
)
def test_api_surface_file_respects_import_boundaries(filename: str) -> None:
    path = API_SRC / filename
    if not path.exists():
        pytest.skip(f"jung.api.{filename} not present yet")

    forbidden = API_SURFACE_FORBIDDEN_MODULES[filename]
    check_processors = filename in API_SURFACE_FORBID_PHASE_PROCESSORS

    violations: list[str] = []
    for module in _resolved_imported_modules(path):
        if _matches_any_prefix(module, forbidden):
            violations.append(f"{path.relative_to(ROOT)} imports {module}")
        elif check_processors and _is_phase_processor_import(module):
            violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert violations == []


@pytest.mark.parametrize(
    "source",
    [
        "from jung.persistence.sqlite_store import SQLiteStore",
        "from jung.llm.openai_compatible import OpenAICompatibleLLM",
        "from ..phases.intake import processor",
    ],
)
def test_api_import_boundary_catches_resolved_bypass_imports(source: str) -> None:
    modules = _resolved_imported_modules_from_source(source, package="jung.api")
    forbidden = ("jung.persistence", "jung.llm.openai_compatible")
    violations = [
        module
        for module in modules
        if _matches_any_prefix(module, forbidden) or _is_phase_processor_import(module)
    ]
    assert violations


def test_api_init_has_no_imports() -> None:
    init_path = API_SRC / "__init__.py"
    if not init_path.exists():
        pytest.skip("jung.api package not present yet")
    assert _resolved_imported_modules(init_path) == []


# ---------------------------------------------------------------------------
# Rule 5: client surface boundaries.
# ---------------------------------------------------------------------------

_CLIENT_ALLOWED_EXTERNAL_ROOTS = frozenset({"httpx", "pydantic", "websockets"})


def _client_import_violations(modules: list[str]) -> list[str]:
    violations: list[str] = []
    for module in modules:
        root = module.split(".")[0]
        if root == "__future__" or root in sys.stdlib_module_names:
            continue
        if root in _CLIENT_ALLOWED_EXTERNAL_ROOTS:
            continue
        if module == "jung.api.contracts" or module.startswith("jung.api.contracts."):
            continue
        if module == "jung.client" or module.startswith("jung.client."):
            continue
        violations.append(module)
    return violations


def test_client_uses_contract_only_import_allow_list() -> None:
    if not CLIENT_SRC.exists():
        pytest.skip("jung.client package not present yet")

    violations: list[str] = []
    for path in _python_files(CLIENT_SRC):
        violations.extend(
            f"{path.relative_to(ROOT)} imports {module}"
            for module in _client_import_violations(_resolved_imported_modules(path))
        )

    assert violations == []


def test_client_import_allow_list_accepts_resolved_supported_imports() -> None:
    modules = _resolved_imported_modules_from_source(
        "\n".join(
            (
                "from __future__ import annotations",
                "import asyncio",
                "import httpx",
                "import pydantic",
                "import websockets",
                "from jung.api.contracts import AppSnapshotResponse",
                "from .api_client import JungApiClient",
            )
        ),
        package="jung.client",
    )

    assert _client_import_violations(modules) == []


@pytest.mark.parametrize(
    "source",
    (
        "import requests",
        "import tenacity",
        "import openai",
        "from jung.application import TherapyApplication",
        "from ..application import TherapyApplication",
        "from jung import workflow",
        "from jung.persistence.sqlite_store import SQLiteStore",
        "from jung.phases.intake import processor",
        "from jung import llm",
    ),
)
def test_client_import_allow_list_rejects_unsupported_imports(source: str) -> None:
    modules = _resolved_imported_modules_from_source(source, package="jung.client")

    assert _client_import_violations(modules)


# ---------------------------------------------------------------------------
# Rule 6: core transport independence.
# ---------------------------------------------------------------------------


def test_core_does_not_import_transport_frameworks_outside_api_and_client() -> None:
    violations: list[str] = []

    for path in _python_files(JUNG_SRC):
        relative = path.relative_to(JUNG_SRC)
        if relative.parts[0] in {"api", "client"}:
            continue

        for module in _resolved_imported_modules(path):
            if module.split(".", 1)[0] in TRANSPORT_FRAMEWORK_ROOTS:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert violations == []
