"""
Centralized dependency injection container for the psychoanalyst application.

This module provides a comprehensive dependency injection system that manages
service lifecycles, handles dependencies, and supports both singleton and
factory patterns for service creation.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Callable, Optional, TypeVar, Type
from threading import Lock

from config import Config
from services.db_service import DatabaseService
from services.llm_service import LLMService
from services.rag_service import RAGService
from context.user_context import UserContext
from exceptions import ConfigurationError

T = TypeVar('T')

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
    
    def __init__(self, config: Config):
        """
        Initialize the service container.
        
        Args:
            config: Application configuration object
        """
        self.config = config
        self._instances: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._lock = Lock()
        self._initialized = False
        
        logger.info("Initializing ServiceContainer")
        self._setup_factories()
        logger.info("ServiceContainer initialized with factories")
    
    def _setup_factories(self) -> None:
        """Register service factories for dependency creation."""
        self._factories.update({
            'db_service': self._create_db_service,
            'llm_service': self._create_llm_service,
            'rag_service': self._create_rag_service,
            'migration_service': self._create_migration_service,
        })
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
                        logger.error(f"Failed to create {service_name}: {e}", exc_info=True)
                        raise ConfigurationError(f"Failed to create {service_name}: {e}")
        
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
    
    def list_services(self) -> Dict[str, bool]:
        """
        List all registered services and their instantiation status.
        
        Returns:
            Dictionary mapping service names to instantiation status
        """
        return {
            service: service in self._instances
            for service in self._factories.keys()
        }
    
    # Service Factory Methods
    
    def _create_db_service(self) -> DatabaseService:
        """
        Create database service with connection pooling.
        
        Returns:
            Configured DatabaseService instance
        """
        logger.debug("Creating DatabaseService")
        
        # Get pool size from configuration with default
        pool_size = getattr(self.config, 'DATABASE_POOL_SIZE', 5)
        
        try:
            db_service = DatabaseService(
                db_path=self.config.DATABASE_PATH,
                pool_size=pool_size
            )
            logger.info(f"Created DatabaseService with pool size {pool_size}")
            return db_service
        except Exception as e:
            logger.error(f"Failed to create DatabaseService: {e}")
            raise
    
    def _create_llm_service(self) -> LLMService:
        """
        Create LLM service.
        
        Returns:
            Configured LLMService instance
        """
        logger.debug("Creating LLMService")
        
        if not self.config.GOOGLE_API_KEY or self.config.GOOGLE_API_KEY == "your_actual_google_gemini_api_key_here":
            raise ConfigurationError("GOOGLE_API_KEY must be configured")
        
        try:
            model_name = getattr(self.config, 'MODEL_NAME', 'gemini-2.5-flash')
            llm_service = LLMService(
                api_key=self.config.GOOGLE_API_KEY,
                model_name=model_name
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
            rag_service = RAGService(
                domain_knowledge_path=self.config.DOMAIN_KNOWLEDGE_PATH,
                vector_db_path=self.config.VECTOR_DB_PATH
            )
            logger.info("Created RAGService")
            return rag_service
        except Exception as e:
            logger.error(f"Failed to create RAGService: {e}")
            raise
    
    def _create_migration_service(self):
        """
        Create migration service.
        
        Returns:
            Configured MigrationService instance
        """
        from services.migration_service import MigrationService
        
        logger.debug("Creating MigrationService")
        
        try:
            # Get migrations directory from config with default
            migrations_dir = getattr(self.config, 'MIGRATIONS_DIR', 'migrations')
            
            migration_service = MigrationService(
                db_service=self.get('db_service'),
                migrations_dir=migrations_dir
            )
            logger.info(f"Created MigrationService with directory {migrations_dir}")
            return migration_service
        except Exception as e:
            logger.error(f"Failed to create MigrationService: {e}")
            raise
    
    def __str__(self) -> str:
        """String representation of the container."""
        service_status = self.list_services()
        instantiated = sum(service_status.values())
        total = len(service_status)
        return f"ServiceContainer(services={total}, instantiated={instantiated})"
    
    def __repr__(self) -> str:
        """Detailed representation of the container."""
        return f"ServiceContainer(config={self.config.__class__.__name__}, services={list(self._factories.keys())})"
    
    # Agent Factory Methods
    
    def create_intake_agent(self, user_context: UserContext):
        """
        Create intake agent with injected dependencies.
        
        Args:
            user_context: User context for this intake session
            
        Returns:
            IntakeAgent: Configured intake agent instance
        """
        from agents.intake_agent import IntakeAgent
        
        logger.debug(f"Creating IntakeAgent for user {user_context.user_id}")
        
        try:
            agent = IntakeAgent(
                llm_service=self.get('llm_service'),
                db_service=self.get('db_service'),
                user_context=user_context
            )
            logger.info(f"Created IntakeAgent for user {user_context.user_id}")
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
        from agents.assessment_agent import AssessmentAgent
        
        logger.debug(f"Creating AssessmentAgent for user {user_context.user_id}")
        
        try:
            # Create reflection agent dependency
            reflection_agent = self.create_reflection_agent(user_context)
            
            agent = AssessmentAgent(
                llm_service=self.get('llm_service'),
                db_service=self.get('db_service'),
                rag_service=self.get('rag_service'),
                user_context=user_context,
                reflection_agent=reflection_agent
            )
            logger.info(f"Created AssessmentAgent for user {user_context.user_id}")
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
        from agents.psychoanalyst_agent import PsychoanalystAgent
        
        logger.debug(f"Creating PsychoanalystAgent for user {user_context.user_id}")
        
        try:
            agent = PsychoanalystAgent(
                llm_service=self.get('llm_service'),
                db_service=self.get('db_service'),
                rag_service=self.get('rag_service'),
                user_context=user_context
            )
            logger.info(f"Created PsychoanalystAgent for user {user_context.user_id}")
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
        from agents.reflection_agent import ReflectionAgent
        
        logger.debug(f"Creating ReflectionAgent for user {user_context.user_id}")
        
        try:
            # Create memory and planning agent dependencies
            memory_agent = self.create_memory_agent(user_context)
            planning_agent = self.create_planning_agent(user_context)
            
            agent = ReflectionAgent(
                llm_service=self.get('llm_service'),
                db_service=self.get('db_service'),
                rag_service=self.get('rag_service'),
                user_context=user_context,
                memory_agent=memory_agent,
                planning_agent=planning_agent
            )
            logger.info(f"Created ReflectionAgent for user {user_context.user_id}")
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
        from agents.memory_agent import MemoryAgent
        
        logger.debug(f"Creating MemoryAgent for user {user_context.user_id}")
        
        try:
            agent = MemoryAgent(
                llm_service=self.get('llm_service'),
                db_service=self.get('db_service'),
                rag_service=self.get('rag_service'),
                user_context=user_context
            )
            logger.info(f"Created MemoryAgent for user {user_context.user_id}")
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
        from agents.planning_agent import PlanningAgent
        
        logger.debug(f"Creating PlanningAgent for user {user_context.user_id}")
        
        try:
            # Create memory agent dependency
            memory_agent = self.create_memory_agent(user_context)
            
            agent = PlanningAgent(
                llm_service=self.get('llm_service'),
                db_service=self.get('db_service'),
                rag_service=self.get('rag_service'),
                user_context=user_context,
                memory_agent=memory_agent
            )
            logger.info(f"Created PlanningAgent for user {user_context.user_id}")
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
            if 'db_service' in self._instances:
                try:
                    db_service = self._instances['db_service']
                    if hasattr(db_service, '_pool'):
                        # Close all connections in the pool
                        while not db_service._pool.empty():
                            try:
                                conn = db_service._pool.get_nowait()
                                conn.close()
                            except:
                                pass
                        logger.debug("Closed database connection pool")
                except Exception as e:
                    logger.error(f"Error closing database connections: {e}")
            
            # Clear all instances
            self._instances.clear()
            logger.info("ServiceContainer shutdown complete")
    
    def health_check(self) -> dict:
        """
        Perform health check on all registered services.
        
        Returns:
            dict: Health status of all services
        """
        health_status = {
            'status': 'healthy',
            'services': {},
            'timestamp': datetime.now().isoformat()
        }
        
        overall_healthy = True
        
        # Check each service that has been instantiated
        for service_name, service in self._instances.items():
            try:
                if hasattr(service, 'health_check'):
                    service_healthy = service.health_check()
                    health_status['services'][service_name] = {
                        'status': 'healthy' if service_healthy else 'unhealthy'
                    }
                    if not service_healthy:
                        overall_healthy = False
                else:
                    # If service doesn't have health check, assume it's healthy
                    health_status['services'][service_name] = {'status': 'healthy'}
                    
            except Exception as e:
                health_status['services'][service_name] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
                overall_healthy = False
        
        health_status['status'] = 'healthy' if overall_healthy else 'unhealthy'
        
        return health_status