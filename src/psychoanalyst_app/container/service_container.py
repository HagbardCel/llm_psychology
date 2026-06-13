"""
Centralized dependency injection container for the psychoanalyst application.

This module provides a comprehensive dependency injection system that manages
service lifecycles, handles dependencies, and supports both singleton and
factory patterns for service creation.
"""

import inspect
import logging
from collections.abc import Callable
from datetime import datetime
from threading import RLock
from typing import Any, TypeVar

from psychoanalyst_app.config import Settings
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.exceptions import ConfigurationError
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.migration_service import MigrationService
from psychoanalyst_app.services.rag import NoOpRAGService
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

T = TypeVar("T")

logger = logging.getLogger(__name__)


class ServiceContainer:
    """
    Centralized dependency injection container.

    Manages service lifecycles, provides singleton instances, handles service
    dependencies, and supports testing with mock services.
    """

    LLM_SERVICE_KEYS = [
        "llm_service",
        "llm_service_intake",
        "llm_service_assessment",
        "llm_service_therapist",
        "llm_service_reflection",
        "llm_service_memory",
        "llm_service_planning",
    ]
    AGENT_LLM_SERVICE_MAP = {
        "INTAKE": "llm_service_intake",
        "ASSESSMENT": "llm_service_assessment",
        "THERAPIST": "llm_service_therapist",
        "REFLECTION": "llm_service_reflection",
        "MEMORY": "llm_service_memory",
        "PLANNING": "llm_service_planning",
    }

    def __init__(self, config: Settings):
        self.config = config
        self._instances: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}
        self._lock = RLock()
        self._initialized = False

        # Cache for LLMService instances by provider/model/base URL.
        self._llm_service_cache: dict[tuple[str, str, str], Any] = {}

        logger.info("Initializing ServiceContainer")
        self._setup_factories()
        logger.info("ServiceContainer initialized with factories")

    def _setup_factories(self) -> None:
        self._factories.update(
            {
                "db_executor": self._create_db_executor,
                "llm_service": self._create_default_llm_service,
                "llm_service_intake": lambda: self._create_agent_llm_service("INTAKE"),
                "llm_service_assessment": lambda: self._create_agent_llm_service(
                    "ASSESSMENT"
                ),
                "llm_service_therapist": lambda: self._create_agent_llm_service(
                    "THERAPIST"
                ),
                "llm_service_reflection": lambda: self._create_agent_llm_service(
                    "REFLECTION"
                ),
                "llm_service_memory": lambda: self._create_agent_llm_service("MEMORY"),
                "llm_service_planning": lambda: self._create_agent_llm_service(
                    "PLANNING"
                ),
                "rag_service": self._create_rag_service,
                "migration_service": self._create_migration_service,
                "trio_db_service": self._create_trio_db_service,
                "style_service": self._create_style_service,
            }
        )
        logger.debug("Registered %d service factories", len(self._factories))

    def get(self, service_name: str) -> Any:
        """Get service instance using singleton pattern."""
        if service_name not in self._instances:
            with self._lock:
                if service_name not in self._instances:
                    if service_name not in self._factories:
                        available_services = list(self._factories.keys())
                        raise ValueError(
                            f"Unknown service: {service_name}. "
                            f"Available services: {available_services}"
                        )

                    logger.debug("Creating new instance of %s", service_name)
                    try:
                        self._instances[service_name] = self._factories[service_name]()
                        logger.info("Successfully created %s", service_name)
                    except Exception as e:
                        logger.error(
                            "Failed to create %s: %s", service_name, e, exc_info=True
                        )
                        raise ConfigurationError(
                            f"Failed to create {service_name}: {e}"
                        ) from e

        return self._instances[service_name]

    def register(self, service_name: str, instance: Any) -> None:
        """Register a service instance (useful for testing with mocks)."""
        with self._lock:
            if service_name == "llm_service":
                self._llm_service_cache.clear()
                for llm_key in self.LLM_SERVICE_KEYS:
                    self._instances[llm_key] = instance
                logger.debug(
                    "Registered mock LLM service for all agent-specific LLM keys"
                )
            else:
                self._instances[service_name] = instance
            logger.debug("Registered custom instance for %s", service_name)

    def register_factory(self, service_name: str, factory: Callable[[], Any]) -> None:
        """Register a custom factory for service creation."""
        with self._lock:
            self._factories[service_name] = factory
            if service_name in self._instances:
                del self._instances[service_name]
            logger.debug("Registered custom factory for %s", service_name)

    def clear(self) -> None:
        """Clear all service instances and factories. Useful for testing cleanup."""
        with self._lock:
            self._instances.clear()
            self._factories.clear()
            self._setup_factories()
            self._llm_service_cache.clear()
            logger.debug("Cleared all service instances")

    def is_registered(self, service_name: str) -> bool:
        return service_name in self._factories

    def list_services(self) -> dict[str, bool]:
        return {
            service: service in self._instances for service in self._factories.keys()
        }

    # Service factories ------------------------------------------------------

    def _create_db_executor(self) -> TrioSQLiteExecutor:
        return TrioSQLiteExecutor(
            self.config.DATABASE_PATH,
            pool_size=self.config.DATABASE_POOL_SIZE,
            connect_timeout_seconds=float(self.config.DATABASE_POOL_TIMEOUT),
            pool_acquire_timeout_seconds=float(self.config.DATABASE_POOL_TIMEOUT),
        )

    def _create_migration_service(self) -> MigrationService:
        logger.debug("Creating MigrationService")
        return MigrationService(
            db_path=self.config.DATABASE_PATH,
            busy_timeout_seconds=float(self.config.DATABASE_POOL_TIMEOUT),
        )

    def _create_trio_db_service(self) -> TrioDatabaseService:
        logger.debug("Creating TrioDatabaseService")
        return TrioDatabaseService(
            db_path=self.config.DATABASE_PATH,
            migration_service=self.get("migration_service"),
            executor=self.get("db_executor"),
        )

    def _create_rag_service(self) -> NoOpRAGService:
        logger.info("Created no-op RAGService")
        return NoOpRAGService()

    def _create_style_service(self) -> StyleService:
        style_dir = getattr(self.config, "STYLES_DIR", None) or None
        return StyleService(styles_dir=style_dir)

    def _get_or_create_llm_service_for_model(
        self, model_name: str, config_key: str = "DEFAULT"
    ) -> LLMService:
        """Get existing cached LLMService for model, or create one."""
        provider = self.config.LLM_PROVIDER
        base_url = self.config.get_llm_base_url()
        cache_key = (provider, model_name, base_url or "")
        if cache_key in self._llm_service_cache:
            logger.debug(
                "Reusing existing LLMService for provider %s model %s",
                provider,
                model_name,
            )
            return self._llm_service_cache[cache_key]

        if provider == "gemini" and not self.config.GOOGLE_API_KEY:
            raise ConfigurationError("GOOGLE_API_KEY must be configured")

        effective_rate_limit_enabled = self.config.effective_llm_rate_limit_enabled()
        llm_service = LLMService(
            provider=provider,
            api_key=(
                self.config.GOOGLE_API_KEY
                if provider == "gemini"
                else self.config.LLM_API_KEY
            ),
            model_name=model_name,
            base_url=base_url,
            rate_limit_enabled=effective_rate_limit_enabled,
            requests_per_minute=self.config.LLM_REQUESTS_PER_MINUTE,
            burst_capacity=self.config.LLM_BURST_CAPACITY,
            llm_call_logging_enabled=self.config.LLM_CALL_LOGGING_ENABLED,
            llm_call_logging_redact=self.config.LLM_CALL_LOGGING_REDACT,
            llm_call_logging_max_field_chars=(
                self.config.LLM_CALL_LOGGING_MAX_FIELD_CHARS
            ),
            llm_call_logging_include_chunks=(
                self.config.LLM_CALL_LOGGING_INCLUDE_CHUNKS
            ),
            enable_thinking=self.config.LLM_ENABLE_THINKING,
        )

        self._llm_service_cache[cache_key] = llm_service
        logger.info(
            "Created new LLMService for provider %s model %s (source: %s), "
            "base_url: %s, rate limiting: %s (configured: %s)",
            provider,
            model_name,
            config_key,
            base_url or "<provider-default>",
            effective_rate_limit_enabled,
            self.config.LLM_RATE_LIMIT_ENABLED,
        )
        return llm_service

    def _create_default_llm_service(self) -> LLMService:
        if not self.config.MODEL_NAME:
            raise ConfigurationError("MODEL_NAME must be configured")
        return self._get_or_create_llm_service_for_model(
            self.config.MODEL_NAME, "DEFAULT_MODEL"
        )

    def _create_agent_llm_service(self, agent_type: str) -> LLMService:
        if self.config.LLM_PROVIDER == "gemini" and not self.config.GOOGLE_API_KEY:
            raise ConfigurationError("GOOGLE_API_KEY must be configured")
        model_name = self.config.get_model_for_agent(agent_type)
        return self._get_or_create_llm_service_for_model(model_name, agent_type)

    def _get_llm_service_for_agent(self, agent_type: str) -> LLMService:
        """Resolve the configured LLM service for a given agent."""
        service_key = self.AGENT_LLM_SERVICE_MAP.get(agent_type.upper(), "llm_service")
        return self.get(service_key)

    def __str__(self) -> str:
        service_status = self.list_services()
        instantiated = sum(service_status.values())
        total = len(service_status)
        return f"ServiceContainer(services={total}, instantiated={instantiated})"

    def __repr__(self) -> str:
        return (
            f"ServiceContainer(config={self.config.__class__.__name__}, "
            f"services={list(self._factories.keys())})"
        )

    # Agent factories --------------------------------------------------------

    def create_agent(self, agent_type: str, user_context: UserContext):
        """Create an agent instance using a centralized mapping."""
        normalized = agent_type.upper()
        builders = {
            "INTAKE": self.create_intake_agent,
            "ASSESSMENT": self.create_assessment_agent,
            "THERAPIST": self.create_therapist_agent,
            "REFLECTION": self.create_reflection_agent,
            "MEMORY": self.create_memory_agent,
            "PLANNING": self.create_planning_agent,
        }
        builder = builders.get(normalized)
        if not builder:
            raise ValueError(f"Unknown agent type: {agent_type}")
        return builder(user_context)

    def create_intake_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.intake import TrioIntakeAgent

        return TrioIntakeAgent(
            llm_service=self._get_llm_service_for_agent("INTAKE"),
            user_context=user_context,
            config=self.config,
        )

    def create_assessment_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.assessment import TrioAssessmentAgent

        return TrioAssessmentAgent(
            llm_service=self._get_llm_service_for_agent("ASSESSMENT"),
            db_service=self.get("trio_db_service"),
            rag_service=self.get("rag_service"),
            user_context=user_context,
            reflection_agent=self.create_reflection_agent(user_context),
            style_service=self.get("style_service"),
        )

    def create_therapist_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.therapist import TrioTherapistAgent

        return TrioTherapistAgent(
            llm_service=self._get_llm_service_for_agent("THERAPIST"),
            db_service=self.get("trio_db_service"),
            rag_service=self.get("rag_service"),
            reflection_agent=self.create_reflection_agent(user_context),
            style_service=self.get("style_service"),
            config=self.config,
        )

    def create_reflection_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.reflection import TrioReflectionAgent

        return TrioReflectionAgent(
            llm_service=self._get_llm_service_for_agent("REFLECTION"),
            db_service=self.get("trio_db_service"),
            rag_service=self.get("rag_service"),
            user_context=user_context,
            memory_agent=self.create_memory_agent(user_context),
            planning_agent=self.create_planning_agent(user_context),
            config=self.config,
        )

    def create_memory_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.memory import TrioMemoryAgent

        return TrioMemoryAgent(
            llm_service=self._get_llm_service_for_agent("MEMORY"),
            db_service=self.get("trio_db_service"),
            rag_service=self.get("rag_service"),
            user_context=user_context,
        )

    def create_planning_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.planning import TrioPlanningAgent

        return TrioPlanningAgent(
            llm_service=self._get_llm_service_for_agent("PLANNING"),
            db_service=self.get("trio_db_service"),
            rag_service=self.get("rag_service"),
            user_context=user_context,
            memory_agent=self.create_memory_agent(user_context),
            style_service=self.get("style_service"),
        )

    # Lifecycle --------------------------------------------------------------

    def shutdown(self) -> None:
        """Shutdown the container and cleanup resources."""
        logger.info("Shutting down ServiceContainer")

        with self._lock:
            db_service = self._instances.get("trio_db_service")
            if db_service:
                close_method = getattr(db_service, "close", None)
                if callable(close_method):
                    try:
                        close_method()
                        logger.debug("Closed TrioDatabaseService resources")
                    except Exception as exc:
                        logger.error("Error closing TrioDatabaseService: %s", exc)

            self._instances.clear()
            self._llm_service_cache.clear()
            logger.info("ServiceContainer shutdown complete")

    async def health_check(self) -> dict:
        """Perform health check on all registered services."""
        health_status = {
            "status": "healthy",
            "services": {},
            "timestamp": datetime.now().isoformat(),
        }

        overall_healthy = True

        for service_name, service in self._instances.items():
            try:
                if hasattr(service, "health_check"):
                    health_check_method = service.health_check
                    if inspect.iscoroutinefunction(health_check_method):
                        service_healthy = await health_check_method()
                    else:
                        service_healthy = health_check_method()

                    health_status["services"][service_name] = {
                        "status": "healthy" if service_healthy else "unhealthy"
                    }
                    if not service_healthy:
                        overall_healthy = False
                else:
                    health_status["services"][service_name] = {"status": "healthy"}
            except Exception as e:
                health_status["services"][service_name] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                overall_healthy = False

        health_status["status"] = "healthy" if overall_healthy else "unhealthy"
        return health_status
