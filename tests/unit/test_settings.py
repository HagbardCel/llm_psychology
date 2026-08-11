"""Unit tests for JungSettings configuration contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jung.config import JungSettings, LogLevel, load_settings
from jung.llm.gateway import LLMTask, StructuredOutputMode
from jung.llm.policies import TaskOverride, build_model_policies
from tests.support.settings import make_test_settings

ALL_ENV_NAMES = (
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
)


@pytest.fixture
def clear_jung_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ALL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_settings_defaults(clear_jung_env: Path) -> None:
    settings = JungSettings(_env_file=None)
    assert settings.data_dir == Path("./data")
    assert settings.database_path == Path("./data") / "jung.db"
    assert settings.model_name == "local-model"
    assert settings.llm_base_url == "http://127.0.0.1:8080/v1"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.api_log_level is LogLevel.INFO
    assert settings.shutdown_timeout_seconds == 30.0
    assert settings.enable_llm_tracing is False
    assert settings.debug_run_dir is None
    assert settings.llm_extra_body is None
    assert settings.llm_default_headers is None
    assert settings.llm_task_config == {}


def test_full_override_load() -> None:
    settings = make_test_settings(
        data_dir=Path("/tmp/jung-data"),
        llm_base_url="http://example.test/v1",
        llm_api_key="  secret  ",
        model_name="custom-model",
        api_host="127.0.0.1",
        api_port=9000,
        enable_llm_tracing=True,
        debug_run_dir=Path("/tmp/debug"),
        llm_extra_body={"global": True},
        llm_default_headers={"X-Test": "1"},
        llm_task_config=json.dumps(
            {
                "assessment": {
                    "model": "  assess-model  ",
                    "temperature": 0.2,
                    "timeout_seconds": 90,
                    "max_completion_tokens": 4096,
                    "structured_output_mode": "json_object",
                }
            }
        ),
    )
    assert settings.database_path == Path("/tmp/jung-data/jung.db")
    assert settings.llm_api_key == "  secret  "
    assert settings.model_name == "custom-model"
    assert settings.llm_base_url == "http://example.test/v1"
    assert settings.api_port == 9000
    assert settings.enable_llm_tracing is True
    assert settings.llm_extra_body == {"global": True}
    assert settings.llm_default_headers == {"X-Test": "1"}
    override = settings.llm_task_config[LLMTask.ASSESSMENT]
    assert override.model == "assess-model"
    assert override.temperature == 0.2
    policies = build_model_policies(
        default_model=settings.model_name,
        task_overrides=settings.llm_task_config,
    )
    assert policies[LLMTask.ASSESSMENT].model == "assess-model"
    assert (
        policies[LLMTask.ASSESSMENT].structured_output_mode
        is StructuredOutputMode.JSON_OBJECT
    )


def test_llm_api_key_is_not_stripped() -> None:
    settings = make_test_settings(llm_api_key="  secret  ")
    assert settings.llm_api_key == "  secret  "


def test_typed_task_override_mapping_accepted() -> None:
    settings = make_test_settings(
        llm_task_config={LLMTask.ASSESSMENT: TaskOverride(temperature=0.2)},
    )
    assert settings.llm_task_config[LLMTask.ASSESSMENT].temperature == 0.2


def test_boolean_timeout_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(shutdown_timeout_seconds=True)


def test_blank_optional_json_treated_as_unset() -> None:
    settings = make_test_settings(
        llm_extra_body="   ",
        llm_task_config="",
    )
    assert settings.llm_extra_body is None
    assert settings.llm_task_config == {}


def test_extra_body_null_json_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(llm_extra_body="null")


def test_nested_null_allowed_inside_extra_body() -> None:
    settings = make_test_settings(
        llm_extra_body=json.dumps({"some_provider_option": None}),
    )
    assert settings.llm_extra_body == {"some_provider_option": None}


def test_streaming_task_rejects_non_prompt_structured_mode() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(
            llm_task_config=json.dumps(
                {"therapy_response": {"structured_output_mode": "json_schema"}}
            ),
        )


def test_typed_null_task_field_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(
            llm_task_config=json.dumps({"assessment": {"model": None}}),
        )


def test_boolean_numeric_override_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(
            llm_task_config=json.dumps({"assessment": {"temperature": True}}),
        )


def test_numeric_string_temperature_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(
            llm_task_config=json.dumps({"assessment": {"temperature": "0.2"}}),
        )


def test_unknown_task_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(llm_task_config=json.dumps({"not_a_task": {}}))


def test_unknown_task_field_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(
            llm_task_config=json.dumps({"assessment": {"not_a_field": 1}}),
        )


def test_blank_model_name_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(model_name="   ")


def test_invalid_port_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(api_port=0)


def test_non_positive_timeout_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(shutdown_timeout_seconds=0)


def test_invalid_log_level_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(api_log_level="verbose")


def test_wildcard_cors_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(api_allowed_origins="*")


def test_cors_comma_separated_normalized() -> None:
    settings = make_test_settings(
        api_allowed_origins=" https://a.test , https://a.test,https://b.test ",
    )
    assert settings.api_allowed_origins == ("https://a.test", "https://b.test")


def test_header_non_string_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(
            llm_default_headers=json.dumps({"Authorization": 123}),
        )


def test_header_error_does_not_leak_secret() -> None:
    secret = "super-secret-header-value"
    with pytest.raises(ValidationError) as exc_info:
        make_test_settings(
            llm_default_headers=json.dumps({"Authorization": {"token": secret}}),
        )
    assert secret not in str(exc_info.value)


def test_extra_body_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(llm_extra_body='{"scale": NaN}')


def test_blank_data_dir_falls_back(clear_jung_env: Path) -> None:
    settings = make_test_settings(data_dir="   ")
    assert settings.data_dir == Path("./data")


def test_load_settings_reads_environ(
    clear_jung_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_NAME", "from-env")
    monkeypatch.setenv("JUNG_DATA_DIR", str(clear_jung_env))
    settings = JungSettings(_env_file=None)
    assert settings.model_name == "from-env"
    assert settings.database_path == clear_jung_env / "jung.db"


def test_dotenv_ignores_unrelated_entries(
    clear_jung_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = clear_jung_env / ".env"
    env_file.write_text(
        "LOCAL_LLM_SMOKE_MODEL=should-ignore\n"
        "OPENAI_API_KEY=should-ignore\n"
        "MODEL_NAME=from-dotenv\n",
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.model_name == "from-dotenv"


def test_task_extra_body_and_global_extra_body() -> None:
    settings = make_test_settings(
        llm_extra_body=json.dumps({"global_flag": True}),
        llm_task_config=json.dumps(
            {
                "therapy_response": {
                    "extra_body": {"task_flag": False},
                }
            }
        ),
    )
    assert settings.llm_extra_body == {"global_flag": True}
    assert settings.llm_task_config[LLMTask.THERAPY_RESPONSE].extra_body == {
        "task_flag": False
    }
