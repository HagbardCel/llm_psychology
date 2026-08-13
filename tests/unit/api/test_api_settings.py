"""Unit tests for API bind safety and settings loading."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from jung.config import JungSettings, validate_bind_host
from tests.support.settings import make_test_settings

API_ENV_NAMES = (
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "MODEL_NAME",
    "JUNG_DATA_DIR",
    "JUNG_API_HOST",
    "JUNG_API_PORT",
    "JUNG_API_LOG_LEVEL",
    "JUNG_API_ALLOWED_ORIGINS",
    "JUNG_API_ALLOW_REMOTE_BIND",
    "JUNG_SHUTDOWN_TIMEOUT",
    "JUNG_ENABLE_LLM_TRACING",
    "JUNG_DEBUG_RUN_DIR",
    "JUNG_LLM_EXTRA_BODY_JSON",
    "JUNG_LLM_TASK_CONFIG_JSON",
    "JUNG_LLM_DEFAULT_HEADERS_JSON",
    "JUNG_SUPERVISOR_LLM_BASE_URL",
    "JUNG_SUPERVISOR_MODEL_NAME",
    "JUNG_SUPERVISOR_LLM_API_KEY",
    "JUNG_SUPERVISOR_LLM_EXTRA_BODY_JSON",
    "JUNG_SUPERVISOR_LLM_DEFAULT_HEADERS_JSON",
)


@pytest.fixture(autouse=True)
def isolate_settings_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in API_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _settings(
    *,
    host: str = "127.0.0.1",
    allow_remote_bind: bool = False,
    origins: tuple[str, ...] = (),
    port: int = 8000,
    data_dir: Path | None = None,
) -> JungSettings:
    return make_test_settings(
        data_dir=data_dir or Path("data"),
        api_host=host,
        api_port=port,
        api_allow_remote_bind=allow_remote_bind,
        api_allowed_origins=origins,
    )


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "127.0.0.2", "::1"],
)
def test_validate_bind_host_allows_loopback(host: str) -> None:
    validate_bind_host(_settings(host=host))


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "192.168.1.10"],
)
def test_validate_bind_host_rejects_remote_without_override(host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        validate_bind_host(_settings(host=host))


def test_validate_bind_host_allows_remote_with_override() -> None:
    validate_bind_host(_settings(host="0.0.0.0", allow_remote_bind=True))


def test_wildcard_origin_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        _settings(origins=("*",))


def test_log_level_normalized() -> None:
    settings = make_test_settings(api_log_level=" INFO ")
    assert settings.api_log_level.value == "info"


def test_origins_deduplicated() -> None:
    settings = make_test_settings(
        api_allowed_origins=(
            " https://frontend.test ",
            "https://frontend.test",
        ),
    )
    assert settings.api_allowed_origins == ("https://frontend.test",)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_port": 0},
        {"api_port": 65536},
        {"api_port": True},
    ],
)
def test_rejects_invalid_api_scalars(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_test_settings(**kwargs)


def test_cli_passes_fastapi_app_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    from jung.api import app as app_module

    captured: dict[str, object] = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("jung.api.app.load_settings", lambda: _settings())

    app_module.cli()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["log_level"] == "info"
    assert captured["access_log"] is False
    jung_logger = captured["log_config"]["loggers"]["jung"]
    assert jung_logger == {
        "handlers": ["default"],
        "level": logging.INFO,
        "propagate": False,
    }
    assert type(captured["app"]).__name__ == "FastAPI"


def test_uvicorn_log_config_configures_jung_logger() -> None:
    from uvicorn.config import LOG_LEVELS, LOGGING_CONFIG

    from jung.api.app import _uvicorn_log_config_with_jung

    config = _uvicorn_log_config_with_jung("info")

    assert config["loggers"]["jung"] == {
        "handlers": ["default"],
        "level": LOG_LEVELS["info"],
        "propagate": False,
    }
    assert "jung" not in LOGGING_CONFIG["loggers"]


def test_cli_rejects_remote_bind_before_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jung.api import app as app_module

    run = MagicMock()
    monkeypatch.setattr("uvicorn.run", run)
    monkeypatch.setattr(
        "jung.api.app.load_settings",
        lambda: _settings(host="192.168.0.5"),
    )

    with pytest.raises(ValueError, match="loopback"):
        app_module.cli()

    run.assert_not_called()


def test_load_settings_uses_jung_data_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JUNG_DATA_DIR", str(tmp_path))
    settings = JungSettings(_env_file=None)
    assert settings.database_path == tmp_path / "jung.db"


def test_load_settings_delegates_composition_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JUNG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JUNG_SHUTDOWN_TIMEOUT", "42")
    settings = JungSettings(_env_file=None)
    assert settings.shutdown_timeout_seconds == 42.0
