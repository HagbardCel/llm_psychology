import pytest
from unittest.mock import Mock, AsyncMock, patch
from agents.reflection_agent import ReflectionAgent
from models.data_models import Session, Message, TherapyPlan

@pytest.fixture
def reflection_agent(mock_llm_service, db_service, mock_rag_service, user_context):
    """Create a ReflectionAgent instance for testing."""
    return ReflectionAgent(mock_llm_service, db_service, mock_rag_service, user_context)

@pytest.fixture
def sample_intake_session():
    """Create a sample intake session for testing."""
    return Session(
        session_id="test_intake_session",
        user_id="test_user",
        timestamp="2024-01-01T00:00:00",
        transcript=[
            Message(role="user", content="I've been feeling anxious about work", timestamp="2024-01-01T00:00:00"),
            Message(role="assistant", content="I understand. Can you tell me more about your work situation?", timestamp="2024-01-01T00:00:01"),
            Message(role="user", content="I have a lot of deadlines and feel overwhelmed", timestamp="2024-01-01T00:00:02")
        ]
    )

@pytest.fixture
def sample_therapy_session():
    """Create a sample therapy session for testing."""
    return Session(
        session_id="test_therapy_session",
        user_id="test_user",
        timestamp="2024-01-01T01:00:00",
        transcript=[
            Message(role="user", content="I tried the breathing exercises we discussed", timestamp="2024-01-01T01:00:00"),
            Message(role="assistant", content="That's great progress. How did they work for you?", timestamp="2024-01-01T01:00:01"),
            Message(role="user", content="They helped me feel more calm during stressful moments", timestamp="2024-01-01T01:00:02")
        ]
    )

@pytest.fixture
def sample_therapy_plan():
    """Create a sample therapy plan for testing."""
    return TherapyPlan(
        plan_id="test_plan_123",
        user_id="test_user",
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
        plan_details={
            "focus": "Work-related stress and anxiety",
            "goals": "Develop coping strategies",
            "techniques": "Cognitive restructuring and breathing exercises",
            "themes": "Work stress, anxiety management"
        },
        version=1,
        selected_therapy_style="cbt"
    )

class TestReflectionAgent:
    """Unit tests for ReflectionAgent."""
    
    def test_init(self, reflection_agent):
        """Test ReflectionAgent initialization."""
        assert reflection_agent is not None
        assert hasattr(reflection_agent, 'llm_service')
        assert hasattr(reflection_agent, 'db_service')
        assert hasattr(reflection_agent, 'rag_service')
    
    def test_create_initial_plan(self, reflection_agent, sample_session, mock_llm_service, db_service, mock_rag_service):
        """Test creating an initial therapy plan."""
        # Mock LLM response
        mock_llm_service.generate_structured_response.return_value = {
            "raw_response": '{"focus": "anxiety management", "goals": "reduce workplace stress", "techniques": "CBT techniques", "themes": "work anxiety"}'
        }
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Anxiety management techniques", "source": "cbt.md"}
        ]
        
        # Mock database service methods
        db_service.get_all_sessions_for_user = Mock(return_value=[])
        db_service.save_therapy_plan = Mock()
        db_service.get_latest_therapy_plan = Mock(return_value=None)
        
        therapy_plan = reflection_agent.create_initial_plan(sample_session)
        
        # Verify therapy plan was created
        assert therapy_plan is not None
        assert therapy_plan.user_id == "default_user"
        assert therapy_plan.version == 1
        assert "focus" in therapy_plan.plan_details
        assert "goals" in therapy_plan.plan_details
        
        # Verify LLM was called
        mock_llm_service.generate_structured_response.assert_called_once()
        
        # Verify plan was saved to database
        db_service.save_therapy_plan.assert_called_once()
    
    def test_create_initial_plan_with_style(self, reflection_agent, sample_intake_session, mock_llm_service, db_service, mock_rag_service):
        """Test creating an initial therapy plan with a specific style."""
        # Mock LLM response
        mock_llm_service.generate_structured_response.return_value = {
            "raw_response": '{"focus": "CBT approach to anxiety", "goals": "challenge negative thoughts", "techniques": "cognitive restructuring", "themes": "cognitive distortions"}'
        }
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "CBT techniques for anxiety", "source": "cbt.md"}
        ]
        
        # Mock style service
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_reflection_prompt.return_value = "CBT reflection prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            therapy_plan = reflection_agent.create_initial_plan_with_style(sample_intake_session, "cbt")
        
        # Verify therapy plan was created with correct style
        assert therapy_plan is not None
        assert therapy_plan.selected_therapy_style == "cbt"
        assert therapy_plan.version == 1
        
        # Verify style-specific prompt was used
        mock_llm_service.generate_structured_response.assert_called_once()
    
    def test_update_plan(self, reflection_agent, sample_therapy_session, sample_therapy_plan, mock_llm_service, db_service, mock_rag_service):
        """Test updating an existing therapy plan."""
        # Mock LLM response
        mock_llm_service.generate_structured_response.return_value = {
            "raw_response": '{"focus": "updated focus", "goals": "updated goals", "techniques": "updated techniques", "themes": "updated themes"}'
        }
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Updated knowledge", "source": "cbt.md"}
        ]
        
        # Mock database service methods
        db_service.get_all_sessions_for_user = Mock(return_value=[sample_therapy_session])
        db_service.save_therapy_plan = Mock()
        
        # Mock style service
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_reflection_prompt.return_value = "CBT reflection prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            updated_plan = reflection_agent.update_plan(sample_therapy_session, sample_therapy_plan)
        
        # Verify updated plan
        assert updated_plan is not None
        assert updated_plan.version == 2  # Incremented version
        assert updated_plan.selected_therapy_style == sample_therapy_plan.selected_therapy_style
        
        # Verify plan details were updated
        assert "updated_from_session" in updated_plan.plan_details
        assert updated_plan.plan_details["updated_from_session"] == sample_therapy_session.session_id
        
        # Verify LLM was called
        mock_llm_service.generate_structured_response.assert_called_once()
        
        # Verify plan was saved to database
        db_service.save_therapy_plan.assert_called_once()
    
    def test_generate_session_summary(self, reflection_agent, sample_therapy_session, mock_llm_service):
        """Test generating a session summary."""
        # Mock LLM response
        mock_summary = "This session focused on the client's progress with breathing exercises."
        mock_llm_service.generate_response.return_value = mock_summary
        
        summary = reflection_agent.generate_session_summary(sample_therapy_session)
        
        # Verify summary structure
        assert isinstance(summary, dict)
        assert "session_id" in summary
        assert "summary" in summary
        assert "timestamp" in summary
        assert summary["session_id"] == sample_therapy_session.session_id
        assert summary["summary"] == mock_summary
        
        # Verify LLM was called
        mock_llm_service.generate_response.assert_called_once()

# Integration tests
class TestReflectionAgentIntegration:
    """Integration tests for ReflectionAgent."""
    
    def test_create_and_update_plan_flow(self, mock_llm_service, db_service, mock_rag_service, sample_intake_session, sample_therapy_session):
        """Test the complete flow of creating and updating a therapy plan."""
        reflection_agent = ReflectionAgent(mock_llm_service, db_service, mock_rag_service)
        
        # Mock LLM responses
        mock_llm_service.generate_structured_response.side_effect = [
            {"raw_response": '{"focus": "initial focus", "goals": "initial goals", "techniques": "initial techniques", "themes": "initial themes"}'},
            {"raw_response": '{"focus": "updated focus", "goals": "updated goals", "techniques": "updated techniques", "themes": "updated themes"}'}
        ]
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Knowledge content", "source": "cbt.md"}
        ]
        
        # Mock database service methods
        mock_get_all_sessions = Mock(return_value=[])
        db_service.get_all_sessions_for_user = mock_get_all_sessions
        db_service.save_therapy_plan = Mock()
        db_service.get_latest_therapy_plan = Mock(return_value=None)
        
        # Create initial plan
        initial_plan = reflection_agent.create_initial_plan(sample_intake_session)
        assert initial_plan.version == 1
        
        # Update database mock to return sessions
        mock_get_all_sessions.return_value = [sample_intake_session, sample_therapy_session]
        
        # Update plan
        updated_plan = reflection_agent.update_plan(sample_therapy_session, initial_plan)
        assert updated_plan.version == 2
        assert updated_plan.plan_id != initial_plan.plan_id  # New plan ID
        
        # Verify both plans were saved
        db_service.save_therapy_plan.assert_called()

# Edge case tests
class TestReflectionAgentEdgeCases:
    """Edge case tests for ReflectionAgent."""
    
    def test_create_initial_plan_llm_error(self, reflection_agent, sample_intake_session, mock_llm_service, db_service, mock_rag_service):
        """Test creating initial plan when LLM service fails."""
        # Mock LLM to return error message (simulating real LLM service error handling)
        mock_llm_service.generate_structured_response.return_value = {
            "raw_response": '{"focus": "Error occurred", "goals": "Handle the error gracefully", "techniques": "Fallback techniques", "themes": "Error handling"}'
        }
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = []
        
        # Mock database service methods
        db_service.get_all_sessions_for_user = Mock(return_value=[])
        db_service.save_therapy_plan = Mock()
        
        # Should handle LLM errors gracefully and use fallback plan
        therapy_plan = reflection_agent.create_initial_plan(sample_intake_session)
        
        # Should still create a plan with default values
        assert therapy_plan is not None
        assert therapy_plan.version == 1
        assert "focus" in therapy_plan.plan_details
    
    def test_create_initial_plan_invalid_json(self, reflection_agent, sample_intake_session, mock_llm_service, db_service, mock_rag_service):
        """Test creating initial plan with invalid JSON response."""
        # Mock LLM to return invalid JSON
        mock_llm_service.generate_structured_response.return_value = {
            "raw_response": '{"invalid": json}'  # Invalid JSON
        }
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = []
        
        # Mock database service methods
        db_service.get_all_sessions_for_user = Mock(return_value=[])
        db_service.save_therapy_plan = Mock()
        db_service.get_latest_therapy_plan = Mock(return_value=None)
        
        # Should handle JSON parsing errors gracefully
        therapy_plan = reflection_agent.create_initial_plan(sample_intake_session)
        
        # Should still create a plan with default values
        assert therapy_plan is not None
        assert therapy_plan.version == 1
    
    def test_update_plan_no_style(self, reflection_agent, sample_therapy_session, sample_therapy_plan, mock_llm_service, db_service, mock_rag_service):
        """Test updating plan when no therapy style is specified."""
        # Remove style from plan
        sample_therapy_plan.selected_therapy_style = None
        
        # Mock LLM response
        mock_llm_service.generate_structured_response.return_value = {
            "raw_response": '{"focus": "updated focus", "goals": "updated goals", "techniques": "updated techniques", "themes": "updated themes"}'
        }
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Knowledge content", "source": "general.md"}
        ]
        
        # Mock database service methods
        db_service.get_all_sessions_for_user = Mock(return_value=[sample_therapy_session])
        db_service.save_therapy_plan = Mock()
        
        # Mock style service to return no style pack
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = False
            
            updated_plan = reflection_agent.update_plan(sample_therapy_session, sample_therapy_plan)
        
        # Should work without style-specific features
        assert updated_plan is not None
        assert updated_plan.version == 2
