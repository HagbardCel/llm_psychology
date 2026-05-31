"""
Integration tests for Trio orchestration layer.

Tests workflow engine, conversation manager, and agent orchestrator.
"""

from datetime import datetime

import pytest
import trio

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.models.data_models import UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import WorkflowState
from psychoanalyst_app.orchestration.trio_agent_orchestrator import TrioAgentOrchestrator
from psychoanalyst_app.orchestration.trio_conversation_manager import (
    LLM_RETRY_ERROR_MESSAGE,
    LLM_TERMINAL_ERROR_MESSAGE,
    TrioConversationManager,
)
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine


@pytest.fixture
async def service_container(app_config, mock_llm_service, mock_rag_service):
    """Create service container with mocked services for testing."""
    container = ServiceContainer(app_config)

    # Register mocks BEFORE any get() calls to prevent real service creation
    container.register("llm_service", mock_llm_service)
    container.register("rag_service", mock_rag_service)

    # Now safe to get trio_db_service (uses real in-memory DB)
    trio_db_service = container.get("trio_db_service")
    await trio_db_service.initialize()

    yield container

    await trio_db_service.clear_all_data()


@pytest.fixture
async def workflow_engine(service_container):
    """Create Trio workflow engine."""
    trio_db_service = service_container.get("trio_db_service")
    return TrioWorkflowEngine(trio_db_service)


@pytest.fixture
async def conversation_manager(service_container):
    """Create Trio conversation manager."""
    trio_db_service = service_container.get("trio_db_service")
    llm_service = service_container.get("llm_service")
    rag_service = service_container.get("rag_service")

    async with trio.open_nursery() as nursery:
        manager = TrioConversationManager(
            llm_service,
            rag_service,
            trio_db_service,
            nursery=nursery,
            config=service_container.config,
        )
        yield manager
        nursery.cancel_scope.cancel()


@pytest.fixture
async def orchestrator(service_container, workflow_engine, conversation_manager):
    """Create Trio agent orchestrator."""
    async with trio.open_nursery() as nursery:
        orch = TrioAgentOrchestrator(
            service_container, workflow_engine, conversation_manager, nursery
        )
        yield orch
        nursery.cancel_scope.cancel()


@pytest.fixture
async def test_user(service_container):
    """Create a test user profile."""
    trio_db_service = service_container.get("trio_db_service")

    user_profile = UserProfile(
        user_id="orchestration_test_user",
        name="Orchestration Test User",
        data_of_birth=None,
        profession="Tester",
        status=UserStatus.PROFILE_ONLY,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    await trio_db_service.save_user_profile(user_profile)
    return user_profile


# ===== WorkflowEngine Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_workflow_engine_get_new_user_state(workflow_engine):
    """Test getting state for new user returns NEW."""
    state = await workflow_engine.get_user_state("nonexistent_user")
    assert state == WorkflowState.NEW


@pytest.mark.trio
@pytest.mark.integration
async def test_workflow_engine_get_existing_user_state(workflow_engine, test_user):
    """Test getting state for existing user."""
    state = await workflow_engine.get_user_state(test_user.user_id)
    assert state == WorkflowState.NEW  # PROFILE_ONLY maps to NEW


@pytest.mark.trio
@pytest.mark.integration
async def test_workflow_engine_get_current_agent(workflow_engine):
    """Test agent mapping for different states."""
    assert workflow_engine.get_current_agent(WorkflowState.NEW) == "INTAKE"
    assert (
        workflow_engine.get_current_agent(WorkflowState.INTAKE_IN_PROGRESS) == "INTAKE"
    )
    assert (
        workflow_engine.get_current_agent(WorkflowState.ASSESSMENT_IN_PROGRESS)
        == "ASSESSMENT"
    )
    assert (
        workflow_engine.get_current_agent(WorkflowState.THERAPY_IN_PROGRESS)
        == "THERAPIST"
    )


@pytest.mark.trio
@pytest.mark.integration
async def test_workflow_engine_transition(workflow_engine, test_user):
    """Test state transition."""
    # Initial state should be NEW
    state = await workflow_engine.get_user_state(test_user.user_id)
    assert state == WorkflowState.NEW

    # Transition to INTAKE_IN_PROGRESS
    await workflow_engine.transition(
        test_user.user_id, WorkflowState.INTAKE_IN_PROGRESS
    )

    # Verify transition
    new_state = await workflow_engine.get_user_state(test_user.user_id)
    assert new_state == WorkflowState.INTAKE_IN_PROGRESS


@pytest.mark.trio
@pytest.mark.integration
async def test_workflow_engine_can_transition(workflow_engine):
    """Test transition validation."""
    # Valid transitions
    assert workflow_engine.can_transition(
        WorkflowState.NEW, WorkflowState.INTAKE_IN_PROGRESS
    )
    assert workflow_engine.can_transition(
        WorkflowState.INTAKE_IN_PROGRESS, WorkflowState.INTAKE_COMPLETE
    )

    # Invalid transitions
    assert not workflow_engine.can_transition(
        WorkflowState.NEW, WorkflowState.THERAPY_IN_PROGRESS
    )
    assert not workflow_engine.can_transition(
        WorkflowState.INTAKE_COMPLETE, WorkflowState.THERAPY_IN_PROGRESS
    )


# ===== ConversationManager Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_conversation_manager_preserves_pending_greeting_across_reconnect(
    conversation_manager,
):
    session_id = "reconnecting-session"
    conversation_manager.mark_initial_greeting_pending(session_id)

    conversation_manager.register_websocket(session_id, object())
    conversation_manager.register_websocket(session_id, object())

    assert conversation_manager.has_initial_greeting_sent(session_id) is True
    assert conversation_manager.is_initial_greeting_pending(session_id) is True

    conversation_manager.mark_initial_greeting_complete(session_id)
    conversation_manager.register_websocket(session_id, object())

    assert conversation_manager.has_initial_greeting_sent(session_id) is False
    assert conversation_manager.is_initial_greeting_pending(session_id) is False


@pytest.mark.trio
@pytest.mark.integration
async def test_conversation_manager_claims_initial_greeting_once(
    conversation_manager,
):
    session_id = "single-greeting-session"

    assert conversation_manager.claim_initial_greeting(session_id) is True
    assert conversation_manager.claim_initial_greeting(session_id) is False


@pytest.mark.trio
@pytest.mark.integration
async def test_conversation_manager_add_message(
    conversation_manager, service_container
):
    """Test adding message to conversation."""
    trio_db_service = service_container.get("trio_db_service")

    # Create a session first
    import uuid

    from psychoanalyst_app.models.data_models import Session

    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        user_id="test_user",
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    await trio_db_service.save_session(session)

    # Add message
    await conversation_manager.add_message(session_id, "user", "Hello")

    # Verify message was added
    updated_session = await trio_db_service.get_session(session_id)
    assert len(updated_session.transcript) == 1
    assert updated_session.transcript[0].role == "user"
    assert updated_session.transcript[0].content == "Hello"


@pytest.mark.trio
@pytest.mark.integration
async def test_conversation_manager_stream_response(
    conversation_manager, service_container, test_user
):
    """Test streaming LLM response."""
    import uuid

    from psychoanalyst_app.models.data_models import Session
    from psychoanalyst_app.orchestration.models import ConversationContext

    # Create session
    trio_db_service = service_container.get("trio_db_service")
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        user_id=test_user.user_id,
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    await trio_db_service.save_session(session)

    # Create context
    context = ConversationContext(
        session_id=session_id,
        user_profile=test_user,
        message_history=[],
        therapy_plan=None,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
    )

    # Stream response
    full_response = ""
    chunk_count = 0

    async for chunk in conversation_manager.stream_response(
        "Hello", context, use_rag=False
    ):
        full_response += chunk
        chunk_count += 1

    # Verify we got chunks
    assert chunk_count > 0
    assert len(full_response) > 0
    assert "Hello" in full_response or len(full_response) > 10  # Basic sanity check


@pytest.mark.trio
@pytest.mark.integration
async def test_conversation_manager_limits_repeated_llm_failures(
    conversation_manager, service_container, test_user
):
    """Repeated LLM failures stop returning the retry-loop fallback."""
    import uuid

    from psychoanalyst_app.models.data_models import Session
    from psychoanalyst_app.orchestration.models import ConversationContext

    class FailingLLMService:
        provider = "openai_compatible"
        model_name = "local-model"
        base_url = "http://host.docker.internal:8080/v1"
        llm = type(
            "FakeLLMClient",
            (),
            {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}},
        )()

        async def stream_response(self, _prompt, _conversation_history):
            if False:
                yield ""
            raise RuntimeError("adapter broke")

    trio_db_service = service_container.get("trio_db_service")
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        user_id=test_user.user_id,
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    await trio_db_service.save_session(session)
    context = ConversationContext(
        session_id=session_id,
        user_profile=test_user,
        message_history=[],
        therapy_plan=None,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
    )
    failing_service = FailingLLMService()

    first = [
        chunk
        async for chunk in conversation_manager.stream_response(
            "Hello", context, use_rag=False, llm_service=failing_service
        )
    ]
    second = [
        chunk
        async for chunk in conversation_manager.stream_response(
            "Hello again", context, use_rag=False, llm_service=failing_service
        )
    ]

    assert "".join(first) == LLM_RETRY_ERROR_MESSAGE
    assert "".join(second) == LLM_TERMINAL_ERROR_MESSAGE


@pytest.mark.trio
@pytest.mark.integration
async def test_conversation_manager_rag_filter_source_and_content(conversation_manager):
    """Test that conversation-manager RAG uses correct source filter and content key."""
    from psychoanalyst_app.models.data_models import TherapyPlan

    therapy_plan = TherapyPlan(
        user_id="rag_test_user",
        plan_details={"focus": "test"},
        initial_goals=["test"],
        current_progress="test",
        planned_interventions=["test"],
        selected_therapy_style="cbt",
    )

    # Ensure we prefer `content` over legacy `text` keys.
    conversation_manager.rag_service.retrieve_relevant_knowledge.return_value = [
        {"text": "WRONG", "content": "RIGHT", "source": "cbt.md"}
    ]

    rag_context = await conversation_manager._retrieve_rag_context("query", therapy_plan)

    conversation_manager.rag_service.retrieve_relevant_knowledge.assert_called_once_with(
        "query", 3, "cbt.md"
    )
    assert "RIGHT" in rag_context
    assert "WRONG" not in rag_context


# ===== AgentOrchestrator Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_orchestrator_create_user_profile(orchestrator):
    """Test user profile creation via orchestrator."""
    user_profile = await orchestrator.create_user_profile(
        {
            "user_id": "new_test_user",
            "name": "New Test User",
            "data_of_birth": "",
            "profession": "Engineer",
        }
    )

    assert user_profile.user_id == "new_test_user"
    assert user_profile.name == "New Test User"
    assert user_profile.profession == "Engineer"
    # First profile completion advances the workflow to intake.
    assert user_profile.status == UserStatus.INTAKE_IN_PROGRESS
    assert await orchestrator.get_user_state(user_profile.user_id) == WorkflowState.INTAKE_IN_PROGRESS


@pytest.mark.trio
@pytest.mark.integration
async def test_orchestrator_start_session(orchestrator, test_user):
    """Test starting a session via orchestrator."""
    session_info = await orchestrator.start_session(test_user.user_id)

    assert session_info.user_id == test_user.user_id
    assert session_info.agent_type == "INTAKE"  # NEW state → INTAKE agent
    assert session_info.workflow_state == WorkflowState.NEW
    assert session_info.session_id is not None


@pytest.mark.trio
@pytest.mark.integration
async def test_orchestrator_get_user_state(orchestrator, test_user):
    """Test getting user state via orchestrator."""
    state = await orchestrator.get_user_state(test_user.user_id)
    assert state == WorkflowState.NEW


@pytest.mark.trio
@pytest.mark.integration
async def test_orchestrator_process_message_new_user(orchestrator):
    """Test processing message for new user."""
    user_id = "brand_new_user"

    await orchestrator.create_user_profile(
        {
            "user_id": user_id,
            "name": "John Doe",
            "primary_language": "English",
        }
    )

    # Process message (should continue intake)
    full_response = ""
    async for chunk in orchestrator.process_message(
        user_id, "John Doe", session_id=None
    ):
        full_response += chunk

    # Verify response was generated
    assert len(full_response) > 0

    # Verify user profile was created
    trio_db_service = orchestrator.service_container.get("trio_db_service")
    user_profile = await trio_db_service.get_user_profile(user_id)
    assert user_profile is not None
    assert user_profile.name == "John Doe"

    # Verify state transitioned to INTAKE_IN_PROGRESS
    state = await orchestrator.get_user_state(user_id)
    assert state == WorkflowState.INTAKE_IN_PROGRESS


@pytest.mark.trio
@pytest.mark.integration
async def test_orchestrator_concurrent_processing(orchestrator):
    """Test concurrent message processing using nursery."""
    results = []

    async def process_for_user(user_num):
        user_id = f"concurrent_user_{user_num}"
        full_response = ""

        await orchestrator.create_user_profile(
            {
            "user_id": user_id,
            "name": f"User {user_num}",
            "primary_language": "English",
        }
    )

        async for chunk in orchestrator.process_message(
            user_id, f"User {user_num}", session_id=None
        ):
            full_response += chunk

        results.append((user_id, full_response))

    # Process messages for 3 users concurrently
    async with trio.open_nursery() as nursery:
        for i in range(3):
            nursery.start_soon(process_for_user, i)

    # Verify all completed
    assert len(results) == 3

    # Verify all users were created
    trio_db_service = orchestrator.service_container.get("trio_db_service")
    for i in range(3):
        user_id = f"concurrent_user_{i}"
        profile = await trio_db_service.get_user_profile(user_id)
        assert profile is not None


@pytest.mark.trio
@pytest.mark.integration
async def test_orchestrator_creates_agents(orchestrator):
    """Test that orchestrator creates actual agent instances."""
    # Test that agents are created on demand
    user_id = "test_agent_creation"

    # Create agents for different types
    intake_agent = await orchestrator._get_or_create_agent("INTAKE", user_id)
    assert intake_agent is not None
    assert "TrioIntakeAgent" in str(type(intake_agent))

    assessment_agent = await orchestrator._get_or_create_agent("ASSESSMENT", user_id)
    assert assessment_agent is not None
    assert "TrioAssessmentAgent" in str(type(assessment_agent))

    therapist_agent = await orchestrator._get_or_create_agent(
        "THERAPIST", user_id
    )
    assert therapist_agent is not None
    assert "TrioTherapistAgent" in str(type(therapist_agent))

    # Verify caching works
    intake_agent_cached = await orchestrator._get_or_create_agent("INTAKE", user_id)
    assert intake_agent_cached is intake_agent  # Same instance


# ===== Integration Tests =====


@pytest.mark.trio
@pytest.mark.integration
async def test_full_orchestration_flow(orchestrator):
    """Test complete flow from user creation through message processing."""
    user_id = "full_flow_user"

    await orchestrator.create_user_profile(
        {
            "user_id": user_id,
            "name": "Alice Smith",
            "primary_language": "English",
        }
    )

    # Step 1: Process first message (starts intake)
    response1 = ""
    async for chunk in orchestrator.process_message(user_id, "Alice Smith"):
        response1 += chunk

    assert len(response1) > 0

    # Step 2: Verify user was created
    trio_db_service = orchestrator.service_container.get("trio_db_service")
    user_profile = await trio_db_service.get_user_profile(user_id)
    assert user_profile is not None
    assert user_profile.name == "Alice Smith"

    # Step 3: Verify state
    state = await orchestrator.get_user_state(user_id)
    assert state == WorkflowState.INTAKE_IN_PROGRESS

    # Step 4: Process another message (should continue intake)
    response2 = ""
    session_id = None  # Will use existing or create new
    async for chunk in orchestrator.process_message(
        user_id, "I'm feeling anxious", session_id
    ):
        response2 += chunk

    assert len(response2) > 0
