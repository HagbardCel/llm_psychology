"""Unit tests for SQLite codec helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from jung.domain.errors import InvariantViolation
from jung.persistence import _sqlite_support as sql


def test_dt_rejects_naive_datetime() -> None:
    with pytest.raises(InvariantViolation, match="timezone-aware"):
        sql.dt(datetime.now())


def test_dt_normalizes_aware_datetime_to_utc_isoformat() -> None:
    source = datetime(2026, 7, 12, 12, tzinfo=timezone(timedelta(hours=2)))
    assert sql.dt(source) == source.astimezone(UTC).isoformat()
