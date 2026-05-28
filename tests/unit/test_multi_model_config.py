"""Tests for multi-model configuration support."""

import pytest

from psychoanalyst_app.config import Settings
from psychoanalyst_app.container.service_container import ServiceContainer


def _clear_agent_model_env(monkeypatch):
    # Settings loads values from `.env` by default; make tests deterministic by
    # explicitly overriding all agent-model env vars unless a test sets them.
    for key in (
        "INTAKE_MODEL",
        "ASSESSMENT_MODEL",
        "PSYCHOANALYST_MODEL",
        "REFLECTION_MODEL",
        "MEMORY_MODEL",
        "PLANNING_MODEL",
    ):
        monkeypatch.setenv(key, "")


def test_agent_specific_models_from_config(monkeypatch):
    """Test that agents get correct model configurations from env vars."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "default-model")
    monkeypatch.setenv("INTAKE_MODEL", "intake-model")
    monkeypatch.setenv("PSYCHOANALYST_MODEL", "psychoanalyst-model")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-api-key")

    container = ServiceContainer(Settings())

    # Test intake agent gets specific model
    intake_service = container.get("llm_service_intake")
    assert intake_service.model_name == "intake-model"

    # Test psychoanalyst agent gets specific model
    psychoanalyst_service = container.get("llm_service_psychoanalyst")
    assert psychoanalyst_service.model_name == "psychoanalyst-model"


def test_fallback_to_default_model(monkeypatch):
    """Test that missing agent models fall back to MODEL_NAME."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "default-model")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-api-key")
    # Don't set INTAKE_MODEL - should fall back to MODEL_NAME

    container = ServiceContainer(Settings())
    intake_service = container.get("llm_service_intake")
    assert intake_service.model_name == "default-model"


def test_all_agent_models_configurable(monkeypatch):
    """Test that all 6 agent models can be individually configured."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "default-model")
    monkeypatch.setenv("INTAKE_MODEL", "intake-model")
    monkeypatch.setenv("ASSESSMENT_MODEL", "assessment-model")
    monkeypatch.setenv("PSYCHOANALYST_MODEL", "psychoanalyst-model")
    monkeypatch.setenv("REFLECTION_MODEL", "reflection-model")
    monkeypatch.setenv("MEMORY_MODEL", "memory-model")
    monkeypatch.setenv("PLANNING_MODEL", "planning-model")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-api-key")

    container = ServiceContainer(Settings())

    assert container.get("llm_service_intake").model_name == "intake-model"
    assert container.get("llm_service_assessment").model_name == "assessment-model"
    assert (
        container.get("llm_service_psychoanalyst").model_name == "psychoanalyst-model"
    )
    assert container.get("llm_service_reflection").model_name == "reflection-model"
    assert container.get("llm_service_memory").model_name == "memory-model"
    assert container.get("llm_service_planning").model_name == "planning-model"


def test_config_class_fields(monkeypatch):
    """Test that Settings class properly loads agent model fields."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "default-model")
    monkeypatch.setenv("INTAKE_MODEL", "test-intake-model")
    monkeypatch.setenv("ASSESSMENT_MODEL", "test-assessment-model")

    settings = Settings()

    assert settings.INTAKE_MODEL == "test-intake-model"
    assert settings.ASSESSMENT_MODEL == "test-assessment-model"
    # Fields not set should be empty string (fallback happens in ServiceContainer)
    assert settings.REFLECTION_MODEL == ""


def test_local_llm_provider_config_defaults(monkeypatch):
    """Test local provider config normalization and default base URLs."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "llama3.1")
    monkeypatch.setenv("LLM_PROVIDER", "OLLAMA")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    settings = Settings()

    assert settings.LLM_PROVIDER == "ollama"
    assert settings.get_llm_base_url() == "http://host.docker.internal:11434"


def test_default_llm_provider_is_local_llamacpp(monkeypatch):
    """Test default Settings point to local llama.cpp, not Gemini."""
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.LLM_PROVIDER == "openai_compatible"
    assert settings.MODEL_NAME == "local-model"
    assert settings.get_llm_base_url() == "http://host.docker.internal:8080/v1"


def test_lmstudio_provider_config_default_base_url(monkeypatch):
    """Test LM Studio gets its OpenAI-compatible default URL."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "local-model")
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    settings = Settings()

    assert settings.get_llm_base_url() == "http://host.docker.internal:1234/v1"


def test_openai_compatible_provider_config_default_base_url(monkeypatch):
    """Test generic OpenAI-compatible local servers get the llama.cpp default URL."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "local-model")
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    settings = Settings()

    assert settings.get_llm_base_url() == "http://host.docker.internal:8080/v1"


def test_openai_compatible_provider_config_custom_base_url(monkeypatch):
    """Test explicit OpenAI-compatible base URLs override the llama.cpp default."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "local-model")
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://llamacpp:8080/v1")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    settings = Settings()

    assert settings.get_llm_base_url() == "http://llamacpp:8080/v1"


def test_default_llm_service_unchanged(monkeypatch):
    """Test that default llm_service still uses MODEL_NAME."""
    _clear_agent_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "default-model")
    monkeypatch.setenv("INTAKE_MODEL", "intake-model")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-api-key")

    container = ServiceContainer(Settings())

    # Default service should still use MODEL_NAME
    default_service = container.get("llm_service")
    assert default_service.model_name == "default-model"

    # Agent-specific service should use INTAKE_MODEL
    intake_service = container.get("llm_service_intake")
    assert intake_service.model_name == "intake-model"


def test_llm_call_logging_defaults():
    """Test local-safe LLM call logging defaults."""
    settings = Settings(_env_file=None)

    assert settings.LLM_CALL_LOGGING_ENABLED is False
    assert settings.LLM_CALL_LOGGING_REDACT is True
    assert settings.LLM_CALL_LOGGING_MAX_FIELD_CHARS == 256
    assert settings.LLM_CALL_LOGGING_INCLUDE_CHUNKS is False
