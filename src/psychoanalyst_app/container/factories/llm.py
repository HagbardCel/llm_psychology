"""LLM service factory functions for ServiceContainer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from psychoanalyst_app.exceptions import ConfigurationError
from psychoanalyst_app.services.llm_service import LLMService

if TYPE_CHECKING:
    from psychoanalyst_app.container.service_container import ServiceContainer

logger = logging.getLogger(__name__)


def get_or_create_llm_service_for_model(
    container: ServiceContainer,
    model_name: str,
    config_key: str = "DEFAULT",
) -> LLMService:
    """Get cached LLMService for model, or create and cache it."""
    if model_name in container._llm_service_cache:
        logger.debug("Reusing existing LLMService for model %s", model_name)
        return container._llm_service_cache[model_name]

    if not container.config.GOOGLE_API_KEY:
        raise ConfigurationError("GOOGLE_API_KEY must be configured")

    llm_service = LLMService(
        api_key=container.config.GOOGLE_API_KEY,
        model_name=model_name,
        rate_limit_enabled=container.config.LLM_RATE_LIMIT_ENABLED,
        requests_per_minute=container.config.LLM_REQUESTS_PER_MINUTE,
        burst_capacity=container.config.LLM_BURST_CAPACITY,
        llm_call_logging_enabled=container.config.LLM_CALL_LOGGING_ENABLED,
        llm_call_logging_redact=container.config.LLM_CALL_LOGGING_REDACT,
        llm_call_logging_max_field_chars=(
            container.config.LLM_CALL_LOGGING_MAX_FIELD_CHARS
        ),
        llm_call_logging_include_chunks=(
            container.config.LLM_CALL_LOGGING_INCLUDE_CHUNKS
        ),
    )

    container._llm_service_cache[model_name] = llm_service
    logger.info(
        "Created new LLMService for model %s (source: %s), rate limiting: %s",
        model_name,
        config_key,
        container.config.LLM_RATE_LIMIT_ENABLED,
    )
    return llm_service


def create_default_llm_service(container: ServiceContainer) -> LLMService:
    """Create default LLM service."""
    logger.debug("Creating LLMService")
    if not container.config.MODEL_NAME:
        raise ConfigurationError("MODEL_NAME must be configured")
    return get_or_create_llm_service_for_model(
        container, container.config.MODEL_NAME, "DEFAULT_MODEL"
    )


def create_agent_llm_service(
    container: ServiceContainer, agent_type: str
) -> LLMService:
    """Create agent-specific LLM service."""
    if not container.config.GOOGLE_API_KEY:
        raise ConfigurationError("GOOGLE_API_KEY must be configured")
    model_name = container.config.get_model_for_agent(agent_type)
    logger.debug(
        "Creating agent LLM service for %s with model %s",
        agent_type,
        model_name,
    )
    return get_or_create_llm_service_for_model(container, model_name, agent_type)


def get_llm_service_for_agent(
    container: ServiceContainer, agent_type: str
) -> LLMService:
    """Resolve configured LLM service key for given agent."""
    service_key = container.AGENT_LLM_SERVICE_MAP.get(agent_type.upper(), "llm_service")
    return container.get(service_key)
