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

from config import Settings, settings
from context.user_context import UserContext
from exceptions import ConfigurationError
from services.llm_service import LLMService
from services.migration_service import MigrationService
from services.rag_service import RAGService
from services.style_service import StyleService
from services.trio_db_service import TrioDatabaseService

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

    def __init__(self, config: Settings = settings):
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

        logger.info("Initializing ServiceContainer")
        self._setup_factories()
        logger.info("ServiceContainer initialized with factories")

    def _setup_factories(self) -> None:
        """Register service factories for dependency creation."""
        self._factories.update(
            {
                "llm_service": self._create_llm_service,
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
            trio_db_service = TrioDatabaseService(
                db_path=self.config.DATABASE_PATH, migration_service=migration_service
            )
            logger.info(
                f"Created pure TrioDatabaseService for {self.config.DATABASE_PATH}"
            )
            return trio_db_service
        except Exception as e:
            logger.error(f"Failed to create TrioDatabaseService: {e}")
            raise

    def _create_llm_service(self) -> LLMService:
        """
        Create LLM service.

        Returns:
            Configured LLMService instance
        """
        logger.debug("Creating LLMService")

        if not self.config.GOOGLE_API_KEY:
            raise ConfigurationError("GOOGLE_API_KEY must be configured")

        try:
            model_name = getattr(self.config, "MODEL_NAME", "gemini-2.5-flash")
            llm_service = LLMService(
                api_key=self.config.GOOGLE_API_KEY, model_name=model_name
            )
            logger.info(f"Created LLMService with model {model_name}")
            return llm_service
        except Exception as e:
            logger.error(f"Failed to create LLMService: {e}")
            raise

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
            # StyleService uses default "src/styles" if no path provided
            style_service = StyleService()
            logger.info(f"Created StyleService with default styles directory")
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

    def create_intake_agent(self, user_context: UserContext):
        """
        Create intake agent with injected dependencies.

        Args:
            user_context: User context for this intake session

        Returns:
            IntakeAgent: Configured intake agent instance
        """
        from agents.trio_intake_agent import TrioIntakeAgent

        logger.debug(f"Creating TrioIntakeAgent for user {user_context.user_id}")

        try:
            agent = TrioIntakeAgent(
                llm_service=self.get("llm_service"),
                db_service=self.get("trio_db_service"),
                user_context=user_context,
            )
            logger.info(f"Created TrioIntakeAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create IntakeAgent: {e}")
            raise

    def create_assessment_agent(self, user_context: UserContext):
        """
        Create assessment agent with injected dependencies.

        Args:
            user_context: User context for this assessment session

        Returns:
            AssessmentAgent: Configured assessment agent instance
        """
        from agents.trio_assessment_agent import TrioAssessmentAgent

        logger.debug(f"Creating TrioAssessmentAgent for user {user_context.user_id}")

        try:
            # Create reflection agent dependency
            reflection_agent = self.create_reflection_agent(user_context)

            agent = TrioAssessmentAgent(
                llm_service=self.get("llm_service"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
                reflection_agent=reflection_agent,
            )
            logger.info(f"Created TrioAssessmentAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create AssessmentAgent: {e}")
            raise

    def create_psychoanalyst_agent(self, user_context: UserContext):
        """
        Create psychoanalyst agent with injected dependencies.

        Args:
            user_context: User context for this therapy session

        Returns:
            PsychoanalystAgent: Configured psychoanalyst agent instance
        """
        from agents.trio_psychoanalyst_agent import TrioPsychoanalystAgent

        logger.debug(f"Creating TrioPsychoanalystAgent for user {user_context.user_id}")

        try:
            agent = TrioPsychoanalystAgent(
                llm_service=self.get("llm_service"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
            )
            logger.info(
                f"Created TrioPsychoanalystAgent for user {user_context.user_id}"
            )
            return agent
        except Exception as e:
            logger.error(f"Failed to create PsychoanalystAgent: {e}")
            raise

    def create_reflection_agent(self, user_context: UserContext):
        """
        Create reflection agent with injected dependencies.

        Args:
            user_context: User context for this reflection session

        Returns:
            ReflectionAgent: Configured reflection agent instance
        """
        from agents.trio_reflection_agent import TrioReflectionAgent

        logger.debug(f"Creating TrioReflectionAgent for user {user_context.user_id}")

        try:
            # Create memory and planning agent dependencies
            memory_agent = self.create_memory_agent(user_context)
            planning_agent = self.create_planning_agent(user_context)

            agent = TrioReflectionAgent(
                llm_service=self.get("llm_service"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
                memory_agent=memory_agent,
                planning_agent=planning_agent,
            )
            logger.info(f"Created TrioReflectionAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create ReflectionAgent: {e}")
            raise

    def create_memory_agent(self, user_context: UserContext):
        """
        Create memory agent with injected dependencies.

        Args:
            user_context: User context for this memory session

        Returns:
            MemoryAgent: Configured memory agent instance
        """
        from agents.trio_memory_agent import TrioMemoryAgent

        logger.debug(f"Creating TrioMemoryAgent for user {user_context.user_id}")

        try:
            agent = TrioMemoryAgent(
                llm_service=self.get("llm_service"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
            )
            logger.info(f"Created TrioMemoryAgent for user {user_context.user_id}")
            return agent
        except Exception as e:
            logger.error(f"Failed to create MemoryAgent: {e}")
            raise

    def create_planning_agent(self, user_context: UserContext):
        """
        Create planning agent with injected dependencies.

        Args:
            user_context: User context for this planning session

        Returns:
            PlanningAgent: Configured planning agent instance
        """
        from agents.trio_planning_agent import TrioPlanningAgent

        logger.debug(f"Creating TrioPlanningAgent for user {user_context.user_id}")

        try:
            # Create memory agent dependency
            memory_agent = self.create_memory_agent(user_context)

            agent = TrioPlanningAgent(
                llm_service=self.get("llm_service"),
                db_service=self.get("trio_db_service"),
                rag_service=self.get("rag_service"),
                user_context=user_context,
                memory_agent=memory_agent,
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
            # Close database connection pool if it exists
            if "trio_db_service" in self._instances:
                try:
                    db_service = self._instances["trio_db_service"]
                    if hasattr(db_service, "_pool"):
                        # Close all connections in the pool
                        while not db_service._pool.empty():
                            try:
                                conn = db_service._pool.get_nowait()
                                conn.close()
                            except Exception:
                                pass
                        logger.debug("Closed database connection pool")
                except Exception as e:
                    logger.error(f"Error closing database connections: {e}")

            # Clear all instances
            self._instances.clear()
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
