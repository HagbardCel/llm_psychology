"""
Unit tests for WebSocketGateway.

Tests WebSocket event handling and streaming responses.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, call

from src.gateways.websocket_gateway import WebSocketGateway
from src.orchestration.models import WorkflowState, SessionInfo
from src.models.data_models import UserProfile


@pytest.fixture
def mock_sio():
    """Create a mock Socket.IO server."""
    sio = Mock()
    sio.emit = AsyncMock()
    return sio


@pytest.fixture
def mock_orchestrator():
    """Create a mock agent orchestrator."""
    orchestrator = Mock()

    # Mock streaming
    async def mock_process_message(*args, **kwargs):
        chunks = ["This ", "is ", "a ", "test ", "response."]
        for chunk in chunks:
            yield chunk

    orchestrator.process_message = mock_process_message
    orchestrator.get_user_state = AsyncMock(return_value=WorkflowState.THERAPY_IN_PROGRESS)
    orchestrator.start_session = AsyncMock()
    orchestrator.create_user_profile = AsyncMock()
    orchestrator.workflow_engine = Mock()
    orchestrator.workflow_engine.get_current_agent = Mock(return_value="PSYCHOANALYST")

    return orchestrator


@pytest.fixture
def mock_connection_manager():
    """Create a mock connection manager."""
    manager = Mock()
    manager.get_user_id = Mock(return_value="user123")
    manager.is_authenticated = Mock(return_value=True)
    return manager


@pytest.fixture
def gateway(mock_sio, mock_orchestrator, mock_connection_manager):
    """Create a WebSocketGateway instance."""
    return WebSocketGateway(mock_sio, mock_orchestrator, mock_connection_manager)


class TestWebSocketGatewayInitialization:
    """Test WebSocketGateway initialization."""

    def test_initialization(self, gateway, mock_sio, mock_orchestrator, mock_connection_manager):
        """Test that WebSocketGateway initializes correctly."""
        assert gateway.sio == mock_sio
        assert gateway.orchestrator == mock_orchestrator
        assert gateway.connection_manager == mock_connection_manager


class TestHandleChatMessage:
    """Test handling chat messages."""

    @pytest.mark.asyncio
    async def test_handle_chat_message_success(self, gateway, mock_sio, mock_connection_manager):
        """Test successful chat message handling with streaming."""
        # Setup
        data = {"message": "Hello, therapist!", "session_id": "session123"}

        # Execute
        await gateway.handle_chat_message("sid123", data)

        # Verify typing indicators
        assert mock_sio.emit.call_count >= 2  # At least typing_start and typing_stop
        typing_start_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "typing_start"]
        typing_stop_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "typing_stop"]
        assert len(typing_start_calls) >= 1
        assert len(typing_stop_calls) >= 1

        # Verify streaming chunks were emitted
        chunk_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "chat_response_chunk"]
        assert len(chunk_calls) > 0

        # Verify final complete message
        final_calls = [c for c in chunk_calls if c[0][1].get("is_complete") is True]
        assert len(final_calls) == 1
        assert final_calls[0][0][1]["full_response"] == "This is a test response."

    @pytest.mark.asyncio
    async def test_handle_chat_message_empty(self, gateway, mock_sio):
        """Test handling empty message."""
        data = {"message": "", "session_id": "session123"}

        await gateway.handle_chat_message("sid123", data)

        # Should emit error for empty message
        error_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "error"]
        assert len(error_calls) == 1
        assert "Empty message" in error_calls[0][0][1]["message"]

    @pytest.mark.asyncio
    async def test_handle_chat_message_not_authenticated(self, gateway, mock_sio, mock_connection_manager):
        """Test handling message from unauthenticated user."""
        mock_connection_manager.get_user_id.return_value = None

        data = {"message": "Hello", "session_id": "session123"}
        await gateway.handle_chat_message("sid123", data)

        # Should emit error for not authenticated
        error_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "error"]
        assert len(error_calls) == 1
        assert "Not authenticated" in error_calls[0][0][1]["message"]

    @pytest.mark.asyncio
    async def test_handle_chat_message_streaming_chunks(self, gateway, mock_sio):
        """Test that message is streamed chunk by chunk."""
        data = {"message": "Test message", "session_id": "session123"}

        await gateway.handle_chat_message("sid123", data)

        # Get all chunk emissions
        chunk_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "chat_response_chunk"]

        # Should have multiple incomplete chunks plus one complete
        incomplete_chunks = [c for c in chunk_calls if c[0][1].get("is_complete") is False]
        complete_chunks = [c for c in chunk_calls if c[0][1].get("is_complete") is True]

        assert len(incomplete_chunks) == 5  # "This ", "is ", "a ", "test ", "response."
        assert len(complete_chunks) == 1

        # Verify chunks are emitted in order
        assert incomplete_chunks[0][0][1]["chunk"] == "This "
        assert incomplete_chunks[1][0][1]["chunk"] == "is "
        assert incomplete_chunks[2][0][1]["chunk"] == "a "

    @pytest.mark.asyncio
    async def test_handle_chat_message_error_handling(self, gateway, mock_sio, mock_orchestrator):
        """Test error handling during message processing."""
        # Make orchestrator raise an error
        async def error_generator(*args, **kwargs):
            raise Exception("Processing error")
            yield

        mock_orchestrator.process_message = error_generator

        data = {"message": "Test", "session_id": "session123"}
        await gateway.handle_chat_message("sid123", data)

        # Should emit error and stop typing
        error_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "error"]
        typing_stop_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "typing_stop"]

        assert len(error_calls) >= 1
        assert len(typing_stop_calls) >= 1


class TestHandleSessionRequest:
    """Test handling session start requests."""

    @pytest.mark.asyncio
    async def test_handle_session_request_success(self, gateway, mock_sio, mock_orchestrator):
        """Test successful session start."""
        # Setup
        mock_orchestrator.start_session.return_value = SessionInfo(
            session_id="new_session123",
            agent_type="INTAKE",
            workflow_state=WorkflowState.INTAKE_IN_PROGRESS,
            user_id="user123",
            created_at=datetime.now()
        )

        data = {"type": "intake"}

        # Execute
        await gateway.handle_session_request("sid123", data)

        # Verify session_started event was emitted
        session_started_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "session_started"]
        assert len(session_started_calls) == 1

        event_data = session_started_calls[0][0][1]
        assert event_data["session_id"] == "new_session123"
        assert event_data["agent_type"] == "INTAKE"
        assert event_data["workflow_state"] == WorkflowState.INTAKE_IN_PROGRESS.value

    @pytest.mark.asyncio
    async def test_handle_session_request_not_authenticated(self, gateway, mock_sio, mock_connection_manager):
        """Test session request from unauthenticated user."""
        mock_connection_manager.get_user_id.return_value = None

        data = {"type": "therapy"}
        await gateway.handle_session_request("sid123", data)

        # Should emit error
        error_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "error"]
        assert len(error_calls) == 1


class TestHandleUserStatusRequest:
    """Test handling user status requests."""

    @pytest.mark.asyncio
    async def test_handle_user_status_success(self, gateway, mock_sio, mock_orchestrator):
        """Test successful user status request."""
        # Setup
        mock_orchestrator.get_user_state.return_value = WorkflowState.THERAPY_IN_PROGRESS
        mock_orchestrator.workflow_engine.get_current_agent.return_value = "PSYCHOANALYST"

        # Execute
        await gateway.handle_user_status_request("sid123")

        # Verify user_status event was emitted
        status_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "user_status"]
        assert len(status_calls) == 1

        status_data = status_calls[0][0][1]
        assert status_data["user_id"] == "user123"
        assert status_data["workflow_state"] == WorkflowState.THERAPY_IN_PROGRESS.value
        assert status_data["next_agent"] == "PSYCHOANALYST"

    @pytest.mark.asyncio
    async def test_handle_user_status_not_authenticated(self, gateway, mock_sio, mock_connection_manager):
        """Test status request from unauthenticated user."""
        mock_connection_manager.get_user_id.return_value = None

        await gateway.handle_user_status_request("sid123")

        # Should emit error
        error_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "error"]
        assert len(error_calls) == 1


class TestHandleStyleSelection:
    """Test handling therapy style selection."""

    @pytest.mark.asyncio
    async def test_handle_style_selection_success(self, gateway, mock_sio, mock_orchestrator):
        """Test successful style selection."""
        # Setup
        mock_orchestrator.service_container = Mock()
        assessment_agent = Mock()
        mock_orchestrator.service_container.get_assessment_agent.return_value = assessment_agent

        data = {"selected_style": "cbt"}

        # Execute
        await gateway.handle_style_selection("sid123", data)

        # Verify style_selected event was emitted
        style_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "style_selected"]
        assert len(style_calls) == 1

        event_data = style_calls[0][0][1]
        assert event_data["selected_style"] == "cbt"
        assert "CBT" in event_data["message"]

    @pytest.mark.asyncio
    async def test_handle_style_selection_no_style(self, gateway, mock_sio):
        """Test style selection without providing a style."""
        data = {}

        await gateway.handle_style_selection("sid123", data)

        # Should emit error
        error_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "error"]
        assert len(error_calls) == 1
        assert "No style selected" in error_calls[0][0][1]["message"]


class TestHandleSessionExtension:
    """Test handling session extension requests."""

    @pytest.mark.asyncio
    async def test_handle_session_extension_success(self, gateway, mock_sio):
        """Test successful session extension."""
        data = {"session_id": "session123"}

        await gateway.handle_session_extension("sid123", data)

        # Verify session_extended event was emitted
        extended_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "session_extended"]
        assert len(extended_calls) == 1

        event_data = extended_calls[0][0][1]
        assert event_data["session_id"] == "session123"
        assert event_data["additional_minutes"] == 5

    @pytest.mark.asyncio
    async def test_handle_session_extension_no_session_id(self, gateway, mock_sio):
        """Test extension request without session ID."""
        data = {}

        await gateway.handle_session_extension("sid123", data)

        # Should emit error
        error_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "error"]
        assert len(error_calls) == 1
        assert "No session ID" in error_calls[0][0][1]["message"]


class TestEmitPatterns:
    """Test Socket.IO emission patterns."""

    @pytest.mark.asyncio
    async def test_emit_to_correct_room(self, gateway, mock_sio):
        """Test that events are emitted to the correct socket ID."""
        data = {"message": "Test", "session_id": "session123"}

        await gateway.handle_chat_message("specific_sid", data)

        # All emits should go to the specific socket ID
        for call_args in mock_sio.emit.call_args_list:
            assert call_args[1]["room"] == "specific_sid"

    @pytest.mark.asyncio
    async def test_streaming_preserves_order(self, gateway, mock_sio):
        """Test that streaming chunks are emitted in order."""
        data = {"message": "Test", "session_id": "session123"}

        await gateway.handle_chat_message("sid123", data)

        # Get chunk calls in order
        chunk_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "chat_response_chunk"]
        incomplete_chunks = [c for c in chunk_calls if c[0][1].get("is_complete") is False]

        # Verify they're in the expected order
        expected_chunks = ["This ", "is ", "a ", "test ", "response."]
        actual_chunks = [c[0][1]["chunk"] for c in incomplete_chunks]

        assert actual_chunks == expected_chunks
