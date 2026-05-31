"""
Centralized dependency injection container for the psychoanalyst application.

This module provides a comprehensive dependency injection system that manages
service lifecycles, handles dependencies, and supports both singleton and
factory patterns for service creation.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from threading import RLock
from typing import Any, TypeVar

from psychoanalyst_app.config import Settings
from psychoanalyst_app.container.factories import (
    build_assessment_agent,
    build_intake_agent,
    build_memory_agent,
    build_planning_agent,
    build_therapist_agent,
    build_reflection_agent,
    create_agent,
    create_agent_llm_service,
    create_db_executor,
    create_default_llm_service,
    create_migration_service,
    create_rag_service,
    create_style_service,
    create_trio_db_service,
    get_llm_service_for_agent,
    get_or_create_llm_service_for_model,
)
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.exceptions import ConfigurationError
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.migration_service import MigrationService
from psychoanalyst_app.services.rag import NoOpRAGService, RAGServiceProtocol
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

T = TypeVar("T")

logger = logging.getLogger(__name__)


class ServiceContainer:
    """
    Centralized dependency injection container.

    Manages service lifecycles, provides singleton instances, handles service
    dependencies, and supports testing with mock services.

    Features:
    - Singleton pattern for expensive services
    - Factory pattern for agents that need per-request instances
    - Thread-safe service registration and retrieval
    - Configuration-driven service setup
    - Mock service support for testing
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
        """
        Initialize the service container.

        Args:
            config: Application configuration object
        """
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
        """Register service factories for dependency creation."""
        self._factories.update(
            {
                "db_executor": self._create_db_executor,
                "llm_service": self._create_llm_service,
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
        logger.debug(f"Registered {len(self._factories)} service factories")

    def get(self, service_name: str) -> Any:
        """
        Get service instance using singleton pattern.

        Args:
            service_name: Name of the service to retrieve

        Returns:
            Service instance

        Raises:
            ValueError: If service is not registered
            ConfigurationError: If service cannot be created due to configuration
        """
        if service_name not in self._instances:
            with self._lock:
                # Double-check locking pattern
                if service_name not in self._instances:
                    if service_name not in self._factories:
                        available_services = list(self._factories.keys())
                        raise ValueError(
                            f"Unknown service: {service_name}. "
                            f"Available services: {available_services}"
                        )

                    logger.debug(f"Creating new instance of {service_name}")
                    try:
                        self._instances[service_name] = self._factories[service_name]()
                        logger.info(f"Successfully created {service_name}")
                    except Exception as e:
                        logger.error(
                            f"Failed to create {service_name}: {e}", exc_info=True
                        )
                        raise ConfigurationError(
                            f"Failed to create {service_name}: {e}"
                        ) from e

        return self._instances[service_name]

    def register(self, service_name: str, instance: Any) -> None:
        """
        Register a service instance (useful for testing with mocks).

        Args:
            service_name: Name of the service
            instance: Service instance to register
        """
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
            logger.debug(f"Registered custom instance for {service_name}")

    def register_factory(self, service_name: str, factory: Callable[[], Any]) -> None:
        """
        Register a custom factory for service creation.

        Args:
            service_name: Name of the service
            factory: Factory function that creates the service
        """
        with self._lock:
            self._factories[service_name] = factory
            # Remove existing instance if any
            if service_name in self._instances:
                del self._instances[service_name]
            logger.debug(f"Registered custom factory for {service_name}")

    def clear(self) -> None:
        """
        Clear all service instances and factories.
        Useful for testing cleanup.
        """
        with self._lock:
            self._instances.clear()
            self._factories.clear()
            self._setup_factories()  # Re-register default factories
            self._llm_service_cache.clear()
            logger.debug("Cleared all service instances")

    def is_registered(self, service_name: str) -> bool:
        """
        Check if a service is registered.

        Args:
            service_name: Name of the service to check

        Returns:
            True if service is registered, False otherwise
        """
        return service_name in self._factories

    def list_services(self) -> dict[str, bool]:
        """
        List all registered services and their instantiation status.

        Returns:
            Dictionary mapping service names to instantiation status
        """
        return {
            service: service in self._instances for service in self._factories.keys()
        }

    # Service Factory Methods

    def _create_migration_service(self) -> MigrationService:
        """Create migration service."""
        return create_migration_service(self)

    def _create_trio_db_service(self) -> TrioDatabaseService:
        """Create a pure Trio database service using synchronous SQLite."""
        return create_trio_db_service(self)

    def _create_db_executor(self) -> TrioSQLiteExecutor:
        """Create the shared TrioSQLiteExecutor instance."""
        return create_db_executor(self)

    def _get_or_create_llm_service_for_model(
        self, model_name: str, config_key: str = "DEFAULT"
    ) -> LLMService:
        """Get existing LLMService for a model or create a new one."""
        return get_or_create_llm_service_for_model(self, model_name, config_key)

    def _create_llm_service(self) -> LLMService:
        """Create LLM service."""
        return create_default_llm_service(self)

    def _create_agent_llm_service(self, agent_type: str) -> LLMService:
        """Create agent-specific LLM service."""
        return create_agent_llm_service(self, agent_type)

    def _get_llm_service_for_agent(self, agent_type: str) -> LLMService:
        """Resolve the configured LLM service for a given agent."""
        return get_llm_service_for_agent(self, agent_type)

    def _create_rag_service(self) -> NoOpRAGService:
        """Create RAG service."""
        return create_rag_service(self)

    def _create_style_service(self) -> StyleService:
        """Create style service."""
        return create_style_service(self)

    def __str__(self) -> str:
        """String representation of the container."""
        service_status = self.list_services()
        instantiated = sum(service_status.values())
        total = len(service_status)
        return f"ServiceContainer(services={total}, instantiated={instantiated})"

    def __repr__(self) -> str:
        """Detailed representation of the container."""
        return (
            f"ServiceContainer(config={self.config.__class__.__name__}, "
            f"services={list(self._factories.keys())})"
        )

    # Agent Factory Methods

    def create_agent(self, agent_type: str, user_context: UserContext):
        """
        Create an agent instance using a centralized mapping.

        Args:
            agent_type: Agent identifier (e.g., "INTAKE")
            user_context: Context for the requesting user

        Returns:
            Configured agent instance
        """
        return create_agent(self, agent_type, user_context)

    def create_intake_agent(self, user_context: UserContext):
        """
        Create intake agent with injected dependencies.

        Args:
            user_context: User context for this intake session

        Returns:
            IntakeAgent: Configured intake agent instance
        """
        return self.create_agent("INTAKE", user_context)

    def create_assessment_agent(self, user_context: UserContext):
        """
        Create assessment agent with injected dependencies.

        Args:
            user_context: User context for this assessment session

        Returns:
            AssessmentAgent: Configured assessment agent instance
        """
        return self.create_agent("ASSESSMENT", user_context)

    def create_therapist_agent(self, user_context: UserContext):
        """
        Create therapist agent with injected dependencies.

        Args:
            user_context: User context for this therapy session

        Returns:
            TherapistAgent: Configured therapist agent instance
        """
        return self.create_agent("THERAPIST", user_context)

    def create_reflection_agent(self, user_context: UserContext):
        """
        Create reflection agent with injected dependencies.

        Args:
            user_context: User context for this reflection session

        Returns:
            ReflectionAgent: Configured reflection agent instance
        """
        return self.create_agent("REFLECTION", user_context)

    def create_memory_agent(self, user_context: UserContext):
        """
        Create memory agent with injected dependencies.

        Args:
            user_context: User context for this memory session

        Returns:
            MemoryAgent: Configured memory agent instance
        """
        return self.create_agent("MEMORY", user_context)

    def create_planning_agent(self, user_context: UserContext):
        """
        Create planning agent with injected dependencies.

        Args:
            user_context: User context for this planning session

        Returns:
            PlanningAgent: Configured planning agent instance
        """
        return self.create_agent("PLANNING", user_context)

    # Container Lifecycle Methods

    def shutdown(self) -> None:
        """
        Shutdown the container and cleanup resources.

        This method should be called when the application is shutting down
        to properly cleanup database connections and other resources.
        """
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

            # Clear caches so future tests start clean
            self._instances.clear()
            self._llm_service_cache.clear()
            logger.info("ServiceContainer shutdown complete")

    async def health_check(self) -> dict:
        """
        Perform health check on all registered services.

        Returns:
            dict: Health status of all services
        """
        import inspect

        health_status = {
            "status": "healthy",
            "services": {},
            "timestamp": datetime.now().isoformat(),
        }

        overall_healthy = True

        # Check each service that has been instantiated
        for service_name, service in self._instances.items():
            try:
                if hasattr(service, "health_check"):
                    # Call health_check with or without await based on whether it's
                    # async
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
                    # If service doesn't have health check, assume it's healthy
                    health_status["services"][service_name] = {"status": "healthy"}

            except Exception as e:
                health_status["services"][service_name] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                overall_healthy = False

        health_status["status"] = "healthy" if overall_healthy else "unhealthy"

        return health_status
