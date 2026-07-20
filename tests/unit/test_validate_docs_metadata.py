"""Tests for documentation metadata review cadence validation."""

from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/validate_docs_metadata.py"
SPEC = spec_from_file_location("validate_docs_metadata", SCRIPT_PATH)
assert SPEC and SPEC.loader
VALIDATOR = module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
_validate_review_freshness = VALIDATOR._validate_review_freshness
_validate_active_readme_index = VALIDATOR._validate_active_readme_index


def _metadata(last_reviewed: str, cycle: str = "30") -> dict[str, str]:
    return {
        "last_reviewed": last_reviewed,
        "review_cycle_days": cycle,
    }


def _write_active_index(repo_root: Path, targets: list[str]) -> None:
    docs = repo_root / "docs"
    docs.mkdir()
    links = "\n".join(f"- [Document]({target})" for target in targets)
    (docs / "README.md").write_text(
        f"# Documentation Index\n\n## Active Docs (Canonical)\n{links}\n\n## Supporting\n",
        encoding="utf-8",
    )


def _expected_active_targets() -> list[str]:
    return [path.removeprefix("docs/") for path in VALIDATOR.ACTIVE_DOCS]


def test_active_readme_index_accepts_exact_ordered_targets(tmp_path: Path) -> None:
    _write_active_index(tmp_path, _expected_active_targets())
    errors: list[str] = []

    _validate_active_readme_index(tmp_path, errors)

    assert errors == []


def test_active_readme_index_rejects_missing_target_document(tmp_path: Path) -> None:
    _write_active_index(tmp_path, _expected_active_targets()[:-1])
    errors: list[str] = []

    _validate_active_readme_index(tmp_path, errors)

    assert len(errors) == 1
    assert "active-doc link targets must exactly match" in errors[0]
    assert "workflow-specification.md" in errors[0]


def test_active_readme_index_rejects_unexpected_legacy_document(tmp_path: Path) -> None:
    targets = _expected_active_targets()
    targets.insert(1, "ARCHITECTURE.md")
    _write_active_index(tmp_path, targets)
    errors: list[str] = []

    _validate_active_readme_index(tmp_path, errors)

    assert len(errors) == 1
    assert "ARCHITECTURE.md" in errors[0]


def test_active_readme_index_rejects_duplicate_active_link(tmp_path: Path) -> None:
    targets = _expected_active_targets()
    targets.insert(1, targets[0])
    _write_active_index(tmp_path, targets)
    errors: list[str] = []

    _validate_active_readme_index(tmp_path, errors)

    assert len(errors) == 1
    assert errors[0].count("README.md") >= 2


def test_review_freshness_accepts_fresh_document() -> None:
    errors: list[str] = []

    _validate_review_freshness(
        "docs/example.md",
        _metadata("2026-05-15"),
        errors,
        today=date(2026, 5, 31),
    )

    assert errors == []


def test_review_freshness_accepts_document_on_due_date() -> None:
    errors: list[str] = []

    _validate_review_freshness(
        "docs/example.md",
        _metadata("2026-05-01"),
        errors,
        today=date(2026, 5, 31),
    )

    assert errors == []


def test_review_freshness_rejects_overdue_document() -> None:
    errors: list[str] = []

    _validate_review_freshness(
        "docs/example.md",
        _metadata("2026-04-30"),
        errors,
        today=date(2026, 5, 31),
    )

    assert errors == [
        "docs/example.md: documentation review is overdue "
        "(last reviewed 2026-04-30, due 2026-05-30)"
    ]
