"""Unit tests for composition settings loading."""

from __future__ import annotations

import json
import sys

import pytest

from jung._env import parse_optional_json_object
from jung.config import ApplicationSettings, load_application_settings
from jung.llm.gateway import LLMSettings, LLMTask, StructuredOutputMode
from jung.llm.policies import build_model_policies


def _valid_llm() -> LLMSettings:
    return LLMSettings(
        default_model="local-model",
        base_url="http://127.0.0.1:8080/v1",
        api_key="",
    )


def test_load_application_settings_defaults() -> None:
    settings = load_application_settings({}, database_path="data/jung.db")
    assert settings.database_path == "data/jung.db"
    assert settings.llm.default_model == "local-model"
    assert settings.llm.base_url == "http://127.0.0.1:8080/v1"
    assert settings.shutdown_timeout_seconds == 30.0
    assert settings.event_queue_size == 64
    assert settings.enable_llm_tracing is False
    assert settings.log_prompt_previews is False
    assert settings.llm.extra_body is None
    assert settings.llm.task_extra_body is None
    assert settings.llm.default_headers is None


def test_load_application_settings_scalar_overrides() -> None:
    settings = load_application_settings(
        {
            "JUNG_SHUTDOWN_TIMEOUT": "45",
            "JUNG_EVENT_QUEUE_SIZE": "128",
            "JUNG_ENABLE_LLM_TRACING": "true",
            "JUNG_LOG_PROMPT_PREVIEWS": "true",
        },
        database_path="data/jung.db",
    )
    assert settings.shutdown_timeout_seconds == 45.0
    assert settings.event_queue_size == 128
    assert settings.enable_llm_tracing is True
    assert settings.log_prompt_previews is True


@pytest.mark.parametrize(
    ("env_name", "env_value", "default"),
    [
        ("JUNG_ENABLE_LLM_TRACING", None, False),
        ("JUNG_SHUTDOWN_TIMEOUT", None, 30.0),
        ("JUNG_EVENT_QUEUE_SIZE", None, 64),
    ],
)
def test_absent_scalar_uses_default(
    env_name: str,
    env_value: str | None,
    default: object,
) -> None:
    environ: dict[str, str] = {}
    if env_value is not None:
        environ[env_name] = env_value
    settings = load_application_settings(environ, database_path="data/jung.db")
    if env_name == "JUNG_ENABLE_LLM_TRACING":
        assert settings.enable_llm_tracing is default
    elif env_name == "JUNG_SHUTDOWN_TIMEOUT":
        assert settings.shutdown_timeout_seconds == default
    else:
        assert settings.event_queue_size == default


@pytest.mark.parametrize(
    "env_name",
    ["JUNG_ENABLE_LLM_TRACING", "JUNG_SHUTDOWN_TIMEOUT", "JUNG_EVENT_QUEUE_SIZE"],
)
def test_blank_scalar_raises(env_name: str) -> None:
    with pytest.raises(ValueError, match=env_name):
        load_application_settings({env_name: "   "}, database_path="data/jung.db")


def test_required_strings_are_trimmed() -> None:
    settings = load_application_settings(
        {
            "LLM_BASE_URL": "  http://example.test/v1  ",
            "MODEL_NAME": "  custom-model  ",
            "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                {"assessment": {"model": "  assess-model  "}}
            ),
        },
        database_path="data/jung.db",
    )
    assert settings.llm.base_url == "http://example.test/v1"
    assert settings.llm.default_model == "custom-model"
    assert settings.llm.task_models is not None
    assert settings.llm.task_models[LLMTask.ASSESSMENT] == "assess-model"


def test_llm_api_key_is_not_stripped() -> None:
    settings = load_application_settings(
        {"LLM_API_KEY": "  secret  "},
        database_path="data/jung.db",
    )
    assert settings.llm.api_key == "  secret  "


def test_extra_body_parsed_separately_from_task_extra_body() -> None:
    settings = load_application_settings(
        {
            "JUNG_LLM_EXTRA_BODY_JSON": json.dumps(
                {
                    "chat_template_kwargs": {
                        "enable_thinking": True,
                        "reasoning_budget": 1024,
                    }
                }
            ),
            "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                {
                    "therapy_response": {
                        "extra_body": {
                            "chat_template_kwargs": {
                                "enable_thinking": False,
                            }
                        }
                    }
                }
            ),
        },
        database_path="data/jung.db",
    )
    assert settings.llm.extra_body == {
        "chat_template_kwargs": {
            "enable_thinking": True,
            "reasoning_budget": 1024,
        }
    }
    assert settings.llm.task_extra_body == {
        LLMTask.THERAPY_RESPONSE: {
            "chat_template_kwargs": {
                "enable_thinking": False,
            }
        }
    }


def test_nested_null_allowed_inside_extra_body() -> None:
    settings = load_application_settings(
        {
            "JUNG_LLM_EXTRA_BODY_JSON": json.dumps(
                {"some_provider_option": None},
            ),
        },
        database_path="data/jung.db",
    )
    assert settings.llm.extra_body == {"some_provider_option": None}


def test_task_config_builds_model_policies() -> None:
    settings = load_application_settings(
        {
            "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                {
                    "assessment": {
                        "model": "assess-model",
                        "structured_output_mode": "json_object",
                        "max_completion_tokens": 4096,
                        "temperature": 0.2,
                        "timeout_seconds": 90,
                    }
                }
            ),
        },
        database_path="data/jung.db",
    )
    policies = build_model_policies(settings.llm)
    policy = policies[LLMTask.ASSESSMENT]
    assert policy.model == "assess-model"
    assert policy.structured_output_mode is StructuredOutputMode.JSON_OBJECT
    assert policy.max_completion_tokens == 4096
    assert policy.temperature == 0.2
    assert policy.timeout_seconds == 90.0


@pytest.mark.parametrize(
    ("task_name", "mode"),
    [
        ("therapy_response", "json_schema"),
        ("intake_response", "json_object"),
    ],
)
def test_streaming_task_rejects_non_prompt_structured_mode(
    task_name: str,
    mode: str,
) -> None:
    with pytest.raises(ValueError, match='must be "prompt"'):
        load_application_settings(
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {task_name: {"structured_output_mode": mode}}
                ),
            },
            database_path="data/jung.db",
        )


def test_streaming_task_accepts_prompt_mode() -> None:
    settings = load_application_settings(
        {
            "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                {"therapy_response": {"structured_output_mode": "prompt"}}
            ),
        },
        database_path="data/jung.db",
    )
    assert settings.llm.task_structured_modes is not None
    assert (
        settings.llm.task_structured_modes[LLMTask.THERAPY_RESPONSE]
        is StructuredOutputMode.PROMPT
    )


def test_structured_task_accepts_json_object() -> None:
    settings = load_application_settings(
        {
            "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                {"assessment": {"structured_output_mode": "json_object"}}
            ),
        },
        database_path="data/jung.db",
    )
    assert settings.llm.task_structured_modes is not None
    assert (
        settings.llm.task_structured_modes[LLMTask.ASSESSMENT]
        is StructuredOutputMode.JSON_OBJECT
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", True),
        ("timeout_seconds", True),
        ("max_completion_tokens", True),
    ],
)
def test_task_config_rejects_boolean_numeric_fields(
    field: str,
    value: bool,
) -> None:
    with pytest.raises(ValueError):
        load_application_settings(
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps({"assessment": {field: value}}),
            },
            database_path="data/jung.db",
        )


def test_typed_null_task_field_rejected() -> None:
    with pytest.raises(ValueError, match="must not be null"):
        load_application_settings(
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {"assessment": {"model": None}}
                ),
            },
            database_path="data/jung.db",
        )


def test_non_object_task_entry_rejected() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_application_settings(
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {"assessment": "not-an-object"}
                ),
            },
            database_path="data/jung.db",
        )


def test_oversized_json_integer_error_is_path_aware() -> None:
    limit = sys.get_int_max_str_digits()
    if limit == 0:
        pytest.skip("Python integer-string digit limit is disabled")

    huge_integer = "9" * (limit + 1)
    raw = f'{{"scale":{huge_integer}}}'

    with pytest.raises(ValueError) as exc_info:
        parse_optional_json_object("JUNG_LLM_EXTRA_BODY_JSON", raw)

    message = str(exc_info.value)
    assert message == "JUNG_LLM_EXTRA_BODY_JSON must be a JSON object"
    assert huge_integer not in message


@pytest.mark.parametrize(
    ("payload", "expected_path"),
    [
        ({"not_a_task": {}}, "JUNG_LLM_TASK_CONFIG_JSON.not_a_task"),
        (
            {"assessment": {"not_a_field": 1}},
            "JUNG_LLM_TASK_CONFIG_JSON.assessment.not_a_field",
        ),
    ],
)
def test_task_config_rejects_unknown_schema_entries(
    payload: dict[str, object],
    expected_path: str,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        load_application_settings(
            {"JUNG_LLM_TASK_CONFIG_JSON": json.dumps(payload)},
            database_path="data/jung.db",
        )

    assert expected_path in str(exc_info.value)


@pytest.mark.parametrize(
    "raw",
    [
        "null",
        "[]",
        '"string"',
        "123",
    ],
)
def test_extra_body_rejects_non_object_top_level_json(raw: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        load_application_settings(
            {"JUNG_LLM_EXTRA_BODY_JSON": raw},
            database_path="data/jung.db",
        )

    assert str(exc_info.value) == "JUNG_LLM_EXTRA_BODY_JSON must be a JSON object"


@pytest.mark.parametrize("name", ["LLM_BASE_URL", "MODEL_NAME"])
def test_blank_required_string_rejected(name: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        load_application_settings(
            {name: "   "},
            database_path="data/jung.db",
        )

    assert str(exc_info.value) == f"{name} must be non-empty"


def test_blank_optional_json_treated_as_unset() -> None:
    settings = load_application_settings(
        {
            "JUNG_LLM_EXTRA_BODY_JSON": "   ",
            "JUNG_LLM_TASK_CONFIG_JSON": "",
        },
        database_path="data/jung.db",
    )
    assert settings.llm.extra_body is None
    assert settings.llm.task_extra_body is None


def test_default_header_non_string_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="JUNG_LLM_DEFAULT_HEADERS_JSON.Authorization must be a string",
    ):
        load_application_settings(
            {
                "JUNG_LLM_DEFAULT_HEADERS_JSON": json.dumps(
                    {"Authorization": 123},
                ),
            },
            database_path="data/jung.db",
        )


def test_default_header_error_does_not_leak_secret() -> None:
    secret = "super-secret-header-value"
    with pytest.raises(ValueError) as exc_info:
        load_application_settings(
            {
                "JUNG_LLM_DEFAULT_HEADERS_JSON": json.dumps(
                    {"Authorization": {"token": secret}},
                ),
            },
            database_path="data/jung.db",
        )
    assert secret not in str(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        '{"scale": NaN}',
        '{"scale": Infinity}',
        '{"scale": 1e400}',
    ],
)
def test_extra_body_rejects_non_finite_numbers(payload: str) -> None:
    with pytest.raises(ValueError):
        load_application_settings(
            {"JUNG_LLM_EXTRA_BODY_JSON": payload},
            database_path="data/jung.db",
        )


def test_log_prompt_previews_requires_tracing() -> None:
    with pytest.raises(
        ValueError, match="log_prompt_previews requires enable_llm_tracing"
    ):
        load_application_settings(
            {"JUNG_LOG_PROMPT_PREVIEWS": "true"},
            database_path="data/jung.db",
        )


@pytest.mark.parametrize(
    "field",
    ["temperature", "timeout_seconds"],
)
def test_task_numeric_huge_integer_raises_value_error(field: str) -> None:
    huge_int = 10**400
    with pytest.raises(ValueError) as exc_info:
        load_application_settings(
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {"assessment": {field: huge_int}}
                ),
            },
            database_path="data/jung.db",
        )
    assert f"JUNG_LLM_TASK_CONFIG_JSON.assessment.{field}" in str(exc_info.value)


def test_empty_task_extra_body_is_omitted() -> None:
    settings = load_application_settings(
        {
            "JUNG_LLM_TASK_CONFIG_JSON": json.dumps({"assessment": {"extra_body": {}}}),
        },
        database_path="data/jung.db",
    )
    assert settings.llm.task_extra_body is None


def test_settings_post_init_rejects_prompt_previews_without_tracing() -> None:
    with pytest.raises(
        ValueError, match="log_prompt_previews requires enable_llm_tracing"
    ):
        ApplicationSettings(
            database_path="data/jung.db",
            llm=_valid_llm(),
            enable_llm_tracing=False,
            log_prompt_previews=True,
        )


def test_settings_post_init_rejects_invalid_queue_size() -> None:
    with pytest.raises(ValueError, match="event_queue_size"):
        ApplicationSettings(
            database_path="data/jung.db",
            llm=_valid_llm(),
            event_queue_size=0,
        )


def test_settings_post_init_rejects_invalid_shutdown_timeout() -> None:
    with pytest.raises(ValueError, match="shutdown_timeout_seconds"):
        ApplicationSettings(
            database_path="data/jung.db",
            llm=_valid_llm(),
            shutdown_timeout_seconds=0,
        )


def test_settings_rejects_huge_shutdown_timeout() -> None:
    with pytest.raises(ValueError, match="shutdown_timeout_seconds"):
        ApplicationSettings(
            database_path="data/jung.db",
            llm=_valid_llm(),
            shutdown_timeout_seconds=10**400,
        )
