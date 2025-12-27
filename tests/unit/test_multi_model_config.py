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
