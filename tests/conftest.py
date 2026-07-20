"""Root pytest hooks shared by the supported Jung test suite."""

from __future__ import annotations

import pytest


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--no-mocks",
        action="store_true",
        default=False,
        help="Run tests with real LLM services (no mocks)",
    )


def pytest_collection_modifyitems(config, items):
    """
    Ensure `-m unit` / `-m integration` selections are reliable.

    Many tests live under `tests/unit/` and `tests/integration/` but are not
    explicitly decorated. We auto-mark based on path unless a test already has
    an explicit `unit` or `integration` marker.
    """

    def _has_marker(item, name: str) -> bool:
        return item.get_closest_marker(name) is not None

    for item in items:
        path = str(getattr(item, "fspath", "")).replace("\\", "/")

        if "/tests/unit/" in path:
            if not _has_marker(item, "unit") and not _has_marker(item, "integration"):
                item.add_marker(pytest.mark.unit)
            continue

        if "/tests/integration/" in path:
            if not _has_marker(item, "unit") and not _has_marker(item, "integration"):
                item.add_marker(pytest.mark.integration)

    if not config.getoption("--no-mocks"):
        skip_reason = "Real LLM tests require --no-mocks to hit live services."
        for item in items:
            if item.get_closest_marker("real_llm"):
                item.add_marker(pytest.mark.skip(reason=skip_reason))
