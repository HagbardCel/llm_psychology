"""
Integration tests for Trio WebSocket functionality using a real WebSocket client.
"""

import json
from datetime import datetime

import pytest
import trio
from trio_websocket import ConnectionClosed, ConnectionRejected, open_websocket_url

from config import settings
from container.service_container import ServiceContainer
from models.data_models import UserProfile, UserStatus
from trio_server import TrioServer

# Mark all tests in this file as Trio tests
pytestmark = pytest.mark.trio

# Use the loopback address for the test server
WEBSOCKET_URL = "ws://127.0.0.1:8002/ws"


@pytest.fixture
def app_config(tmp_path):
    """Create test configuration."""

    # Use temporary file database (in-memory doesn't work with Trio threading)
    test_db_path = str(tmp_path / "test_trio_websocket.db")

    # Create a modified copy of settings
    mock_settings = settings.model_copy(update={"DATABASE_PATH": test_db_path})
    return mock_settings


@pytest.fixture
async def service_container(app_config, mock_llm_service, mock_rag_service):
    """Create service container with test configuration."""
    container = ServiceContainer(app_config)

    # Mock services BEFORE getting trio_db_service to prevent llm_service creation
    container.register("llm_service", mock_llm_service)
    container.register("rag_service", mock_rag_service)

    trio_db_service = container.get("trio_db_service")
    await trio_db_service.initialize()

    yield container

    await trio_db_service.clear_all_data()


@pytest.fixture
async def trio_server(service_container):
    """Create Trio server instance for testing."""
    async with trio.open_nursery() as nursery:
        server = TrioServer(service_container, host="127.0.0.1", port=8002)
        server.nursery = nursery
        server._initialize_orchestration(nursery)
        yield server
        nursery.cancel_scope.cancel()


@pytest.fixture
async def test_user(service_container):
    """Create a test user profile."""
    trio_db_service = service_container.get("trio_db_service")

    user_profile = UserProfile(
        user_id="websocket_test_user",
        name="WebSocket Test User",
        birthdate=None,
        profession="Tester",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    await trio_db_service.save_user_profile(user_profile)
    return user_profile


async def start_test_server(trio_server, nursery):
    """Helper to start the server in the background."""
    await nursery.start(trio_server.run)


@pytest.mark.trio
@pytest.mark.integration
async def test_websocket_connection_and_session_request(trio_server, test_user):
    """
    Tests connecting to the WebSocket, sending a session_request,
    and receiving a session_started confirmation.
    """
    async with trio.open_nursery() as nursery:
        await nursery.start(trio_server.run)
        await trio.sleep(0.1)  # Give server time to start

        try:
            # Include user_id in WebSocket URL
            ws_url = f"{WEBSOCKET_URL}?user_id={test_user.user_id}"
            async with open_websocket_url(ws_url) as ws:
                # Receive connection confirmation
                conn_message = await ws.get_message()
                conn_data = json.loads(conn_message)
                assert conn_data["type"] == "connected"
                assert conn_data["data"]["user_id"] == test_user.user_id

                # 1. Send session_request
                await ws.send_message(
                    json.dumps(
                        {"type": "session_request", "data": {"session_type": "therapy"}}
                    )
                )

                # 2. Receive session_started
                message = await ws.get_message()
                data = json.loads(message)

                assert data["type"] == "session_started"
                assert data["data"]["user_id"] == test_user.user_id
                assert "session_id" in data["data"]

        except ConnectionClosed as e:
            pytest.fail(f"Connection was closed unexpectedly: {e}")
        finally:
            nursery.cancel_scope.cancel()


@pytest.mark.trio
@pytest.mark.integration
async def test_websocket_chat_message_flow(trio_server, test_user):
    """
    Tests sending a chat message and receiving a streamed response.
    """
    async with trio.open_nursery() as nursery:
        await nursery.start(trio_server.run)
        await trio.sleep(0.1)

        try:
            # Include user_id in WebSocket URL
            ws_url = f"{WEBSOCKET_URL}?user_id={test_user.user_id}"
            async with open_websocket_url(ws_url) as ws:
                # Receive connection confirmation
                conn_message = await ws.get_message()
                conn_data = json.loads(conn_message)
                assert conn_data["type"] == "connected"

                # 1. Start session
                await ws.send_message(
                    json.dumps({"type": "session_request", "data": {}})
                )
                session_started_msg = await ws.get_message()
                session_id = json.loads(session_started_msg)["data"]["session_id"]

                # 2. Send chat message
                await ws.send_message(
                    json.dumps(
                        {
                            "type": "chat_message",
                            "data": {
                                "user_id": test_user.user_id,
                                "message": "Hello there",
                                "session_id": session_id,
                            },
                        }
                    )
                )

                # 3. Receive streamed response
                full_response = ""
                is_complete = False
                with trio.move_on_after(10):  # 10 second timeout
                    while True:
                        message = await ws.get_message()
                        data = json.loads(message)
                        if data.get("type") == "chat_response_chunk":
                            full_response += data.get("data", {}).get("chunk", "")
                            if data.get("data", {}).get("is_complete"):
                                is_complete = True
                                break

                assert is_complete, "Stream was not marked as complete"
                assert len(full_response) > 0, "Did not receive a response message"

        except ConnectionClosed as e:
            pytest.fail(f"Connection was closed unexpectedly: {e}")
        finally:
            nursery.cancel_scope.cancel()


@pytest.mark.trio
@pytest.mark.integration
async def test_websocket_missing_user_id(trio_server):
    """
    Tests that the server rejects the connection if user_id is not provided.
    """
    async with trio.open_nursery() as nursery:
        await nursery.start(trio_server.run)
        await trio.sleep(0.1)

        # Test without user_id - should be rejected
        with pytest.raises(ConnectionRejected):
            async with open_websocket_url(WEBSOCKET_URL) as ws:
                # Should fail before we can send anything
                await ws.get_message()

        nursery.cancel_scope.cancel()
