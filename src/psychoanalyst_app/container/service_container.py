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
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.exceptions import ConfigurationError
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.migration_service import MigrationService
from psychoanalyst_app.services.rag_service import RAGService
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
        "llm_service_psychoanalyst",
        "llm_service_reflection",
        "llm_service_memory",
        "llm_service_planning",
    ]
    AGENT_LLM_SERVICE_MAP = {
        "INTAKE": "llm_service_intake",
        "ASSESSMENT": "llm_service_assessment",
        "PSYCHOANALYST": "llm_service_psychoanalyst",
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

        # Cache for LLMService instances by model name
        self._llm_service_cache: dict[str, Any] = {}

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
                "llm_service_psychoanalyst": lambda: self._create_agent_llm_service(
                    "PSYCHOANALYST"
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

    def register_llm_service_for(self, agent_type: str, instance: LLMService) -> None:
        """
        Register a specific LLM service implementation for an agent type.

        Args:
            agent_type: Agent identifier (e.g., "INTAKE")
            instance: LLMService instance to use for that agent
        """
        normalized = agent_type.upper()
        llm_key = self.AGENT_LLM_SERVICE_MAP.get(normalized)
        if not llm_key:
            raise ValueError(f"Unknown agent type for LLM override: {agent_type}")
        with self._lock:
            self._instances[llm_key] = instance
            logger.debug("Registered custom LLM service for %s", agent_type)

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
        """
        Create migration service.

        Returns:
            Configured MigrationService instance
        """
        logger.debug("Creating MigrationService")

        try:
            migration_service = MigrationService(db_path=self.config.DATABASE_PATH)
            logger.info(f"Created MigrationService for {self.config.DATABASE_PATH}")
            return migration_service
        except Exception as e:
            logger.error(f"Failed to create MigrationService: {e}")
            raise

    def _create_trio_db_service(self) -> TrioDatabaseService:
        """
        Create a pure Trio database service using synchronous SQLite.

        Returns:
            Configured TrioDatabaseService instance
        """
        logger.debug("Creating pure TrioDatabaseService")

        try:
            migration_service = self.get("migration_service")
            executor = self.get("db_executor")
            trio_db_service = TrioDatabaseService(
                db_path=self.config.DATABASE_PATH,
                migration_service=migration_service,
                executor=executor,
            )
            logger.info(
                f"Created pure TrioDatabaseService for {self.config.DATABASE_PATH}"
            )
            return trio_db_service
        except Exception as e:
            logger.error(f"Failed to create TrioDatabaseService: {e}")
            raise

    def _create_db_executor(self) -> TrioSQLiteExecutor:
        """Create the shared TrioSQLiteExecutor instance."""
        return TrioSQLiteExecutor(
            self.config.DATABASE_PATH,
            pool_size=self.config.DATABASE_POOL_SIZE,
            connect_timeout_seconds=float(self.config.DATABASE_POOL_TIMEOUT),
            pool_acquire_timeout_seconds=float(self.config.DATABASE_POOL_TIMEOUT),
        )

    def _get_or_create_llm_service_for_model(
        self, model_name: str, config_key: str = "DEFAULT"
    ) -> LLMService:
        """
        Get existing LLMService for a model or create a new one.

        Args:
            model_name: Name of the LLM model
            config_key: Configuration key alias for logging (e.g., "INTAKE_MODEL")

        Returns:
            LLMService instance (shared per model)
        """
        # Check cache first
        if model_name in self._llm_service_cache:
            logger.debug(f"Reusing existing LLMService for model {model_name}")
            return self._llm_service_cache[model_name]

        # Create new instance
        if not self.config.GOOGLE_API_KEY:
            raise ConfigurationError("GOOGLE_API_KEY must be configured")

        try:
            llm_service = LLMService(
                api_key=self.config.GOOGLE_API_KEY,
                model_name=model_name,
                rate_limit_enabled=self.config.LLM_RATE_LIMIT_ENABLED,
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
            )

            # Cache it
            self._llm_service_cache[model_name] = llm_service

            logger.info(
                "Created new LLMService for model %s (source: %s), rate limiting: %s",
                model_name,
                config_key,
                self.config.LLM_RATE_LIMIT_ENABLED,
            )
            return llm_service
        except Exception as e:
            logger.error(f"Failed to create LLMService for {model_name}: {e}")
            raise

    def _create_llm_service(self) -> LLMService:
        """
        Create LLM service.

        Returns:
            Configured LLMService instance
        """
        logger.debug("Creating LLMService")
        if not self.config.MODEL_NAME:
            raise ConfigurationError("MODEL_NAME must be configured")
        return self._get_or_create_llm_service_for_model(
            self.config.MODEL_NAME, "DEFAULT_MODEL"
        )

    def _create_agent_llm_service(self, agent_type: str) -> LLMService:
        """
        Create agent-specific LLM service with role and environment-aware defaults.

        Args:
            agent_type: Agent identifier (e.g., "INTAKE")

        Returns:
            Configured LLMService instance
        """
        if not self.config.GOOGLE_API_KEY:
            raise ConfigurationError("GOOGLE_API_KEY must be configured")

        # Use new environment-aware model selection logic
        model_name = self.config.get_model_for_agent(agent_type)

        logger.debug(
            f"Creating agent LLM service for {agent_type} with model {model_name}"
        )
        return self._get_or_create_llm_service_for_model(model_name, agent_type)

    def _get_llm_service_for_agent(self, agent_type: str) -> LLMService:
        """
        Resolve the configured LLM service for a given agent.

        Args:
            agent_type: Agent identifier (e.g., "INTAKE")

        Returns:
            LLMService configured for that agent
        """
        service_key = self.AGENT_LLM_SERVICE_MAP.get(agent_type.upper(), "llm_service")
        return self.get(service_key)

    def _create_rag_service(self) -> RAGService:
        """
        Create RAG service.

        Returns:
            Configured RAGService instance
        """
        logger.debug("Creating RAGService")

        try:
            use_onnx = getattr(self.config, "USE_ONNX_EMBEDDINGS", True)
            model_name = getattr(
                self.config, "EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2"
            )

            rag_service = RAGService(
                domain_knowledge_path=self.config.DOMAIN_KNOWLEDGE_PATH,
                vector_db_path=self.config.VECTOR_DB_PATH,
                styles_dir=getattr(self.config, "STYLES_DIR", None),
                use_onnx=use_onnx,
                model_name=model_name,
            )
            logger.info(
                f"Created FAISS-based RAGService with ONNX={use_onnx}, "
                f"model={model_name}"
            )
            return rag_service
        except Exception as e:
            logger.error(f"Failed to create RAGService: {e}")
            raise

    def _create_style_service(self) -> StyleService:
        """
        Create style service.

        Returns:
            Configured StyleService instance
        """
        logger.debug("Creating StyleService")

        try:
            style_dir = getattr(self.config, "STYLES_DIR", None) or None
            style_service = StyleService(styles_dir=style_dir)
            logger.info(
                "Created StyleService with %s styles directory",
                style_dir or "package",
            )
            return style_service
        except Exception as e:
            logger.error(f"Failed to create StyleService: {e}")
            raise

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
        normalized = agent_type.upper()
        builders = {
            "INTAKE": self._build_intake_agent,
            "ASSESSMENT": self._build_assessment_agent,
            "PSYCHOANALYST": self._build_psychoanalyst_agent,
            "REFLECTION": self._build_reflection_agent,
            "MEMORY": self._build_memory_agent,
            "PLANNING": self._build_planning_agent,
        }
        builder = builders.get(normalized)
        if not builder:
            raise ValueError(f"Unknown agent type: {agent_type}")
        return builder(user_context)

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

    def create_psychoanalyst_agent(self, user_context: UserContext):
        """
        Create psychoanalyst agent with injected dependencies.

        Args:
            user_context: User context for this therapy session

        Returns:
            PsychoanalystAgent: Configured psychoanalyst agent instance
        """
        return self.create_agent("PSYCHOANALYST", user_context)

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

    def _build_intake_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.trio_intake_agent import TrioIntakeAgent

        logger.debug(f"Creating TrioIntakeAgent for user {user_context.user_id}")

        try:
            agent = TrioIntakeAgent(
                llm_service=self._get_llm_service_for_agent("INTAKE"),
                user_context=user_context,
                config=self.config,
            )
            logger.info(f"Created TrioIntakeAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create IntakeAgent: {e}")
            raise

    def _build_assessment_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.trio_assessment_agent import TrioAssessmentAgent

        logger.debug(f"Creating TrioAssessmentAgent for user {user_context.user_id}")

        try:
            reflection_agent = self.create_reflection_agent(user_context)
            agent = TrioAssessmentAgent(
                llm_service=self._get_llm_service_for_agent("ASSESSMENT"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
                reflection_agent=reflection_agent,
                style_service=self.get("style_service"),
            )
            logger.info(f"Created TrioAssessmentAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create AssessmentAgent: {e}")
            raise

    def _build_psychoanalyst_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.trio_psychoanalyst_agent import (
            TrioPsychoanalystAgent,
        )

        logger.debug(f"Creating TrioPsychoanalystAgent for user {user_context.user_id}")

        try:
            reflection_agent = self.create_reflection_agent(user_context)
            agent = TrioPsychoanalystAgent(
                llm_service=self._get_llm_service_for_agent("PSYCHOANALYST"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                reflection_agent=reflection_agent,
                style_service=self.get("style_service"),
                config=self.config,
            )
            logger.info(
                f"Created TrioPsychoanalystAgent for user {user_context.user_id}"
            )
            return agent
        except Exception as e:
            logger.error(f"Failed to create PsychoanalystAgent: {e}")
            raise

    def _build_reflection_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.trio_reflection_agent import TrioReflectionAgent

        logger.debug(f"Creating TrioReflectionAgent for user {user_context.user_id}")

        try:
            memory_agent = self.create_memory_agent(user_context)
            planning_agent = self.create_planning_agent(user_context)
            agent = TrioReflectionAgent(
                llm_service=self._get_llm_service_for_agent("REFLECTION"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
                memory_agent=memory_agent,
                planning_agent=planning_agent,
                config=self.config,
            )
            logger.info(f"Created TrioReflectionAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create ReflectionAgent: {e}")
            raise

    def _build_memory_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.trio_memory_agent import TrioMemoryAgent

        logger.debug(f"Creating TrioMemoryAgent for user {user_context.user_id}")

        try:
            agent = TrioMemoryAgent(
                llm_service=self._get_llm_service_for_agent("MEMORY"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
            )
            logger.info(f"Created TrioMemoryAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create MemoryAgent: {e}")
            raise

    def _build_planning_agent(self, user_context: UserContext):
        from psychoanalyst_app.agents.trio_planning_agent import TrioPlanningAgent

        logger.debug(f"Creating TrioPlanningAgent for user {user_context.user_id}")

        try:
            memory_agent = self.create_memory_agent(user_context)
            agent = TrioPlanningAgent(
                llm_service=self._get_llm_service_for_agent("PLANNING"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
                memory_agent=memory_agent,
                style_service=self.get("style_service"),
            )
            logger.info(f"Created TrioPlanningAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create PlanningAgent: {e}")
            raise

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
