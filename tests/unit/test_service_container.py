"""
Unit tests for ServiceContainer dependency injection system.
"""

import pytest
from unittest.mock import Mock, patch
from container.service_container import ServiceContainer
from context.user_context import UserContext
from config import Config
from exceptions import ConfigurationError


class TestServiceContainer:
    """Test ServiceContainer functionality."""
    
    @pytest.fixture
    def container(self):
        """Create service container for testing."""
        return ServiceContainer(Config)
    
    @pytest.fixture
    def user_context(self):
        """Create user context for testing."""
        return UserContext("test_user")
    
    def test_container_initialization(self, container):
        """Test container initializes correctly."""
        assert container is not None
        assert len(container._factories) > 0
        assert 'db_service' in container._factories
        assert 'llm_service' in container._factories
        assert 'rag_service' in container._factories
    
    def test_service_registration(self, container):
        """Test service registration and retrieval."""
        # Register a mock service
        mock_service = Mock()
        container.register('test_service', mock_service)
        
        # Retrieve the service
        retrieved = container.get('test_service')
        assert retrieved is mock_service
    
    def test_factory_registration(self, container):
        """Test factory registration."""
        mock_factory = Mock(return_value="test_instance")
        container.register_factory('test_factory', mock_factory)
        
        # Get service (should call factory)
        result = container.get('test_factory')
        assert result == "test_instance"
        mock_factory.assert_called_once()
    
    def test_singleton_behavior(self, container):
        """Test that services are singletons."""
        mock_factory = Mock(return_value="singleton_instance")
        container.register_factory('singleton_test', mock_factory)
        
        # Get service twice
        instance1 = container.get('singleton_test')
        instance2 = container.get('singleton_test')
        
        # Should be same instance
        assert instance1 is instance2
        # Factory should be called only once
        mock_factory.assert_called_once()
    
    def test_unknown_service_error(self, container):
        """Test error for unknown service."""
        with pytest.raises(ValueError, match="Unknown service: nonexistent"):
            container.get('nonexistent')
    
    def test_list_services(self, container):
        """Test listing services."""
        services = container.list_services()
        assert isinstance(services, dict)
        assert 'db_service' in services
        assert 'llm_service' in services
        assert 'rag_service' in services
        
        # None should be instantiated yet
        assert not any(services.values())
    
    def test_container_clear(self, container):
        """Test clearing container."""
        # Add a service
        container.register('test_service', Mock())
        assert 'test_service' in container._instances
        
        # Clear container
        container.clear()
        assert 'test_service' not in container._instances
        # Factories should be reset
        assert 'db_service' in container._factories
    
    def test_is_registered(self, container):
        """Test service registration check."""
        assert container.is_registered('db_service')
        assert container.is_registered('llm_service')
        assert not container.is_registered('nonexistent')
    
    def test_string_representation(self, container):
        """Test string representation."""
        str_repr = str(container)
        assert 'ServiceContainer' in str_repr
        assert 'services=' in str_repr
        
        repr_str = repr(container)
        assert 'ServiceContainer' in repr_str
        assert 'config=' in repr_str


class TestServiceContainerAgentCreation:
    """Test agent creation through container."""
    
    @pytest.fixture
    def container(self):
        """Create container with mocked services."""
        container = ServiceContainer(Config)
        
        # Mock services to avoid actual initialization
        container.register('db_service', Mock())
        container.register('llm_service', Mock())
        container.register('rag_service', Mock())
        
        return container
    
    @pytest.fixture
    def user_context(self):
        """Create user context for testing."""
        return UserContext("test_user")
    
    @patch('agents.intake_agent.IntakeAgent')
    def test_create_intake_agent(self, mock_intake_agent, container, user_context):
        """Test intake agent creation."""
        mock_agent = Mock()
        mock_intake_agent.return_value = mock_agent
        
        agent = container.create_intake_agent(user_context)
        
        assert agent is mock_agent
        mock_intake_agent.assert_called_once_with(
            llm_service=container.get('llm_service'),
            db_service=container.get('db_service'),
            user_context=user_context
        )
    
    @patch('agents.reflection_agent.ReflectionAgent')
    @patch('agents.assessment_agent.AssessmentAgent')
    def test_create_assessment_agent(self, mock_assessment_agent, mock_reflection_agent, container, user_context):
        """Test assessment agent creation."""
        mock_reflection = Mock()
        mock_assessment = Mock()
        mock_reflection_agent.return_value = mock_reflection
        mock_assessment_agent.return_value = mock_assessment
        
        agent = container.create_assessment_agent(user_context)
        
        assert agent is mock_assessment
        # Should create reflection agent first
        mock_reflection_agent.assert_called_once()
        # Then create assessment agent with reflection agent
        mock_assessment_agent.assert_called_once_with(
            llm_service=container.get('llm_service'),
            db_service=container.get('db_service'),
            rag_service=container.get('rag_service'),
            user_context=user_context,
            reflection_agent=mock_reflection
        )
    
    @patch('agents.psychoanalyst_agent.PsychoanalystAgent')
    def test_create_psychoanalyst_agent(self, mock_psychoanalyst_agent, container, user_context):
        """Test psychoanalyst agent creation."""
        mock_agent = Mock()
        mock_psychoanalyst_agent.return_value = mock_agent
        
        agent = container.create_psychoanalyst_agent(user_context)
        
        assert agent is mock_agent
        mock_psychoanalyst_agent.assert_called_once_with(
            llm_service=container.get('llm_service'),
            db_service=container.get('db_service'),
            rag_service=container.get('rag_service'),
            user_context=user_context
        )
    
    @patch('agents.reflection_agent.ReflectionAgent')
    @patch('agents.planning_agent.PlanningAgent')
    @patch('agents.memory_agent.MemoryAgent')
    def test_create_reflection_agent(self, mock_memory_agent, mock_planning_agent, mock_reflection_agent, container, user_context):
        """Test reflection agent creation."""
        mock_memory = Mock()
        mock_planning = Mock()
        mock_reflection = Mock()
        mock_memory_agent.return_value = mock_memory
        mock_planning_agent.return_value = mock_planning
        mock_reflection_agent.return_value = mock_reflection
        
        agent = container.create_reflection_agent(user_context)
        
        assert agent is mock_reflection
        # Should create memory agent twice (once for reflection, once for planning)
        assert mock_memory_agent.call_count == 2
        # Should create planning agent once
        mock_planning_agent.assert_called_once()
        # Then create reflection agent with both dependencies
        mock_reflection_agent.assert_called_once_with(
            llm_service=container.get('llm_service'),
            db_service=container.get('db_service'),
            rag_service=container.get('rag_service'),
            user_context=user_context,
            memory_agent=mock_memory,
            planning_agent=mock_planning
        )
    
    @patch('agents.memory_agent.MemoryAgent')
    def test_create_memory_agent(self, mock_memory_agent, container, user_context):
        """Test memory agent creation."""
        mock_agent = Mock()
        mock_memory_agent.return_value = mock_agent
        
        agent = container.create_memory_agent(user_context)
        
        assert agent is mock_agent
        mock_memory_agent.assert_called_once_with(
            llm_service=container.get('llm_service'),
            db_service=container.get('db_service'),
            rag_service=container.get('rag_service'),
            user_context=user_context
        )
    
    @patch('agents.planning_agent.PlanningAgent')
    @patch('agents.memory_agent.MemoryAgent')
    def test_create_planning_agent(self, mock_memory_agent, mock_planning_agent, container, user_context):
        """Test planning agent creation."""
        mock_memory = Mock()
        mock_planning = Mock()
        mock_memory_agent.return_value = mock_memory
        mock_planning_agent.return_value = mock_planning
        
        agent = container.create_planning_agent(user_context)
        
        assert agent is mock_planning
        # Should create memory agent first
        mock_memory_agent.assert_called_once_with(
            llm_service=container.get('llm_service'),
            db_service=container.get('db_service'),
            rag_service=container.get('rag_service'),
            user_context=user_context
        )
        # Then create planning agent with memory agent
        mock_planning_agent.assert_called_once_with(
            llm_service=container.get('llm_service'),
            db_service=container.get('db_service'),
            rag_service=container.get('rag_service'),
            user_context=user_context,
            memory_agent=mock_memory
        )


class TestServiceContainerHealthCheck:
    """Test container health check functionality."""
    
    @pytest.fixture
    def container(self):
        """Create container for health check tests."""
        return ServiceContainer(Config)
    
    def test_health_check_no_services(self, container):
        """Test health check with no instantiated services."""
        health = container.health_check()
        
        assert health['status'] == 'healthy'
        assert health['services'] == {}
        assert 'timestamp' in health
    
    def test_health_check_healthy_services(self, container):
        """Test health check with healthy services."""
        # Mock service with health check
        mock_service = Mock()
        mock_service.health_check.return_value = True
        container.register('healthy_service', mock_service)
        
        health = container.health_check()
        
        assert health['status'] == 'healthy'
        assert health['services']['healthy_service']['status'] == 'healthy'
    
    def test_health_check_unhealthy_services(self, container):
        """Test health check with unhealthy services."""
        # Mock unhealthy service
        mock_service = Mock()
        mock_service.health_check.return_value = False
        container.register('unhealthy_service', mock_service)
        
        health = container.health_check()
        
        assert health['status'] == 'unhealthy'
        assert health['services']['unhealthy_service']['status'] == 'unhealthy'
    
    def test_health_check_service_without_health_check(self, container):
        """Test health check with service that doesn't have health_check method."""
        # Mock service without health_check
        mock_service = Mock(spec=[])  # Empty spec means no methods
        container.register('no_health_check', mock_service)
        
        health = container.health_check()
        
        assert health['status'] == 'healthy'
        assert health['services']['no_health_check']['status'] == 'healthy'
    
    def test_health_check_service_health_check_exception(self, container):
        """Test health check when service health check raises exception."""
        # Mock service that raises exception
        mock_service = Mock()
        mock_service.health_check.side_effect = Exception("Health check failed")
        container.register('exception_service', mock_service)
        
        health = container.health_check()
        
        assert health['status'] == 'unhealthy'
        assert health['services']['exception_service']['status'] == 'unhealthy'
        assert 'error' in health['services']['exception_service']


class TestServiceContainerShutdown:
    """Test container shutdown functionality."""
    
    def test_shutdown_clears_instances(self):
        """Test that shutdown clears all instances."""
        container = ServiceContainer(Config)
        container.register('test_service', Mock())
        
        assert len(container._instances) > 0
        
        container.shutdown()
        
        assert len(container._instances) == 0
    
    @patch('container.service_container.DatabaseService')
    def test_shutdown_closes_database_connections(self, mock_db_service):
        """Test that shutdown closes database connections."""
        container = ServiceContainer(Config)
        
        # Mock database service with connection pool
        mock_db = Mock()
        mock_conn1 = Mock()
        mock_conn2 = Mock()
        
        # Setup queue behavior
        from queue import Queue
        pool_queue = Queue()
        pool_queue.put(mock_conn1)
        pool_queue.put(mock_conn2)
        
        mock_db._pool = pool_queue
        container._instances['db_service'] = mock_db
        
        container.shutdown()
        
        # Connections should be closed
        mock_conn1.close.assert_called_once()
        mock_conn2.close.assert_called_once()