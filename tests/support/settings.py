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
        "supervisor_llm_base_url": None,
        "supervisor_model_name": None,
        "supervisor_llm_api_key": None,
        "supervisor_llm_extra_body": None,
        "supervisor_llm_default_headers": None,
        "shutdown_timeout_seconds": 30.0,
        "enable_llm_tracing": False,
        "debug_run_dir": None,
        "api_host": "127.0.0.1",
        "api_port": 8000,
        "api_log_level": LogLevel.INFO,
        "api_allowed_origins": (),
        "api_allow_remote_bind": False,
    }
    values.update(overrides)
    return JungSettings(_env_file=None, **values)


def settings_for_database(
    database_path: Path | str, **overrides: object
) -> JungSettings:
    """Build settings for a product database path whose filename must be jung.db."""
    path = Path(database_path)
    if path.name != "jung.db":
        raise ValueError(
            "settings_for_database requires the fixed product database "
            "filename 'jung.db'"
        )
    return make_test_settings(data_dir=path.parent, **overrides)
