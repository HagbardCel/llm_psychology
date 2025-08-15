import pytest
from unittest.mock import Mock, AsyncMock, patch
import time
from agents.psychoanalyst_agent import PsychoanalystAgent
from models.data_models import Session, Message, TherapyPlan, UserProfile
from services.style_service import StyleService

class MockUI:
    """Mock UI for testing agents."""
    
    def __init__(self):
        self.displayed_messages = []
        self.user_inputs = []
        self.input_index = 0
    
    async def display_system_status(self, message):
        self.displayed_messages.append(("system", message))
    
    async def display_message(self, role, message):
        self.displayed_messages.append((role, message))
    
    async def get_user_input(self, prompt=None):
        if self.input_index < len(self.user_inputs):
            input_value = self.user_inputs[self.input_index]
            self.input_index += 1
            return input_value
        return ""

class TestPsychoanalystAgent:
    """Unit tests for PsychoanalystAgent."""
    
    @pytest.fixture
    def psychoanalyst_agent(self, mock_llm_service, db_service, mock_rag_service, user_context):
        """Create a PsychoanalystAgent instance for testing."""
        return PsychoanalystAgent(mock_llm_service, db_service, mock_rag_service, user_context)
    
    @pytest.fixture
    def mock_ui(self):
        """Create a mock UI for testing."""
        return MockUI()
    
    @pytest.fixture
    def sample_therapy_plan(self):
        """Create a sample therapy plan for testing."""
        return TherapyPlan(
            plan_id="test_plan_123",
            user_id="test_user_123",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            plan_details={
                "focus": "Work-related stress and anxiety",
                "goals": "Develop coping strategies",
                "techniques": "Cognitive restructuring"
            },
            version=1,
            selected_therapy_style="cbt"
        )
    
    def test_init(self, psychoanalyst_agent):
        """Test PsychoanalystAgent initialization."""
        assert psychoanalyst_agent is not None
        assert hasattr(psychoanalyst_agent, 'llm_service')
        assert hasattr(psychoanalyst_agent, 'db_service')
        assert hasattr(psychoanalyst_agent, 'rag_service')
    
    @pytest.mark.asyncio
    async def test_conduct_session(self, psychoanalyst_agent, mock_ui, mock_llm_service, db_service, mock_rag_service, sample_therapy_plan):
        """Test conducting a therapy session."""
        # Set up mock UI inputs (simulate a short conversation)
        mock_ui.user_inputs = [
            "I've been feeling overwhelmed at work",  # User input
            "quit"  # End conversation
        ]
        
        # Mock LLM responses
        mock_llm_service.generate_response.side_effect = [
            "Hello, welcome to our session.",  # Initial greeting
            "I understand you're feeling overwhelmed. Tell me more.",  # Continue conversation
            "Let's summarize what we've discussed."  # Closing
        ]
        
        # Mock RAG service responses
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Relevant psychological knowledge", "source": "cbt.md"}
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
        db_service.save_user_profile(mock_profile)
        
        # Mock style service
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_psychoanalyst_prompt.return_value = "CBT therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            session = await psychoanalyst_agent.conduct_session(sample_therapy_plan, 5, mock_ui)
        
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
    async def test_conduct_session_with_time_extension(self, psychoanalyst_agent, mock_ui, mock_llm_service, db_service, mock_rag_service, sample_therapy_plan):
        """Test conducting a session with time extension prompt."""
        # Set up mock UI inputs
        mock_ui.user_inputs = [
            "I want to discuss my feelings",  # User input
            "n"  # Don't extend session
        ]
        
        # Mock LLM responses
        mock_llm_service.generate_response.side_effect = [
            "Hello, welcome to our session.",
            "I'm here to listen to your feelings.",
            "Let's wrap up our session.",
            "Thank you for sharing today."
        ]
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Relevant knowledge", "source": "cbt.md"}
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
        db_service.save_user_profile(mock_profile)
        
        # Mock style service
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_psychoanalyst_prompt.return_value = "Therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            # Patch time to simulate session timeout
            with patch('time.time') as mock_time:
                # Simulate time progression
                mock_time.side_effect = [0, 0, 301, 301, 301]  # 5 minutes = 300 seconds
                
                session = await psychoanalyst_agent.conduct_session(sample_therapy_plan, 5, mock_ui)
        
        # Verify session was created
        assert session is not None
        
        # Verify extension prompt was shown
        displayed_messages = [msg[1] for msg in mock_ui.displayed_messages if msg[0] == "system"]
        assert any("session time is now up" in msg.lower() for msg in displayed_messages)
    
    @pytest.mark.asyncio
    async def test_conduct_session_empty_inputs(self, psychoanalyst_agent, mock_ui, mock_llm_service, db_service, mock_rag_service, sample_therapy_plan):
        """Test conducting session with empty user inputs."""
        # Set up mock UI inputs with empty responses
        mock_ui.user_inputs = ["", "", "I'm feeling okay", "quit"]
        
        # Mock LLM responses
        mock_llm_service.generate_response.side_effect = [
            "Hello, welcome to our session.",
            "I'm here to listen.",
            "Thank you for sharing.",
            "Let's wrap up."
        ]
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Knowledge content", "source": "cbt.md"}
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
        db_service.save_user_profile(mock_profile)
        
        # Mock style service
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_psychoanalyst_prompt.return_value = "Therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            session = await psychoanalyst_agent.conduct_session(sample_therapy_plan, 5, mock_ui)
        
        # Verify session was created successfully
        assert session is not None
        assert len(session.transcript) > 0

# Integration tests
class TestPsychoanalystAgentIntegration:
    """Integration tests for PsychoanalystAgent."""
    
    @pytest.mark.asyncio
    async def test_session_with_real_dependencies(self, mock_llm_service, db_service, mock_rag_service, sample_therapy_plan):
        """Test session with real service dependencies (mocked)."""
        psychoanalyst_agent = PsychoanalystAgent(mock_llm_service, db_service, mock_rag_service)
        
        # Create mock UI
        mock_ui = MockUI()
        mock_ui.user_inputs = ["I'm feeling stressed", "quit"]
        
        # Mock responses
        mock_llm_service.generate_response.side_effect = [
            "Welcome to your session.",
            "I understand you're feeling stressed.",
            "Thank you for sharing."
        ]
        
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Stress management techniques", "source": "cbt.md"}
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
        db_service.save_user_profile(mock_profile)
        
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_psychoanalyst_prompt.return_value = "Therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            session = await psychoanalyst_agent.conduct_session(sample_therapy_plan, 5, mock_ui)
            
            # Verify the process works with mocked dependencies
            assert isinstance(session, Session)
            mock_llm_service.generate_response.assert_called()
            mock_rag_service.retrieve_relevant_knowledge.assert_called()

# Edge case tests
class TestPsychoanalystAgentEdgeCases:
    """Edge case tests for PsychoanalystAgent."""
    
    @pytest.mark.asyncio
    async def test_conduct_session_llm_error(self, mock_llm_service, db_service, mock_rag_service, sample_therapy_plan):
        """Test conducting session when LLM service fails."""
        psychoanalyst_agent = PsychoanalystAgent(mock_llm_service, db_service, mock_rag_service)
        
        # Create mock UI
        mock_ui = MockUI()
        mock_ui.user_inputs = ["I'm feeling stressed", "quit"]
        
        # Mock LLM to return error message (simulating real LLM service error handling)
        mock_llm_service.generate_response.return_value = "I apologize, but I'm having trouble processing your request right now."
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Knowledge content", "source": "cbt.md"}
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
        db_service.save_user_profile(mock_profile)
        
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_psychoanalyst_prompt.return_value = "Therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            # Should handle LLM errors gracefully
            session = await psychoanalyst_agent.conduct_session(sample_therapy_plan, 5, mock_ui)
            
            # Session should still be created with error message
            assert session is not None
            # Check that the error message is in the transcript
            assert any("I apologize" in msg.content for msg in session.transcript)
    
    @pytest.mark.asyncio
    async def test_conduct_session_no_user_profile(self, mock_llm_service, db_service, mock_rag_service, sample_therapy_plan):
        """Test conducting session when no user profile exists."""
        psychoanalyst_agent = PsychoanalystAgent(mock_llm_service, db_service, mock_rag_service)
        
        # Create mock UI
        mock_ui = MockUI()
        mock_ui.user_inputs = ["Hello", "quit"]
        
        # Mock responses
        mock_llm_service.generate_response.side_effect = [
            "Hello, welcome to our session.",
            "I'm here to listen.",
            "Thank you for sharing."
        ]
        
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Knowledge content", "source": "cbt.md"}
        ]
        
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_psychoanalyst_prompt.return_value = "Therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            session = await psychoanalyst_agent.conduct_session(sample_therapy_plan, 5, mock_ui)
            
            # Should work even without user profile (defaults to "Client")
            assert session is not None
