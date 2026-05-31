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

from psychoanalyst_app.models.data_models import Message, Session, UserProfile, UserStatus

pytestmark = pytest.mark.trio


async def wait_for_message(ws, target_type: str, *, max_messages: int = 1000):
    """Receive messages until the desired type is found."""
    for _ in range(max_messages):
        msg = json.loads(await ws.get_message())
        if msg.get("type") == target_type:
            return msg
    raise AssertionError(f"Expected {target_type} message")


def _clear_in_memory_session_state(test_server_websocket, user_id: str) -> None:
    server = test_server_websocket["server"]
    session_id = server.orchestrator.get_active_session_id(user_id)
    server.orchestrator.session_lifecycle.active_sessions.clear_active_session(
        user_id, session_id
    )
    server.orchestrator.response_handler._assessment_recommendations.pop(user_id, None)


@pytest.fixture
async def test_user(test_server_websocket) -> UserProfile:
    profile = UserProfile(
        user_id="websocket_test_user",
        name="WebSocket Test User",
        data_of_birth=None,
        profession="Tester",
        status=UserStatus.PLAN_UPDATE_COMPLETE,
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
        connected_msg = await wait_for_message(ws, "connected")
        assert connected_msg["type"] == "connected"
        assert connected_msg["data"]["user_id"] == test_user.user_id
        assert connected_msg["data"]["name"] == test_user.name
        assert connected_msg["data"]["status"] == test_user.status.value

        session_started_msg = await wait_for_message(ws, "session_started")
        assert session_started_msg["type"] == "session_started"

        data = session_started_msg["data"]
        assert data["user_id"] == test_user.user_id
        assert isinstance(data["session_id"], str) and data["session_id"]
        assert isinstance(data["agent_type"], str) and data["agent_type"]
        assert isinstance(data["workflow_state"], str) and data["workflow_state"]
        assert isinstance(data["created_at"], str) and data["created_at"]

        workflow_next_action = await wait_for_message(ws, "workflow_next_action")
        required_action = workflow_next_action.get("data", {}).get("required_action")
        if required_action in {"start_intake", "continue_therapy"}:
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
async def test_ws_rejects_unknown_user(test_server_websocket):
    ws_url = f"{test_server_websocket['ws_url']}?user_id=missing_user"

    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        error_msg = await wait_for_message(ws, "error")
        assert "profile" in error_msg.get("data", {}).get("message", "").lower()

        with pytest.raises(ConnectionClosed):
            await ws.get_message()


@pytest.mark.integration
async def test_ws_workflow_next_action_follows_session_started(
    test_server_websocket, test_user
):
    ws_url = f"{test_server_websocket['ws_url']}?user_id={test_user.user_id}"

    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        session_started_index = None
        workflow_next_action_index = None
        message_types = []

        with trio.fail_after(5):
            for _ in range(50):
                msg = json.loads(await ws.get_message())
                msg_type = msg.get("type")
                message_types.append(msg_type)
                if msg_type == "session_started" and session_started_index is None:
                    session_started_index = len(message_types) - 1
                if (
                    msg_type == "workflow_next_action"
                    and workflow_next_action_index is None
                ):
                    workflow_next_action_index = len(message_types) - 1
                if (
                    session_started_index is not None
                    and workflow_next_action_index is not None
                ):
                    break

        assert session_started_index is not None, "Expected session_started event"
        assert workflow_next_action_index is not None, "Expected workflow_next_action event"
        assert session_started_index < workflow_next_action_index


@pytest.mark.integration
async def test_ws_reconnect_reemits_style_selection_state_from_persistence(
    test_server_websocket,
):
    """Reconnect after memory loss should restore style-selection state."""
    user_id = "websocket_reconnect_assessment_user"
    db_service = test_server_websocket["db_service"]
    profile = UserProfile(
        user_id=user_id,
        name="Reconnect Assessment User",
        data_of_birth=None,
        profession="Tester",
        status=UserStatus.ASSESSMENT_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    intake_session = Session(
        session_id="reconnect-intake-session",
        user_id=user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="Intake complete.",
                timestamp=datetime.now(),
                agent="INTAKE",
            )
        ],
        topics=[],
    )
    recommendations = [
        {
            "style_id": "cbt",
            "explanation": "Structured support fits the current goals.",
            "score": 0.9,
        }
    ]

    await db_service.save_user_profile(profile)
    await db_service.save_session(intake_session)
    await db_service.save_assessment_recommendations(
        user_id=user_id,
        intake_session_block_id=intake_session.session_id,
        recommendations=recommendations,
    )
    _clear_in_memory_session_state(test_server_websocket, user_id)

    ws_url = f"{test_server_websocket['ws_url']}?user_id={user_id}"
    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        session_started = await wait_for_message(ws, "session_started")
        assert session_started["data"]["user_id"] == user_id

        workflow_next_action = await wait_for_message(ws, "workflow_next_action")
        assert (
            workflow_next_action.get("data", {}).get("required_action")
            == "select_therapy_style"
        )

        assessment_recommendations = await wait_for_message(
            ws, "assessment_recommendations"
        )
        assert assessment_recommendations["data"]["user_id"] == user_id
        assert assessment_recommendations["data"]["recommendations"] == recommendations


@pytest.mark.integration
async def test_ws_reconnect_reuses_persisted_intake_session_after_memory_loss(
    test_server_websocket,
):
    """An intake user should rebind to the existing intake session on reconnect."""
    user_id = "websocket_reconnect_intake_user"
    db_service = test_server_websocket["db_service"]
    profile = UserProfile(
        user_id=user_id,
        name="Reconnect Intake User",
        data_of_birth=None,
        profession="Tester",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    intake_session = Session(
        session_id="persisted-intake-session",
        user_id=user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="Intake started.",
                timestamp=datetime.now(),
                agent="INTAKE",
            )
        ],
        topics=[],
    )

    await db_service.save_user_profile(profile)
    await db_service.save_session(intake_session)
    _clear_in_memory_session_state(test_server_websocket, user_id)

    ws_url = f"{test_server_websocket['ws_url']}?user_id={user_id}"
    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        _ = await wait_for_message(ws, "connected")
        session_started = await wait_for_message(ws, "session_started")

    assert session_started["data"]["session_id"] == intake_session.session_id
    assert test_server_websocket["server"].orchestrator.get_active_session_id(
        user_id
    ) == intake_session.session_id


@pytest.mark.integration
async def test_ws_chat_response_chunk_contract(test_server_websocket, test_user):
    ws_url = f"{test_server_websocket['ws_url']}?user_id={test_user.user_id}"

    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        _ = await wait_for_message(ws, "connected")
        _ = await wait_for_message(ws, "session_started")
        workflow_next_action = await wait_for_message(ws, "workflow_next_action")

        # Drain initial greeting if present so we only validate the response
        # to the explicit chat_message below.
        if workflow_next_action.get("data", {}).get("required_action") in {
            "start_intake",
            "continue_therapy",
        }:
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
async def test_ws_rejects_chat_while_initial_greeting_is_pending(
    test_server_websocket, test_user
):
    ws_url = f"{test_server_websocket['ws_url']}?user_id={test_user.user_id}"

    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        _ = await wait_for_message(ws, "connected")
        session_started = await wait_for_message(ws, "session_started")
        workflow_next_action = await wait_for_message(ws, "workflow_next_action")
        if workflow_next_action.get("data", {}).get("required_action") in {
            "start_intake",
            "continue_therapy",
        }:
            with trio.fail_after(5):
                for _ in range(1000):
                    msg = json.loads(await ws.get_message())
                    if (
                        msg.get("type") == "chat_response_chunk"
                        and msg.get("data", {}).get("is_complete")
                    ):
                        break

        session_id = session_started["data"]["session_id"]
        manager = test_server_websocket["server"].conversation_manager
        manager.mark_initial_greeting_pending(session_id)
        try:
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {"message": "Hello too early"},
                    }
                )
            )

            error = await wait_for_message(ws, "error")
            assert error["data"]["code"] == "chat_disabled_initial_greeting"
        finally:
            manager.mark_initial_greeting_complete(session_id)


@pytest.mark.integration
async def test_ws_end_session_contract(test_server_websocket, test_user):
    ws_url = f"{test_server_websocket['ws_url']}?user_id={test_user.user_id}"

    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://127.0.0.1")]
    ) as ws:
        _ = await wait_for_message(ws, "connected")
        _ = await wait_for_message(ws, "session_started")
        workflow_next_action = await wait_for_message(ws, "workflow_next_action")
        if workflow_next_action.get("data", {}).get("required_action") in {
            "start_intake",
            "continue_therapy",
        }:
            with trio.fail_after(5):
                for _ in range(1000):
                    msg = json.loads(await ws.get_message())
                    if msg.get("type") != "chat_response_chunk":
                        continue
                    if msg.get("data", {}).get("is_complete"):
                        break

        await ws.send_message(
            json.dumps({"type": "end_session", "data": {"reason": "User ended session"}})
        )

        session_ended = None
        with trio.fail_after(5):
            for _ in range(1000):
                msg = json.loads(await ws.get_message())
                if msg.get("type") != "session_ended":
                    continue
                session_ended = msg
                break

        assert session_ended is not None, "Expected a session_ended message"
        data = session_ended.get("data", {})
        assert data.get("reason") == "User ended session"
        assert data.get("workflow_state") in {
            "plan_update_in_progress",
            "plan_update_complete",
        }


@pytest.mark.integration
async def test_ws_missing_user_id_is_rejected(test_server_websocket):
    with pytest.raises((ConnectionRejected, ConnectionClosed)):
        async with open_websocket_url(
            test_server_websocket["ws_url"],
            extra_headers=[("Origin", "http://127.0.0.1")],
        ) as ws:
            await ws.get_message()
