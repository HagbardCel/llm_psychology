"""Unit tests for composition settings loading."""

from __future__ import annotations

import json

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
    assert settings.debug_run_dir is None
    assert settings.llm.extra_body is None
    assert settings.llm.task_extra_body is None
    assert settings.llm.default_headers is None


def test_load_application_settings_scalar_overrides() -> None:
    settings = load_application_settings(
        {
            "JUNG_SHUTDOWN_TIMEOUT": "45",
            "JUNG_EVENT_QUEUE_SIZE": "128",
            "JUNG_ENABLE_LLM_TRACING": "true",
            "JUNG_DEBUG_RUN_DIR": "  /tmp/jung-debug-run  ",
        },
        database_path="data/jung.db",
    )
    assert settings.shutdown_timeout_seconds == 45.0
    assert settings.event_queue_size == 128
    assert settings.enable_llm_tracing is True
    assert settings.debug_run_dir is not None
    assert str(settings.debug_run_dir) == "/tmp/jung-debug-run"


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


@pytest.mark.parametrize(
    ("environ", "expected_fragment"),
    [
        (
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {"assessment": {"temperature": True}}
                )
            },
            "temperature",
        ),
        (
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {"assessment": {"timeout_seconds": True}}
                )
            },
            "timeout_seconds",
        ),
        (
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {"assessment": {"max_completion_tokens": True}}
                )
            },
            "max_completion_tokens",
        ),
        (
            {"JUNG_LLM_TASK_CONFIG_JSON": json.dumps({"assessment": "not-an-object"})},
            "must be a JSON object",
        ),
        (
            {"JUNG_LLM_TASK_CONFIG_JSON": json.dumps({"not_a_task": {}})},
            "JUNG_LLM_TASK_CONFIG_JSON.not_a_task",
        ),
        (
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {"assessment": {"not_a_field": 1}}
                )
            },
            "JUNG_LLM_TASK_CONFIG_JSON.assessment.not_a_field",
        ),
        (
            {"JUNG_LLM_EXTRA_BODY_JSON": "null"},
            "JUNG_LLM_EXTRA_BODY_JSON must be a JSON object",
        ),
        (
            {"JUNG_LLM_EXTRA_BODY_JSON": "[]"},
            "JUNG_LLM_EXTRA_BODY_JSON must be a JSON object",
        ),
        (
            {"JUNG_LLM_EXTRA_BODY_JSON": '"string"'},
            "JUNG_LLM_EXTRA_BODY_JSON must be a JSON object",
        ),
        (
            {"JUNG_LLM_EXTRA_BODY_JSON": "123"},
            "JUNG_LLM_EXTRA_BODY_JSON must be a JSON object",
        ),
    ],
)
def test_settings_rejects_schema_invalid_payloads(
    environ: dict[str, str],
    expected_fragment: str,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        load_application_settings(environ, database_path="data/jung.db")

    assert expected_fragment in str(exc_info.value)


def test_malformed_optional_json_object_is_project_owned_error() -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_optional_json_object(
            "JUNG_LLM_EXTRA_BODY_JSON",
            '{"broken":',
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


def test_task_numeric_huge_integer_raises_value_error() -> None:
    huge_int = 10**400
    with pytest.raises(ValueError) as exc_info:
        load_application_settings(
            {
                "JUNG_LLM_TASK_CONFIG_JSON": json.dumps(
                    {"assessment": {"temperature": huge_int}}
                ),
            },
            database_path="data/jung.db",
        )
    assert "JUNG_LLM_TASK_CONFIG_JSON.assessment.temperature" in str(exc_info.value)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"event_queue_size": 0}, "event_queue_size"),
        ({"shutdown_timeout_seconds": 0}, "shutdown_timeout_seconds"),
        ({"shutdown_timeout_seconds": 10**400}, "shutdown_timeout_seconds"),
    ],
)
def test_settings_post_init_rejects_invalid_values(
    kwargs: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        ApplicationSettings(
            database_path="data/jung.db",
            llm=_valid_llm(),
            **kwargs,
        )
