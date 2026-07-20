#!/usr/bin/env python3
"""Validate required metadata and indexing for active documentation files."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

ACTIVE_DOCS = [
    "docs/README.md",
    "docs/ui-scope.md",
    "docs/refactor/target-architecture.md",
    "docs/refactor/api-v1-contract.md",
    "docs/refactor/workflow-specification.md",
]

REQUIRED_KEYS = {
    "owner",
    "status",
    "last_reviewed",
    "review_cycle_days",
    "source_of_truth_for",
}


def _parse_front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML front matter start delimiter")

    lines = text.splitlines()
    end_index: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        raise ValueError("missing YAML front matter end delimiter")

    metadata: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"invalid front matter line: {line}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def _validate_active_readme_index(repo_root: Path, errors: list[str]) -> None:
    readme_path = repo_root / "docs/README.md"
    text = readme_path.read_text(encoding="utf-8")

    marker = "## Active Docs (Canonical)"
    if marker not in text:
        errors.append(f"{readme_path}: missing '{marker}' section")
        return

    active_section = text.split(marker, 1)[1]
    active_section = re.split(r"\n##\s+", active_section, maxsplit=1)[0]

    expected_links = [doc_path.removeprefix("docs/") for doc_path in ACTIVE_DOCS]
    actual_links = [
        target.split("#", maxsplit=1)[0].removeprefix("./")
        for target in re.findall(r"\[[^]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)", active_section)
    ]

    if actual_links != expected_links:
        errors.append(
            f"{readme_path}: active-doc link targets must exactly match "
            f"{expected_links!r} in order; found {actual_links!r}"
        )


def _validate_review_freshness(
    doc: str,
    metadata: dict[str, str],
    errors: list[str],
    *,
    today: date | None = None,
) -> None:
    try:
        reviewed = date.fromisoformat(metadata["last_reviewed"])
    except ValueError:
        errors.append(
            f"{doc}: last_reviewed must be ISO date YYYY-MM-DD, "
            f"got '{metadata['last_reviewed']}'"
        )
        return

    try:
        cycle = int(metadata["review_cycle_days"])
        if cycle <= 0:
            raise ValueError
    except ValueError:
        errors.append(
            f"{doc}: review_cycle_days must be a positive integer, "
            f"got '{metadata['review_cycle_days']}'"
        )
        return

    due = reviewed + timedelta(days=cycle)
    if (today or date.today()) > due:
        errors.append(
            f"{doc}: documentation review is overdue "
            f"(last reviewed {reviewed.isoformat()}, due {due.isoformat()})"
        )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    errors: list[str] = []

    for doc in ACTIVE_DOCS:
        path = repo_root / doc
        if not path.exists():
            errors.append(f"{doc}: file not found")
            continue

        try:
            metadata = _parse_front_matter(path)
        except ValueError as exc:
            errors.append(f"{doc}: {exc}")
            continue

        missing_keys = sorted(REQUIRED_KEYS - set(metadata))
        if missing_keys:
            errors.append(f"{doc}: missing required metadata keys: {missing_keys}")
            continue

        if metadata["status"] != "active":
            errors.append(f"{doc}: status must be 'active', got '{metadata['status']}'")

        _validate_review_freshness(doc, metadata, errors)

        if not metadata["owner"]:
            errors.append(f"{doc}: owner must not be empty")
        if not metadata["source_of_truth_for"]:
            errors.append(f"{doc}: source_of_truth_for must not be empty")

        text = path.read_text(encoding="utf-8")
        for marker in ("Last Verified", "Last Updated"):
            if marker in text:
                errors.append(
                    f"{doc}: remove duplicate body freshness marker '{marker}'"
                )

    _validate_active_readme_index(repo_root, errors)

    if errors:
        print("Documentation metadata validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Documentation metadata validation passed.")
    print(f"Validated active docs: {len(ACTIVE_DOCS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
