"""Unit tests for logging configuration defaults and handler wiring."""

import logging

import pytest

from psychoanalyst_app.config import Settings, setup_logging

pytestmark = [pytest.mark.unit]


def test_app_file_logging_defaults_to_disabled() -> None:
    settings = Settings(_env_file=None)
    assert settings.APP_FILE_LOGGING_ENABLED is False
    assert settings.APP_FILE_LOG_PATH == "logs/app.log"


def test_setup_logging_skips_app_file_handler_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        APP_FILE_LOGGING_ENABLED=False,
        LLM_CALL_LOGGING_ENABLED=False,
    )

    setup_logging(settings)

    assert not any(
        isinstance(handler, logging.FileHandler)
        for handler in logging.getLogger().handlers
    )
    assert not (tmp_path / "logs" / "app.log").exists()


def test_setup_logging_creates_app_file_handler_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        APP_FILE_LOGGING_ENABLED=True,
        APP_FILE_LOG_PATH="logs/test_app.log",
        LLM_CALL_LOGGING_ENABLED=False,
    )

    setup_logging(settings)
    logging.getLogger("test_logger").info("hello from app log test")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert (tmp_path / "logs" / "test_app.log").exists()


def test_setup_logging_can_enable_llm_file_without_app_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        APP_FILE_LOGGING_ENABLED=False,
        LLM_CALL_LOGGING_ENABLED=True,
    )

    setup_logging(settings)
    llm_logger = logging.getLogger("llm_calls")
    llm_logger.info("hello from llm logger test")
    for handler in llm_logger.handlers:
        handler.flush()

    assert not (tmp_path / "logs" / "app.log").exists()
    assert (tmp_path / "logs" / "llm_calls.log").exists()
