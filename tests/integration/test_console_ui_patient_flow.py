"""
Comprehensive integration test for console UI patient flow using Trio.

This test simulates a complete new patient journey through the console UI:
1. Connection and name collection (NEW state)
2. Intake conversation (2+ messages)
3. Assessment recommendations and style selection
4. First therapy session (2+ messages)

The test uses trio-websocket to match the console_client.py implementation.
"""

import json
import uuid
from datetime import datetime
from unittest.mock import Mock

import httpx
import pytest
import trio
from trio_websocket import ConnectionClosed, open_websocket_url

from psychoanalyst_app.orchestration.models import WorkflowEvent, WorkflowState


@pytest.fixture(scope="function")
def mock_llm_service_with_context():
    """Create a mock LLM service with contextual responses."""
    llm = Mock()

    # Define contextual responses based on prompts
    async def mock_stream(prompt, *args, **kwargs):
        """Stream mock responses based on context - returns list of chunks."""
        prompt_lower = prompt.lower()

        # Intake responses
        if "intake" in prompt_lower or "name" in prompt_lower:
            if "hello" in prompt_lower or "great to meet you" in prompt_lower:
                # Initial greeting after name
                chunks = [
                    "Hello ",
                    "Fabian, ",
                    "welcome! ",
                    "I'm here ",
                    "to help you. ",
                    "Let's start ",
                    "by understanding ",
                    "what brings ",
                    "you here ",
                    "today. ",
                    "What has ",
                    "been on ",
                    "your mind ",
                    "lately?",
                ]
            elif any(word in prompt_lower for word in ["anxious", "anxiety", "stress"]):
                # Follow-up to anxiety mention
                chunks = [
                    "I hear ",
                    "that you've ",
                    "been feeling ",
                    "anxious. ",
                    "That must ",
                    "be difficult. ",
                    "Can you ",
                    "tell me ",
                    "more about ",
                    "when these ",
                    "feelings started? ",
                    "What situations ",
                    "tend to ",
                    "trigger them?",
                ]
            elif any(word in prompt_lower for word in ["work", "manager", "job"]):
                # Follow-up about work
                chunks = [
                    "Work-related ",
                    "stress can ",
                    "really affect ",
                    "our wellbeing. ",
                    "It sounds ",
                    "like this ",
                    "has been ",
                    "going on ",
                    "for a while. ",
                    "How has ",
                    "this been ",
                    "impacting ",
                    "other areas ",
                    "of your life?",
                ]
            else:
                # Generic intake response
                chunks = [
                    "Thank you ",
                    "for sharing ",
                    "that with me. ",
                    "I'd like ",
                    "to understand ",
                    "more. ",
                    "Can you ",
                    "tell me ",
                    "about your ",
                    "support system?",
                ]

        # Assessment responses
        elif "assessment" in prompt_lower or "recommend" in prompt_lower:
            chunks = [
                "Based on ",
                "your intake, ",
                "I can recommend ",
                "three therapeutic ",
                "approaches:\n\n",
                "1. **CBT** - ",
                "Cognitive Behavioral Therapy ",
                "focuses on ",
                "identifying and ",
                "changing negative ",
                "thought patterns.\n\n",
                "2. **Freud** - ",
                "Psychodynamic therapy ",
                "explores unconscious ",
                "patterns.\n\n",
                "3. **Jung** - ",
                "Analytical psychology ",
                "focuses on ",
                "personal growth.\n\n",
                "Which approach ",
                "resonates with you?",
            ]

        # Therapy session responses
        elif (
            "therapy" in prompt_lower
            or "session" in prompt_lower
            or "cbt" in prompt_lower
        ):
            if "ready to begin" in prompt_lower or "first session" in prompt_lower:
                # Opening therapy session
                chunks = [
                    "Welcome to ",
                    "your first ",
                    "therapy session. ",
                    "I'm glad ",
                    "you're here. ",
                    "In CBT, ",
                    "we'll work ",
                    "together to ",
                    "identify thought ",
                    "patterns that ",
                    "may be ",
                    "contributing to ",
                    "your anxiety. ",
                    "What would ",
                    "you like ",
                    "to focus on ",
                    "today?",
                ]
            elif "anxious" in prompt_lower or "worried" in prompt_lower:
                # Therapeutic response to anxiety
                chunks = [
                    "I understand ",
                    "you're feeling ",
                    "anxious. ",
                    "Let's explore ",
                    "that together. ",
                    "When you ",
                    "notice these ",
                    "anxious feelings, ",
                    "what thoughts ",
                    "are going ",
                    "through your ",
                    "mind? ",
                    "Can you ",
                    "identify any ",
                    "specific worries?",
                ]
            elif "thought" in prompt_lower or "think" in prompt_lower:
                # Response to thoughts
                chunks = [
                    "That's an ",
                    "important insight. ",
                    "In CBT, ",
                    "we call these ",
                    "automatic thoughts. ",
                    "Let's examine ",
                    "if this ",
                    "thought is ",
                    "based on ",
                    "facts or ",
                    "assumptions. ",
                    "What evidence ",
                    "supports this ",
                    "thought? ",
                    "What evidence ",
                    "contradicts it?",
                ]
            else:
                # Generic therapy response
                chunks = [
                    "Thank you ",
                    "for sharing. ",
                    "How does ",
                    "that make ",
                    "you feel? ",
                    "Let's explore ",
                    "this further.",
                ]
        else:
            # Fallback response
            chunks = ["Thank you. ", "Please continue."]

        # Return list of chunks (not yield)
        return chunks

    llm.generate_response_stream = mock_stream

    async def mock_stream_response(prompt, *args, **kwargs):
        chunks = await mock_stream(prompt, *args, **kwargs)
        for chunk in chunks:
            yield chunk

    llm.stream_response = mock_stream_response
    llm.generate_response = Mock(return_value="This is a generated response.")

    # Structured outputs: used by Tier extraction/enrichment paths.
    async def mock_structured_output_async(prompt, schema, method="json_schema"):
        from pydantic import BaseModel

        if isinstance(schema, type) and issubclass(schema, BaseModel):
            schema_name = schema.__name__
            if schema_name == "PatientProfileExtract":
                return schema.model_validate(
                    {
                        "basic_info": {
                            "alias": "Fabian",
                            "data_of_birth": None,
                            "gender": None,
                            "cultural_background": None,
                            "primary_language": "English",
                        },
                        "family": {
                            "parents": None,
                            "siblings": None,
                            "family_atmosphere": None,
                            "significant_events": None,
                        },
                        "history": {
                            "education": None,
                            "work_history": None,
                            "relationship_to_work": None,
                        },
                        "context": {
                            "relationships": None,
                            "social_context": None,
                            "current_situation": None,
                        },
                        "frame": {
                            "preferred_school": None,
                            "boundary_notes": None,
                            "frame_notes": None,
                        },
                    }
                )
            if schema_name == "PatientAnalysis":
                return schema.model_validate(
                    {
                        "current_focus": {
                            "theme": "Anxiety",
                            "salience": "Work stress causing persistent anxiety",
                        },
                        "transference": {
                            "idealization": None,
                            "devaluation": None,
                            "boundaries": None,
                            "other_patterns": "Developing alliance",
                        },
                        "narratives": [],
                        "defenses": {
                            "primary_defenses": ["intellectualization"],
                            "defensive_style": "Cerebral",
                            "flexibility": "Moderate",
                        },
                        "orientation": {
                            "pacing": "Gradual",
                            "risk_areas": ["perfectionism"],
                            "key_questions": ["What triggers the anxiety?"],
                        },
                    }
                )
            if schema_name == "Tier4Extract":
                return schema.model_validate(
                    {
                        "initial_goals": ["Reduce workplace anxiety"],
                        "current_progress": "Baseline established",
                        "planned_interventions": ["Cognitive restructuring"],
                        "status": "active",
                    }
                )
            if schema_name == "PlanUpdate":
                return schema.model_validate(
                    {
                        "focus": "Anxiety management",
                        "goals": "- Reduce anxiety\n- Improve sleep",
                        "techniques": "- Cognitive restructuring\n- Mindfulness",
                        "themes": "Anxiety, coping",
                        "timeline": "12 weeks",
                    }
                )
            if schema_name == "Tier2Enrichment":
                return schema.model_validate(
                    {
                        "psychological_summary": "Mock summary",
                        "dominant_affects": ["anxiety"],
                        "key_themes": ["work stress"],
                        "notable_interactions": None,
                        "interpretations": None,
                        "patient_reactions": None,
                    }
                )
            if schema_name == "SessionAnalysis":
                return schema.model_validate(
                    {
                        "key_themes": ["work stress"],
                        "emotional_state": "anxious",
                        "insights": [],
                        "progress_indicators": [],
                    }
                )
            if schema_name == "SessionBriefing":
                from datetime import datetime

                now = datetime.now()
                return schema.model_validate(
                    {
                        "briefing_type": "resumption",
                        "generated_at": now.isoformat(),
                        "session_count": 1,
                        "last_session_id": "session_001",
                        "last_session_date": now.date().isoformat(),
                        "narrative_handoff": (
                            "Patient discussed anxiety about work and ongoing stress. "
                            "We explored triggers and began identifying automatic thoughts."
                        ),
                        "patient_observations": "Patient was engaged.",
                        "plan_progression_notes": "Plan remains appropriate.",
                        "relationship_quality": "developing",
                        "continuity_points": ["Follow up on work anxiety"],
                        "emotional_summary": {
                            "last_session": "anxious",
                            "trend": "stable",
                            "note": "Stable anxiety with engagement",
                        },
                        "key_themes": [
                            {
                                "theme": "work stress",
                                "status": "ongoing",
                                "priority": "high",
                                "frequency": 1,
                                "first_appearance": "session_001",
                                "last_discussed": "session_001",
                            }
                        ],
                        "progress_highlights": ["Identified triggers"],
                        "unresolved_issues": ["Perfectionism"],
                        "recommended_approach": {
                            "opening_tone": "Warm",
                            "opening_focus": "Check in",
                            "things_to_avoid": "Overwhelming questions",
                            "suggested_questions": ["How have you been?"],
                            "therapeutic_goals_for_session": ["Build rapport"],
                        },
                    }
                )
        return {}

    llm.generate_structured_output_async = mock_structured_output_async

    def mock_structured_output(prompt, schema, method="json_schema"):
        from datetime import datetime

        from pydantic import BaseModel

        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            return {}

        schema_name = schema.__name__
        if schema_name == "PatientProfileExtract":
            return schema.model_validate(
                {
                    "basic_info": {
                        "alias": "Fabian",
                        "data_of_birth": None,
                        "gender": None,
                        "cultural_background": None,
                        "primary_language": "English",
                    },
                    "family": {
                        "parents": None,
                        "siblings": None,
                        "family_atmosphere": None,
                        "significant_events": None,
                    },
                    "history": {
                        "education": None,
                        "work_history": None,
                        "relationship_to_work": None,
                    },
                    "context": {
                        "relationships": None,
                        "social_context": None,
                        "current_situation": None,
                    },
                    "frame": {
                        "preferred_school": None,
                        "boundary_notes": None,
                        "frame_notes": None,
                    },
                }
            )
        if schema_name == "PatientAnalysis":
            return schema.model_validate(
                {
                    "current_focus": {
                        "theme": "Anxiety",
                        "salience": "Work stress causing persistent anxiety",
                    },
                    "transference": {
                        "idealization": None,
                        "devaluation": None,
                        "boundaries": None,
                        "other_patterns": "Developing alliance",
                    },
                    "narratives": [],
                    "defenses": {
                        "primary_defenses": ["intellectualization"],
                        "defensive_style": "Cerebral",
                        "flexibility": "Moderate",
                    },
                    "orientation": {
                        "pacing": "Gradual",
                        "risk_areas": ["perfectionism"],
                        "key_questions": ["What triggers the anxiety?"],
                    },
                }
            )
        if schema_name == "Tier4Extract":
            return schema.model_validate(
                {
                    "initial_goals": ["Reduce workplace anxiety"],
                    "current_progress": "Baseline established",
                    "planned_interventions": ["Cognitive restructuring"],
                    "status": "active",
                }
            )
        if schema_name == "PlanUpdate":
            return schema.model_validate(
                {
                    "focus": "Anxiety management",
                    "goals": "- Reduce anxiety\n- Improve sleep",
                    "techniques": "- Cognitive restructuring\n- Mindfulness",
                    "themes": "Anxiety, coping",
                    "timeline": "12 weeks",
                }
            )
        if schema_name == "Tier2Enrichment":
            return schema.model_validate(
                {
                    "psychological_summary": "Mock summary",
                    "dominant_affects": ["anxiety"],
                    "key_themes": ["work stress"],
                    "notable_interactions": None,
                    "interpretations": None,
                    "patient_reactions": None,
                }
            )
        if schema_name == "SessionAnalysis":
            return schema.model_validate(
                {
                    "key_themes": ["work stress"],
                    "emotional_state": "anxious",
                    "insights": [],
                    "progress_indicators": [],
                }
            )
        if schema_name == "SessionBriefing":
            now = datetime.now()
            return schema.model_validate(
                {
                    "briefing_type": "resumption",
                    "generated_at": now.isoformat(),
                    "session_count": 1,
                    "last_session_id": "session_001",
                    "last_session_date": now.date().isoformat(),
                    "narrative_handoff": (
                        "Patient discussed anxiety about work and ongoing stress. "
                        "We explored triggers and began identifying automatic thoughts."
                    ),
                    "patient_observations": "Patient was engaged.",
                    "plan_progression_notes": "Plan remains appropriate.",
                    "relationship_quality": "developing",
                    "continuity_points": ["Follow up on work anxiety"],
                    "emotional_summary": {
                        "last_session": "anxious",
                        "trend": "stable",
                        "note": "Stable anxiety with engagement",
                    },
                    "key_themes": [
                        {
                            "theme": "work stress",
                            "status": "ongoing",
                            "priority": "high",
                            "frequency": 1,
                            "first_appearance": "session_001",
                            "last_discussed": "session_001",
                        }
                    ],
                    "progress_highlights": ["Identified triggers"],
                    "unresolved_issues": ["Perfectionism"],
                    "recommended_approach": {
                        "opening_tone": "Warm",
                        "opening_focus": "Check in",
                        "things_to_avoid": "Overwhelming questions",
                        "suggested_questions": ["How have you been?"],
                        "therapeutic_goals_for_session": ["Build rapport"],
                    },
                }
            )

        return schema.model_validate({})

    llm.generate_structured_output = Mock(side_effect=mock_structured_output)

    return llm


@pytest.fixture(scope="function")
def test_config(tmp_path):
    """Create test configuration."""
    from psychoanalyst_app.config import Settings

    # Use temporary file database (in-memory doesn't work well with Trio threading)
    test_db_path = str(tmp_path / "test_console_ui.db")

    # Create a modified copy of settings
    settings = Settings()
    mock_settings = settings.model_copy(update={"DATABASE_PATH": test_db_path})
    return mock_settings


@pytest.fixture(scope="function")
async def test_server_websocket(
    test_config, mock_llm_service_with_context, mock_rag_service
):
    """Create and start a test server instance with WebSocket support and contextual mock LLM."""
    from psychoanalyst_app.container.service_container import ServiceContainer
    from psychoanalyst_app.trio_server import TrioServer

    # Create service container with mocked services
    container = ServiceContainer(test_config)
    container.register("llm_service", mock_llm_service_with_context)
    container.register("rag_service", mock_rag_service)

    # Initialize database
    db_service = container.get("trio_db_service")
    await db_service.initialize()

    # Create server on random available port
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
            "server": server,
            "host": "127.0.0.1",
            "port": port,
            "url": f"http://127.0.0.1:{port}",
            "ws_url": f"ws://127.0.0.1:{port}",
            "container": container,
            "orchestrator": server.orchestrator,
            "db_service": db_service,
        }

        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_complete_patient_journey_intake_to_therapy(
    test_server_websocket, mock_rag_service
):
    """
    Test complete patient journey from connection to therapy session.

    Simulates:
    1. New patient connects with user_id
    2. Provides name as first message
    3. Exchanges 2+ messages during intake
    4. Receives assessment recommendations
    5. Selects therapy style
    6. Has first therapy session with 2+ message exchanges
    """
    import logging

    logger = logging.getLogger(__name__)

    logger.info("=== Starting Complete Patient Journey Test ===")

    # Test data
    user_id = f"console_test_{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient() as client:
        profiles_response = await client.get(
            f"{test_server_websocket['url']}/api/user/profiles"
        )
        assert profiles_response.status_code == 200, profiles_response.text
        assert profiles_response.json().get("profiles") == []

        response = await client.post(
            f"{test_server_websocket['url']}/api/user/register",
            json={
                "user_id": user_id,
                "name": "Fabian",
                "primary_language": "English",
            },
        )
        assert response.status_code == 201, response.text

    # Track received events
    received_events = {
        "connected": [],
        "session_started": [],
        "chat_response_chunk": [],
        "workflow_next_action": [],
        "typing_start": [],
        "typing_stop": [],
        "error": [],
    }

    # Current message accumulation
    current_response = {"chunks": [], "complete": False}

    # WebSocket message receiver
    async def websocket_receiver(ws):
        """Receive and categorize WebSocket messages."""
        nonlocal current_response
        try:
            while True:
                try:
                    message = await ws.get_message()
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type in received_events:
                        logger.debug(f"Received: {msg_type}")

                        # Accumulate chunks for chat responses
                        if msg_type == "chat_response_chunk":
                            chunk_data = data.get("data", {})
                            if chunk_data.get("is_complete"):
                                # Mark as complete and add full response
                                current_response["complete"] = True
                                current_response["full_response"] = "".join(
                                    current_response["chunks"]
                                )
                                # Add complete marker with full response
                                data["data"]["full_response"] = current_response[
                                    "full_response"
                                ]
                                # Reset for next message
                                current_response["chunks"] = []
                                current_response["complete"] = False
                            else:
                                # Accumulate chunk
                                current_response["chunks"].append(
                                    chunk_data.get("chunk", "")
                                )

                        received_events[msg_type].append(data)
                    else:
                        logger.warning(f"Unknown message type: {msg_type}")

                except ConnectionClosed:
                    logger.info("WebSocket connection closed")
                    break
        except Exception as e:
            logger.error(f"Error in receiver: {e}")

    # ==========================================
    # PHASE 1: Connection & Name Collection
    # ==========================================
    logger.info("\n--- Phase 1: Connection & Name Collection ---")

    ws_url = f"{test_server_websocket['ws_url']}/ws?user_id={user_id}"
    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://localhost:5173")]
    ) as ws:
        # Start receiver in background
        async with trio.open_nursery() as nursery:
            nursery.start_soon(websocket_receiver, ws)

            # Give receiver time to start
            await trio.sleep(0.1)

            # Wait for session_started event
            await trio.sleep(0.3)
            assert (
                len(received_events["session_started"]) > 0
            ), "Should receive session_started"

            session_data = received_events["session_started"][-1]
            assert "session_id" in session_data["data"]
            session_id = session_data["data"]["session_id"]
            user_status = session_data["data"].get("user_status", "unknown")

            logger.info(f"✓ Session started: {session_id}, status: {user_status}")

            # Clear chunk buffer for next message
            received_events["chat_response_chunk"].clear()

            # Send name as first user message
            logger.info("Sending name: Fabian")
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": "Fabian",
                            "session_id": session_id,
                        },
                    }
                )
            )

            # Wait for response
            await trio.sleep(0.5)

            # Verify response was received
            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive response to name"

            full_response = (
                complete_responses[0].get("data", {}).get("full_response", "")
            )
            assert len(full_response) > 0, "Response should not be empty"
            logger.info(f"✓ Received greeting response ({len(full_response)} chars)")

            # Verify user profile was created
            db_service = test_server_websocket["db_service"]
            user_profile = await db_service.get_user_profile(user_id)
            assert user_profile is not None, "User profile should be created"
            assert user_profile.user_id == user_id, "User ID should match"
            assert user_profile.name == "Fabian", "Name should be stored"
            logger.info(f"✓ User profile created: {user_profile.name}")

            # Verify state is INTAKE_IN_PROGRESS
            orchestrator = test_server_websocket["orchestrator"]
            state = await orchestrator.get_user_state(user_id)
            assert state == WorkflowState.INTAKE_IN_PROGRESS
            logger.info(f"✓ Workflow state: {state.value}")

            # ==========================================
            # PHASE 2: Intake Conversation
            # ==========================================
            logger.info("\n--- Phase 2: Intake Conversation ---")

            # Message 1: Describe presenting problem
            received_events["chat_response_chunk"].clear()
            intake_message_1 = "I've been feeling really anxious about work and it's affecting my sleep"

            logger.info(f"Sending intake message 1: {intake_message_1[:50]}...")
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": intake_message_1,
                            "session_id": session_id,
                        },
                    }
                )
            )

            await trio.sleep(0.5)

            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive response to message 1"
            response_1 = complete_responses[0].get("data", {}).get("full_response", "")
            assert len(response_1) > 0
            logger.info(f"✓ Response 1 received ({len(response_1)} chars)")

            # Message 2: Provide more context
            received_events["chat_response_chunk"].clear()
            intake_message_2 = "It started about 3 months ago when I got a new manager who micromanages everything"

            logger.info(f"Sending intake message 2: {intake_message_2[:50]}...")
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": intake_message_2,
                            "session_id": session_id,
                        },
                    }
                )
            )

            await trio.sleep(0.5)

            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive response to message 2"
            response_2 = complete_responses[0].get("data", {}).get("full_response", "")
            assert len(response_2) > 0
            logger.info(f"✓ Response 2 received ({len(response_2)} chars)")

            # Message 3: Express readiness
            received_events["chat_response_chunk"].clear()
            intake_message_3 = (
                "I haven't tried therapy before but I'm ready to make a change"
            )

            logger.info(f"Sending intake message 3: {intake_message_3[:50]}...")
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": intake_message_3,
                            "session_id": session_id,
                        },
                    }
                )
            )

            await trio.sleep(0.5)

            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive response to message 3"
            response_3 = complete_responses[0].get("data", {}).get("full_response", "")
            assert len(response_3) > 0
            logger.info(f"✓ Response 3 received ({len(response_3)} chars)")

            # Verify session transcript has all messages
            session = await db_service.get_session(session_id)
            assert session is not None, "Session should exist"
            user_messages = [m for m in session.transcript if m.role == "user"]
            assistant_messages = [
                m for m in session.transcript if m.role == "assistant"
            ]

            assert (
                len(user_messages) >= 3
            ), f"Should have at least 3 user messages, got {len(user_messages)}"
            assert (
                len(assistant_messages) >= 3
            ), f"Should have at least 3 assistant messages, got {len(assistant_messages)}"
            logger.info(
                f"✓ Session transcript: {len(user_messages)} user msgs, {len(assistant_messages)} assistant msgs"
            )

            # ==========================================
            # PHASE 3: Assessment & Style Selection
            # ==========================================
            logger.info("\n--- Phase 3: Assessment & Style Selection ---")

            # Manually transition to INTAKE_COMPLETE to trigger assessment
            await orchestrator.workflow_engine.transition(
                user_id, WorkflowState.INTAKE_COMPLETE, WorkflowEvent.COMPLETE_INTAKE
            )

            state = await orchestrator.get_user_state(user_id)
            assert state == WorkflowState.INTAKE_COMPLETE
            logger.info(f"✓ Transitioned to {state.value}")

            # Continue with the existing session for assessment
            assessment_session_id = session_id
            logger.info(f"✓ Assessment uses existing session: {assessment_session_id}")

            # Transition to ASSESSMENT_IN_PROGRESS
            await orchestrator.workflow_engine.transition(
                user_id,
                WorkflowState.ASSESSMENT_IN_PROGRESS,
                WorkflowEvent.START_ASSESSMENT,
            )
            state = await orchestrator.get_user_state(user_id)
            assert state == WorkflowState.ASSESSMENT_IN_PROGRESS
            logger.info(f"✓ Transitioned to {state.value}")

            # Wait for recommendations message
            await trio.sleep(0.5)

            # Select therapy style (handled via workflow step, not chat)
            selected_style = "cbt"
            logger.info(f"Selecting therapy style: {selected_style}")

            # Manually create therapy plan and transition state
            from psychoanalyst_app.models.data_models import TherapyPlan

            therapy_plan = TherapyPlan(
                plan_id=str(uuid.uuid4()),
                user_id=user_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                plan_details={
                    "focus": "Anxiety management and work-related stress",
                    "goals": "Develop coping strategies for workplace anxiety",
                    "techniques": "Cognitive restructuring, thought challenging",
                },
                initial_goals=["Develop coping strategies for workplace anxiety"],
                current_progress="Baseline established",
                planned_interventions=["Cognitive restructuring"],
                version=1,
                selected_therapy_style=selected_style,
            )

            await db_service.save_therapy_plan(therapy_plan)
            logger.info("✓ Therapy plan created")

            # Transition to ASSESSMENT_COMPLETE
            await orchestrator.workflow_engine.transition(
                user_id,
                WorkflowState.ASSESSMENT_COMPLETE,
                WorkflowEvent.COMPLETE_ASSESSMENT,
            )

            state = await orchestrator.get_user_state(user_id)
            assert state == WorkflowState.ASSESSMENT_COMPLETE
            logger.info(f"✓ Transitioned to {state.value}")

            # ==========================================
            # PHASE 4: First Therapy Session
            # ==========================================
            logger.info("\n--- Phase 4: First Therapy Session ---")

            # Transition to therapy
            await orchestrator.workflow_engine.transition(
                user_id,
                WorkflowState.INITIAL_PLAN_COMPLETE,
            )
            await orchestrator.workflow_engine.transition(
                user_id,
                WorkflowState.THERAPY_IN_PROGRESS,
                WorkflowEvent.START_THERAPY,
            )

            # Continue with the existing session for therapy
            received_events["chat_response_chunk"].clear()
            therapy_session_id = session_id
            logger.info(f"✓ Therapy uses existing session: {therapy_session_id}")

            # Wait for initial greeting if present
            await trio.sleep(0.3)

            # Clear for therapy messages
            received_events["chat_response_chunk"].clear()

            # Therapy Message 1
            therapy_message_1 = (
                "I'm feeling anxious right now thinking about work tomorrow"
            )
            logger.info(f"Sending therapy message 1: {therapy_message_1[:50]}...")

            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": therapy_message_1,
                            "session_id": therapy_session_id,
                        },
                    }
                )
            )

            await trio.sleep(0.5)

            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive therapy response 1"
            therapy_response_1 = (
                complete_responses[0].get("data", {}).get("full_response", "")
            )
            assert len(therapy_response_1) > 0
            logger.info(
                f"✓ Therapy response 1 received ({len(therapy_response_1)} chars)"
            )

            # Therapy Message 2
            received_events["chat_response_chunk"].clear()
            therapy_message_2 = (
                "I keep thinking my manager will criticize everything I do"
            )
            logger.info(f"Sending therapy message 2: {therapy_message_2[:50]}...")

            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": therapy_message_2,
                            "session_id": therapy_session_id,
                        },
                    }
                )
            )

            await trio.sleep(0.5)

            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive therapy response 2"
            therapy_response_2 = (
                complete_responses[0].get("data", {}).get("full_response", "")
            )
            assert len(therapy_response_2) > 0
            logger.info(
                f"✓ Therapy response 2 received ({len(therapy_response_2)} chars)"
            )

            # Verify therapy session transcript
            therapy_session = await db_service.get_session(therapy_session_id)
            assert therapy_session is not None, "Therapy session should exist"

            therapy_user_messages = [
                m for m in therapy_session.transcript if m.role == "user"
            ]
            therapy_assistant_messages = [
                m for m in therapy_session.transcript if m.role == "assistant"
            ]

            assert (
                len(therapy_user_messages) >= 2
            ), "Should have at least 2 therapy user messages"
            assert (
                len(therapy_assistant_messages) >= 2
            ), "Should have at least 2 therapy assistant messages"
            logger.info(
                f"✓ Therapy transcript: {len(therapy_user_messages)} user msgs, {len(therapy_assistant_messages)} assistant msgs"
            )

            # Final state verification
            final_state = await orchestrator.get_user_state(user_id)
            assert final_state == WorkflowState.THERAPY_IN_PROGRESS
            logger.info(f"✓ Final state: {final_state.value}")

            # Verify no errors occurred
            assert (
                len(received_events["error"]) == 0
            ), f"Should have no errors, got: {received_events['error']}"
            logger.info("✓ No errors throughout entire flow")

            logger.info("\n=== Complete Patient Journey Test PASSED ===")
            logger.info("Summary:")
            logger.info(f"  - User profile created: {user_profile.name}")
            logger.info(f"  - Intake messages: {len(user_messages)}")
            logger.info(f"  - Therapy plan: {therapy_plan.selected_therapy_style}")
            logger.info(f"  - Therapy messages: {len(therapy_user_messages)}")
            logger.info(f"  - Final state: {final_state.value}")

            # Cancel nursery to stop receiver
            nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_intake_flow_only(test_server_websocket, mock_rag_service):
    """
    Simplified test covering only intake flow (Phases 1-2).

    This test is a baseline to verify the intake process works reliably:
    1. New patient connects with user_id
    2. Provides name as first message
    3. Exchanges 3 messages during intake
    4. Verifies user profile creation and state transitions
    """
    import logging

    logger = logging.getLogger(__name__)

    logger.info("=== Starting Intake Flow Test ===")

    # Test data
    user_id = f"intake_test_{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{test_server_websocket['url']}/api/user/register",
            json={
                "user_id": user_id,
                "name": "Fabian",
                "primary_language": "English",
            },
        )
        assert response.status_code == 201, response.text

    # Track received events
    received_events = {
        "connected": [],
        "session_started": [],
        "chat_response_chunk": [],
        "typing_start": [],
        "typing_stop": [],
        "error": [],
    }

    # Current message accumulation
    current_response = {"chunks": [], "complete": False}

    # WebSocket message receiver
    async def websocket_receiver(ws):
        """Receive and categorize WebSocket messages."""
        nonlocal current_response
        try:
            while True:
                try:
                    message = await ws.get_message()
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type in received_events:
                        logger.debug(f"Received: {msg_type}")

                        # Accumulate chunks for chat responses
                        if msg_type == "chat_response_chunk":
                            chunk_data = data.get("data", {})
                            if chunk_data.get("is_complete"):
                                # Mark as complete and add full response
                                current_response["complete"] = True
                                current_response["full_response"] = "".join(
                                    current_response["chunks"]
                                )
                                # Add complete marker with full response
                                data["data"]["full_response"] = current_response[
                                    "full_response"
                                ]
                                # Reset for next message
                                current_response["chunks"] = []
                                current_response["complete"] = False
                            else:
                                # Accumulate chunk
                                current_response["chunks"].append(
                                    chunk_data.get("chunk", "")
                                )

                        received_events[msg_type].append(data)
                    else:
                        logger.warning(f"Unknown message type: {msg_type}")

                except ConnectionClosed:
                    logger.info("WebSocket connection closed")
                    break
        except Exception as e:
            logger.error(f"Error in receiver: {e}")

    # ==========================================
    # PHASE 1: Connection & Name Collection
    # ==========================================
    logger.info("\n--- Phase 1: Connection & Name Collection ---")

    ws_url = f"{test_server_websocket['ws_url']}/ws?user_id={user_id}"
    async with open_websocket_url(
        ws_url, extra_headers=[("Origin", "http://localhost:5173")]
    ) as ws:
        # Start receiver in background
        async with trio.open_nursery() as nursery:
            nursery.start_soon(websocket_receiver, ws)

            # Give receiver time to start
            await trio.sleep(0.1)

            # Wait for session_started event
            await trio.sleep(0.3)
            assert (
                len(received_events["session_started"]) > 0
            ), "Should receive session_started"

            session_data = received_events["session_started"][-1]
            assert "session_id" in session_data["data"]
            session_id = session_data["data"]["session_id"]
            user_status = session_data["data"].get("user_status", "unknown")

            logger.info(f"✓ Session started: {session_id}, status: {user_status}")

            # Clear chunk buffer for next message
            received_events["chat_response_chunk"].clear()

            # Send name as first user message
            logger.info("Sending name: Fabian")
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": "Fabian",
                            "session_id": session_id,
                        },
                    }
                )
            )

            # Wait for response
            await trio.sleep(0.5)

            # Verify response was received
            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive response to name"

            full_response = (
                complete_responses[0].get("data", {}).get("full_response", "")
            )
            assert len(full_response) > 0, "Response should not be empty"
            logger.info(f"✓ Received greeting response ({len(full_response)} chars)")

            # Verify user profile was created
            db_service = test_server_websocket["db_service"]
            user_profile = await db_service.get_user_profile(user_id)
            assert user_profile is not None, "User profile should be created"
            assert user_profile.user_id == user_id, "User ID should match"
            assert user_profile.name == "Fabian", "Name should be stored"
            logger.info(f"✓ User profile created: {user_profile.name}")

            # Verify state is INTAKE_IN_PROGRESS
            orchestrator = test_server_websocket["orchestrator"]
            state = await orchestrator.get_user_state(user_id)
            assert state == WorkflowState.INTAKE_IN_PROGRESS
            logger.info(f"✓ Workflow state: {state.value}")

            # ==========================================
            # PHASE 2: Intake Conversation
            # ==========================================
            logger.info("\n--- Phase 2: Intake Conversation ---")

            # Message 1: Describe presenting problem
            received_events["chat_response_chunk"].clear()
            intake_message_1 = "I've been feeling really anxious about work and it's affecting my sleep"

            logger.info(f"Sending intake message 1: {intake_message_1[:50]}...")
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": intake_message_1,
                            "session_id": session_id,
                        },
                    }
                )
            )

            await trio.sleep(0.5)

            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive response to message 1"
            response_1 = complete_responses[0].get("data", {}).get("full_response", "")
            assert len(response_1) > 0
            logger.info(f"✓ Response 1 received ({len(response_1)} chars)")

            # Message 2: Provide more context
            received_events["chat_response_chunk"].clear()
            intake_message_2 = "It started about 3 months ago when I got a new manager who micromanages everything"

            logger.info(f"Sending intake message 2: {intake_message_2[:50]}...")
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": intake_message_2,
                            "session_id": session_id,
                        },
                    }
                )
            )

            await trio.sleep(0.5)

            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive response to message 2"
            response_2 = complete_responses[0].get("data", {}).get("full_response", "")
            assert len(response_2) > 0
            logger.info(f"✓ Response 2 received ({len(response_2)} chars)")

            # Message 3: Express readiness
            received_events["chat_response_chunk"].clear()
            intake_message_3 = (
                "I haven't tried therapy before but I'm ready to make a change"
            )

            logger.info(f"Sending intake message 3: {intake_message_3[:50]}...")
            await ws.send_message(
                json.dumps(
                    {
                        "type": "chat_message",
                        "data": {
                            "user_id": user_id,
                            "message": intake_message_3,
                            "session_id": session_id,
                        },
                    }
                )
            )

            await trio.sleep(0.5)

            complete_responses = [
                c
                for c in received_events["chat_response_chunk"]
                if c.get("data", {}).get("is_complete") == True
            ]
            assert len(complete_responses) > 0, "Should receive response to message 3"
            response_3 = complete_responses[0].get("data", {}).get("full_response", "")
            assert len(response_3) > 0
            logger.info(f"✓ Response 3 received ({len(response_3)} chars)")

            # Verify session transcript has all messages
            session = await db_service.get_session(session_id)
            assert session is not None, "Session should exist"
            user_messages = [m for m in session.transcript if m.role == "user"]
            assistant_messages = [
                m for m in session.transcript if m.role == "assistant"
            ]

            assert (
                len(user_messages) >= 3
            ), f"Should have at least 3 user messages, got {len(user_messages)}"
            assert (
                len(assistant_messages) >= 3
            ), f"Should have at least 3 assistant messages, got {len(assistant_messages)}"
            logger.info(
                f"✓ Session transcript: {len(user_messages)} user msgs, {len(assistant_messages)} assistant msgs"
            )

            # Verify no errors occurred
            assert (
                len(received_events["error"]) == 0
            ), f"Should have no errors, got: {received_events['error']}"
            logger.info("✓ No errors throughout intake flow")

            logger.info("\n=== Intake Flow Test PASSED ===")
            logger.info("Summary:")
            logger.info(f"  - User profile created: {user_profile.name}")
            logger.info(
                f"  - Intake messages: {len(user_messages)} user, {len(assistant_messages)} assistant"
            )
            logger.info(f"  - Final state: {state.value}")

            # Cancel nursery to stop receiver
            nursery.cancel_scope.cancel()
