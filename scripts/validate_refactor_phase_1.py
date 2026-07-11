#!/usr/bin/env python3
"""Validate substantive, discoverable Phase 1 refactor evidence."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REQUIRED = [
    "docs/refactor/target-architecture.md",
    "docs/refactor/api-v1-contract.md",
    "docs/refactor/workflow-specification.md",
    "docs/refactor/deletion-inventory.md",
    "docs/refactor/test-treatment-inventory.md",
    "docs/refactor/baseline-metrics.md",
    "docs/refactor/dependency-inventory.md",
    "docs/refactor/phase-1-implementation-plan.md",
    *[
        f"docs/adr/000{i}-{name}.md"
        for i, name in [
            (1, "single-user-api-modular-monolith"),
            (2, "asyncio-fastapi-runtime"),
            (3, "workflow-stage-command-operation-model"),
            (4, "single-sqlite-store-and-schema-reset"),
            (5, "phase-processors-and-llm-gateway"),
        ]
    ],
]

FORBIDDEN_IN_AUTHORITATIVE = (
    "complete_profile",
    "stream_message",
)

API_ENDPOINTS = (
    "GET /api/v1/state",
    "GET /api/v1/profile",
    "PUT /api/v1/profile",
    "GET /api/v1/styles",
    "PUT /api/v1/style",
    "GET /api/v1/sessions",
    "GET /api/v1/sessions/{session_id}",
    "POST /api/v1/sessions",
    "POST /api/v1/sessions/{session_id}/end",
    "POST /api/v1/operations/current/retry",
    "GET /api/v1/health",
    "WS /api/v1/chat",
)

CHARACTERIZATION_FILES = (
    "tests/characterization/conftest.py",
    "tests/characterization/legacy_client.py",
    "tests/characterization/assertions.py",
    "tests/characterization/test_onboarding_flow.py",
    "tests/characterization/test_therapy_lifecycle.py",
    "tests/characterization/test_restart.py",
)

DELETION_COLUMNS = (
    "Path / symbols",
    "Responsibility",
    "Target",
    "Test action",
    "Blocker",
    "Phase",
    "Status",
)


def _links_exist(root: Path, path: str, text: str) -> list[str]:
    broken = []
    for target in re.findall(r"\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)", text):
        candidate = (root / path).parent / target
        if not candidate.exists():
            broken.append(f"{path}: {target}")
    return broken


def _direct_requirements(root: Path) -> set[str]:
    packages: set[str] = set()
    for name in ("requirements.in", "requirements-dev.in"):
        path = root / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "-")):
                continue
            packages.add(line.split("=")[0].split(">")[0].split("<")[0].strip())
    return packages


def _adr_status_accepted(root: Path) -> list[str]:
    errors: list[str] = []
    for index in range(1, 6):
        matches = list((root / "docs/adr").glob(f"000{index}-*.md"))
        if not matches:
            errors.append(f"missing ADR 000{index}")
            continue
        text = matches[0].read_text(encoding="utf-8")
        if "status: accepted" not in text:
            errors.append(f"ADR 000{index} is not accepted")
    return errors


def _forbidden_terms(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in (
        "docs/refactor/target-architecture.md",
        "docs/refactor/api-v1-contract.md",
        "docs/refactor/architecture-refactor-roadmap.md",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        for term in FORBIDDEN_IN_AUTHORITATIVE:
            if term in text:
                errors.append(f"obsolete term {term!r} in {relative}")
    return errors


def _api_contract_complete(root: Path) -> list[str]:
    text = (root / "docs/refactor/api-v1-contract.md").read_text(encoding="utf-8")
    errors: list[str] = []
    for header in (
        "## 1. Shared schemas",
        "## 2. Endpoint matrix",
        "## 3. WebSocket messages",
        "## 4. Errors, revisions, and reconnect rules",
        "ProfileUpdate",
        "StyleSummary",
        "PlanSummary",
        "Reconnect rules",
        "EventStream",
    ):
        if header not in text:
            errors.append(f"missing API contract section/content {header!r}")
    for endpoint in API_ENDPOINTS:
        if endpoint not in text:
            errors.append(f"missing API endpoint {endpoint}")
    return errors


def _workflow_complete(root: Path) -> list[str]:
    text = (root / "docs/refactor/workflow-specification.md").read_text(
        encoding="utf-8"
    )
    errors: list[str] = []
    for header in (
        "## Command matrix",
        "## Transition table",
        "## Operation lifecycle",
        "## ChatTurn lifecycle",
        "## Startup and shutdown recovery",
        "## Legacy mapping",
        "## Legacy value inventory",
    ):
        if header not in text:
            errors.append(f"missing workflow section {header!r}")
    return errors


def _baseline_sha_valid(root: Path) -> list[str]:
    text = (root / "docs/refactor/baseline-metrics.md").read_text(encoding="utf-8")
    errors: list[str] = []
    match = re.search(r"`([0-9a-f]{40})`", text)
    if not match:
        errors.append("baseline-metrics.md missing 40-char SHA")
        return errors
    sha = match.group(1)
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"baseline SHA not found in repository: {sha}")
    for key in (
        "production_python_code_loc",
        "persistence_abstraction_modules",
        "tokenize",
        "Dependency classification",
    ):
        if key not in text:
            errors.append(f"missing baseline content {key!r}")
    return errors


def _deletion_inventory_columns(root: Path) -> list[str]:
    text = (root / "docs/refactor/deletion-inventory.md").read_text(encoding="utf-8")
    errors: list[str] = []
    for column in DELETION_COLUMNS:
        if column not in text:
            errors.append(f"missing deletion inventory column {column!r}")
    grouped_paths = [
        "orchestration/trio_*",
        "services/db/",
        "ws_protocol",
        "LangChain",
    ]
    for item in grouped_paths:
        if item not in text:
            errors.append(f"missing grouped deletion path {item!r}")
    return errors


def _characterization_layout(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in CHARACTERIZATION_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing characterization file: {relative}")
    smoke_found = False
    for relative in (
        "tests/characterization/test_onboarding_flow.py",
        "tests/characterization/test_therapy_lifecycle.py",
    ):
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "characterization_smoke" not in text:
            errors.append(f"missing smoke marker: {relative}")
        if "xfail" in text or "NotImplementedError" in text:
            errors.append(f"placeholder characterization: {relative}")
        if "must_preserve" not in text and "characterization_smoke" in text:
            errors.append(f"missing assertion classification in smoke test: {relative}")
        if "characterization_smoke" in text:
            smoke_found = True
    restart = root / "tests/characterization/test_restart.py"
    if restart.is_file():
        text = restart.read_text(encoding="utf-8")
        if ".restart()" not in text:
            errors.append("restart characterization does not restart the server")
        if "xfail" in text or "NotImplementedError" in text:
            errors.append(
                "placeholder characterization: tests/characterization/test_restart.py"
            )
    if not smoke_found:
        errors.append("no characterization smoke tests found")
    return errors


def validate(root: Path | None = None) -> list[str]:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    errors: list[str] = []

    for item in REQUIRED:
        path = root / item
        if not path.is_file():
            errors.append(f"missing: {item}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            errors.append(f"missing front matter: {item}")
        if "owner:" not in text or "source_of_truth_for:" not in text:
            errors.append(f"incomplete metadata: {item}")
        if item != "docs/refactor/phase-1-implementation-plan.md" and re.search(
            r"\b(?:TODO|TBD|FIXME|NotImplementedError|xfail)\b", text, re.I
        ):
            errors.append(f"unresolved marker: {item}")
        errors.extend(
            f"broken link: {value}" for value in _links_exist(root, item, text)
        )

    target = root / "docs/refactor/target-architecture.md"
    if target.is_file():
        text = target.read_text(encoding="utf-8")
        markers = (
            "submit_message",
            "EventStream",
            "application event subscription",
        )
        for marker in markers:
            if marker not in text:
                errors.append(f"missing target architecture marker {marker!r}")

    errors.extend(_adr_status_accepted(root))
    errors.extend(_forbidden_terms(root))
    errors.extend(_api_contract_complete(root))
    errors.extend(_workflow_complete(root))
    errors.extend(_baseline_sha_valid(root))
    errors.extend(_deletion_inventory_columns(root))
    errors.extend(_characterization_layout(root))

    dependency_inventory = root / "docs/refactor/dependency-inventory.md"
    if dependency_inventory.is_file():
        inventory_text = dependency_inventory.read_text(encoding="utf-8")
        if "baseline-metrics.md" not in inventory_text:
            errors.append("dependency-inventory.md must link to baseline-metrics.md")

    test_treatment = root / "docs/refactor/test-treatment-inventory.md"
    if test_treatment.is_file():
        treatment_text = test_treatment.read_text(encoding="utf-8")
        for action in ("retain", "rewrite_application", "delete_with_component"):
            if action not in treatment_text:
                errors.append(f"missing test treatment action {action!r}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Phase 1 refactor validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Phase 1 refactor artifacts and characterization evidence validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
