#!/usr/bin/env python3
"""Validate substantive, discoverable Phase 1 refactor evidence."""

from __future__ import annotations

import re
from pathlib import Path

REQUIRED = [
    "docs/refactor/target-architecture.md",
    "docs/refactor/api-v1-contract.md",
    "docs/refactor/workflow-specification.md",
    "docs/refactor/deletion-inventory.md",
    "docs/refactor/test-treatment-inventory.md",
    "docs/refactor/baseline-metrics.md",
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

CHARACTERIZATION_FILES = (
    "tests/characterization/conftest.py",
    "tests/characterization/legacy_client.py",
    "tests/characterization/assertions.py",
    "tests/characterization/test_onboarding_flow.py",
    "tests/characterization/test_therapy_lifecycle.py",
    "tests/characterization/test_restart.py",
)

DELETION_SECTIONS = (
    "## Filesystem deletion roots",
    "## Legacy Make targets",
    "## Legacy CI workflows",
    "## Exceptions",
)

DELETION_EXCEPTION_COLUMNS = (
    "Path",
    "Treatment",
    "Owner PR",
    "Status",
    "Evidence",
)


def _links_exist(root: Path, path: str, text: str) -> list[str]:
    broken = []
    for target in re.findall(r"\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)", text):
        candidate = (root / path).parent / target
        if not candidate.exists():
            broken.append(f"{path}: {target}")
    return broken


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
    ):
        if header not in text:
            errors.append(f"missing API contract section {header!r}")
    return errors


def _workflow_complete(root: Path) -> list[str]:
    text = (root / "docs/refactor/workflow-specification.md").read_text(
        encoding="utf-8"
    )
    errors: list[str] = []
    if "## Transition table" not in text:
        errors.append("missing workflow transition table")
    if "## Operation lifecycle" not in text:
        errors.append("missing workflow operation lifecycle")
    if "## ChatTurn lifecycle" not in text:
        errors.append("missing workflow chat turn lifecycle")
    return errors


def _baseline_sha_valid(root: Path) -> list[str]:
    text = (root / "docs/refactor/baseline-metrics.md").read_text(encoding="utf-8")
    errors: list[str] = []
    if not re.search(r"`([0-9a-f]{40})`", text):
        errors.append("baseline-metrics.md missing 40-char SHA")
    for key in (
        "production_python_code_loc",
        "persistence_related_modules",
        "tokenize",
        "Dependency classification",
    ):
        if key not in text:
            errors.append(f"missing baseline content {key!r}")
    return errors


def _deletion_inventory_structure(root: Path) -> list[str]:
    text = (root / "docs/refactor/deletion-inventory.md").read_text(encoding="utf-8")
    errors: list[str] = []
    for section in DELETION_SECTIONS:
        if section not in text:
            errors.append(f"missing deletion inventory section {section!r}")
    for column in DELETION_EXCEPTION_COLUMNS:
        if column not in text:
            errors.append(f"missing deletion inventory exception column {column!r}")
    if "status: active" not in text.split("---", 2)[1]:
        errors.append("deletion inventory must have status: active")
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

    errors.extend(_adr_status_accepted(root))
    errors.extend(_forbidden_terms(root))
    errors.extend(_api_contract_complete(root))
    errors.extend(_workflow_complete(root))
    errors.extend(_baseline_sha_valid(root))
    errors.extend(_deletion_inventory_structure(root))
    errors.extend(_characterization_layout(root))

    test_treatment = root / "docs/refactor/test-treatment-inventory.md"
    if test_treatment.is_file():
        treatment_text = test_treatment.read_text(encoding="utf-8")
        for action in ("rewrite_api", "rewrite_application", "delete_with_component"):
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
