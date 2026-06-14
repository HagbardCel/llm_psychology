"""Unit tests for intake note-tracking feature flag validation."""

import pytest
from pydantic import ValidationError

from psychoanalyst_app.config import Settings

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def clear_intake_flag_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "INTAKE_NOTE_TRACKING_ENABLED",
        "INTAKE_RECORD_COMPLETION_GATE_ENABLED",
        "INTAKE_NOTE_TRACKING_STRICT_QUOTE_VALIDATION",
        "INTAKE_RECORD_DIRECT_ASK_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_intake_flag_defaults_are_valid() -> None:
    settings = Settings(_env_file=None)
    assert settings.INTAKE_NOTE_TRACKING_ENABLED is False
    assert settings.INTAKE_RECORD_COMPLETION_GATE_ENABLED is False
    assert settings.INTAKE_RECORD_DIRECT_ASK_ENABLED is False
    assert settings.INTAKE_NOTE_TRACKING_STRICT_QUOTE_VALIDATION is True


def test_note_tracking_enabled_alone_is_valid() -> None:
    settings = Settings(_env_file=None, INTAKE_NOTE_TRACKING_ENABLED=True)
    assert settings.INTAKE_NOTE_TRACKING_ENABLED is True


def test_note_tracking_with_direct_ask_is_valid() -> None:
    settings = Settings(
        _env_file=None,
        INTAKE_NOTE_TRACKING_ENABLED=True,
        INTAKE_RECORD_DIRECT_ASK_ENABLED=True,
    )
    assert settings.INTAKE_RECORD_DIRECT_ASK_ENABLED is True


def test_note_tracking_with_direct_ask_and_gate_is_valid() -> None:
    settings = Settings(
        _env_file=None,
        INTAKE_NOTE_TRACKING_ENABLED=True,
        INTAKE_RECORD_DIRECT_ASK_ENABLED=True,
        INTAKE_RECORD_COMPLETION_GATE_ENABLED=True,
    )
    assert settings.INTAKE_RECORD_COMPLETION_GATE_ENABLED is True


def test_strict_quote_validation_without_note_tracking_is_valid() -> None:
    settings = Settings(
        _env_file=None,
        INTAKE_NOTE_TRACKING_ENABLED=False,
        INTAKE_NOTE_TRACKING_STRICT_QUOTE_VALIDATION=True,
    )
    assert settings.INTAKE_NOTE_TRACKING_STRICT_QUOTE_VALIDATION is True


def test_completion_gate_without_note_tracking_raises() -> None:
    with pytest.raises(ValidationError, match="Invalid intake note-tracking flag combination"):
        Settings(
            _env_file=None,
            INTAKE_RECORD_COMPLETION_GATE_ENABLED=True,
        )


def test_direct_ask_without_note_tracking_raises() -> None:
    with pytest.raises(ValidationError, match="Invalid intake note-tracking flag combination"):
        Settings(
            _env_file=None,
            INTAKE_RECORD_DIRECT_ASK_ENABLED=True,
        )


def test_completion_gate_without_direct_ask_raises() -> None:
    with pytest.raises(ValidationError, match="Invalid intake note-tracking flag combination"):
        Settings(
            _env_file=None,
            INTAKE_NOTE_TRACKING_ENABLED=True,
            INTAKE_RECORD_COMPLETION_GATE_ENABLED=True,
            INTAKE_RECORD_DIRECT_ASK_ENABLED=False,
        )


def test_multiple_flag_violations_reported_together() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            INTAKE_RECORD_COMPLETION_GATE_ENABLED=True,
            INTAKE_NOTE_TRACKING_ENABLED=False,
            INTAKE_RECORD_DIRECT_ASK_ENABLED=False,
        )

    message = str(exc_info.value)
    assert (
        "INTAKE_RECORD_COMPLETION_GATE_ENABLED requires "
        "INTAKE_NOTE_TRACKING_ENABLED=true"
    ) in message
    assert (
        "INTAKE_RECORD_COMPLETION_GATE_ENABLED requires "
        "INTAKE_RECORD_DIRECT_ASK_ENABLED=true"
    ) in message
