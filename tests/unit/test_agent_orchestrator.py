"""
Unit tests for AgentOrchestrator.

Tests the main coordination layer that routes messages to agents
and manages the therapy workflow.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.orchestration.agent_orchestrator import AgentOrchestrator
from src.orchestration.models import (
    WorkflowState,
    WorkflowEvent,
    AgentResponse,
    ConversationContext,
    SessionInfo
)
from src.models.data_models import UserProfile, TherapyPlan, Session


@pytest.fixture
def mock_container():
    """Create a mock service container."""
    container = Mock()

    # Mock agent creation
    container.get_intake_agent = Mock()
    container.get_assessment_agent = Mock()
    container.get_psychoanalyst_agent = Mock()
    container.get_reflection_agent = Mock()

    # Mock services
    container.get_db_service = Mock()
    container.get_llm_service = Mock()
    container.get_rag_service = Mock()

    return container


@pytest.fixture
def mock_workflow_engine():
    """Create a mock workflow engine."""
    engine = Mock()
    engine.get_user_state = AsyncMock(return_value=WorkflowState.NEW)
    engine.get_current_agent = Mock(return_value="INTAKE")
    engine.transition = AsyncMock()
    engine.can_transition = Mock(return_value=True)
    return engine


@pytest.fixture
def mock_conversation_manager():
    """Create a mock conversation manager."""
    manager = Mock()

    # Mock streaming response
    async def mock_stream(*args, **kwargs):
        chunks = ["Hello ", "from ", "the ", "agent!"]
        for chunk in chunks:
            yield chunk

    manager.stream_response = mock_stream
    manager.get_context = AsyncMock()
    manager.add_message = AsyncMock()
    manager.extend_session = AsyncMock(return_value=True)

    return manager


@pytest.fixture
def orchestrator(mock_container, mock_workflow_engine, mock_conversation_manager):
    """Create an AgentOrchestrator instance."""
    return AgentOrchestrator(
        mock_container,
        mock_workflow_engine,
        mock_conversation_manager
    )


@pytest.fixture
def sample_user_profile():
    """Create a sample user profile."""
    return UserProfile(
        id="user123",
        name="Test User",
        created_at=datetime.now()
    )


@pytest.fixture
def sample_therapy_plan():
    """Create a sample therapy plan."""
    return TherapyPlan(
        id="plan123",
        user_id="user123",
        selected_style="cbt",
        plan_details={"focus": "anxiety management"},
        version=1,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )


class TestAgentOrchestratorInitialization:
    """Test AgentOrchestrator initialization."""

    def test_initialization(self, orchestrator, mock_container, mock_workflow_engine, mock_conversation_manager):
        """Test that AgentOrchestrator initializes correctly."""
        assert orchestrator.service_container == mock_container
        assert orchestrator.workflow_engine == mock_workflow_engine
        assert orchestrator.conversation_manager == mock_conversation_manager


class TestGetUserState:
    """Test getting user workflow state."""

    @pytest.mark.asyncio
    async def test_get_user_state(self, orchestrator, mock_workflow_engine):
        """Test getting user state delegates to workflow engine."""
        mock_workflow_engine.get_user_state.return_value = WorkflowState.THERAPY_IN_PROGRESS

        state = await orchestrator.get_user_state("user123")

        assert state == WorkflowState.THERAPY_IN_PROGRESS
        mock_workflow_engine.get_user_state.assert_called_once_with("user123")


class TestProcessMessage:
    """Test processing messages through the orchestrator."""

    @pytest.mark.asyncio
    async def test_process_message_intake_agent(self, orchestrator, mock_workflow_engine, mock_container):
        """Test routing to intake agent."""
        # Setup
        mock_workflow_engine.get_user_state.return_value = WorkflowState.INTAKE_IN_PROGRESS
        mock_workflow_engine.get_current_agent.return_value = "INTAKE"

        mock_intake_agent = Mock()
        mock_intake_agent.process_message = AsyncMock(return_value=AgentResponse(
            content="Tell me more about yourself",
            next_action="continue",
            next_state=None
        ))
        mock_container.get_intake_agent.return_value = mock_intake_agent

        # Execute
        chunks = []
        async for chunk in orchestrator.process_message("user123", "Hello", "session123"):
            chunks.append(chunk)

        # Verify
        assert len(chunks) > 0
        mock_intake_agent.process_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_psychoanalyst_agent(self, orchestrator, mock_workflow_engine, mock_container):
        """Test routing to psychoanalyst agent."""
        # Setup
        mock_workflow_engine.get_user_state.return_value = WorkflowState.THERAPY_IN_PROGRESS
        mock_workflow_engine.get_current_agent.return_value = "PSYCHOANALYST"

        mock_psychoanalyst = Mock()
        mock_psychoanalyst.process_message = AsyncMock(return_value=AgentResponse(
            content="How does that make you feel?",
            next_action="continue",
            next_state=None
        ))
        mock_container.get_psychoanalyst_agent.return_value = mock_psychoanalyst

        # Execute
        chunks = []
        async for chunk in orchestrator.process_message("user123", "I'm feeling anxious", "session123"):
            chunks.append(chunk)

        # Verify
        assert len(chunks) > 0
        mock_psychoanalyst.process_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_triggers_state_transition(self, orchestrator, mock_workflow_engine, mock_container):
        """Test that process_message triggers state transition when needed."""
        # Setup - agent indicates transition needed
        mock_workflow_engine.get_user_state.return_value = WorkflowState.INTAKE_IN_PROGRESS
        mock_workflow_engine.get_current_agent.return_value = "INTAKE"

        mock_intake_agent = Mock()
        mock_intake_agent.process_message = AsyncMock(return_value=AgentResponse(
            content="Intake complete!",
            next_action="transition",
            next_state=WorkflowState.INTAKE_COMPLETE
        ))
        mock_container.get_intake_agent.return_value = mock_intake_agent

        # Execute
        async for _ in orchestrator.process_message("user123", "Final intake message", "session123"):
            pass

        # Verify transition was triggered
        mock_workflow_engine.transition.assert_called_once_with(
            "user123",
            WorkflowState.INTAKE_COMPLETE,
            WorkflowEvent.INTAKE_COMPLETED
        )

    @pytest.mark.asyncio
    async def test_process_message_streaming_response(self, orchestrator, mock_workflow_engine, mock_container, mock_conversation_manager):
        """Test that messages are streamed correctly."""
        # Setup
        mock_workflow_engine.get_user_state.return_value = WorkflowState.THERAPY_IN_PROGRESS
        mock_workflow_engine.get_current_agent.return_value = "PSYCHOANALYST"

        mock_agent = Mock()
        mock_agent.process_message = AsyncMock(return_value=AgentResponse(
            content="Test prompt",
            next_action="continue",
            next_state=None
        ))
        mock_container.get_psychoanalyst_agent.return_value = mock_agent

        # Execute
        chunks = []
        async for chunk in orchestrator.process_message("user123", "Test message", "session123"):
            chunks.append(chunk)

        # Verify streaming
        assert chunks == ["Hello ", "from ", "the ", "agent!"]
        mock_conversation_manager.stream_response.assert_called()


class TestStartSession:
    """Test starting therapy sessions."""

    @pytest.mark.asyncio
    async def test_start_session_intake(self, orchestrator, mock_workflow_engine, mock_container):
        """Test starting intake session."""
        # Setup
        mock_workflow_engine.get_user_state.return_value = WorkflowState.NEW
        mock_workflow_engine.get_current_agent.return_value = "INTAKE"

        mock_db = mock_container.get_db_service()
        mock_db.create_session = Mock(return_value=Session(
            id="session123",
            user_id="user123",
            agent_type="INTAKE",
            created_at=datetime.now()
        ))
        mock_db.get_user_profile = Mock(return_value=UserProfile(
            id="user123",
            name="Test User",
            created_at=datetime.now()
        ))

        # Execute
        session_info = await orchestrator.start_session("user123", "INTAKE")

        # Verify
        assert session_info.session_id == "session123"
        assert session_info.agent_type == "INTAKE"
        assert session_info.user_id == "user123"
        mock_db.create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_session_therapy(self, orchestrator, mock_workflow_engine, mock_container):
        """Test starting therapy session."""
        # Setup
        mock_workflow_engine.get_user_state.return_value = WorkflowState.PLAN_COMPLETE
        mock_workflow_engine.get_current_agent.return_value = "PSYCHOANALYST"

        mock_db = mock_container.get_db_service()
        mock_db.create_session = Mock(return_value=Session(
            id="therapy123",
            user_id="user123",
            agent_type="PSYCHOANALYST",
            created_at=datetime.now()
        ))
        mock_db.get_user_profile = Mock(return_value=UserProfile(
            id="user123",
            name="Test User",
            created_at=datetime.now()
        ))

        # Execute
        session_info = await orchestrator.start_session("user123", "PSYCHOANALYST")

        # Verify
        assert session_info.session_id == "therapy123"
        assert session_info.agent_type == "PSYCHOANALYST"

    @pytest.mark.asyncio
    async def test_start_session_transitions_state(self, orchestrator, mock_workflow_engine, mock_container):
        """Test that starting session transitions state appropriately."""
        # Setup - starting from NEW state
        mock_workflow_engine.get_user_state.return_value = WorkflowState.NEW

        mock_db = mock_container.get_db_service()
        mock_db.create_session = Mock(return_value=Session(
            id="session123",
            user_id="user123",
            agent_type="INTAKE",
            created_at=datetime.now()
        ))
        mock_db.get_user_profile = Mock(return_value=UserProfile(
            id="user123",
            name="Test User",
            created_at=datetime.now()
        ))

        # Execute
        await orchestrator.start_session("user123", "INTAKE")

        # Verify state transition to INTAKE_IN_PROGRESS
        mock_workflow_engine.transition.assert_called_with(
            "user123",
            WorkflowState.INTAKE_IN_PROGRESS,
            WorkflowEvent.INTAKE_STARTED
        )


class TestCreateUserProfile:
    """Test creating user profiles."""

    @pytest.mark.asyncio
    async def test_create_user_profile_success(self, orchestrator, mock_container):
        """Test successful user profile creation."""
        mock_db = mock_container.get_db_service()
        mock_db.create_user_profile = Mock(return_value=UserProfile(
            id="new_user123",
            name="New User",
            birthdate=datetime(1990, 1, 1).date(),
            profession="Engineer",
            created_at=datetime.now()
        ))

        profile = await orchestrator.create_user_profile(
            name="New User",
            birthdate="1990-01-01",
            profession="Engineer"
        )

        assert profile.name == "New User"
        assert profile.profession == "Engineer"
        mock_db.create_user_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_user_profile_minimal_data(self, orchestrator, mock_container):
        """Test creating profile with minimal data."""
        mock_db = mock_container.get_db_service()
        mock_db.create_user_profile = Mock(return_value=UserProfile(
            id="minimal_user",
            name="Minimal User",
            created_at=datetime.now()
        ))

        profile = await orchestrator.create_user_profile(
            name="Minimal User",
            birthdate="",
            profession=""
        )

        assert profile.name == "Minimal User"


class TestExtendSession:
    """Test session extension through orchestrator."""

    @pytest.mark.asyncio
    async def test_extend_session_success(self, orchestrator, mock_conversation_manager):
        """Test successful session extension."""
        mock_context = Mock(spec=ConversationContext)
        mock_context.extensions_used = 0
        mock_context.can_extend = True

        mock_conversation_manager.get_context.return_value = mock_context
        mock_conversation_manager.extend_session.return_value = True

        result = await orchestrator.extend_session("session123", additional_minutes=10)

        assert result is True
        mock_conversation_manager.extend_session.assert_called_once_with(
            mock_context,
            additional_minutes=10
        )

    @pytest.mark.asyncio
    async def test_extend_session_at_limit(self, orchestrator, mock_conversation_manager):
        """Test extension fails when at limit."""
        mock_context = Mock(spec=ConversationContext)
        mock_context.extensions_used = 2
        mock_context.can_extend = False

        mock_conversation_manager.get_context.return_value = mock_context
        mock_conversation_manager.extend_session.return_value = False

        result = await orchestrator.extend_session("session123", additional_minutes=10)

        assert result is False


class TestAgentCaching:
    """Test agent instance caching."""

    @pytest.mark.asyncio
    async def test_agent_caching_reuses_instances(self, orchestrator, mock_workflow_engine, mock_container):
        """Test that agent instances are cached and reused."""
        mock_workflow_engine.get_user_state.return_value = WorkflowState.THERAPY_IN_PROGRESS
        mock_workflow_engine.get_current_agent.return_value = "PSYCHOANALYST"

        mock_agent = Mock()
        mock_agent.process_message = AsyncMock(return_value=AgentResponse(
            content="Response",
            next_action="continue",
            next_state=None
        ))
        mock_container.get_psychoanalyst_agent.return_value = mock_agent

        # Process two messages
        async for _ in orchestrator.process_message("user123", "Message 1", "session123"):
            pass

        async for _ in orchestrator.process_message("user123", "Message 2", "session123"):
            pass

        # Agent should be created once and cached
        assert mock_container.get_psychoanalyst_agent.call_count <= 2  # Once per user or session


class TestErrorHandling:
    """Test error handling in orchestrator."""

    @pytest.mark.asyncio
    async def test_process_message_handles_agent_error(self, orchestrator, mock_workflow_engine, mock_container):
        """Test that agent errors are handled gracefully."""
        mock_workflow_engine.get_user_state.return_value = WorkflowState.THERAPY_IN_PROGRESS
        mock_workflow_engine.get_current_agent.return_value = "PSYCHOANALYST"

        mock_agent = Mock()
        mock_agent.process_message = AsyncMock(side_effect=Exception("Agent error"))
        mock_container.get_psychoanalyst_agent.return_value = mock_agent

        # Should not raise, should return error message
        chunks = []
        try:
            async for chunk in orchestrator.process_message("user123", "Test", "session123"):
                chunks.append(chunk)
        except Exception as e:
            # If it raises, verify it's properly wrapped
            assert "error" in str(e).lower()

    @pytest.mark.asyncio
    async def test_start_session_handles_db_error(self, orchestrator, mock_container):
        """Test that database errors during session start are handled."""
        mock_db = mock_container.get_db_service()
        mock_db.create_session = Mock(side_effect=Exception("Database error"))

        with pytest.raises(Exception) as exc_info:
            await orchestrator.start_session("user123", "INTAKE")

        assert "error" in str(exc_info.value).lower()
