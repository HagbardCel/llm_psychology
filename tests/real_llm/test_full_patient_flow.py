"""
Comprehensive end-to-end integration test for the full patient journey.

This test simulates a complete new patient flow against a live server:
1.  Connects to the WebSocket.
2.  Verifies that the initial, LLM-generated prompt is specific and non-generic.
3.  Simulates a user providing their name.
4.  Engages in a multi-turn intake conversation.
5.  Triggers the assessment phase.
6.  Selects a therapy style.
7.  Starts the first therapy session and exchanges messages.
"""

import json
import os
import uuid

import httpx
import pytest
import trio
from trio_websocket import ConnectionClosed, open_websocket_url

# Mark all tests in this file as real-LLM E2E (not part of the default deterministic suite)
pytestmark = [pytest.mark.trio, pytest.mark.real_llm]

# Use the service name for container-to-container communication
SERVER_URL = "http://api-usertest:8000"
WEBSOCKET_URL = "ws://api-usertest:8000/ws"

# A list of known generic/placeholder prompts to test against.
GENERIC_PROMPTS = [
    "Hello, how can I help you today?",
    "Welcome to your therapy session.",
    "Please tell me what's on your mind.",
    "",
]


async def check_server_is_running():
    """Checks if the server is running before starting the test."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{SERVER_URL}/health")
            return (
                response.status_code == 200
                and response.json().get("status") == "healthy"
            )
    except httpx.ConnectError:
        return False


async def test_full_patient_journey_with_real_llm():
    """
    An end-to-end test simulating a new patient from initial greeting to therapy,
    validating that the initial prompt is non-generic.
    """
    import logging

    logger = logging.getLogger(__name__)

    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key or api_key == "test_mock_api_key_for_testing":
        pytest.fail(
            "GOOGLE_API_KEY must be configured with a real key when running "
            "real LLM tests (pass --no-mocks only after setting it)."
        )

    if not await check_server_is_running():
        pytest.skip(f"Server is not running at {SERVER_URL}. Skipping end-to-end test.")

    user_id = f"e2e_test_{uuid.uuid4().hex[:8]}"
    session_id = None
    received_events = {"chat_response_chunk": [], "session_started": [], "error": []}
    current_response_chunks = []

    async def websocket_receiver(ws):
        nonlocal current_response_chunks
        try:
            while True:
                message = await ws.get_message()
                data = json.loads(message)
                msg_type = data.get("type")
                if msg_type == "chat_response_chunk":
                    chunk_data = data.get("data", {})
                    current_response_chunks.append(chunk_data.get("chunk", ""))
                    if chunk_data.get("is_complete"):
                        full_response = "".join(current_response_chunks)
                        received_events["chat_response_chunk"].append(full_response)
                        current_response_chunks = []
                elif msg_type in received_events:
                    received_events[msg_type].append(data)
        except ConnectionClosed:
            logger.info("Receiver connection closed.")
        except Exception as e:
            logger.error(f"Receiver error: {e}")

    async def send_and_wait_for_response(ws, message_text, sid):
        """Sends a message and waits for the full response to be received."""
        received_events["chat_response_chunk"].clear()
        msg = {
            "type": "chat_message",
            "data": {"user_id": user_id, "message": message_text, "session_id": sid},
        }
        await ws.send_message(json.dumps(msg))

        # Wait for the response to be fully received
        with trio.move_on_after(60) as cancel_scope:
            while not received_events["chat_response_chunk"]:
                await trio.sleep(0.1)

        if cancel_scope.cancelled_caught:
            pytest.fail(f"Test timed out waiting for response to: '{message_text}'")

        return received_events["chat_response_chunk"][0]

    try:
        async with open_websocket_url(
            f"{WEBSOCKET_URL}?user_id={user_id}",
            extra_headers=[
                ("Origin", "http://localhost"),
            ],
        ) as ws:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(websocket_receiver, ws)
                await trio.sleep(0.2)  # Let receiver start

                # 1. Start session and get initial prompt
                logger.info("--- Phase 1: Verifying Initial Prompt ---")
                with trio.move_on_after(60) as cancel_scope:
                    while not received_events["chat_response_chunk"]:
                        await trio.sleep(0.1)

                if cancel_scope.cancelled_caught:
                    pytest.fail("Test timed out waiting for the initial server prompt.")

                assert received_events[
                    "session_started"
                ], "session_started event was not received."
                session_id = received_events["session_started"][-1]["data"]["session_id"]
                initial_prompt = received_events["chat_response_chunk"][0]

                logger.info(f"Received initial prompt: '{initial_prompt}'")
                assert initial_prompt, "The initial prompt was empty."
                assert (
                    initial_prompt.strip() not in GENERIC_PROMPTS
                ), "Initial prompt is a generic placeholder."
                assert (
                    len(initial_prompt.split()) > 5
                ), "Initial prompt seems too short."
                logger.info("✓ Initial prompt is specific and non-generic.")

                # 2. Intake Flow
                logger.info("\n--- Phase 2: Intake Conversation ---")
                name_response = await send_and_wait_for_response(
                    ws, "My name is Fabian", session_id
                )
                assert name_response, "Did not get a response to the name."
                logger.info("✓ Responded to name.")

                problem_response = await send_and_wait_for_response(
                    ws,
                    "I've been feeling anxious about an upcoming project.",
                    session_id,
                )
                assert (
                    problem_response
                ), "Did not get a response to the presenting problem."
                logger.info("✓ Responded to presenting problem.")

                # 3. Assessment and Style Selection
                logger.info("\n--- Phase 3: Assessment and Style Selection ---")
                assessment_prompt = await send_and_wait_for_response(
                    ws, "I'm ready to figure out a plan.", session_id
                )
                assert assessment_prompt, "Did not receive style recommendations."
                logger.info("✓ Received style recommendations.")

                style_selection_response = await send_and_wait_for_response(
                    ws, "I think I'd like to try CBT.", session_id
                )
                assert (
                    style_selection_response
                ), "Did not get a response to style selection."
                logger.info("✓ Responded to style selection.")

                # 4. First Therapy Session
                logger.info("\n--- Phase 4: First Therapy Session ---")
                therapy_start_response = await send_and_wait_for_response(
                    ws, "I'm ready to begin.", session_id
                )
                assert (
                    therapy_start_response
                ), "Did not get an opening for the therapy session."
                logger.info("✓ Received therapy session opening.")

                therapy_message_response = await send_and_wait_for_response(
                    ws, "The project at work is making me nervous.", session_id
                )
                assert (
                    therapy_message_response
                ), "Did not get a response to the first therapy message."
                logger.info("✓ Responded to first therapy message.")

                assert not received_events[
                    "error"
                ], f"Received errors during the test: {received_events['error']}"
                logger.info("\n✓ End-to-end patient flow test completed successfully!")

                nursery.cancel_scope.cancel()

    except Exception as e:
        pytest.fail(f"An unexpected error occurred during the test: {e}")
