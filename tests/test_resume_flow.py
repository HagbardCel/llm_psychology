#!/usr/bin/env python3
"""
Test script to verify the resumable sessions functionality.
This test simulates different user states and verifies the correct workflow.
"""

import sys
import os
import asyncio
import unittest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set test environment
os.environ['APP_ENV'] = 'testing'

from config import Config
from services.db_service import DatabaseService, UserStatus
from services.rag_service import RAGService
from services.llm_service import LLMService
from agents.intake_agent import IntakeAgent
from agents.assessment_agent import AssessmentAgent
from agents.reflection_agent import ReflectionAgent
from agents.psychoanalyst_agent import PsychoanalystAgent
from utils.data_models import Session, Message, TherapyPlan, UserProfile
from ui.textual_ui import ConsoleUI

class TestResumeFlow(unittest.TestCase):
    """Test cases for resumable sessions functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.db_service = DatabaseService(Config.DATABASE_PATH)
        self.db_service.clear_all_data()  # Start with clean database
        
    def test_user_status_no_data(self):
        """Test that user status is NO_DATA when no data exists."""
        status = self.db_service.get_user_status()
        self.assertEqual(status, UserStatus.NO_DATA)
    
    def test_user_status_profile_only(self):
        """Test that user status is PROFILE_ONLY when only profile exists."""
        # Create a user profile
        profile = UserProfile(
            user_id="default_user",
            name="Test User",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.db_service.save_user_profile(profile)
        
        status = self.db_service.get_user_status()
        self.assertEqual(status, UserStatus.PROFILE_ONLY)
    
    def test_user_status_intake_complete(self):
        """Test that user status is INTAKE_COMPLETE when sessions exist but no plan."""
        # Create a user profile
        profile = UserProfile(
            user_id="default_user",
            name="Test User",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.db_service.save_user_profile(profile)
        
        # Create a session
        session = Session(
            session_id="test_session_1",
            user_id="default_user",
            timestamp=datetime.now(),
            transcript=[Message(role="user", content="Hello", timestamp=datetime.now())]
        )
        self.db_service.save_session(session)
        
        status = self.db_service.get_user_status()
        self.assertEqual(status, UserStatus.INTAKE_COMPLETE)
    
    def test_user_status_plan_complete(self):
        """Test that user status is PLAN_COMPLETE when therapy plan exists."""
        # Create a user profile
        profile = UserProfile(
            user_id="default_user",
            name="Test User",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.db_service.save_user_profile(profile)
        
        # Create a session
        session = Session(
            session_id="test_session_1",
            user_id="default_user",
            timestamp=datetime.now(),
            transcript=[Message(role="user", content="Hello", timestamp=datetime.now())]
        )
        self.db_service.save_session(session)
        
        # Create a therapy plan
        plan = TherapyPlan(
            plan_id="test_plan_1",
            user_id="default_user",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details={"focus": "test", "goals": "test", "techniques": "test", "themes": "test"},
            version=1
        )
        self.db_service.save_therapy_plan(plan)
        
        status = self.db_service.get_user_status()
        self.assertEqual(status, UserStatus.PLAN_COMPLETE)

class TestMainWorkflow(unittest.IsolatedAsyncioTestCase):
    """Test the main workflow with mocked agents."""
    
    def setUp(self):
        """Set up test environment."""
        self.db_service = DatabaseService(Config.DATABASE_PATH)
        self.db_service.clear_all_data()  # Start with clean database
    
    @patch('agents.psychoanalyst_agent.PsychoanalystAgent.conduct_session')
    @patch('agents.reflection_agent.ReflectionAgent.update_plan')
    async def test_plan_complete_workflow(self, mock_update_plan, mock_conduct_session):
        """Test workflow when user has complete therapy plan."""
        # Set up test data
        profile = UserProfile(
            user_id="default_user",
            name="Test User",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.db_service.save_user_profile(profile)
        
        session = Session(
            session_id="test_session_1",
            user_id="default_user",
            timestamp=datetime.now(),
            transcript=[Message(role="user", content="Hello", timestamp=datetime.now())]
        )
        self.db_service.save_session(session)
        
        plan = TherapyPlan(
            plan_id="test_plan_1",
            user_id="default_user",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details={"focus": "test", "goals": "test", "techniques": "test", "themes": "test"},
            version=1
        )
        self.db_service.save_therapy_plan(plan)
        
        # Mock the agents
        mock_conduct_session.return_value = session
        mock_update_plan.return_value = plan
        
        # Verify user status
        status = self.db_service.get_user_status()
        self.assertEqual(status, UserStatus.PLAN_COMPLETE)
        
        # The actual main workflow test would go here
        # For now, we're just verifying the setup works
        
    @patch('agents.assessment_agent.AssessmentAgent.conduct_assessment')
    @patch('agents.assessment_agent.AssessmentAgent.create_initial_plan_with_style')
    @patch('agents.psychoanalyst_agent.PsychoanalystAgent.conduct_session')
    @patch('agents.reflection_agent.ReflectionAgent.update_plan')
    async def test_intake_complete_workflow(self, mock_update_plan, mock_conduct_session, 
                                          mock_create_plan, mock_conduct_assessment):
        """Test workflow when user has completed intake but no therapy plan."""
        from datetime import datetime
        
        # Set up test data - only profile and session
        profile = UserProfile(
            user_id="default_user",
            name="Test User",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.db_service.save_user_profile(profile)
        
        session = Session(
            session_id="test_session_1",
            user_id="default_user",
            timestamp=datetime.now(),
            transcript=[Message(role="user", content="Hello", timestamp=datetime.now())]
        )
        self.db_service.save_session(session)
        
        # Mock the assessment agent responses
        mock_conduct_assessment.return_value = [{"style_id": "jung", "name": "Jung", "description": "Jungian therapy", "assessment": "Good fit"}]
        mock_create_plan.return_value = TherapyPlan(
            plan_id="test_plan_1",
            user_id="default_user",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details={"focus": "test", "goals": "test", "techniques": "test", "themes": "test"},
            version=1,
            selected_therapy_style="jung"
        )
        
        # Mock the session conduct
        mock_conduct_session.return_value = session
        mock_update_plan.return_value = mock_create_plan.return_value
        
        # Verify user status
        status = self.db_service.get_user_status()
        self.assertEqual(status, UserStatus.INTAKE_COMPLETE)

if __name__ == '__main__':
    # Run the tests
    unittest.main()
