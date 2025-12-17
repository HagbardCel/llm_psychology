"""
Integration tests for the WebSocket protocol contract.

These tests start a real TrioServer instance (via `test_server_websocket`) and verify
that the messages exchanged match the documented protocol in `docs/WEBSOCKET_PROTOCOL.md`.
"""

import json
from datetime import datetime

import pytest
import trio
from trio_websocket import ConnectionClosed, ConnectionRejected, open_websocket_url

from models.data_models import UserProfile, UserStatus

pytestmark = pytest.mark.trio


@pytest.fixture
async def test_user(test_server_websocket) -> UserProfile:
    profile = UserProfile(
        user_id="websocket_test_user",
        name="WebSocket Test User",
        birthdate=None,
        profession="Tester",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    await test_server_websocket["db_service"].save_user_profile(profile)
    return profile


@pytest.mark.integration
async def test_ws_connected_and_session_started_contract(test_server_websocket, test_user):
    ws_url = f"{test_server_websocket['ws_url']}?user_id={test_user.user_id}"

    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        connected_msg = json.loads(await ws.get_message())
        assert connected_msg["type"] == "connected"
        assert connected_msg["data"]["user_id"] == test_user.user_id
        assert connected_msg["data"]["name"] == test_user.name
        assert connected_msg["data"]["status"] == test_user.status.value

        await ws.send_message(
            json.dumps({"type": "session_request", "data": {"session_type": "therapy"}})
        )

        session_started_msg = json.loads(await ws.get_message())
        assert session_started_msg["type"] == "session_started"

        data = session_started_msg["data"]
        assert data["user_id"] == test_user.user_id
        assert isinstance(data["session_id"], str) and data["session_id"]
        assert isinstance(data["agent_type"], str) and data["agent_type"]
        assert isinstance(data["workflow_state"], str) and data["workflow_state"]
        assert isinstance(data["created_at"], str) and data["created_at"]
        assert isinstance(data["has_initial_message"], bool)
        assert data["has_initial_message"] is True

        # When has_initial_message=true, the server streams an initial greeting
        # without requiring a user chat_message.
        greeting = ""
        with trio.fail_after(5):
            for _ in range(1000):
                msg = json.loads(await ws.get_message())
                if msg.get("type") != "chat_response_chunk":
                    continue
                chunk_data = msg.get("data", {})
                greeting += chunk_data.get("chunk", "")
                if chunk_data.get("is_complete"):
                    break
        assert greeting.strip(), "Expected a non-empty initial greeting"


@pytest.mark.integration
async def test_ws_chat_response_chunk_contract(test_server_websocket, test_user):
    ws_url = f"{test_server_websocket['ws_url']}?user_id={test_user.user_id}"

    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        _ = json.loads(await ws.get_message())  # connected

        await ws.send_message(
            json.dumps({"type": "session_request", "data": {"session_type": "therapy"}})
        )
        session_started_msg = json.loads(await ws.get_message())

        # Drain initial greeting if present so we only validate the response
        # to the explicit chat_message below.
        if session_started_msg.get("data", {}).get("has_initial_message"):
            with trio.fail_after(5):
                for _ in range(1000):
                    msg = json.loads(await ws.get_message())
                    if msg.get("type") != "chat_response_chunk":
                        continue
                    if msg.get("data", {}).get("is_complete"):
                        break

        await ws.send_message(
            json.dumps(
                {
                    "type": "chat_message",
                    "data": {"message": "Hello there"},
                }
            )
        )

        full_response = ""
        saw_complete = False

        # Read until completion (server sends an explicit completion message)
        for _ in range(1000):
            msg = json.loads(await ws.get_message())
            if msg.get("type") != "chat_response_chunk":
                continue

            chunk_data = msg.get("data", {})
            assert "chunk" in chunk_data
            assert "is_complete" in chunk_data
            assert isinstance(chunk_data["chunk"], str)
            assert isinstance(chunk_data["is_complete"], bool)

            full_response += chunk_data["chunk"]
            if chunk_data["is_complete"]:
                saw_complete = True
                break

        assert saw_complete, "Expected a completion chunk with is_complete=true"
        assert full_response.strip(), "Expected at least one non-empty chunk before completion"


@pytest.mark.integration
async def test_ws_missing_user_id_is_rejected(test_server_websocket):
    with pytest.raises((ConnectionRejected, ConnectionClosed)):
        async with open_websocket_url(
            test_server_websocket["ws_url"],
            extra_headers=[("Origin", "http://127.0.0.1")],
        ) as ws:
            await ws.get_message()
