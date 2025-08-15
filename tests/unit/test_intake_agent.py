import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from agents.intake_agent import IntakeAgent
from models.data_models import Session, Message, UserProfile, Topic
from prompts.intake_prompts import INITIAL_GREETING_PROMPT, CONTINUE_CONVERSATION_PROMPT, CLOSING_PROMPT

class TestIntakeAgent:
    """Unit tests for IntakeAgent."""
    
    def test_init(self, intake_agent):
        """Test IntakeAgent initialization."""
        assert intake_agent is not None
        assert hasattr(intake_agent, 'llm_service')
        assert hasattr(intake_agent, 'db_service')
    
    @pytest.mark.asyncio
    async def test_collect_user_profile(self, intake_agent, mock_ui, db_service):
        """Test collecting user profile information."""
        # Set up mock UI inputs
        mock_ui.user_inputs = ["John Doe", "1990-01-01", "Software Engineer"]
        
        # Mock LLM response
        intake_agent.llm_service.generate_response.return_value = "Welcome response"
        
        # Test profile collection
        profile = await intake_agent._collect_user_profile(mock_ui)
        
        # Verify profile data
        assert profile.name == "John Doe"
        assert profile.profession == "Software Engineer"
        # Note: birthdate parsing would need to be tested more thoroughly
        
        # Verify UI interactions
        displayed_messages = [msg[1] for msg in mock_ui.displayed_messages if msg[0] == "system"]
        assert any("get to know you better" in msg for msg in displayed_messages)
        assert any("Thank you, John Doe" in msg for msg in displayed_messages)
        
        # Verify profile was saved to database
        saved_profile = db_service.get_user_profile(intake_agent.user_id)
        assert saved_profile is not None
        assert saved_profile.name == "John Doe"
    
    def test_get_pending_topics(self, intake_agent):
        """Test getting pending topics."""
        session = Session(
            session_id="test_session",
            user_id="test_user",
            timestamp="2024-01-01T00:00:00",
            transcript=[],
            topics=[
                Topic(name="anxiety", status="pending"),
                Topic(name="depression", status="covered"),
                Topic(name="stress", status="pending")
            ]
        )
        
        pending_topics = intake_agent._get_pending_topics(session)
        assert len(pending_topics) == 2
        assert "anxiety" in pending_topics
        assert "stress" in pending_topics
    
    def test_get_covered_topics(self, intake_agent):
        """Test getting covered topics."""
        session = Session(
            session_id="test_session",
            user_id="test_user",
            timestamp="2024-01-01T00:00:00",
            transcript=[],
            topics=[
                Topic(name="anxiety", status="covered"),
                Topic(name="depression", status="partially_covered"),
                Topic(name="stress", status="pending")
            ]
        )
        
        covered_topics = intake_agent._get_covered_topics(session)
        assert len(covered_topics) == 2
        assert "anxiety" in covered_topics
        assert "depression" in covered_topics
    
    def test_update_topic_status(self, intake_agent):
        """Test updating topic status."""
        session = Session(
            session_id="test_session",
            user_id="test_user",
            timestamp="2024-01-01T00:00:00",
            transcript=[],
            topics=[
                Topic(name="anxiety", status="pending"),
                Topic(name="stress", status="pending")
            ]
        )
        
        intake_agent._update_topic_status(session, "anxiety", "covered")
        
        anxiety_topic = next((t for t in session.topics if t.name == "anxiety"), None)
        assert anxiety_topic is not None
        assert anxiety_topic.status == "covered"
        
        stress_topic = next((t for t in session.topics if t.name == "stress"), None)
        assert stress_topic is not None
        assert stress_topic.status == "pending"
    
    @pytest.mark.asyncio
    async def test_conduct_intake(self, intake_agent, mock_ui, mock_llm_service, db_service):
        """Test conducting the intake conversation."""
        # Set up mock UI inputs (simulate a short conversation)
        mock_ui.user_inputs = [
            "I've been feeling stressed about work",  # User input
            "quit"  # End conversation
        ]
        
        # Mock LLM responses
        mock_llm_service.generate_response.side_effect = [
            "Hello John, welcome to your session.",  # Initial greeting
            "I understand you're feeling stressed. Tell me more.",  # Continue conversation
            "Thank you for sharing. Let's summarize."  # Closing
        ]
        
        # Mock user profile
        mock_profile = UserProfile(
            user_id="default_user",
            name="John Doe",
            birthdate="1990-01-01",
            profession="Software Engineer",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00"
        )
        
        # Mock the _collect_user_profile method
        with patch.object(intake_agent, '_collect_user_profile', return_value=mock_profile):
            session = await intake_agent.conduct_intake(mock_ui)
        
        # Verify session was created
        assert session is not None
        assert session.user_id == "default_user"
        assert len(session.transcript) >= 3  # At least greeting, user input, response, closing
        
        # Verify LLM was called with correct prompts
        calls = mock_llm_service.generate_response.call_args_list
        assert len(calls) == 3
        
        # Verify session was saved to database
        saved_session = db_service.get_session(session.session_id)
        assert saved_session is not None
        assert saved_session.session_id == session.session_id
    
    @pytest.mark.asyncio
    async def test_conduct_intake_empty_inputs(self, intake_agent, mock_ui, mock_llm_service):
        """Test conducting intake with empty user inputs."""
        # Set up mock UI inputs with empty responses
        mock_ui.user_inputs = ["", "", "I'm feeling okay", "quit"]
        
        # Mock LLM responses
        mock_llm_service.generate_response.side_effect = [
            "Hello, welcome to your session.",
            "I'm here to listen.",
            "Thank you for sharing.",
            "Let's wrap up."
        ]
        
        # Mock user profile
        mock_profile = UserProfile(
            user_id="default_user",
            name="Test User",
            birthdate="1990-01-01",
            profession="Tester",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00"
        )
        
        with patch.object(intake_agent, '_collect_user_profile', return_value=mock_profile):
            session = await intake_agent.conduct_intake(mock_ui)
        
        # Verify session was created successfully
        assert session is not None
        assert len(session.transcript) > 0

# Additional tests for edge cases and error handling
class TestIntakeAgentEdgeCases:
    """Edge case tests for IntakeAgent."""
    
    @pytest.mark.asyncio
    async def test_collect_user_profile_invalid_date(self, mock_llm_service, db_service, mock_ui):
        """Test collecting user profile with invalid date format."""
        intake_agent = IntakeAgent(mock_llm_service, db_service)
        mock_ui.user_inputs = ["John Doe", "invalid-date", "Software Engineer"]
        
        profile = await intake_agent._collect_user_profile(mock_ui)
        
        # Should handle invalid date gracefully
        assert profile.name == "John Doe"
        assert profile.birthdate is None  # Should be None for invalid date
        assert profile.profession == "Software Engineer"
    
    @pytest.mark.asyncio
    async def test_collect_user_profile_empty_name(self, mock_llm_service, db_service, mock_ui):
        """Test collecting user profile with empty name."""
        intake_agent = IntakeAgent(mock_llm_service, db_service)
        mock_ui.user_inputs = ["", "", ""]  # Empty inputs
        
        profile = await intake_agent._collect_user_profile(mock_ui)
        
        # Should default to Anonymous User
        assert profile.name == "Anonymous User"
        assert profile.profession is None
    
    @pytest.mark.asyncio
    async def test_conduct_intake_llm_error(self, mock_llm_service, db_service, mock_ui):
        """Test conducting intake when LLM service fails."""
        intake_agent = IntakeAgent(mock_llm_service, db_service)
        
        # Mock LLM to return error message (simulating real LLM service error handling)
        mock_llm_service.generate_response.return_value = "I apologize, but I'm having trouble processing your request right now."
        
        mock_ui.user_inputs = ["I'm feeling stressed", "quit"]
        
        # Mock user profile
        mock_profile = UserProfile(
            user_id="default_user",
            name="Test User",
            birthdate="1990-01-01",
            profession="Tester",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00"
        )
        
        with patch.object(intake_agent, '_collect_user_profile', return_value=mock_profile):
            # Should handle LLM errors gracefully - the session should still be created
            # even if LLM calls fail
            session = await intake_agent.conduct_intake(mock_ui)
            
            # Session should still be created despite LLM errors
            assert session is not None
            # Verify that the session has some content even with LLM errors
            assert len(session.transcript) > 0
