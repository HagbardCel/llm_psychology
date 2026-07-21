"""Guard against legacy operational script identifiers."""

from __future__ import annotations

import subprocess
from pathlib import Path

FORBIDDEN_IDENTIFIERS = (
    "psychoanalyst.db",
    "psychoanalyst_test.db",
    "psychoanalyst_usertest.db",
    "assessment_recommendations",
    "therapy_plans",
    "user_profiles",
    "patient_analysis",
    "session_enrichment_jobs",
    "psychoanalyst_app",
    "psychoanalyst-hooks",
)

SHELL_SHEBANGS = ("#!/usr/bin/env bash", "#!/bin/bash", "#!/bin/sh")


def _is_tracked_script(path: Path) -> bool:
    if path.suffix in {".py", ".sh"}:
        return True
    if path.suffix:
        return False
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return False
    return first_line.startswith(SHELL_SHEBANGS)


def test_tracked_scripts_have_no_legacy_identifiers() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--", "scripts"],
        check=True,
        capture_output=True,
    )
    paths = [Path(part) for part in result.stdout.decode("utf-8").split("\0") if part]
    violations: list[str] = []

    for rel_path in paths:
        path = repo_root / rel_path
        if not path.is_file() or not _is_tracked_script(path):
            continue
        text = path.read_text(encoding="utf-8")
        for identifier in FORBIDDEN_IDENTIFIERS:
            if identifier in text:
                violations.append(f"{rel_path}: {identifier}")

    assert not violations, "legacy identifiers found:\n" + "\n".join(violations)
