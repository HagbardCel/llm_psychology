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


@pytest.mark.parametrize(
    ("targets_factory", "expect_error_substring"),
    [
        (lambda paths: paths, None),
        (lambda paths: paths[:-1], "workflow-specification.md"),
        (
            lambda paths: [paths[0], "ARCHITECTURE.md", *paths[1:]],
            "ARCHITECTURE.md",
        ),
    ],
)
def test_active_readme_index_consistency(
    tmp_path: Path,
    targets_factory,
    expect_error_substring: str | None,
) -> None:
    _write_active_index(tmp_path, targets_factory(_expected_active_targets()))
    errors: list[str] = []

    _validate_active_readme_index(tmp_path, errors)

    if expect_error_substring is None:
        assert errors == []
    else:
        assert len(errors) == 1
        assert expect_error_substring in errors[0]


@pytest.mark.parametrize(
    ("last_reviewed", "today", "expect_error"),
    [
        ("2026-05-15", date(2026, 5, 31), False),
        ("2026-05-01", date(2026, 5, 31), False),
        ("2026-04-30", date(2026, 5, 31), True),
    ],
)
def test_review_freshness(
    last_reviewed: str,
    today: date,
    expect_error: bool,
) -> None:
    errors: list[str] = []

    _validate_review_freshness(
        "docs/example.md",
        _metadata(last_reviewed),
        errors,
        today=today,
    )

    if expect_error:
        assert errors == [
            "docs/example.md: documentation review is overdue "
            "(last reviewed 2026-04-30, due 2026-05-30)"
        ]
    else:
        assert errors == []


def test_markdown_link_extraction_excludes_code_fences() -> None:
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
            "See [inline](inline-target.md) and ![image](images/pic.png).",
            "Reference usage: [ref link][ref-label].",
            "",
            "[ref-label]: reference-target.md",
        ]
    )

    stripped = _strip_code(text)
    assert "fenced-target.md" in stripped
    assert "real-target.md" in stripped
    assert "inside-fence.md" not in stripped
    assert "inline-code.md" not in stripped
    assert "tilde-fence.md" not in stripped

    targets = _extract_link_targets(stripped)
    assert "real-target.md" in targets
    assert "inline-target.md" in targets
    assert "images/pic.png" in targets
    assert "reference-target.md" in targets
    assert "inside-fence.md" not in targets


@pytest.mark.parametrize(
    ("docs_layout", "expect_error_substring"),
    [
        (
            {
                "target.md": "# Target\n",
                "index.md": (
                    "See [target](target.md#section) and [external](https://example.com).\n"
                    "Ignore code: `[fake](missing.md)`.\n\n"
                    "```text\n[also fake](missing-too.md)\n```\n"
                ),
            },
            None,
        ),
        (
            {"index.md": "See [missing](does-not-exist.md).\n"},
            "does-not-exist.md",
        ),
        (
            {
                "sibling.md": "# Sibling\n",
                "refactor/nested.md": "Back up: [sibling](../sibling.md).\n",
            },
            None,
        ),
    ],
)
def test_local_link_resolution(
    tmp_path: Path,
    docs_layout: dict[str, str],
    expect_error_substring: str | None,
) -> None:
    docs = tmp_path / "docs"
    for relative, content in docs_layout.items():
        path = docs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    errors: list[str] = []
    _validate_local_links(tmp_path, errors)

    if expect_error_substring is None:
        assert errors == []
    else:
        assert len(errors) == 1
        assert expect_error_substring in errors[0]
