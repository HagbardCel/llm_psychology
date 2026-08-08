"""Unit tests for target domain models."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jung.domain.models import (
    AppState,
    Message,
    MessageRole,
    Plan,
    Profile,
    Stage,
    is_profile_complete,
)


def test_is_profile_complete_requires_name_and_language():
    assert is_profile_complete(Profile(name="Alex", primary_language="English")) is True
    assert (
        is_profile_complete(Profile(name="Guest", primary_language="English")) is True
    )
    assert is_profile_complete(Profile(name="  ", primary_language="English")) is False
    assert is_profile_complete(Profile(name="Alex", primary_language="  ")) is False


def test_plan_requires_non_empty_focus_and_progress():
    with pytest.raises(ValidationError):
        Plan(
            id=uuid4(),
            version=1,
            selected_style="cbt",
            focus="",
            themes=[],
            goals=[],
            current_progress="progress",
            planned_interventions=[],
            revision_recommendations=[],
            created_at=datetime.now(UTC),
        )


def test_plan_version_must_be_at_least_one():
    with pytest.raises(ValidationError):
        Plan(
            id=uuid4(),
            version=0,
            selected_style="cbt",
            focus="anxiety",
            themes=[],
            goals=[],
            current_progress="progress",
            planned_interventions=[],
            revision_recommendations=[],
            created_at=datetime.now(UTC),
        )


def test_message_sequence_must_be_positive():
    with pytest.raises(ValidationError):
        Message(
            id=uuid4(),
            session_id=uuid4(),
            sequence=0,
            role=MessageRole.USER,
            content="hi",
            created_at=datetime.now(UTC),
        )


def test_profile_optional_fields():
    profile = Profile(
        name="Alex",
        primary_language="de",
        date_of_birth=date(1990, 1, 2),
        notes="note",
    )
    assert profile.date_of_birth == date(1990, 1, 2)
    assert profile.notes == "note"


def test_domain_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        AppState(
            stage=Stage.SETUP,
            revision=0,
            created_at=datetime.now(),
            updated_at=datetime.now(UTC),
        )


def test_domain_timestamp_normalizes_offset_to_utc() -> None:
    source = datetime(2026, 7, 12, 12, tzinfo=timezone(timedelta(hours=2)))
    state = AppState(
        stage=Stage.SETUP,
        revision=0,
        created_at=source,
        updated_at=source,
    )
    assert state.created_at.utcoffset() == timedelta(0)
