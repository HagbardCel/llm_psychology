#!/usr/bin/env python3
"""Static cutover checks for Phase 6 legacy deletion."""

from __future__ import annotations

import argparse
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

INVENTORY_PATH = Path("docs/refactor/deletion-inventory.md")

ALLOWED_TREATMENTS = frozenset(
    {
        "reimplement_minimal",
        "port_then_delete",
        "retain_outside_root",
        "retain_test",
    }
)
ALLOWED_STATUSES = frozenset({"planned", "in_progress", "complete"})

INVENTORY_SECTIONS = (
    "## Filesystem deletion roots",
    "## Legacy Make targets",
    "## Legacy CI workflows",
    "## Exceptions",
)

EXCEPTION_COLUMNS = ("Path", "Treatment", "Owner PR", "Status", "Evidence")

LEGACY_GATE_INVOCATIONS = (
    "$(MAKE) validate-schemas",
    "$(MAKE) validate-generated-contracts",
    "$(MAKE) validate-architecture",
    "$(MAKE) characterization-smoke",
    "$(MAKE) probe-console-deterministic",
    "$(MAKE) test-validate",
)

TARGET_GATE_INVOCATIONS = (
    "$(MAKE) test-target",
    "$(MAKE) probe-console-v1-deterministic",
    "scripts/validate_refactor_phase_5.py",
    "scripts/validate_refactor_phase_6.py",
)

TARGET_ENTRY_POINTS = {
    "jung-api": "jung.api.app:cli",
    "jung-console": "jung.client.terminal:cli",
    "jung-db": "jung.tools.db_backup:main",
}

FORBIDDEN_DIRECT_DEPS = frozenset(
    {
        "trio",
        "quart",
        "hypercorn",
        "trio-websocket",
        "quart-trio",
        "quart-cors",
        "langchain-core",
        "langchain-google-genai",
        "langchain-ollama",
        "langchain-openai",
        "pytest-trio",
    }
)

TARGET_SUPPORT_TESTS = (
    "tests/unit/test_validate_refactor_phase_5.py",
    "tests/unit/test_validate_refactor_phase_6.py",
    "tests/unit/test_recording_fake_llm.py",
    "tests/unit/test_measure_codebase.py",
)

REQUIRED_TARGET_MAKE_TARGETS = (
    "test-target",
    "smoke-target-local-llm",
    "finalization-check-target",
    "validate-refactor-phase-6",
    "probe-console-v1-deterministic",
)


@dataclass(frozen=True, slots=True)
class InventoryException:
    path: str
    treatment: str
    owner_pr: str
    status: str
    evidence: str


@dataclass(frozen=True, slots=True)
class Inventory:
    filesystem_roots: tuple[str, ...]
    make_targets: tuple[str, ...]
    workflow_items: tuple[str, ...]
    exceptions: tuple[InventoryException, ...]


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _makefile_targets(root: Path) -> set[str]:
    makefile = root / "Makefile"
    if not makefile.is_file():
        return set()
    targets: set[str] = set()
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if line.startswith("\t"):
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(token in line for token in (":=", "+=", "?=")):
            continue
        if ":" not in line:
            continue
        target = line.split(":", 1)[0].strip()
        if target and not target.startswith("."):
            targets.add(target)
    return targets


def _recipe_text(root: Path, target: str) -> str:
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    lines: list[str] = []
    collecting = False
    for line in makefile.splitlines():
        if not collecting:
            if line.startswith(f"{target}:") or line.startswith(f"{target} "):
                collecting = True
                lines.append(line)
            continue
        if line and not line.startswith("\t") and ":" in line:
            break
        lines.append(line)
    return "\n".join(lines)


def _parse_inventory(root: Path) -> tuple[Inventory | None, list[str]]:
    errors: list[str] = []
    path = root / INVENTORY_PATH
    if not path.is_file():
        return None, [f"missing inventory: {INVENTORY_PATH}"]

    text = path.read_text(encoding="utf-8")
    for section in INVENTORY_SECTIONS:
        if section not in text:
            errors.append(f"inventory missing section: {section}")

    frontmatter = text.split("---", 2)[1] if text.startswith("---") else ""
    if "status: active" not in frontmatter:
        errors.append("inventory frontmatter must have status: active")

    for column in EXCEPTION_COLUMNS:
        if column not in text:
            errors.append(f"inventory exceptions table missing column: {column}")

    def _bullet_items(section_header: str) -> list[str]:
        items: list[str] = []
        in_section = False
        for line in text.splitlines():
            if line.strip() == section_header:
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if in_section and line.startswith("- "):
                item = line[2:].strip().strip("`")
                if item:
                    items.append(item)
        return items

    filesystem_roots = tuple(_bullet_items("## Filesystem deletion roots"))
    make_targets = tuple(_bullet_items("## Legacy Make targets"))
    workflow_items = tuple(_bullet_items("## Legacy CI workflows"))

    exceptions: list[InventoryException] = []
    in_table = False
    seen_paths: set[str] = set()
    for line in text.splitlines():
        if line.strip() == "## Exceptions":
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.startswith("|"):
            continue
        if line.startswith("| Path") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(EXCEPTION_COLUMNS):
            errors.append(f"inventory exception row has wrong column count: {line}")
            continue
        path_value, treatment, owner_pr, status, evidence = cells
        path_value = path_value.strip("`")
        if path_value in seen_paths:
            errors.append(f"duplicate inventory exception path: {path_value}")
        seen_paths.add(path_value)
        if treatment not in ALLOWED_TREATMENTS:
            errors.append(f"invalid treatment {treatment!r} for {path_value}")
        if status not in ALLOWED_STATUSES:
            errors.append(f"invalid status {status!r} for {path_value}")
        if status in {"planned", "in_progress"} and not evidence.strip():
            errors.append(f"missing evidence for active exception: {path_value}")
        if status == "complete" and not evidence.strip():
            errors.append(f"complete exception requires evidence: {path_value}")
        exceptions.append(
            InventoryException(
                path=path_value,
                treatment=treatment,
                owner_pr=owner_pr,
                status=status,
                evidence=evidence,
            )
        )

    if errors:
        return None, errors

    return (
        Inventory(
            filesystem_roots=filesystem_roots,
            make_targets=make_targets,
            workflow_items=workflow_items,
            exceptions=tuple(exceptions),
        ),
        [],
    )


def _inventory_exception_paths(root: Path, inventory: Inventory) -> list[str]:
    errors: list[str] = []
    for row in inventory.exceptions:
        if row.status not in {"planned", "in_progress"}:
            continue
        candidate = root / row.path
        if row.path.endswith("/"):
            if not candidate.is_dir():
                errors.append(f"planned exception directory missing: {row.path}")
        elif not candidate.exists():
            errors.append(f"planned exception path missing: {row.path}")
    return errors


def _read_pyproject_scripts(root: Path) -> dict[str, str]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return {}
    return {str(key): str(value) for key, value in scripts.items()}


def _gate_uses_invocations(recipe: str, invocations: tuple[str, ...]) -> list[str]:
    return [
        f"gate missing required step: {item}"
        for item in invocations
        if item not in recipe
    ]


def _gate_forbids_invocations(recipe: str, invocations: tuple[str, ...]) -> list[str]:
    return [
        f"gate must not invoke: {item}"
        for item in invocations
        if item in recipe
    ]


def _legacy_runtime_selected(root: Path) -> list[str]:
    errors: list[str] = []
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    if "python -m psychoanalyst_app.server" not in compose:
        errors.append(
            "docker-compose.yml must still use legacy api command pre-cutover"
        )
    if "/health" not in compose:
        errors.append("docker-compose.yml must use legacy health check pre-cutover")

    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    if "psychoanalyst_app.server" not in dockerfile:
        errors.append("Dockerfile CMD must still reference legacy server pre-cutover")
    return errors


def _jung_runtime_selected(root: Path) -> list[str]:
    errors: list[str] = []
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    if "jung-api" not in compose:
        errors.append("docker-compose.yml must run jung-api during cutover")
    if "/api/v1/health" not in compose:
        errors.append(
            "docker-compose.yml must health-check /api/v1/health during cutover"
        )

    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    if 'CMD ["jung-api"]' not in dockerfile:
        errors.append("Dockerfile CMD must be jung-api during cutover")

    scripts = _read_pyproject_scripts(root)
    if set(scripts) != set(TARGET_ENTRY_POINTS):
        errors.append(
            "pyproject entry points must be exactly "
            f"{sorted(TARGET_ENTRY_POINTS)} during cutover, got {sorted(scripts)}"
        )
    for entry, target in TARGET_ENTRY_POINTS.items():
        if scripts.get(entry) != target:
            errors.append(f"pyproject script {entry!r} must map to {target!r}")

    legacy_scripts = {"psychoanalyst-server", "psychoanalyst-db"}
    if legacy_scripts & set(scripts):
        errors.append("legacy project scripts must be removed during cutover")

    return errors


def _filesystem_roots_absent(root: Path, inventory: Inventory) -> list[str]:
    errors: list[str] = []
    for item in inventory.filesystem_roots:
        path = root / item
        if item.endswith("/"):
            if path.is_dir():
                errors.append(f"filesystem deletion root still present: {item}")
        elif path.exists():
            errors.append(f"filesystem deletion root still present: {item}")
    return errors


def _scan_workflows(root: Path, forbidden: frozenset[str]) -> list[str]:
    errors: list[str] = []
    workflow_dir = root / ".github/workflows"
    if not workflow_dir.is_dir():
        return errors
    for workflow in workflow_dir.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                errors.append(
                    f"workflow {_display_path(workflow, root)} references "
                    f"forbidden token: {token}"
                )
    return errors


def _dependency_file_checks(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in (
        "requirements.in",
        "requirements.txt",
        "requirements-dev.in",
        "requirements-dev.txt",
    ):
        path = root / relative
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.split("#", 1)[0].strip()
            if not stripped or stripped.startswith("-"):
                continue
            name = re.split(r"[<>=!~\[]", stripped, maxsplit=1)[0].strip().lower()
            if name in FORBIDDEN_DIRECT_DEPS:
                errors.append(f"{relative} still lists forbidden dependency: {name}")
    return errors


def validate_pre_cutover(root: Path) -> list[str]:
    errors: list[str] = []
    inventory, inventory_errors = _parse_inventory(root)
    errors.extend(inventory_errors)
    if inventory is None:
        return errors

    errors.extend(_inventory_exception_paths(root, inventory))

    makefile_targets = _makefile_targets(root)
    for target in REQUIRED_TARGET_MAKE_TARGETS:
        if target not in makefile_targets:
            errors.append(f"Makefile missing target: {target}")

    for relative in TARGET_SUPPORT_TESTS:
        if not (root / relative).is_file():
            errors.append(f"missing target support test: {relative}")

    smoke_recipe = _recipe_text(root, "smoke-target-local-llm")
    if "smoke-refactor-phase-3-local-llm" not in smoke_recipe:
        errors.append(
            "smoke-target-local-llm must alias smoke-refactor-phase-3-local-llm"
        )

    candidate = _recipe_text(root, "finalization-check-target")
    errors.extend(_gate_uses_invocations(candidate, TARGET_GATE_INVOCATIONS))
    errors.extend(_gate_forbids_invocations(candidate, LEGACY_GATE_INVOCATIONS))
    if "--stage pre-cutover" not in candidate:
        errors.append(
            "finalization-check-target must invoke "
            "validate_refactor_phase_6.py --stage pre-cutover"
        )

    canonical = _recipe_text(root, "finalization-check")
    errors.extend(_gate_uses_invocations(canonical, LEGACY_GATE_INVOCATIONS))

    errors.extend(_legacy_runtime_selected(root))
    return errors


def validate_cutover(root: Path) -> list[str]:
    errors: list[str] = []
    inventory, inventory_errors = _parse_inventory(root)
    errors.extend(inventory_errors)
    if inventory is None:
        return errors

    errors.extend(_inventory_exception_paths(root, inventory))

    canonical = _recipe_text(root, "finalization-check")
    errors.extend(_gate_uses_invocations(canonical, TARGET_GATE_INVOCATIONS))
    errors.extend(_gate_forbids_invocations(canonical, LEGACY_GATE_INVOCATIONS))
    if "--stage cutover" not in canonical:
        errors.append(
            "canonical finalization-check must use "
            "validate_refactor_phase_6.py --stage cutover"
        )

    errors.extend(_jung_runtime_selected(root))
    return errors


def validate_final(root: Path) -> list[str]:
    errors: list[str] = []
    inventory, inventory_errors = _parse_inventory(root)
    errors.extend(inventory_errors)
    if inventory is None:
        return errors

    for row in inventory.exceptions:
        if row.status != "complete":
            errors.append(f"inventory exception not complete: {row.path}")

    errors.extend(_filesystem_roots_absent(root, inventory))

    canonical = _recipe_text(root, "finalization-check")
    if "--final" not in canonical:
        errors.append(
            "canonical finalization-check must use validate_refactor_phase_6.py --final"
        )

    errors.extend(_jung_runtime_selected(root))
    errors.extend(
        _scan_workflows(
            root,
            frozenset(
                {
                    "psychoanalyst_app.server",
                    "characterization-full",
                    "$(MAKE) validate-schemas",
                    "$(MAKE) probe-console-deterministic",
                }
            ),
        )
    )
    errors.extend(_dependency_file_checks(root))

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools_tool = pyproject.get("tool", {}).get("setuptools", {})
    package_data = setuptools_tool.get("package-data", {})
    if isinstance(package_data, dict) and "psychoanalyst_app" in package_data:
        errors.append("pyproject package-data still references psychoanalyst_app")

    if (root / "src/psychoanalyst_app").exists():
        errors.append("src/psychoanalyst_app still exists")

    return errors


def validate(root: Path | None = None, *, stage: str = "pre-cutover") -> list[str]:
    resolved = (root or REPO_ROOT).resolve()
    if stage == "pre-cutover":
        return validate_pre_cutover(resolved)
    if stage == "cutover":
        return validate_cutover(resolved)
    if stage == "final":
        return validate_final(resolved)
    return [f"unknown stage: {stage}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage", choices=("pre-cutover", "cutover"))
    group.add_argument("--final", action="store_true")
    args = parser.parse_args()
    stage = "final" if args.final else args.stage

    errors = validate(stage=stage)
    if errors:
        print(f"Phase 6 refactor validation failed ({stage}):")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"Phase 6 refactor validation passed ({stage}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
