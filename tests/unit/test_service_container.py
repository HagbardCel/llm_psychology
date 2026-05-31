"""
Unit tests for ServiceContainer dependency injection system.
"""

from unittest.mock import Mock, patch

import pytest

from psychoanalyst_app.config import Settings
from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.exceptions import ConfigurationError
from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor


class TestServiceContainer:
    """Test ServiceContainer functionality."""

    @pytest.fixture
    def container(self):
        """Create service container for testing."""
        return ServiceContainer(Settings())

    @pytest.fixture
    def user_context(self):
        """Create user context for testing."""
        return UserContext("test_user")

    def test_container_initialization(self, container):
        """Test container initializes correctly."""
        assert container is not None
        assert len(container._factories) > 0
        assert "trio_db_service" in container._factories
        assert "llm_service" in container._factories
        assert "rag_service" in container._factories

    def test_service_registration(self, container):
        """Test service registration and retrieval."""
        # Register a mock service
        mock_service = Mock()
        container.register("test_service", mock_service)

        # Retrieve the service
        retrieved = container.get("test_service")
        assert retrieved is mock_service

    def test_factory_registration(self, container):
        """Test factory registration."""
        mock_factory = Mock(return_value="test_instance")
        container.register_factory("test_factory", mock_factory)

        # Get service (should call factory)
        result = container.get("test_factory")
        assert result == "test_instance"
        mock_factory.assert_called_once()

    def test_singleton_behavior(self, container):
        """Test that services are singletons."""
        mock_factory = Mock(return_value="singleton_instance")
        container.register_factory("singleton_test", mock_factory)

        # Get service twice
        instance1 = container.get("singleton_test")
        instance2 = container.get("singleton_test")

        # Should be same instance
        assert instance1 is instance2
        # Factory should be called only once
        mock_factory.assert_called_once()

    def test_unknown_service_error(self, container):
        """Test error for unknown service."""
        with pytest.raises(ValueError, match="Unknown service: nonexistent"):
            container.get("nonexistent")

    def test_list_services(self, container):
        """Test listing services."""
        services = container.list_services()
        assert isinstance(services, dict)
        assert "trio_db_service" in services
        assert "llm_service" in services
        assert "rag_service" in services

        # None should be instantiated yet
        assert not any(services.values())

    def test_db_executor_uses_settings_configuration(self, tmp_path):
        """Test DB executor wiring honors pool size/timeout settings."""
        db_path = str(tmp_path / "container_db_executor.db")
        settings = Settings().model_copy(
            update={
                "DATABASE_PATH": db_path,
                "DATABASE_POOL_SIZE": 7,
                "DATABASE_POOL_TIMEOUT": 12,
            }
        )
        container = ServiceContainer(settings)

        executor = container.get("db_executor")

        assert isinstance(executor, TrioSQLiteExecutor)
        assert executor.pool_size == 7
        assert executor.connect_timeout_seconds == 12.0
        assert executor.pool_acquire_timeout_seconds == 12.0

    def test_migration_service_uses_database_timeout_setting(self, tmp_path):
        """Test migration service wiring honors DB timeout settings."""
        db_path = str(tmp_path / "container_migration_service.db")
        settings = Settings().model_copy(
            update={
                "DATABASE_PATH": db_path,
                "DATABASE_POOL_TIMEOUT": 12,
            }
        )
        container = ServiceContainer(settings)

        migration_service = container.get("migration_service")

        assert migration_service.busy_timeout_ms == 12000

    def test_llm_service_uses_logging_settings(self):
        """Test LLM service wiring honors payload logging settings."""
        settings = Settings(_env_file=None).model_copy(
            update={
                "GOOGLE_API_KEY": "test-api-key",
                "MODEL_NAME": "test-model",
                "LLM_CALL_LOGGING_ENABLED": True,
                "LLM_CALL_LOGGING_REDACT": False,
                "LLM_CALL_LOGGING_MAX_FIELD_CHARS": 777,
                "LLM_CALL_LOGGING_INCLUDE_CHUNKS": True,
            }
        )
        with patch(
            "psychoanalyst_app.services.llm_service.LLMService._build_llm_client",
            return_value=Mock(),
        ):
            container = ServiceContainer(settings)
            llm_service = container.get("llm_service")

        assert llm_service.llm_call_logging_enabled is True
        assert llm_service.llm_call_logging_redact is False
        assert llm_service.llm_call_logging_max_field_chars == 777
        assert llm_service.llm_call_logging_include_chunks is True

    def test_local_llm_service_does_not_require_google_api_key(self):
        """Test local providers can be wired without a Gemini key."""
        settings = Settings(_env_file=None).model_copy(
            update={
                "GOOGLE_API_KEY": "",
                "MODEL_NAME": "llama3.1",
                "LLM_PROVIDER": "ollama",
                "LLM_BASE_URL": "http://ollama:11434",
            }
        )
        with patch(
            "psychoanalyst_app.services.llm_service.LLMService._build_llm_client",
            return_value=Mock(),
        ):
            container = ServiceContainer(settings)
            llm_service = container.get("llm_service")

        assert llm_service.provider == "ollama"
        assert llm_service.model_name == "llama3.1"
        assert llm_service.base_url == "http://ollama:11434"

    def test_default_local_llm_service_does_not_require_google_api_key(self):
        """Test default local llama.cpp provider can be wired without a Gemini key."""
        settings = Settings(_env_file=None).model_copy(
            update={
                "GOOGLE_API_KEY": "",
                "MODEL_NAME": "local-model",
            }
        )
        with patch(
            "psychoanalyst_app.services.llm_service.LLMService._build_llm_client",
            return_value=Mock(),
        ):
            container = ServiceContainer(settings)
            llm_service = container.get("llm_service")

        assert llm_service.provider == "openai_compatible"
        assert llm_service.model_name == "local-model"
        assert llm_service.base_url == "http://host.docker.internal:8080/v1"

    def test_gemini_llm_service_requires_google_api_key(self):
        """Test Gemini still fails fast without a configured Google key."""
        settings = Settings(_env_file=None).model_copy(
            update={
                "GOOGLE_API_KEY": "",
                "MODEL_NAME": "gemini-3.0-flash",
                "LLM_PROVIDER": "gemini",
            }
        )
        container = ServiceContainer(settings)

        with pytest.raises(
            ConfigurationError, match="GOOGLE_API_KEY must be configured"
        ):
            container.get("llm_service")

    def test_llm_service_cache_includes_provider_and_base_url(self):
        """Test services are cached by provider/model/base URL, not model alone."""
        settings = Settings(_env_file=None).model_copy(
            update={
                "GOOGLE_API_KEY": "",
                "MODEL_NAME": "shared-model",
                "LLM_PROVIDER": "ollama",
                "LLM_BASE_URL": "http://ollama:11434",
            }
        )
        with patch(
            "psychoanalyst_app.services.llm_service.LLMService._build_llm_client",
            return_value=Mock(),
        ):
            from psychoanalyst_app.container.factories.llm import (
                get_or_create_llm_service_for_model,
            )

            container = ServiceContainer(settings)
            first = container.get("llm_service")
            container.config = settings.model_copy(
                update={
                    "LLM_PROVIDER": "lmstudio",
                    "LLM_BASE_URL": "http://lmstudio:1234/v1",
                }
            )
            second = get_or_create_llm_service_for_model(container, "shared-model")

        assert first is not second
        assert first.provider == "ollama"
        assert second.provider == "lmstudio"

    def test_container_clear(self, container):
        """Test clearing container."""
        # Add a service
        container.register("test_service", Mock())
        assert "test_service" in container._instances

        # Clear container
        container.clear()
        assert "test_service" not in container._instances
        # Factories should be reset
        assert "trio_db_service" in container._factories

    def test_is_registered(self, container):
        """Test service registration check."""
        assert container.is_registered("trio_db_service")
        assert container.is_registered("llm_service")
        assert not container.is_registered("nonexistent")

    def test_string_representation(self, container):
        """Test string representation."""
        str_repr = str(container)
        assert "ServiceContainer" in str_repr
        assert "services=" in str_repr

        repr_str = repr(container)
        assert "ServiceContainer" in repr_str
        assert "config=" in repr_str


class TestServiceContainerAgentCreation:
    """Test agent creation through container."""

    @pytest.fixture
    def container(self):
        """Create container with mocked services."""
        container = ServiceContainer(Settings())

        # Mock services to avoid actual initialization
        container.register("trio_db_service", Mock())
        container.register("llm_service", Mock())
        container.register("rag_service", Mock())
        container.register("style_service", Mock())

        return container

    @pytest.fixture
    def user_context(self):
        """Create user context for testing."""
        return UserContext("test_user")

    @patch("psychoanalyst_app.agents.trio_intake_agent.TrioIntakeAgent")
    def test_create_intake_agent(self, mock_intake_agent, container, user_context):
        """Test Trio intake agent creation."""
        mock_agent = Mock()
        mock_intake_agent.return_value = mock_agent

        agent = container.create_intake_agent(user_context)

        assert agent is mock_agent
        mock_intake_agent.assert_called_once_with(
            llm_service=container.get("llm_service_intake"),
            user_context=user_context,
            config=container.config,
        )

    @patch.object(ServiceContainer, "create_reflection_agent")
    @patch("psychoanalyst_app.agents.trio_assessment_agent.TrioAssessmentAgent")
    def test_create_assessment_agent(
        self,
        mock_assessment_agent,
        mock_create_reflection_agent,
        container,
        user_context,
    ):
        """Test Trio assessment agent creation."""
        mock_assessment = Mock()
        mock_assessment_agent.return_value = mock_assessment
        mock_reflection = Mock()
        mock_create_reflection_agent.return_value = mock_reflection

        agent = container.create_assessment_agent(user_context)

        assert agent is mock_assessment
        mock_create_reflection_agent.assert_called_once_with(user_context)
        mock_assessment_agent.assert_called_once_with(
            llm_service=container.get("llm_service_assessment"),
            db_service=container.get("trio_db_service"),
            rag_service=container.get("rag_service"),
            user_context=user_context,
            reflection_agent=mock_reflection,
            style_service=container.get("style_service"),
        )

    @patch.object(ServiceContainer, "create_reflection_agent")
    @patch("psychoanalyst_app.agents.trio_therapist_agent.TrioTherapistAgent")
    def test_create_therapist_agent(
        self,
        mock_therapist_agent,
        mock_create_reflection_agent,
        container,
        user_context,
    ):
        """Test Trio psychoanalyst agent creation."""
        mock_agent = Mock()
        mock_therapist_agent.return_value = mock_agent
        mock_reflection = Mock()
        mock_create_reflection_agent.return_value = mock_reflection

        agent = container.create_therapist_agent(user_context)

        assert agent is mock_agent
        mock_create_reflection_agent.assert_called_once_with(user_context)
        mock_therapist_agent.assert_called_once_with(
            llm_service=container.get("llm_service_therapist"),
            db_service=container.get("trio_db_service"),
            rag_service=container.get("rag_service"),
            reflection_agent=mock_reflection,
            style_service=container.get("style_service"),
            config=container.config,
        )

    @patch("psychoanalyst_app.agents.trio_reflection_agent.TrioReflectionAgent")
    @patch("psychoanalyst_app.agents.trio_planning_agent.TrioPlanningAgent")
    @patch("psychoanalyst_app.agents.trio_memory_agent.TrioMemoryAgent")
    def test_create_reflection_agent(
        self,
        mock_memory_agent,
        mock_planning_agent,
        mock_reflection_agent,
        container,
        user_context,
    ):
        """Test Trio reflection agent creation."""
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
        mock_memory_agent.assert_called_with(
            llm_service=container.get("llm_service_memory"),
            db_service=container.get("trio_db_service"),
            rag_service=container.get("rag_service"),
            user_context=user_context,
        )
        mock_planning_agent.assert_called_once_with(
            llm_service=container.get("llm_service_planning"),
            db_service=container.get("trio_db_service"),
            rag_service=container.get("rag_service"),
            user_context=user_context,
            memory_agent=mock_memory,
            style_service=container.get("style_service"),
        )
        mock_reflection_agent.assert_called_once_with(
            llm_service=container.get("llm_service_reflection"),
            db_service=container.get("trio_db_service"),
            rag_service=container.get("rag_service"),
            user_context=user_context,
            memory_agent=mock_memory,
            planning_agent=mock_planning,
            config=container.config,
        )

    @patch("psychoanalyst_app.agents.trio_memory_agent.TrioMemoryAgent")
    def test_create_memory_agent(self, mock_memory_agent, container, user_context):
        """Test Trio memory agent creation."""
        mock_agent = Mock()
        mock_memory_agent.return_value = mock_agent

        agent = container.create_memory_agent(user_context)

        assert agent is mock_agent
        mock_memory_agent.assert_called_once_with(
            llm_service=container.get("llm_service_memory"),
            db_service=container.get("trio_db_service"),
            rag_service=container.get("rag_service"),
            user_context=user_context,
        )

    @patch("psychoanalyst_app.agents.trio_planning_agent.TrioPlanningAgent")
    @patch("psychoanalyst_app.agents.trio_memory_agent.TrioMemoryAgent")
    def test_create_planning_agent(
        self, mock_memory_agent, mock_planning_agent, container, user_context
    ):
        """Test Trio planning agent creation."""
        mock_memory = Mock()
        mock_planning = Mock()
        mock_memory_agent.return_value = mock_memory
        mock_planning_agent.return_value = mock_planning

        agent = container.create_planning_agent(user_context)

        assert agent is mock_planning
        # Should create memory agent first
        mock_memory_agent.assert_called_once_with(
            llm_service=container.get("llm_service_memory"),
            db_service=container.get("trio_db_service"),
            rag_service=container.get("rag_service"),
            user_context=user_context,
        )
        # Then create planning agent with memory agent
        mock_planning_agent.assert_called_once_with(
            llm_service=container.get("llm_service_planning"),
            db_service=container.get("trio_db_service"),
            rag_service=container.get("rag_service"),
            user_context=user_context,
            memory_agent=mock_memory,
            style_service=container.get("style_service"),
        )


class TestServiceContainerHealthCheck:
    """Test container health check functionality."""

    @pytest.fixture
    def container(self):
        """Create container for health check tests."""
        return ServiceContainer(Settings())

    async def test_health_check_no_services(self, container):
        """Test health check with no instantiated services."""
        health = await container.health_check()

        assert health["status"] == "healthy"
        assert health["services"] == {}
        assert "timestamp" in health

    async def test_health_check_healthy_services(self, container):
        """Test health check with healthy services."""
        # Mock service with health check
        mock_service = Mock()
        mock_service.health_check.return_value = True
        container.register("healthy_service", mock_service)

        health = await container.health_check()

        assert health["status"] == "healthy"
        assert health["services"]["healthy_service"]["status"] == "healthy"

    async def test_health_check_unhealthy_services(self, container):
        """Test health check with unhealthy services."""
        # Mock unhealthy service
        mock_service = Mock()
        mock_service.health_check.return_value = False
        container.register("unhealthy_service", mock_service)

        health = await container.health_check()

        assert health["status"] == "unhealthy"
        assert health["services"]["unhealthy_service"]["status"] == "unhealthy"

    async def test_health_check_service_without_health_check(self, container):
        """Test health check with service that doesn't have health_check method."""
        # Mock service without health_check
        mock_service = Mock(spec=[])  # Empty spec means no methods
        container.register("no_health_check", mock_service)

        health = await container.health_check()

        assert health["status"] == "healthy"
        assert health["services"]["no_health_check"]["status"] == "healthy"

    async def test_health_check_service_health_check_exception(self, container):
        """Test health check when service health check raises exception."""
        # Mock service that raises exception
        mock_service = Mock()
        mock_service.health_check.side_effect = Exception("Health check failed")
        container.register("exception_service", mock_service)

        health = await container.health_check()

        assert health["status"] == "unhealthy"
        assert health["services"]["exception_service"]["status"] == "unhealthy"
        assert "error" in health["services"]["exception_service"]


class TestServiceContainerShutdown:
    """Test container shutdown functionality."""

    def test_shutdown_clears_instances(self):
        """Test that shutdown clears all instances."""
        container = ServiceContainer(Settings())
        container.register("test_service", Mock())

        assert len(container._instances) > 0

        container.shutdown()

        assert len(container._instances) == 0
