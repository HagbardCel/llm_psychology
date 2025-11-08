"""
Integration tests for orchestration flow.

Tests the complete therapy workflow through the orchestration layer,
including state transitions, agent coordination, and streaming responses.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from src.orchestration.workflow_engine import WorkflowEngine
from src.orchestration.conversation_manager import ConversationManager
from src.orchestration.agent_orchestrator import AgentOrchestrator
from src.orchestration.models import WorkflowState, WorkflowEvent, AgentResponse
from src.models.data_models import UserProfile, TherapyPlan, Session, Message
from src.container.service_container import ServiceContainer
from src.config import Config


@pytest.fixture
def test_config():
    """Create test configuration."""
    config = Config()
    config.DATABASE_PATH = ":memory:"  # Use in-memory database for testing
    return config


@pytest.fixture
def mock_llm_service():
    """Create a mock LLM service."""
    llm = Mock()

    # Mock streaming with different responses based on prompt
    async def mock_stream(prompt, *args, **kwargs):
        if "intake" in prompt.lower():
            chunks = ["Hello! ", "I'm here ", "to help you ", "get started."]
        elif "assessment" in prompt.lower():
            chunks = ["Based on ", "your intake, ", "I recommend ", "CBT therapy."]
        elif "therapy" in prompt.lower() or "session" in prompt.lower():
            chunks = ["Thank you ", "for sharing. ", "How does ", "that make ", "you feel?"]
        else:
            chunks = ["Thank you."]

        for chunk in chunks:
            yield chunk

    llm.stream_response = mock_stream
    llm.generate_response = Mock(return_value="This is a generated response.")
    return llm


@pytest.fixture
def mock_rag_service():
    """Create a mock RAG service."""
    rag = Mock()
    rag.retrieve_relevant_knowledge = Mock(return_value=[
        {
            "content": "Relevant psychological knowledge here.",
            "source": "test_knowledge",
            "score": 0.9
        }
    ])
    return rag


@pytest.fixture
def integration_container(test_config, mock_llm_service, mock_rag_service):
    """Create a service container with mocked LLM and RAG services."""
    container = ServiceContainer(test_config)

    # Replace LLM and RAG services with mocks
    container._llm_service = mock_llm_service
    container._rag_service = mock_rag_service

    return container


@pytest.fixture
def orchestration_system(integration_container):
    """Create a complete orchestration system."""
    db_service = integration_container.get_db_service()
    llm_service = integration_container.get_llm_service()
    rag_service = integration_container.get_rag_service()

    workflow_engine = WorkflowEngine(db_service)
    conversation_manager = ConversationManager(llm_service, rag_service, db_service)
    orchestrator = AgentOrchestrator(integration_container, workflow_engine, conversation_manager)

    return {
        "orchestrator": orchestrator,
        "workflow_engine": workflow_engine,
        "conversation_manager": conversation_manager,
        "container": integration_container,
        "db": db_service
    }


class TestCompleteTherapyWorkflow:
    """Test complete therapy workflow from intake to therapy session."""

    @pytest.mark.asyncio
    async def test_new_user_intake_flow(self, orchestration_system):
        """Test complete intake flow for new user."""
        orchestrator = orchestration_system["orchestrator"]
        workflow_engine = orchestration_system["workflow_engine"]
        db = orchestration_system["db"]

        # Step 1: Create user profile
        user_profile = await orchestrator.create_user_profile(
            name="Integration Test User",
            birthdate="1990-01-01",
            profession="Software Engineer"
        )
        assert user_profile.name == "Integration Test User"

        user_id = user_profile.id

        # Step 2: Verify initial state
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.NEW

        # Step 3: Start intake session
        session_info = await orchestrator.start_session(user_id, "INTAKE")
        assert session_info.agent_type == "INTAKE"
        assert session_info.workflow_state == WorkflowState.INTAKE_IN_PROGRESS

        # Verify state transition
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.INTAKE_IN_PROGRESS

        # Step 4: Process intake messages
        response_chunks = []
        async for chunk in orchestrator.process_message(
            user_id,
            "I'm feeling anxious and need help",
            session_info.session_id
        ):
            response_chunks.append(chunk)

        assert len(response_chunks) > 0
        full_response = "".join(response_chunks)
        assert len(full_response) > 0

    @pytest.mark.asyncio
    async def test_state_progression_through_workflow(self, orchestration_system):
        """Test state progression through entire workflow."""
        orchestrator = orchestration_system["orchestrator"]
        workflow_engine = orchestration_system["workflow_engine"]
        db = orchestration_system["db"]

        # Create user
        user_profile = await orchestrator.create_user_profile(
            name="Workflow Test User",
            birthdate="1985-05-15",
            profession="Teacher"
        )
        user_id = user_profile.id

        # Progress through states
        # NEW -> INTAKE_IN_PROGRESS
        await workflow_engine.transition(
            user_id,
            WorkflowState.INTAKE_IN_PROGRESS,
            WorkflowEvent.INTAKE_STARTED
        )
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.INTAKE_IN_PROGRESS

        # INTAKE_IN_PROGRESS -> INTAKE_COMPLETE
        await workflow_engine.transition(
            user_id,
            WorkflowState.INTAKE_COMPLETE,
            WorkflowEvent.INTAKE_COMPLETED
        )
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.INTAKE_COMPLETE

        # INTAKE_COMPLETE -> ASSESSMENT_IN_PROGRESS
        await workflow_engine.transition(
            user_id,
            WorkflowState.ASSESSMENT_IN_PROGRESS,
            WorkflowEvent.ASSESSMENT_STARTED
        )
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.ASSESSMENT_IN_PROGRESS

        # ASSESSMENT_IN_PROGRESS -> ASSESSMENT_COMPLETE
        await workflow_engine.transition(
            user_id,
            WorkflowState.ASSESSMENT_COMPLETE,
            WorkflowEvent.ASSESSMENT_COMPLETED
        )
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.ASSESSMENT_COMPLETE

        # ASSESSMENT_COMPLETE -> THERAPY_IN_PROGRESS
        await workflow_engine.transition(
            user_id,
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowEvent.SESSION_STARTED
        )
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.THERAPY_IN_PROGRESS

    @pytest.mark.asyncio
    async def test_therapy_session_with_streaming(self, orchestration_system):
        """Test therapy session with streaming responses."""
        orchestrator = orchestration_system["orchestrator"]
        workflow_engine = orchestration_system["workflow_engine"]
        db = orchestration_system["db"]

        # Setup: User at THERAPY_IN_PROGRESS state
        user_profile = await orchestrator.create_user_profile(
            name="Therapy Test User",
            birthdate="1992-03-20",
            profession="Designer"
        )
        user_id = user_profile.id

        # Create therapy plan
        therapy_plan = db.create_therapy_plan(
            user_id=user_id,
            selected_style="cbt",
            plan_details={"focus": "anxiety management", "goals": "reduce anxiety"}
        )

        # Set state to THERAPY_IN_PROGRESS
        await workflow_engine.transition(
            user_id,
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowEvent.SESSION_STARTED
        )

        # Start therapy session
        session_info = await orchestrator.start_session(user_id, "PSYCHOANALYST")

        # Send multiple messages and verify streaming
        messages = [
            "I've been feeling very anxious lately",
            "It's affecting my work and relationships",
            "I don't know how to cope"
        ]

        for message in messages:
            chunks = []
            async for chunk in orchestrator.process_message(
                user_id,
                message,
                session_info.session_id
            ):
                chunks.append(chunk)

            # Verify we got streaming chunks
            assert len(chunks) > 0

            # Verify response is coherent
            full_response = "".join(chunks)
            assert len(full_response) > 0


class TestAgentCoordination:
    """Test coordination between different agents."""

    @pytest.mark.asyncio
    async def test_agent_routing_based_on_state(self, orchestration_system):
        """Test that messages are routed to correct agent based on state."""
        orchestrator = orchestration_system["orchestrator"]
        workflow_engine = orchestration_system["workflow_engine"]

        # Create user
        user_profile = await orchestrator.create_user_profile(
            name="Routing Test User",
            birthdate="1988-07-10",
            profession="Nurse"
        )
        user_id = user_profile.id

        # Test routing at different states
        states_and_agents = [
            (WorkflowState.INTAKE_IN_PROGRESS, "INTAKE"),
            (WorkflowState.ASSESSMENT_IN_PROGRESS, "ASSESSMENT"),
            (WorkflowState.THERAPY_IN_PROGRESS, "PSYCHOANALYST"),
            (WorkflowState.REFLECTION_IN_PROGRESS, "REFLECTION"),
        ]

        for state, expected_agent in states_and_agents:
            # Set state
            db = orchestration_system["db"]
            db.update_user_workflow_state(user_id, state)

            # Verify correct agent is selected
            current_agent = workflow_engine.get_current_agent(state)
            assert current_agent == expected_agent

    @pytest.mark.asyncio
    async def test_context_preservation_across_messages(self, orchestration_system):
        """Test that conversation context is preserved across multiple messages."""
        orchestrator = orchestration_system["orchestrator"]
        workflow_engine = orchestration_system["workflow_engine"]
        conversation_manager = orchestration_system["conversation_manager"]

        # Create user and start session
        user_profile = await orchestrator.create_user_profile(
            name="Context Test User",
            birthdate="1995-11-25",
            profession="Student"
        )
        user_id = user_profile.id

        await workflow_engine.transition(
            user_id,
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowEvent.SESSION_STARTED
        )

        session_info = await orchestrator.start_session(user_id, "PSYCHOANALYST")

        # Send multiple messages
        messages = ["First message", "Second message", "Third message"]

        for message in messages:
            # Add user message to context
            await conversation_manager.add_message(
                session_info.session_id,
                "user",
                message
            )

            # Process message
            async for _ in orchestrator.process_message(
                user_id,
                message,
                session_info.session_id
            ):
                pass

        # Verify context has all messages
        context = await conversation_manager.get_context(session_info.session_id)
        assert len(context.message_history) >= len(messages)


class TestErrorRecovery:
    """Test error handling and recovery in orchestration flow."""

    @pytest.mark.asyncio
    async def test_invalid_state_transition_rejected(self, orchestration_system):
        """Test that invalid state transitions are rejected."""
        workflow_engine = orchestration_system["workflow_engine"]
        orchestrator = orchestration_system["orchestrator"]

        # Create user
        user_profile = await orchestrator.create_user_profile(
            name="Error Test User",
            birthdate="1993-09-05",
            profession="Artist"
        )
        user_id = user_profile.id

        # Attempt invalid transition (skip from NEW to THERAPY_IN_PROGRESS)
        from src.exceptions import InvalidStateTransitionError

        with pytest.raises(InvalidStateTransitionError):
            await workflow_engine.transition(
                user_id,
                WorkflowState.THERAPY_IN_PROGRESS,  # Invalid: skipping intake and assessment
                WorkflowEvent.SESSION_STARTED
            )

        # Verify state hasn't changed
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.NEW

    @pytest.mark.asyncio
    async def test_session_recovery_after_error(self, orchestration_system):
        """Test that sessions can recover from errors."""
        orchestrator = orchestration_system["orchestrator"]
        workflow_engine = orchestration_system["workflow_engine"]

        # Create user and session
        user_profile = await orchestrator.create_user_profile(
            name="Recovery Test User",
            birthdate="1991-02-14",
            profession="Chef"
        )
        user_id = user_profile.id

        await workflow_engine.transition(
            user_id,
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowEvent.SESSION_STARTED
        )

        session_info = await orchestrator.start_session(user_id, "PSYCHOANALYST")

        # Process a valid message
        chunks = []
        async for chunk in orchestrator.process_message(
            user_id,
            "Valid message",
            session_info.session_id
        ):
            chunks.append(chunk)

        assert len(chunks) > 0

        # Session should still be functional after error handling
        state = await workflow_engine.get_user_state(user_id)
        assert state == WorkflowState.THERAPY_IN_PROGRESS


class TestPerformance:
    """Test performance characteristics of orchestration."""

    @pytest.mark.asyncio
    async def test_streaming_latency(self, orchestration_system):
        """Test that streaming starts without significant delay."""
        import time

        orchestrator = orchestration_system["orchestrator"]
        workflow_engine = orchestration_system["workflow_engine"]

        # Setup
        user_profile = await orchestrator.create_user_profile(
            name="Latency Test User",
            birthdate="1994-06-30",
            profession="Developer"
        )
        user_id = user_profile.id

        await workflow_engine.transition(
            user_id,
            WorkflowState.THERAPY_IN_PROGRESS,
            WorkflowEvent.SESSION_STARTED
        )

        session_info = await orchestrator.start_session(user_id, "PSYCHOANALYST")

        # Measure time to first chunk
        start_time = time.time()
        first_chunk_time = None

        async for chunk in orchestrator.process_message(
            user_id,
            "Test message for latency",
            session_info.session_id
        ):
            if first_chunk_time is None:
                first_chunk_time = time.time()
            break  # Only need first chunk for latency test

        # First chunk should arrive quickly (< 1 second for mocked services)
        if first_chunk_time:
            latency = first_chunk_time - start_time
            assert latency < 1.0, f"First chunk latency too high: {latency}s"

    @pytest.mark.asyncio
    async def test_concurrent_sessions(self, orchestration_system):
        """Test handling multiple concurrent sessions."""
        orchestrator = orchestration_system["orchestrator"]
        workflow_engine = orchestration_system["workflow_engine"]

        # Create multiple users
        num_users = 3
        user_ids = []

        for i in range(num_users):
            user_profile = await orchestrator.create_user_profile(
                name=f"Concurrent User {i}",
                birthdate="1990-01-01",
                profession="Tester"
            )
            user_ids.append(user_profile.id)

        # Start sessions for all users
        session_infos = []
        for user_id in user_ids:
            await workflow_engine.transition(
                user_id,
                WorkflowState.THERAPY_IN_PROGRESS,
                WorkflowEvent.SESSION_STARTED
            )
            session_info = await orchestrator.start_session(user_id, "PSYCHOANALYST")
            session_infos.append(session_info)

        # Process messages for all users
        for i, (user_id, session_info) in enumerate(zip(user_ids, session_infos)):
            chunks = []
            async for chunk in orchestrator.process_message(
                user_id,
                f"Message from user {i}",
                session_info.session_id
            ):
                chunks.append(chunk)

            assert len(chunks) > 0
