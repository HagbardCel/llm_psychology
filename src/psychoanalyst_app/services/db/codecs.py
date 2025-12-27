"""Shared datetime codecs for SQLite repositories."""

from __future__ import annotations

from datetime import datetime


def datetime_to_iso(value: datetime) -> str:
    """Serialize datetime to ISO string."""
    return value.isoformat()


def iso_to_datetime(value: str) -> datetime:
    """Deserialize ISO string to datetime."""
    return datetime.fromisoformat(value)

