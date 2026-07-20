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

LINKED_DOC_GLOBS = ["README.md", "AGENTS.md", "docs/**/*.md"]

FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
LINK_TARGET_RE = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(<[^>\n]*>|[^()\s]+)(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)"
)
REFERENCE_DEFINITION_RE = re.compile(
    r"^[ \t]{0,3}\[[^\]\n]+\]:\s*(<[^>\n]*>|\S+)",
    re.MULTILINE,
)
EXTERNAL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


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


def _strip_code_blocks(text: str) -> str:
    """Blank out fenced code blocks (``` or ~~~), preserving line count."""
    lines = text.split("\n")
    result: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in lines:
        stripped = line.strip()
        if fence_char is not None:
            closing_pattern = rf"^{re.escape(fence_char)}{{{fence_len},}}\s*$"
            if re.match(closing_pattern, stripped):
                fence_char = None
                fence_len = 0
            result.append("")
            continue
        opening = FENCE_OPEN_RE.match(stripped)
        if opening:
            token = opening.group(1)
            fence_char = token[0]
            fence_len = len(token)
            result.append("")
            continue
        result.append(line)
    return "\n".join(result)


def _strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code spans before link scanning."""
    return INLINE_CODE_RE.sub("", _strip_code_blocks(text))


def _extract_link_targets(text: str) -> list[str]:
    targets = [match.group(1) for match in LINK_TARGET_RE.finditer(text)]
    targets += [match.group(1) for match in REFERENCE_DEFINITION_RE.finditer(text)]
    return targets


def _normalize_link_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith("#"):
        return None
    if EXTERNAL_SCHEME_RE.match(target):
        return None
    local_target = re.split(r"[?#]", target, maxsplit=1)[0].strip()
    if not local_target:
        return None
    return local_target


def _resolve_local_link(repo_root: Path, doc_path: Path, target: str) -> Path:
    if target.startswith("/"):
        return repo_root / target.lstrip("/")
    return doc_path.parent / target


def _validate_local_links(repo_root: Path, errors: list[str]) -> None:
    doc_paths: set[Path] = set()
    for pattern in LINKED_DOC_GLOBS:
        doc_paths.update(repo_root.glob(pattern))

    for doc_path in sorted(doc_paths):
        rel_doc = doc_path.relative_to(repo_root).as_posix()
        text = doc_path.read_text(encoding="utf-8")
        scannable_text = _strip_code(text)

        for raw_target in _extract_link_targets(scannable_text):
            local_target = _normalize_link_target(raw_target)
            if local_target is None:
                continue

            resolved = _resolve_local_link(repo_root, doc_path, local_target)
            if not resolved.exists():
                errors.append(f"{rel_doc}: unresolved local link target '{raw_target}'")


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
    _validate_local_links(repo_root, errors)

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
