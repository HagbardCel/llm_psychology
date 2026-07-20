"""Tests for documentation metadata review cadence validation."""

from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/validate_docs_metadata.py"
SPEC = spec_from_file_location("validate_docs_metadata", SCRIPT_PATH)
assert SPEC and SPEC.loader
VALIDATOR = module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
_validate_review_freshness = VALIDATOR._validate_review_freshness
_validate_active_readme_index = VALIDATOR._validate_active_readme_index
_validate_local_links = VALIDATOR._validate_local_links
_strip_code = VALIDATOR._strip_code
_extract_link_targets = VALIDATOR._extract_link_targets
_normalize_link_target = VALIDATOR._normalize_link_target


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


@pytest.mark.parametrize(
    ("targets_factory", "expected"),
    [
        (lambda paths: paths[:-1], "workflow-specification.md"),
        (
            lambda paths: [paths[0], "ARCHITECTURE.md", *paths[1:]],
            "ARCHITECTURE.md",
        ),
        (
            lambda paths: [paths[0], paths[0], *paths[1:]],
            "README.md",
        ),
    ],
)
def test_active_index_rejects_noncanonical_targets(
    tmp_path: Path,
    targets_factory,
    expected: str,
) -> None:
    targets = targets_factory(_expected_active_targets())
    _write_active_index(tmp_path, targets)
    errors: list[str] = []

    _validate_active_readme_index(tmp_path, errors)

    assert len(errors) == 1
    assert expected in errors[0]


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


def test_strip_code_blanks_fenced_blocks_and_inline_spans() -> None:
    text = "\n".join(
        [
            "Before [fake](fenced-target.md) text.",
            "```python",
            "[not a link](inside-fence.md)",
            "```",
            "After `[not a link](inline-code.md)` text.",
            "~~~text",
            "[also fenced](tilde-fence.md)",
            "~~~",
            "Real [link](real-target.md) remains.",
        ]
    )

    stripped = _strip_code(text)

    assert "fenced-target.md" in stripped
    assert "real-target.md" in stripped
    assert "inside-fence.md" not in stripped
    assert "inline-code.md" not in stripped
    assert "tilde-fence.md" not in stripped


def test_extract_link_targets_supports_inline_and_reference_style() -> None:
    text = "\n".join(
        [
            "See [inline](inline-target.md) and ![image](images/pic.png).",
            "Angle bracket: [angled](<a target.md>).",
            "Reference usage: [ref link][ref-label].",
            "",
            "[ref-label]: reference-target.md",
        ]
    )

    targets = _extract_link_targets(text)

    assert "inline-target.md" in targets
    assert "images/pic.png" in targets
    assert "<a target.md>" in targets
    assert "reference-target.md" in targets


@pytest.mark.parametrize(
    ("raw_target", "expected"),
    [
        ("docs/page.md", "docs/page.md"),
        ("docs/page.md#section", "docs/page.md"),
        ("docs/page.md?raw=true", "docs/page.md"),
        ("<a target.md>", "a target.md"),
        ("#local-anchor", None),
        ("https://example.com/page.md", None),
        ("http://example.com", None),
        ("mailto:someone@example.com", None),
        ("", None),
    ],
)
def test_normalize_link_target(raw_target: str, expected: str | None) -> None:
    assert _normalize_link_target(raw_target) == expected


def test_validate_local_links_accepts_resolvable_targets(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# Target\n", encoding="utf-8")
    (docs / "index.md").write_text(
        "\n".join(
            [
                "See [target](target.md#section) and [external](https://example.com).",
                "Ignore code: `[fake](missing.md)`.",
                "",
                "```text",
                "[also fake](missing-too.md)",
                "```",
            ]
        ),
        encoding="utf-8",
    )
    errors: list[str] = []

    _validate_local_links(tmp_path, errors)

    assert errors == []


def test_validate_local_links_reports_source_and_unresolved_target(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text(
        "See [missing](does-not-exist.md).\n",
        encoding="utf-8",
    )
    errors: list[str] = []

    _validate_local_links(tmp_path, errors)

    assert len(errors) == 1
    assert "docs/index.md" in errors[0]
    assert "does-not-exist.md" in errors[0]


def test_validate_local_links_checks_image_targets(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text(
        "![diagram](missing-image.png)\n",
        encoding="utf-8",
    )
    errors: list[str] = []

    _validate_local_links(tmp_path, errors)

    assert len(errors) == 1
    assert "missing-image.png" in errors[0]


def test_validate_local_links_resolves_relative_to_containing_document(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    refactor = docs / "refactor"
    refactor.mkdir(parents=True)
    (docs / "sibling.md").write_text("# Sibling\n", encoding="utf-8")
    (refactor / "nested.md").write_text(
        "Back up: [sibling](../sibling.md).\n",
        encoding="utf-8",
    )
    errors: list[str] = []

    _validate_local_links(tmp_path, errors)

    assert errors == []
