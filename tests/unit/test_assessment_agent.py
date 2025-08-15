import pytest
from unittest.mock import Mock, AsyncMock, patch
from agents.assessment_agent import AssessmentAgent
from models.data_models import Session, Message, TherapyPlan
from services.style_service import StyleService

class TestAssessmentAgent:
    """Unit tests for AssessmentAgent."""
    
    @pytest.fixture
    def assessment_agent(self, mock_llm_service, db_service, mock_rag_service, user_context):
        """Create an AssessmentAgent instance for testing."""
        return AssessmentAgent(mock_llm_service, db_service, mock_rag_service, user_context)
    
    @pytest.fixture
    def sample_intake_session(self):
        """Create a sample intake session for testing."""
        return Session(
            session_id="test_session_123",
            user_id="test_user_123",
            timestamp="2024-01-01T00:00:00",
            transcript=[
                Message(role="user", content="I've been feeling anxious about work", timestamp="2024-01-01T00:00:00"),
                Message(role="assistant", content="I understand. Can you tell me more about your work situation?", timestamp="2024-01-01T00:00:01"),
                Message(role="user", content="I have a lot of deadlines and feel overwhelmed", timestamp="2024-01-01T00:00:02")
            ]
        )
    
    def test_init(self, assessment_agent):
        """Test AssessmentAgent initialization."""
        assert assessment_agent is not None
        assert hasattr(assessment_agent, 'llm_service')
        assert hasattr(assessment_agent, 'db_service')
        assert hasattr(assessment_agent, 'rag_service')
    
    def test_generate_recommendations(self, assessment_agent, sample_intake_session):
        """Test generating therapy style recommendations."""
        # Mock LLM response for assessment
        mock_assessment = "This patient shows signs of anxiety and work-related stress, making CBT a good fit."
        assessment_agent.llm_service.generate_response.return_value = mock_assessment
        
        # Mock style service
        mock_styles = ["cbt", "freud", "jung"]
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_available_styles.return_value = mock_styles
            mock_style_service.get_assessment_prompt.side_effect = [
                "CBT assessment prompt",
                "Freud assessment prompt", 
                "Jung assessment prompt"
            ]
            mock_style_service.get_style_description.side_effect = [
                "Cognitive Behavioral Therapy",
                "Freudian Psychoanalysis",
                "Jungian Analytical Psychology"
            ]
            
            recommendations = assessment_agent._generate_recommendations(sample_intake_session)
            
            # Verify recommendations structure
            assert len(recommendations) == 3
            assert all("style_id" in rec for rec in recommendations)
            assert all("name" in rec for rec in recommendations)
            assert all("description" in rec for rec in recommendations)
            assert all("assessment" in rec for rec in recommendations)
            
            # Verify LLM was called for each style
            assert assessment_agent.llm_service.generate_response.call_count == 3
    
    @pytest.mark.asyncio
    async def test_conduct_assessment(self, assessment_agent, sample_intake_session):
        """Test conducting the assessment process."""
        # Mock the _generate_recommendations method
        mock_recommendations = [
            {
                "style_id": "cbt",
                "name": "CBT",
                "description": "Cognitive Behavioral Therapy",
                "assessment": "Good fit for anxiety"
            }
        ]
        
        with patch.object(assessment_agent, '_generate_recommendations', return_value=mock_recommendations):
            recommendations = await assessment_agent.conduct_assessment(sample_intake_session)
            
            # Verify recommendations are returned correctly
            assert recommendations == mock_recommendations
            assert len(recommendations) == 1
            assert recommendations[0]["style_id"] == "cbt"
    
    def test_create_initial_plan_with_style(self, assessment_agent, sample_intake_session):
        """Test creating an initial therapy plan with a selected style."""
        # Mock the ReflectionAgent
        mock_plan = TherapyPlan(
            plan_id="test_plan_123",
            user_id="test_user_123",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            plan_details={"focus": "anxiety", "goals": "reduce stress"},
            version=1,
            selected_therapy_style="cbt"
        )
        
        with patch('agents.reflection_agent.ReflectionAgent') as mock_reflection_agent_class:
            mock_reflection_agent_instance = Mock()
            mock_reflection_agent_instance.create_initial_plan_with_style.return_value = mock_plan
            mock_reflection_agent_class.return_value = mock_reflection_agent_instance
            
            plan = assessment_agent.create_initial_plan_with_style(sample_intake_session, "cbt")
            
            # Verify plan is created correctly
            assert plan is not None
            assert plan.selected_therapy_style == "cbt"
            assert plan.user_id == "test_user_123"

# Integration tests
class TestAssessmentAgentIntegration:
    """Integration tests for AssessmentAgent."""
    
    @pytest.mark.asyncio
    async def test_assessment_with_real_dependencies(self, mock_llm_service, db_service, mock_rag_service, sample_session):
        """Test assessment with real service dependencies (mocked)."""
        assessment_agent = AssessmentAgent(mock_llm_service, db_service, mock_rag_service)
        
        # Mock style service responses
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_available_styles.return_value = ["cbt", "freud"]
            mock_style_service.get_assessment_prompt.return_value = "Assessment prompt for {style}"
            mock_style_service.get_style_description.return_value = "Therapy description"
            
            # Mock LLM responses
            mock_llm_service.generate_response.return_value = "Mock assessment response"
            
            recommendations = await assessment_agent.conduct_assessment(sample_session)
            
            # Verify the process works with mocked dependencies
            assert isinstance(recommendations, list)
            mock_llm_service.generate_response.assert_called()

# Edge case tests
class TestAssessmentAgentEdgeCases:
    """Edge case tests for AssessmentAgent."""
    
    def test_generate_recommendations_empty_session(self, mock_llm_service, db_service, mock_rag_service):
        """Test generating recommendations with an empty session."""
        assessment_agent = AssessmentAgent(mock_llm_service, db_service, mock_rag_service)
        
        empty_session = Session(
            session_id="empty_session",
            user_id="test_user",
            timestamp="2024-01-01T00:00:00",
            transcript=[]
        )
        
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_available_styles.return_value = ["cbt", "freud", "jung"]
            mock_style_service.get_assessment_prompt.side_effect = [
                "CBT assessment prompt",
                "Freud assessment prompt",
                "Jung assessment prompt"
            ]
            mock_style_service.get_style_description.side_effect = [
                "Cognitive Behavioral Therapy",
                "Freudian Psychoanalysis", 
                "Jungian Analytical Psychology"
            ]
            
            mock_llm_service.generate_response.return_value = "Assessment for empty session"
            
            recommendations = assessment_agent._generate_recommendations(empty_session)
            
            assert len(recommendations) == 3
            # Check that all styles are represented
            style_ids = [rec["style_id"] for rec in recommendations]
            assert "cbt" in style_ids
            assert "freud" in style_ids
            assert "jung" in style_ids
    
    @pytest.mark.asyncio
    async def test_conduct_assessment_llm_error(self, mock_llm_service, db_service, mock_rag_service, sample_session):
        """Test assessment when LLM service fails."""
        assessment_agent = AssessmentAgent(mock_llm_service, db_service, mock_rag_service)
        
        # Mock LLM to return error message (simulating real LLM service error handling)
        mock_llm_service.generate_response.return_value = "I apologize, but I'm having trouble processing your request right now."
        
        with patch('agents.assessment_agent.style_service') as mock_style_service:
            mock_style_service.get_available_styles.return_value = ["cbt"]
            mock_style_service.get_assessment_prompt.return_value = "Assessment prompt"
            mock_style_service.get_style_description.return_value = "CBT description"
            
            # Should handle LLM errors gracefully
            recommendations = await assessment_agent.conduct_assessment(sample_session)
            
            # Should still return recommendations with error messages
            assert isinstance(recommendations, list)
            assert len(recommendations) == 1
            assert "I apologize" in recommendations[0]["assessment"]
