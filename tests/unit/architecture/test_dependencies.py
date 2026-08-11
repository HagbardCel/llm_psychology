"""Import boundary checks for the jung package.

These checks walk the `src/jung` directory tree directly rather than
enumerating fixed file lists, so they stay correct as files are added,
renamed, or moved between packages. Boundaries are grouped by the
architectural layer they protect.
"""

from __future__ import annotations

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JUNG_SRC = ROOT / "src" / "jung"
DOMAIN_SRC = JUNG_SRC / "domain"
PHASES_SRC = JUNG_SRC / "phases"
LLM_SRC = JUNG_SRC / "llm"
API_SRC = JUNG_SRC / "api"
CLIENT_SRC = JUNG_SRC / "client"

TRANSPORT_FRAMEWORK_ROOTS = ("fastapi", "starlette", "httpx", "uvicorn")

UNSUPPORTED_ASYNC_ROOTS = ("trio", "quart_trio")

PHASE_LEVEL_FORBIDDEN_MODULES = (
    "jung.application",
    "jung.persistence",
    "jung.api",
    "jung.client",
    "jung.composition",
    "jung.config",
    "jung.workflow",
    "jung.llm.openai_compatible",
)

API_BACKEND_FORBIDDEN_MODULES = (
    "jung.persistence",
    "jung.llm",
    "jung.phases",
    "jung.client",
    "jung.workflow",
)

_CLIENT_ALLOWED_EXTERNAL_ROOTS = frozenset({"httpx", "pydantic"})

_CONTRACTS_FORBIDDEN_PREFIXES = (
    "jung.domain",
    "jung.application",
    "jung.persistence",
    "jung.llm",
    "jung.phases",
    "jung.client",
)


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


def _resolved_imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _module_package_for_path(path)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.extend(_resolve_import_from(package, node))
    return modules


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
    if module == f"jung.phases.{other_phase}.models":
        return True
    return module.startswith(f"jung.phases.{other_phase}.models.")


def test_runtime_is_asyncio_only() -> None:
    violations: list[str] = []
    for path in _python_files(JUNG_SRC):
        for module in _resolved_imported_modules(path):
            if _matches_any_prefix(module, UNSUPPORTED_ASYNC_ROOTS):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_openai_sdk_is_confined_to_llm() -> None:
    violations: list[str] = []
    for path in _python_files(JUNG_SRC):
        under_llm = LLM_SRC in path.parents or path == LLM_SRC
        for module in _resolved_imported_modules(path):
            if module.split(".")[0] == "openai" and not under_llm:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_domain_has_no_forbidden_dependencies() -> None:
    violations: list[str] = []
    for path in _python_files(DOMAIN_SRC):
        for module in _resolved_imported_modules(path):
            if module == "jung":
                continue
            if module.startswith("jung.") and not (
                module == "jung.domain" or module.startswith("jung.domain.")
            ):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_phases_do_not_import_forbidden_layers() -> None:
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


def test_api_does_not_import_backend_implementations() -> None:
    if not API_SRC.exists():
        return

    violations: list[str] = []
    for path in _python_files(API_SRC):
        for module in _resolved_imported_modules(path):
            if _matches_any_prefix(module, API_BACKEND_FORBIDDEN_MODULES):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_client_uses_contract_only_import_allow_list() -> None:
    """Client package may import stdlib, httpx/pydantic, contracts, and itself."""
    if not CLIENT_SRC.exists():
        return

    violations: list[str] = []
    for path in _python_files(CLIENT_SRC):
        violations.extend(
            f"{path.relative_to(ROOT)} imports {module}"
            for module in _client_import_violations(_resolved_imported_modules(path))
        )

    assert violations == []


def test_api_contracts_are_wire_only() -> None:
    """jung.api.contracts must not import domain/application/backend packages."""
    contracts_path = API_SRC / "contracts.py"
    if not contracts_path.exists():
        return

    violations: list[str] = []
    for module in _resolved_imported_modules(contracts_path):
        if _matches_any_prefix(module, _CONTRACTS_FORBIDDEN_PREFIXES):
            violations.append(module)

    assert violations == []


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


def test_private_application_helpers_do_not_leak_outside_application_layer() -> None:
    """Within src/jung, only jung.application and jung._application may import jung._application."""
    violations: list[str] = []
    for path in _python_files(JUNG_SRC):
        relative = path.relative_to(JUNG_SRC)
        if relative.parts[0] == "_application":
            continue
        if relative == Path("application.py"):
            continue
        for module in _resolved_imported_modules(path):
            if module == "jung._application" or module.startswith("jung._application."):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def _reads_os_environ(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr == "environ"
            ):
                return True
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            if any(alias.name == "environ" for alias in node.names):
                return True
    return False


def test_only_config_owns_environment_and_pydantic_settings() -> None:
    """jung.config is the sole production owner of env-backed settings loading."""
    violations: list[str] = []
    for path in _python_files(JUNG_SRC):
        relative = path.relative_to(JUNG_SRC)
        if relative == Path("config.py"):
            continue
        if _reads_os_environ(path):
            violations.append(f"{relative} reads os.environ")
        for module in _resolved_imported_modules(path):
            if module == "pydantic_settings" or module.startswith("pydantic_settings."):
                violations.append(f"{relative} imports {module}")
            if module == "dotenv" or module.startswith("dotenv."):
                violations.append(f"{relative} imports {module}")
    assert violations == []


def test_llm_does_not_import_config() -> None:
    violations: list[str] = []
    for path in _python_files(LLM_SRC):
        for module in _resolved_imported_modules(path):
            if module == "jung.config" or module.startswith("jung.config."):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []
