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


def _metadata(last_reviewed: str, cycle: str = "30") -> dict[str, str]:
    return {
        "last_reviewed": last_reviewed,
        "review_cycle_days": cycle,
    }


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
