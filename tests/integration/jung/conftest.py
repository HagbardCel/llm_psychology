"""Shared fixtures for jung persistence integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from jung.persistence.sqlite_store import SQLiteStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "jung-test.db"


@pytest.fixture
def store(store_path: Path) -> Iterator[SQLiteStore]:
    instance = SQLiteStore(store_path)
    instance.initialize()
    yield instance
