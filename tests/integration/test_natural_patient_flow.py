"""
Integration test for natural patient flow (Intake -> Assessment -> Therapy).

This test relies on the agents' internal logic to trigger state transitions
(e.g., covering enough topics to complete intake) rather than manually forcing
state changes. It supports running against a real LLM via the --real-llm flag.
"""

import json
import logging
import uuid
from datetime import datetime
from unittest.mock import Mock

import pytest
import trio
from trio_websocket import open_websocket_url

from config import settings
from orchestration.models import WorkflowState

# Mark all tests in this file as Trio tests
pytestmark = pytest.mark.trio


@pytest.fixture
def test_settings(use_real_llm, tmp_path):
    """
    Override settings for test.
    Use a longer duration to prevent timeout during slow test execution.
    Use a temporary database.
    """
    # Create a modified copy of settings
    # We need to modify the global settings object for the test duration
    # This is a bit hacky but necessary since the agents read from global settings
    original_duration = settings.SESSION_DURATION_MINUTES
    original_db_path = settings.DATABASE_PATH

    settings.SESSION_DURATION_MINUTES = 2.0  # 2 minutes
    settings.DATABASE_PATH = str(tmp_path / "test_flow.db")

    yield settings

    # Restore original settings
    settings.SESSION_DURATION_MINUTES = original_duration
    settings.DATABASE_PATH = original_db_path


@pytest.fixture
def mock_llm_service_natural_flow():
    """
    Create a mock LLM service that provides responses conducive to natural flow.
    """
    llm = Mock()

    async def mock_stream(prompt, *args, **kwargs):
        """Stream mock responses based on context."""
        prompt_lower = prompt.lower()
        print(f"DEBUG: Mock LLM Prompt: {repr(prompt_lower)}")

        # Default chunks
        chunks = ["I ", "understand. ", "Please ", "tell ", "me ", "more."]

        if "intake" in prompt_lower or "name" in prompt_lower:
            if "hello" in prompt_lower:
                chunks = [
                    "Hello! ",
                    "I'm ",
                    "Dr. AI. ",
                    "What ",
                    "brings ",
                    "you ",
                    "here?",
                ]
            elif "anxious" in prompt_lower:
                chunks = [
                    "I ",
                    "hear ",
                    "that ",
                    "you're ",
                    "anxious. ",
                    "When ",
                    "did ",
                    "it ",
                    "start?",
                ]

        elif (
            "assessment" in prompt_lower and "transcript" in prompt_lower
        ) or "recommendations" in prompt_lower:
            chunks = [
                "Based ",
                "on ",
                "our ",
                "chat, ",
                "I ",
                "recommend:\n",
                "1. CBT\n",
                "2. Psychodynamic\n",
                "3. Humanistic\n",
                "Which ",
                "approach ",
                "resonates ",
                "with ",
                "you?",
            ]

        elif "therapy" in prompt_lower:
            if "cbt" in prompt_lower:
                chunks = ["Great ", "choice. ", "Let's ", "start ", "CBT."]
            else:
                chunks = ["Welcome ", "to ", "therapy. ", "How ", "are ", "you?"]

        return chunks

    llm.generate_response_stream = mock_stream

    def mock_generate_sync(prompt, *args, **kwargs):
        """Mock sync generation."""
        prompt_lower = prompt.lower()
        if "session briefing" in prompt_lower or "comprehensive review" in prompt_lower:
            return json.dumps(
                {
                    "briefing_type": "resumption",
                    "generated_at": datetime.now().isoformat(),
                    "session_count": 1,
                    "last_session_id": "test_session",
                    "last_session_date": datetime.now().date().isoformat(),
                    "narrative_handoff": "The patient expressed anxiety about work and relationships. We explored childhood origins.",
                    "patient_observations": "Patient was open but anxious.",
                    "plan_progression_notes": "Initial assessment completed.",
                    "relationship_quality": "building",
                    "continuity_points": ["Work stress", "Childhood anxiety"],
                    "emotional_summary": {
                        "last_session": "Anxious",
                        "trend": "stable",
                        "note": "Consistent anxiety",
                    },
                    "key_themes": [
                        {
                            "theme": "Anxiety",
                            "status": "ongoing",
                            "priority": "high",
                            "frequency": 1,
                            "first_appearance": "session_1",
                            "last_discussed": "session_1",
                        }
                    ],
                    "progress_highlights": ["Acknowledged anxiety"],
                    "unresolved_issues": ["Coping mechanisms"],
                    "recommended_approach": {
                        "opening_tone": "Warm and welcoming",
                        "opening_focus": "Check in on anxiety",
                        "things_to_avoid": "Overwhelming questions",
                        "suggested_questions": ["How have you been?", "Any changes?"],
                        "therapeutic_goals_for_session": ["Build rapport"],
                    },
                }
            )
        elif "summary" in prompt_lower:
            return "Session summary: Patient discussed anxiety."
        return "Mock response"

    llm.generate_response = mock_generate_sync

    # Mock structured response for assessment
    async def mock_structured(prompt, output_format=None):
        return {
            "raw_response": json.dumps(
                {
                    "recommendations": [
                        {"style": "CBT", "reason": "Good for anxiety"},
                        {"style": "Psychodynamic", "reason": "Explores past"},
                        {"style": "Humanistic", "reason": "Focuses on growth"},
                    ]
                }
            )
        }

    def mock_structured_sync(prompt, output_format=None):
        return {
            "raw_response": json.dumps(
                {
                    "focus": "CBT Focus",
                    "goals": "Reduce anxiety",
                    "techniques": "Cognitive Restructuring",
                    "themes": "Anxiety, Sleep",
                    "timeline": "8 weeks",
                    "recommendations": [
                        {"style": "CBT", "reason": "Good for anxiety"},
                        {"style": "FREUD", "reason": "Not suitable"},
                        {"style": "JUNG", "reason": "Not suitable"},
                    ],
                }
            )
        }

    llm.generate_structured_response = mock_structured_sync
    llm.generate_structured_response_async = mock_structured

    def mock_structured_sync(prompt, output_format=None):
        return {
            "raw_response": json.dumps(
                {
                    "focus": "CBT for anxiety",
                    "goals": "Reduce anxiety symptoms",
                    "techniques": "Cognitive restructuring",
                    "themes": "Anxiety, Coping",
                    "timeline": "12 weeks",
                    "recommendations": [
                        {"style": "CBT", "reason": "Good for anxiety"},
                        {"style": "Psychodynamic", "reason": "Explores past"},
                        {"style": "Humanistic", "reason": "Focuses on growth"},
                    ],
                }
            )
        }

    llm.generate_structured_response = mock_structured_sync

    async def mock_generate_async(prompt, *args, **kwargs):
        """Mock async generation."""
        return (
            "This patient seems suitable for this therapy style based on the session."
        )

    llm.generate_response_async = mock_generate_async

    return llm


@pytest.fixture
async def test_server(
    test_settings, use_real_llm, mock_llm_service_natural_flow, mock_rag_service
):
    """
    Start a test server with the appropriate LLM service (real or mock).
    """
    from container.service_container import ServiceContainer
    from trio_server import TrioServer

    # Create service container
    container = ServiceContainer(test_settings)

    # Register services
    if not use_real_llm:
        container.register("llm_service", mock_llm_service_natural_flow)
        print(f"DEBUG: mock_rag_service type: {type(mock_rag_service)}")
        container.register("rag_service", mock_rag_service)
    else:
        # For real LLM, we assume the container initializes the real service
        # if we don't override it. However, we need to make sure API key is set.
        if not test_settings.GOOGLE_API_KEY:
            pytest.skip("GOOGLE_API_KEY not set for real LLM test")
        print("DEBUG: Using real LLM and RAG services")

    # Initialize database
    db_service = container.get("trio_db_service")
    await db_service.initialize()

    # Find a free port
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = TrioServer(container, host="127.0.0.1", port=port)

    async with trio.open_nursery() as nursery:
        # Use nursery.start() to wait for server readiness signal
        await nursery.start(server.run)

        # Verify server is actually accepting connections via health check
        import httpx

        async with httpx.AsyncClient() as client:
            for _ in range(20):  # 2 seconds max (20 * 0.1s)
                try:
                    response = await client.get(
                        f"http://127.0.0.1:{port}/health", timeout=1.0
                    )
                    if response.status_code == 200:
                        break
                except Exception:
                    pass
                await trio.sleep(0.1)
            else:
                raise RuntimeError("Server failed to respond to health checks")

        # Now orchestrator is guaranteed to exist and server is ready
        yield {
            "url": f"http://127.0.0.1:{port}",
            "ws_url": f"ws://127.0.0.1:{port}",
            "orchestrator": server.orchestrator,
            "db_service": db_service,
        }

        nursery.cancel_scope.cancel()


@pytest.mark.timeout(300)  # 5 minutes for real LLM with rate limiting
@pytest.mark.slow
async def test_natural_patient_flow(test_server, use_real_llm):
    """
    Test the full patient flow driven by natural conversation logic.
    """
    logger = logging.getLogger(__name__)
    user_id = f"flow_test_{uuid.uuid4().hex[:8]}"

    logger.info(
        f"Starting natural flow test for user {user_id} (Real LLM: {use_real_llm})"
    )

    received_messages = []
    completion_events = []

    async def websocket_receiver(ws):
        """Receive and track WebSocket messages, including completion signals."""
        try:
            while True:
                message = await ws.get_message()
                data = json.loads(message)
                if data.get("type") == "chat_response_chunk":
                    if data["data"].get("is_complete"):
                        # Signal that response is complete
                        if completion_events:
                            completion_events[-1].set()
                elif data.get("type") == "session_started":
                    received_messages.append(data)
                elif data.get("type") == "error":
                    logger.error(f"Server error: {data}")
        except Exception:
            pass

    async def wait_for_response_complete(timeout=60):
        """Wait for the server to complete processing (is_complete signal)."""
        event = trio.Event()
        completion_events.append(event)
        with trio.fail_after(timeout):
            await event.wait()
        # Remove this event after it's triggered
        if event in completion_events:
            completion_events.remove(event)

    async with open_websocket_url(
        f"{test_server['ws_url']}/ws?user_id={user_id}",
        extra_headers=[("Origin", "http://localhost:5173")],
    ) as ws:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(websocket_receiver, ws)

            # 1. Start Session
            await ws.send_message(
                json.dumps(
                    {
                        "type": "session_request",
                        "data": {"user_id": user_id, "session_type": "therapy"},
                    }
                )
            )

            # Wait for session_started
            with trio.move_on_after(5):
                while not received_messages:
                    await trio.sleep(0.1)

            assert received_messages, "Did not receive session_started event"
            session_id = received_messages[0]["data"]["session_id"]
            logger.info(f"Test using session_id: {session_id}")

            # 2. Intake - Provide Name
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": "My name is TestUser",
                            "session_id": session_id,
                        },
                    }
                )
            )
            await wait_for_response_complete(timeout=30 if use_real_llm else 10)

            # Rate limiting: delay between API calls for real LLM
            if use_real_llm:
                await trio.sleep(2)

            # 3. Intake - Cover Topics to trigger completion
            # We need to send enough messages to cover ~80% of topics or wait for time
            # Topics: Problem, Symptoms, History, Family, Relationships, Work, Health, Mental Health, Substance, Coping, Support, Goals

            intake_inputs = [
                "I'm having a problem with anxiety.",  # Presenting Problem (problem)
                "I am experiencing symptoms of sleeplessness.",  # Current Symptoms (symptoms)
                "My history includes childhood anxiety.",  # Personal History (history)
                "My family background is complicated.",  # Family Background (family)
                "My relationship with my partner is strained.",  # Relationships (relationship)
                "My work is very stressful.",  # Work/School (work)
                "My physical health is good.",  # Physical Health (health)
                "I have no history of therapy.",  # Mental Health History (therapy)
                "I do not use drugs or alcohol.",  # Substance Use (drugs)
                "I cope by taking deep breaths.",  # Coping Mechanisms (cope)
                "I have a good support system.",  # Support System (support)
                "My goal is to reduce anxiety.",  # Goals for Therapy (goal)
            ]

            for i, msg in enumerate(intake_inputs):
                if not msg:
                    continue
                # Get current session ID (should be available from session_started event)
                # For simplicity in this test, we might just send to the active session if we tracked it
                # But we can also rely on the server handling the session lookup by user_id if session_id is missing/wrong?
                # The server expects a session_id. Let's get it.

                # Wait for session to be established if needed
                # In a real test we'd parse the session_started message.
                # For now, let's assume the orchestrator maintains state.

                await ws.send_message(
                    json.dumps(
                        {
                            "type": "chat_message",
                            "data": {
                                "user_id": user_id,
                                "message": msg,
                                "session_id": session_id,
                            },
                        }
                    )
                )

                # Wait for response completion before sending next message
                await wait_for_response_complete(timeout=30 if use_real_llm else 10)

                # Rate limiting: delay between API calls for real LLM
                if use_real_llm:
                    await trio.sleep(2)

                # Check if we transitioned early
                state = await test_server["orchestrator"].get_user_state(user_id)
                if state in [
                    WorkflowState.INTAKE_COMPLETE,
                    WorkflowState.ASSESSMENT_IN_PROGRESS,
                ]:
                    print(f"Intake completed early at message {i+1}")
                    break

            # 4. Check for Transition to Assessment
            # The agent should detect topic coverage and transition.
            # We can check the user state via the orchestrator.

            orchestrator = test_server["orchestrator"]

            # Poll for state change
            with trio.move_on_after(10):
                while True:
                    state = await orchestrator.get_user_state(user_id)
                    if state in [
                        WorkflowState.INTAKE_COMPLETE,
                        WorkflowState.ASSESSMENT_IN_PROGRESS,
                    ]:
                        break
                    await trio.sleep(0.5)

            assert state in [
                WorkflowState.INTAKE_COMPLETE,
                WorkflowState.ASSESSMENT_IN_PROGRESS,
            ], f"Failed to transition from Intake. Current state: {state}"
            logger.info("Successfully transitioned to Assessment phase")

            # 5. Assessment Phase
            # Send a message to get recommendations if not already received
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": "I'm ready for recommendations.",
                            "session_id": session_id,
                        },
                    }
                )
            )
            await wait_for_response_complete(timeout=30 if use_real_llm else 10)

            # Rate limiting: delay between API calls for real LLM
            if use_real_llm:
                await trio.sleep(2)

            # Select a style (this triggers plan creation with RAG)
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": "I'd like to try CBT.",
                            "session_id": session_id,
                        },
                    }
                )
            )
            # Plan creation with RAG can take 20-30s with real LLM
            await wait_for_response_complete(timeout=60 if use_real_llm else 10)

            # Rate limiting: delay between API calls for real LLM
            if use_real_llm:
                await trio.sleep(2)

            # 6. Check for Transition to Assessment Complete
            # After is_complete, state transition might take a moment
            poll_timeout = 30 if use_real_llm else 10
            with trio.move_on_after(poll_timeout):
                while True:
                    state = await orchestrator.get_user_state(user_id)
                    if state == WorkflowState.ASSESSMENT_COMPLETE:
                        break
                    await trio.sleep(0.5)

            assert (
                state == WorkflowState.ASSESSMENT_COMPLETE
            ), f"Failed to complete Assessment. Current state: {state}"
            logger.info("Successfully completed Assessment")

            # 7. Therapy Phase
            # We need to send a message to trigger the transition from ASSESSMENT_COMPLETE to THERAPY_IN_PROGRESS
            # The orchestrator should route this to the PsychoanalystAgent

            logger.info("Starting Therapy phase...")
            therapy_inputs = [
                "I'm ready to start.",
                "I've been feeling really anxious lately.",
                "It happens mostly at work.",
            ]

            for i, msg in enumerate(therapy_inputs):
                await ws.send_message(
                    json.dumps(
                        {
                            "type": "chat_message",
                            "data": {"message": msg, "session_id": session_id},
                        }
                    )
                )

                # Wait for response completion
                await wait_for_response_complete(timeout=30 if use_real_llm else 10)

                # Rate limiting: delay between API calls for real LLM
                if use_real_llm:
                    await trio.sleep(2)

                if i == 0:
                    # After first message, should be in THERAPY_IN_PROGRESS
                    state = await test_server["orchestrator"].get_user_state(user_id)
                    assert (
                        state == WorkflowState.THERAPY_IN_PROGRESS
                    ), f"Failed to transition to THERAPY_IN_PROGRESS. Current state: {state}"

            logger.info("Successfully verified Therapy phase")

            nursery.cancel_scope.cancel()
