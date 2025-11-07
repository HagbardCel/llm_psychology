import pytest
from unittest.mock import Mock, AsyncMock, patch
import asyncio
from datetime import datetime

# Integration test for complete session flow
class TestCompleteSessionFlow:
    """Integration tests for the complete therapy session flow."""
    
    @pytest.mark.asyncio
    async def test_intake_to_assessment_to_session_flow(self, mock_llm_service, db_service, mock_rag_service):
        """Test the complete flow from intake through assessment to therapy session."""
        from agents.intake_agent import IntakeAgent
        from agents.assessment_agent import AssessmentAgent
        from agents.psychoanalyst_agent import PsychoanalystAgent
        from agents.reflection_agent import ReflectionAgent
        from models.data_models import Session, Message, TherapyPlan, UserProfile
        
        # Create mock UI
        class MockUI:
            def __init__(self):
                self.displayed_messages = []
                self.user_inputs = [
                    "John Doe",  # name
                    "1990-01-01",  # birthdate
                    "Software Engineer",  # profession
                    "I've been feeling anxious about work lately",  # intake conversation
                    "quit",  # end intake
                    "I tried the breathing exercises",  # therapy session
                    "quit"  # end therapy session
                ]
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
        
        mock_ui = MockUI()
        
        # Mock LLM responses for all agents
        mock_llm_service.generate_response.side_effect = [
            # IntakeAgent responses
            "Welcome John, thank you for sharing your information.",
            "I understand you're feeling anxious about work. Tell me more.",
            "Thank you for sharing. Let's summarize our conversation.",
            
            # AssessmentAgent responses
            "Based on your concerns, CBT would be a good approach.",
            
            # PsychoanalystAgent responses
            "Welcome to your CBT session, John.",
            "I'm glad to hear the breathing exercises helped.",
            "Let's wrap up our session.",
            
            # ReflectionAgent responses (initial plan)
            '{"focus": "work-related anxiety", "goals": "develop coping strategies", "techniques": "CBT techniques", "themes": "work stress"}',
            
            # ReflectionAgent responses (update plan)
            '{"focus": "progress with breathing exercises", "goals": "continue CBT techniques", "techniques": "breathing and cognitive restructuring", "themes": "anxiety management"}',
        ]
        
        mock_llm_service.generate_structured_response.side_effect = [
            # ReflectionAgent structured responses
            {"raw_response": '{"focus": "work-related anxiety", "goals": "develop coping strategies", "techniques": "CBT techniques", "themes": "work stress"}'},
            {"raw_response": '{"focus": "progress with breathing exercises", "goals": "continue CBT techniques", "techniques": "breathing and cognitive restructuring", "themes": "anxiety management"}'},
        ]
        
        # Mock RAG service
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "CBT techniques for anxiety", "source": "cbt.md"}
        ]
        
        # Mock style service
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_available_styles.return_value = ["cbt"]
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_assessment_prompt.return_value = "CBT assessment prompt"
            mock_style_service.get_style_description.return_value = "Cognitive Behavioral Therapy"
            mock_style_service.get_psychoanalyst_prompt.return_value = "CBT therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            mock_style_service.get_reflection_prompt.return_value = "CBT reflection prompt"
        
        # Step 1: Intake process
        intake_agent = IntakeAgent(mock_llm_service, db_service)
        intake_session = await intake_agent.conduct_intake(mock_ui)
        
        # Verify intake session was created
        assert intake_session is not None
        assert len(intake_session.transcript) > 0
        assert intake_session.user_id == "default_user"
        
        # Verify user profile was saved
        user_profile = db_service.get_user_profile("default_user")
        assert user_profile is not None
        assert user_profile.name == "John Doe"
        
        # Step 2: Assessment process
        assessment_agent = AssessmentAgent(mock_llm_service, db_service, mock_rag_service)
        recommendations = await assessment_agent.conduct_assessment(intake_session)
        
        # Verify recommendations were generated
        assert isinstance(recommendations, list)
        assert len(recommendations) > 0
        
        # Select CBT as the therapy style
        selected_style = "cbt"
        
        # Create initial plan with selected style
        initial_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
        
        # Verify initial plan was created
        assert initial_plan is not None
        assert initial_plan.selected_therapy_style == "cbt"
        assert initial_plan.version == 1
        
        # Step 3: Therapy session
        psychoanalyst_agent = PsychoanalystAgent(mock_llm_service, db_service, mock_rag_service)
        therapy_session = await psychoanalyst_agent.conduct_session(initial_plan, 5, mock_ui)
        
        # Verify therapy session was created
        assert therapy_session is not None
        assert len(therapy_session.transcript) > 0
        assert therapy_session.session_id != intake_session.session_id
        
        # Step 4: Reflection and plan update
        reflection_agent = ReflectionAgent(mock_llm_service, db_service, mock_rag_service)
        updated_plan = reflection_agent.update_plan(therapy_session, initial_plan)
        
        # Verify plan was updated
        assert updated_plan is not None
        assert updated_plan.version == 2
        assert updated_plan.selected_therapy_style == "cbt"
        assert updated_plan.plan_id != initial_plan.plan_id
        
        # Verify all sessions were saved
        all_sessions = db_service.get_all_sessions_for_user("default_user")
        assert len(all_sessions) == 2  # intake + therapy
        
        # Verify final plan was saved
        final_plan = db_service.get_latest_therapy_plan("default_user")
        assert final_plan is not None
        assert final_plan.version == 2
        
        # Verify the flow completed successfully
        assert mock_llm_service.generate_response.call_count >= 7
        assert mock_llm_service.generate_structured_response.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_resume_flow_integration(self, db_service):
        """Test the resume flow integration with database service."""
        from services.db_service import UserStatus
        
        # Test initial state (no data)
        status = db_service.get_user_status("test_user")
        assert status == UserStatus.NO_DATA
        
        # Create user profile
        from models.data_models import UserProfile
        profile = UserProfile(
            user_id="test_user",
            name="Test User",
            birthdate="1990-01-01",
            profession="Tester",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00"
        )
        db_service.save_user_profile(profile)
        
        # Verify profile-only state
        status = db_service.get_user_status("test_user")
        assert status == UserStatus.PROFILE_ONLY
        
        # Create intake session
        from models.data_models import Session, Message
        session = Session(
            session_id="test_session_1",
            user_id="test_user",
            timestamp="2024-01-01T01:00:00",
            transcript=[
                Message(role="user", content="Hello", timestamp="2024-01-01T01:00:00")
            ]
        )
        db_service.save_session(session)
        
        # Verify intake-complete state
        status = db_service.get_user_status("test_user")
        assert status == UserStatus.INTAKE_COMPLETE
        
        # Create therapy plan
        from models.data_models import TherapyPlan
        plan = TherapyPlan(
            plan_id="test_plan_1",
            user_id="test_user",
            created_at="2024-01-01T02:00:00",
            updated_at="2024-01-01T02:00:00",
            plan_details={"focus": "test", "goals": "test", "techniques": "test", "themes": "test"},
            version=1,
            selected_therapy_style="cbt"
        )
        db_service.save_therapy_plan(plan)
        
        # Verify plan-complete state
        status = db_service.get_user_status("test_user")
        assert status == UserStatus.PLAN_COMPLETE

# Performance and stress tests
class TestPerformanceIntegration:
    """Performance and stress tests for integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_multiple_sessions_performance(self, mock_llm_service, db_service, mock_rag_service):
        """Test performance with multiple sessions."""
        from agents.intake_agent import IntakeAgent
        from agents.psychoanalyst_agent import PsychoanalystAgent
        from agents.reflection_agent import ReflectionAgent
        from models.data_models import Session, Message, TherapyPlan
        
        # Create mock UI for multiple sessions
        class MockUI:
            def __init__(self):
                self.user_inputs = ["Test User", "1990-01-01", "Tester", "I'm feeling stressed", "quit"]
                self.input_index = 0
            
            async def display_system_status(self, message):
                pass
            
            async def display_message(self, role, message):
                pass
            
            async def get_user_input(self, prompt=None):
                if self.input_index < len(self.user_inputs):
                    input_value = self.user_inputs[self.input_index]
                    self.input_index += 1
                    return input_value
                return ""
        
        # Mock responses
        mock_llm_service.generate_response.side_effect = [
            "Welcome", "I understand", "Thank you",  # Intake responses
            "Welcome to session", "I'm here to help", "Let's wrap up"  # Session responses
        ]
        
        mock_llm_service.generate_structured_response.return_value = {
            "raw_response": '{"focus": "stress", "goals": "manage stress", "techniques": "relaxation", "themes": "daily stress"}'
        }
        
        mock_rag_service.retrieve_relevant_knowledge.return_value = [
            {"content": "Stress management", "source": "cbt.md"}
        ]
        
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_psychoanalyst_prompt.return_value = "Therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            mock_style_service.get_reflection_prompt.return_value = "Reflection prompt"
        
        intake_agent = IntakeAgent(mock_llm_service, db_service)
        psychoanalyst_agent = PsychoanalystAgent(mock_llm_service, db_service, mock_rag_service)
        reflection_agent = ReflectionAgent(mock_llm_service, db_service, mock_rag_service)
        
        # Create initial plan
        mock_ui = MockUI()
        intake_session = await intake_agent.conduct_intake(mock_ui)
        
        from agents.assessment_agent import AssessmentAgent
        assessment_agent = AssessmentAgent(mock_llm_service, db_service, mock_rag_service)
        
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_available_styles.return_value = ["cbt"]
            mock_style_service.get_assessment_prompt.return_value = "Assessment prompt"
            mock_style_service.get_style_description.return_value = "CBT"
            
            initial_plan = assessment_agent.create_initial_plan_with_style(intake_session, "cbt")
        
        # Conduct multiple therapy sessions
        sessions = []
        for i in range(3):  # Create 3 sessions
            mock_ui = MockUI()
            mock_ui.user_inputs = [f"Session {i} update", "quit"]
            mock_llm_service.generate_response.side_effect = [
                f"Welcome to session {i}",
                f"Session {i} response",
                f"Wrap up session {i}"
            ]
            
            session = await psychoanalyst_agent.conduct_session(initial_plan, 2, mock_ui)
            sessions.append(session)
            
            # Update plan after each session
            updated_plan = reflection_agent.update_plan(session, initial_plan)
            initial_plan = updated_plan  # Use updated plan for next session
        
        # Verify all sessions were created and saved
        all_sessions = db_service.get_all_sessions_for_user("default_user")
        assert len(all_sessions) == 4  # 1 intake + 3 therapy sessions
        
        # Verify final plan version
        final_plan = db_service.get_latest_therapy_plan("default_user")
        assert final_plan.version == 4  # 1 initial + 3 updates

# Error handling integration tests
class TestErrorHandlingIntegration:
    """Integration tests for error handling scenarios."""
    
    @pytest.mark.asyncio
    async def test_graceful_error_handling(self, mock_llm_service, db_service, mock_rag_service):
        """Test that the system handles errors gracefully."""
        from agents.intake_agent import IntakeAgent
        from agents.assessment_agent import AssessmentAgent
        from agents.psychoanalyst_agent import PsychoanalystAgent
        from agents.reflection_agent import ReflectionAgent
        
        class MockUI:
            def __init__(self):
                self.user_inputs = ["Test User", "1990-01-01", "Tester", "I'm feeling stressed", "quit"]
                self.input_index = 0
            
            async def display_system_status(self, message):
                pass
            
            async def display_message(self, role, message):
                pass
            
            async def get_user_input(self, prompt=None):
                if self.input_index < len(self.user_inputs):
                    input_value = self.user_inputs[self.input_index]
                    self.input_index += 1
                    return input_value
                return ""
        
        # Mock LLM to return error messages (simulating graceful error handling)
        mock_llm_service.generate_response.return_value = "I apologize, but I'm experiencing technical difficulties. Let me try to help you in a different way."
        mock_llm_service.generate_structured_response.return_value = {
            "raw_response": '{"error": "LLM service temporarily unavailable", "fallback": "using default responses"}'
        }
        
        # Mock RAG service to return empty results (simulating failure)
        mock_rag_service.retrieve_relevant_knowledge.return_value = []
        
        mock_ui = MockUI()
        intake_agent = IntakeAgent(mock_llm_service, db_service)
        
        # Should handle errors gracefully and still create session
        intake_session = await intake_agent.conduct_intake(mock_ui)
        assert intake_session is not None
        
        # Test assessment with errors
        assessment_agent = AssessmentAgent(mock_llm_service, db_service, mock_rag_service)
        
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_available_styles.return_value = ["cbt"]
            mock_style_service.get_assessment_prompt.return_value = "Assessment prompt"
            mock_style_service.get_style_description.return_value = "CBT"
            
            recommendations = await assessment_agent.conduct_assessment(intake_session)
            # Should return recommendations even with errors
            assert isinstance(recommendations, list)
        
        # Test session with errors (should raise exception for None plan)
        psychoanalyst_agent = PsychoanalystAgent(mock_llm_service, db_service, mock_rag_service)
        
        with patch('services.style_service.style_service') as mock_style_service:
            mock_style_service.get_style_pack.return_value = True
            mock_style_service.get_psychoanalyst_prompt.return_value = "Therapist prompt"
            mock_style_service.get_knowledge_source.return_value = "cbt.md"
            
            # Should raise exception for None plan
            from exceptions import PsychoanalystAgentError
            with pytest.raises(PsychoanalystAgentError):
                await psychoanalyst_agent.conduct_session(None, 5, mock_ui)
        
        # Test reflection with errors (should handle None plan gracefully)
        reflection_agent = ReflectionAgent(mock_llm_service, db_service, mock_rag_service)
        updated_plan = reflection_agent.update_plan(None, None)
        # Should handle None plan gracefully
        assert updated_plan is not None
