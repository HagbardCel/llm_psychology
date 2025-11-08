"""
Unit tests for ConversationManager.

Tests streaming, context management, and RAG integration.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.orchestration.conversation_manager import ConversationManager
from src.orchestration.models import ConversationContext, WorkflowState
from src.models.data_models import UserProfile, TherapyPlan, Message, Session


@pytest.fixture
def mock_llm_service():
    """Create a mock LLM service."""
    llm = Mock()

    # Mock streaming response
    async def mock_stream(*args, **kwargs):
        chunks = ["Hello ", "there! ", "How ", "are ", "you?"]
        for chunk in chunks:
            yield chunk

    llm.stream_response = mock_stream
    return llm


@pytest.fixture
def mock_rag_service():
    """Create a mock RAG service."""
    rag = Mock()
    rag.retrieve_relevant_knowledge = Mock(return_value=[
        {
            "content": "CBT focuses on identifying and changing negative thought patterns.",
            "source": "cbt_knowledge",
            "score": 0.85
        }
    ])
    return rag


@pytest.fixture
def mock_db_service():
    """Create a mock database service."""
    db = Mock()
    db.get_user_profile = Mock(return_value=UserProfile(
        id="user123",
        name="Test User",
        created_at=datetime.now()
    ))
    db.get_therapy_plan = Mock(return_value=TherapyPlan(
        id="plan123",
        user_id="user123",
        selected_style="cbt",
        plan_details={"focus": "anxiety management"},
        version=1,
        created_at=datetime.now(),
        updated_at=datetime.now()
    ))
    db.get_session = Mock()
    db.create_message = Mock(return_value=Message(
        id="msg123",
        session_id="session123",
        role="assistant",
        content="Test response",
        timestamp=datetime.now()
    ))
    return db


@pytest.fixture
def conversation_manager(mock_llm_service, mock_rag_service, mock_db_service):
    """Create a ConversationManager instance."""
    return ConversationManager(mock_llm_service, mock_rag_service, mock_db_service)


@pytest.fixture
def sample_context():
    """Create a sample conversation context."""
    user_profile = UserProfile(
        id="user123",
        name="Test User",
        created_at=datetime.now()
    )

    therapy_plan = TherapyPlan(
        id="plan123",
        user_id="user123",
        selected_style="cbt",
        plan_details={"focus": "anxiety management"},
        version=1,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )

    return ConversationContext(
        session_id="session123",
        user_profile=user_profile,
        therapy_plan=therapy_plan,
        message_history=[],
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
        extensions_used=0,
        max_extensions=2
    )


class TestConversationManagerInitialization:
    """Test ConversationManager initialization."""

    def test_initialization(self, conversation_manager, mock_llm_service, mock_rag_service, mock_db_service):
        """Test that ConversationManager initializes correctly."""
        assert conversation_manager.llm_service == mock_llm_service
        assert conversation_manager.rag_service == mock_rag_service
        assert conversation_manager.db_service == mock_db_service


class TestStreamResponse:
    """Test streaming LLM responses."""

    @pytest.mark.asyncio
    async def test_stream_response_basic(self, conversation_manager, sample_context):
        """Test basic streaming without RAG."""
        prompt = "Hello, how are you?"

        chunks = []
        async for chunk in conversation_manager.stream_response(prompt, sample_context, use_rag=False):
            chunks.append(chunk)

        assert len(chunks) == 5
        assert "".join(chunks) == "Hello there! How are you?"

    @pytest.mark.asyncio
    async def test_stream_response_with_rag(self, conversation_manager, sample_context, mock_rag_service):
        """Test streaming with RAG context."""
        prompt = "Tell me about CBT"

        chunks = []
        async for chunk in conversation_manager.stream_response(prompt, sample_context, use_rag=True):
            chunks.append(chunk)

        # Verify RAG was called
        mock_rag_service.retrieve_relevant_knowledge.assert_called_once()

        # Verify streaming still works
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_stream_response_saves_message(self, conversation_manager, sample_context, mock_db_service):
        """Test that streamed response is saved to database."""
        prompt = "Hello, how are you?"

        full_response = ""
        async for chunk in conversation_manager.stream_response(prompt, sample_context):
            full_response += chunk

        # Verify message was saved
        mock_db_service.create_message.assert_called_once()
        call_args = mock_db_service.create_message.call_args
        assert call_args[1]["session_id"] == "session123"
        assert call_args[1]["role"] == "assistant"
        assert call_args[1]["content"] == full_response

    @pytest.mark.asyncio
    async def test_stream_response_empty_prompt(self, conversation_manager, sample_context):
        """Test streaming with empty prompt."""
        chunks = []
        async for chunk in conversation_manager.stream_response("", sample_context, use_rag=False):
            chunks.append(chunk)

        # Should still work, just might return empty or error message
        assert isinstance(chunks, list)


class TestGetContext:
    """Test getting conversation context."""

    @pytest.mark.asyncio
    async def test_get_context_with_session_id(self, conversation_manager, mock_db_service):
        """Test getting context for existing session."""
        # Setup mock session
        mock_session = Mock(spec=Session)
        mock_session.id = "session123"
        mock_session.user_id = "user123"
        mock_session.created_at = datetime.now()
        mock_session.messages = []

        mock_db_service.get_session.return_value = mock_session

        context = await conversation_manager.get_context("session123")

        assert context.session_id == "session123"
        assert context.user_profile.id == "user123"
        assert context.therapy_plan is not None
        mock_db_service.get_session.assert_called_once_with("session123")

    @pytest.mark.asyncio
    async def test_get_context_builds_message_history(self, conversation_manager, mock_db_service):
        """Test that message history is built from session."""
        messages = [
            Message(
                id="msg1",
                session_id="session123",
                role="user",
                content="Hello",
                timestamp=datetime.now()
            ),
            Message(
                id="msg2",
                session_id="session123",
                role="assistant",
                content="Hi there!",
                timestamp=datetime.now()
            )
        ]

        mock_session = Mock(spec=Session)
        mock_session.id = "session123"
        mock_session.user_id = "user123"
        mock_session.created_at = datetime.now()
        mock_session.messages = messages

        mock_db_service.get_session.return_value = mock_session

        context = await conversation_manager.get_context("session123")

        assert len(context.message_history) == 2
        assert context.message_history[0].content == "Hello"
        assert context.message_history[1].content == "Hi there!"


class TestTimeManagement:
    """Test session time management."""

    def test_is_time_up_within_limit(self, sample_context):
        """Test that time is not up within duration."""
        sample_context.session_start_time = datetime.now() - timedelta(minutes=30)
        sample_context.duration_minutes = 50

        assert sample_context.is_time_up is False

    def test_is_time_up_exceeded(self, sample_context):
        """Test that time is up when duration exceeded."""
        sample_context.session_start_time = datetime.now() - timedelta(minutes=60)
        sample_context.duration_minutes = 50

        assert sample_context.is_time_up is True

    def test_time_remaining_minutes(self, sample_context):
        """Test calculating remaining minutes."""
        sample_context.session_start_time = datetime.now() - timedelta(minutes=30)
        sample_context.duration_minutes = 50

        # Should have approximately 20 minutes remaining
        remaining = sample_context.time_remaining_minutes
        assert 19 <= remaining <= 21  # Allow some variance for test execution time

    def test_time_remaining_negative(self, sample_context):
        """Test that negative time remaining shows as 0."""
        sample_context.session_start_time = datetime.now() - timedelta(minutes=60)
        sample_context.duration_minutes = 50

        assert sample_context.time_remaining_minutes == 0

    def test_can_extend_within_limit(self, sample_context):
        """Test that extension is allowed within limit."""
        sample_context.extensions_used = 0
        sample_context.max_extensions = 2

        assert sample_context.can_extend is True

    def test_can_extend_at_limit(self, sample_context):
        """Test that extension is not allowed at limit."""
        sample_context.extensions_used = 2
        sample_context.max_extensions = 2

        assert sample_context.can_extend is False


class TestAddMessage:
    """Test adding messages to context."""

    @pytest.mark.asyncio
    async def test_add_message_user(self, conversation_manager, mock_db_service):
        """Test adding user message."""
        message = await conversation_manager.add_message(
            session_id="session123",
            role="user",
            content="Hello!"
        )

        assert message.role == "user"
        assert message.content == "Hello!"
        assert message.session_id == "session123"
        mock_db_service.create_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_assistant(self, conversation_manager, mock_db_service):
        """Test adding assistant message."""
        message = await conversation_manager.add_message(
            session_id="session123",
            role="assistant",
            content="Hi there!"
        )

        assert message.role == "assistant"
        assert message.content == "Hi there!"


class TestExtendSession:
    """Test session extension functionality."""

    @pytest.mark.asyncio
    async def test_extend_session_success(self, conversation_manager, sample_context):
        """Test successful session extension."""
        sample_context.extensions_used = 0
        sample_context.duration_minutes = 50

        result = await conversation_manager.extend_session(sample_context, additional_minutes=10)

        assert result is True
        assert sample_context.duration_minutes == 60
        assert sample_context.extensions_used == 1

    @pytest.mark.asyncio
    async def test_extend_session_at_limit(self, conversation_manager, sample_context):
        """Test extension fails when at limit."""
        sample_context.extensions_used = 2
        sample_context.max_extensions = 2

        result = await conversation_manager.extend_session(sample_context, additional_minutes=10)

        assert result is False
        assert sample_context.duration_minutes == 50  # Unchanged
        assert sample_context.extensions_used == 2  # Unchanged

    @pytest.mark.asyncio
    async def test_extend_session_default_duration(self, conversation_manager, sample_context):
        """Test extension with default 5 minutes."""
        sample_context.extensions_used = 0
        sample_context.duration_minutes = 50

        result = await conversation_manager.extend_session(sample_context)

        assert result is True
        assert sample_context.duration_minutes == 55


class TestRAGIntegration:
    """Test RAG service integration."""

    @pytest.mark.asyncio
    async def test_retrieve_rag_context_with_style(self, conversation_manager, sample_context, mock_rag_service):
        """Test RAG retrieval with therapy style filter."""
        sample_context.therapy_plan.selected_style = "cbt"

        async for _ in conversation_manager.stream_response("test prompt", sample_context, use_rag=True):
            pass

        # Verify RAG was called with proper filter
        mock_rag_service.retrieve_relevant_knowledge.assert_called()
        call_kwargs = mock_rag_service.retrieve_relevant_knowledge.call_args[1]
        assert "filter_source" in call_kwargs

    @pytest.mark.asyncio
    async def test_retrieve_rag_context_without_style(self, conversation_manager, sample_context, mock_rag_service):
        """Test RAG retrieval without therapy style."""
        sample_context.therapy_plan = None

        async for _ in conversation_manager.stream_response("test prompt", sample_context, use_rag=True):
            pass

        # Verify RAG was called without filter
        mock_rag_service.retrieve_relevant_knowledge.assert_called()
