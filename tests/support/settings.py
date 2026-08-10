"""Deterministic JungSettings construction for tests (no ambient env)."""

from __future__ import annotations

from pathlib import Path

from jung.config import JungSettings, LogLevel


def make_test_settings(**overrides: object) -> JungSettings:
    """Build JungSettings with every field explicit so os.environ cannot inject."""
    values: dict[str, object] = {
        "data_dir": Path("./data"),
        "llm_base_url": "http://127.0.0.1:8080/v1",
        "llm_api_key": "",
        "model_name": "local-model",
        "llm_extra_body": None,
        "llm_default_headers": None,
        "llm_task_config": {},
        "shutdown_timeout_seconds": 30.0,
        "enable_llm_tracing": False,
        "debug_run_dir": None,
        "api_host": "127.0.0.1",
        "api_port": 8000,
        "api_log_level": LogLevel.INFO,
        "api_allowed_origins": (),
        "api_allow_remote_bind": False,
        "websocket_send_timeout": 5.0,
        "websocket_close_timeout": 2.0,
    }
    values.update(overrides)
    return JungSettings(_env_file=None, **values)


def settings_for_database(
    database_path: Path | str, **overrides: object
) -> JungSettings:
    """Settings whose database_path matches the given SQLite file path."""
    path = Path(database_path)
    return make_test_settings(data_dir=path.parent, **overrides)
