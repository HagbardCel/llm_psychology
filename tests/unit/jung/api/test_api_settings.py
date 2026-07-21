"""Unit tests for jung.api.settings and CLI startup."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jung.api.settings import (
    ApiSettings,
    load_api_settings,
    validate_api_settings,
    validate_bind_host,
)
from jung.config import build_settings

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
    "JUNG_WS_SEND_TIMEOUT",
    "JUNG_WS_CLOSE_TIMEOUT",
    "JUNG_SHUTDOWN_TIMEOUT",
    "JUNG_EVENT_QUEUE_SIZE",
    "JUNG_ENABLE_LLM_TRACING",
    "JUNG_LOG_PROMPT_PREVIEWS",
    "JUNG_LLM_EXTRA_BODY_JSON",
    "JUNG_LLM_TASK_CONFIG_JSON",
    "JUNG_LLM_DEFAULT_HEADERS_JSON",
)


@pytest.fixture(autouse=True)
def isolate_api_settings_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("jung.api.settings.load_dotenv", lambda: None)
    for name in API_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _settings(
    *,
    host: str = "127.0.0.1",
    allow_remote_bind: bool = False,
    origins: tuple[str, ...] = (),
    port: int = 8000,
    path: Path | None = None,
) -> ApiSettings:
    return ApiSettings(
        application=build_settings(
            database_path=path or Path("data/jung.db"),
            llm_base_url="http://127.0.0.1:8080/v1",
            llm_api_key="",
            default_model="local-model",
        ),
        host=host,
        port=port,
        allow_remote_bind=allow_remote_bind,
        allowed_origins=origins,
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


def test_validate_api_settings_rejects_wildcard_origin() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        validate_api_settings(_settings(origins=("*",)))


def test_validate_api_settings_normalizes_log_level() -> None:
    settings = validate_api_settings(_settings())
    replaced = ApiSettings(
        application=settings.application,
        host=settings.host,
        port=settings.port,
        log_level="INFO",
        allowed_origins=settings.allowed_origins,
        allow_remote_bind=settings.allow_remote_bind,
    )
    assert validate_api_settings(replaced).log_level == "info"


def test_validate_api_settings_normalizes_origins_to_tuple() -> None:
    normalized = validate_api_settings(
        _settings(
            origins=(
                " https://frontend.test ",
                "https://frontend.test",
            )
        )
    )
    assert normalized.allowed_origins == ("https://frontend.test",)
    assert isinstance(normalized.allowed_origins, tuple)
    assert validate_api_settings(normalized) == normalized


def test_validate_api_settings_rejects_bad_port() -> None:
    with pytest.raises(ValueError, match="port"):
        validate_api_settings(_settings(port=0))


@pytest.mark.parametrize(
    ("changes", "expected_name"),
    [
        ({"port": True}, "port"),
        ({"port": 8000.5}, "port"),
        ({"websocket_send_timeout": True}, "websocket_send_timeout"),
        ({"websocket_send_timeout": 10**400}, "websocket_send_timeout"),
    ],
)
def test_validate_api_settings_rejects_invalid_direct_values(
    changes: dict[str, object],
    expected_name: str,
) -> None:
    settings = replace(_settings(), **changes)

    with pytest.raises(ValueError, match=expected_name):
        validate_api_settings(settings)


def test_cli_passes_fastapi_app_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    from jung.api import app as app_module

    captured: dict[str, object] = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("jung.api.settings.load_api_settings", lambda: _settings())

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


@pytest.mark.parametrize(
    "log_level",
    ["info", "debug", "trace"],
)
def test_uvicorn_log_config_configures_jung_logger(
    log_level: str,
) -> None:
    from uvicorn.config import LOG_LEVELS, LOGGING_CONFIG

    from jung.api.app import _uvicorn_log_config_with_jung

    expected_level = LOG_LEVELS[log_level]

    config = _uvicorn_log_config_with_jung(log_level)

    assert config["loggers"]["jung"] == {
        "handlers": ["default"],
        "level": expected_level,
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
        "jung.api.settings.load_api_settings",
        lambda: _settings(host="192.168.0.5"),
    )

    with pytest.raises(ValueError, match="loopback"):
        app_module.cli()

    run.assert_not_called()


def test_load_api_settings_uses_jung_data_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JUNG_DATA_DIR", str(tmp_path))
    settings = load_api_settings()
    assert settings.application.database_path == tmp_path / "jung.db"


def test_load_api_settings_delegates_composition_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JUNG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JUNG_EVENT_QUEUE_SIZE", "96")
    monkeypatch.setenv("JUNG_SHUTDOWN_TIMEOUT", "42")
    settings = load_api_settings()
    assert settings.application.event_queue_size == 96
    assert settings.application.shutdown_timeout_seconds == 42.0


def test_api_settings_websocket_timeout_defaults() -> None:
    settings = _settings()
    assert settings.websocket_send_timeout == 5.0
    assert settings.websocket_close_timeout == 2.0


def test_validate_api_settings_rejects_non_positive_websocket_timeouts() -> None:
    base = _settings()
    with pytest.raises(ValueError, match="websocket_send_timeout"):
        validate_api_settings(
            ApiSettings(
                application=base.application,
                websocket_send_timeout=0,
            )
        )
    with pytest.raises(ValueError, match="websocket_close_timeout"):
        validate_api_settings(
            ApiSettings(
                application=base.application,
                websocket_close_timeout=-1,
            )
        )


def test_load_api_settings_websocket_timeout_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JUNG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JUNG_WS_SEND_TIMEOUT", "12.5")
    monkeypatch.setenv("JUNG_WS_CLOSE_TIMEOUT", "3")
    settings = load_api_settings()
    assert settings.websocket_send_timeout == 12.5
    assert settings.websocket_close_timeout == 3.0


@pytest.mark.parametrize(
    "env_name",
    ["JUNG_WS_SEND_TIMEOUT", "JUNG_WS_CLOSE_TIMEOUT"],
)
@pytest.mark.parametrize(
    "env_value",
    ["nan", "inf", "+inf", "-inf"],
)
def test_load_api_settings_rejects_non_finite_ws_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_name: str,
    env_value: str,
) -> None:
    monkeypatch.setenv("JUNG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(env_name, env_value)
    with pytest.raises(ValueError, match=env_name):
        load_api_settings()


def test_load_api_settings_rejects_malformed_websocket_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JUNG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JUNG_WS_SEND_TIMEOUT", "not-a-float")
    with pytest.raises(ValueError, match="JUNG_WS_SEND_TIMEOUT"):
        load_api_settings()


@pytest.mark.parametrize(
    "timeout_value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_validate_api_settings_rejects_non_finite_websocket_timeouts(
    timeout_value: float,
) -> None:
    base = _settings()
    with pytest.raises(ValueError, match="websocket_send_timeout"):
        validate_api_settings(
            ApiSettings(
                application=base.application,
                websocket_send_timeout=timeout_value,
            )
        )
    with pytest.raises(ValueError, match="websocket_close_timeout"):
        validate_api_settings(
            ApiSettings(
                application=base.application,
                websocket_close_timeout=timeout_value,
            )
        )
