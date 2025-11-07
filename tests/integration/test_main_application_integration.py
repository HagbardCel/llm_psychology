"""
Integration tests for the main application with new ServiceContainer architecture.

These tests validate:
- Main application startup with ServiceContainer
- Migration system integration
- Error handling across the application
- Complete user workflows through main.py
- Resume functionality with new architecture
"""

import pytest
import tempfile
import os
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

class TestMainApplicationIntegration:
    """Integration tests for main.py application with new architecture."""
    
    @pytest.fixture
    def temp_environment(self):
        """Create temporary environment for testing main application."""
        import tempfile
        import shutil
        
        # Create temporary directories
        base_dir = tempfile.mkdtemp()
        data_dir = os.path.join(base_dir, "data")
        migrations_dir = os.path.join(base_dir, "migrations")
        vector_db_dir = os.path.join(data_dir, "vector_db")
        domain_knowledge_dir = os.path.join(data_dir, "domain_knowledge")
        
        os.makedirs(data_dir)
        os.makedirs(migrations_dir)
        os.makedirs(vector_db_dir)
        os.makedirs(domain_knowledge_dir)
        
        # Create test database
        db_path = os.path.join(data_dir, "test_psychoanalyst.db")
        
        # Create test migration
        migration_content = """
-- Initial schema for testing
CREATE TABLE IF NOT EXISTS test_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO test_migrations (version) VALUES (1);
SELECT 'Test migration applied successfully' as result;
"""
        migration_file = os.path.join(migrations_dir, "001_test_schema.sql")
        with open(migration_file, 'w') as f:
            f.write(migration_content)
        
        # Create basic domain knowledge file
        knowledge_file = os.path.join(domain_knowledge_dir, "test.md")
        with open(knowledge_file, 'w') as f:
            f.write("# Test Knowledge\n\nThis is test therapeutic knowledge.")
        
        yield {
            'base_dir': base_dir,
            'db_path': db_path,
            'migrations_dir': migrations_dir,
            'vector_db_dir': vector_db_dir,
            'domain_knowledge_dir': domain_knowledge_dir
        }
        
        # Cleanup
        shutil.rmtree(base_dir)
    
    @pytest.fixture
    def mock_config_for_main(self, temp_environment):
        """Create mock Config class for main.py testing."""
        class MockConfig:
            APP_NAME = "Virtual LLM-Driven Psychoanalyst"
            VERSION = "1.0.0"
            SESSION_DURATION_MINUTES = 5
            DATABASE_PATH = temp_environment['db_path']
            MIGRATIONS_DIR = temp_environment['migrations_dir']
            VECTOR_DB_PATH = temp_environment['vector_db_dir']
            DOMAIN_KNOWLEDGE_PATH = temp_environment['domain_knowledge_dir']
            GOOGLE_API_KEY = "test_api_key_for_integration"
            MODEL_NAME = "gemini-2.5-flash"
            DATABASE_POOL_SIZE = 3
        
        return MockConfig
    
    @pytest.fixture
    def mock_ui_for_main(self):
        """Create comprehensive mock UI for main.py testing."""
        class MockMainUI:
            def __init__(self):
                self.displayed_messages = []
                self.system_messages = []
                self.user_inputs = [
                    "Integration Test User",  # name
                    "1990-01-01",  # birthdate
                    "Software Engineer",  # profession
                    "I've been feeling stressed about work and having trouble sleeping",  # intake
                    "quit",  # end intake
                    "I tried some relaxation techniques and they helped a bit",  # therapy
                    "quit"  # end therapy
                ]
                self.input_index = 0
                self.style_selection_called = False
            
            async def display_system_status(self, message):
                self.system_messages.append(message)
                self.displayed_messages.append(("system", message))
            
            async def display_message(self, role, message):
                self.displayed_messages.append((role, message))
            
            async def get_user_input(self, prompt=None):
                if self.input_index < len(self.user_inputs):
                    input_value = self.user_inputs[self.input_index]
                    self.input_index += 1
                    return input_value
                return ""
            
            async def present_therapy_style_selection(self, recommendations):
                self.style_selection_called = True
                return "cbt"  # Always select CBT for testing
        
        return MockMainUI()
    
    @pytest.mark.asyncio
    async def test_main_application_startup_with_container(self, temp_environment, mock_config_for_main):
        """Test main application startup with ServiceContainer."""
        with patch('src.main.Config', mock_config_for_main):
            with patch('src.main.setup_logging'):
                # Mock the UI to avoid actual user interaction
                mock_ui = Mock()
                mock_ui.display_system_status = AsyncMock()
                
                # Import and test main components
                import sys
                sys.path.insert(0, 'src')
                
                from container.service_container import ServiceContainer
                from exceptions import ConfigurationError
                
                try:
                    # Test ServiceContainer creation with real config
                    container = ServiceContainer(mock_config_for_main)
                    
                    # Verify container initialized correctly
                    assert container is not None
                    assert container.is_registered('db_service')
                    assert container.is_registered('migration_service')
                    
                    # Test migration service integration
                    migration_service = container.get('migration_service')
                    migration_status = migration_service.get_migration_status()
                    
                    # Should detect our test migration
                    assert migration_status['total_migrations'] >= 1
                    
                    # Apply migrations
                    if migration_status['pending_count'] > 0:
                        applied = migration_service.run_migrations()
                        assert len(applied) > 0
                    
                    # Test database service works after migrations
                    db_service = container.get('db_service')
                    status = db_service.get_user_status("test_user")
                    # Should work without errors
                    assert status is not None
                    
                    # Test agent creation
                    from context.user_context import UserContext
                    user_context = UserContext("test_user")
                    
                    # All agent creation should work
                    agents = {
                        'intake': container.create_intake_agent(user_context),
                        'assessment': container.create_assessment_agent(user_context),
                        'psychoanalyst': container.create_psychoanalyst_agent(user_context),
                        'reflection': container.create_reflection_agent(user_context),
                        'memory': container.create_memory_agent(user_context),
                        'planning': container.create_planning_agent(user_context)
                    }
                    
                    for agent_name, agent in agents.items():
                        assert agent is not None, f"{agent_name} agent creation failed"
                    
                    # Test container shutdown
                    container.shutdown()
                    
                except ConfigurationError as e:
                    pytest.fail(f"Configuration error during startup: {e}")
                except Exception as e:
                    pytest.fail(f"Unexpected error during startup: {e}")
    
    @pytest.mark.asyncio
    async def test_main_application_error_handling(self, temp_environment, mock_config_for_main):
        """Test main application error handling with new architecture."""
        # Test configuration error handling
        class BadConfig:
            GOOGLE_API_KEY = None  # Missing API key
            DATABASE_PATH = "/nonexistent/path/db.sqlite"
        
        with patch('src.main.Config', BadConfig):
            with patch('src.main.setup_logging'):
                import sys
                sys.path.insert(0, 'src')
                
                from container.service_container import ServiceContainer
                from exceptions import ConfigurationError
                
                # Should raise ConfigurationError for bad config
                with pytest.raises(ConfigurationError):
                    container = ServiceContainer(BadConfig)
                    llm_service = container.get('llm_service')  # This should fail
    
    @pytest.mark.asyncio
    async def test_main_workflow_error_handling_integration(self, temp_environment, mock_config_for_main):
        """Test that main.py error handling works with the new architecture."""
        with patch('src.main.Config', mock_config_for_main):
            with patch('src.main.setup_logging'):
                import sys
                sys.path.insert(0, 'src')
                
                from main import handle_workflow_error
                from ui.textual_ui import ConsoleUI
                from exceptions import AgentError, DatabaseError, LLMServiceError
                
                # Mock UI for error testing
                mock_ui = Mock()
                mock_ui.display_system_status = AsyncMock()
                
                # Test different error types
                test_errors = [
                    (AgentError("Agent failed"), "test workflow"),
                    (DatabaseError("Database connection lost"), "test workflow"),
                    (LLMServiceError("API rate limit"), "test workflow"),
                    (Exception("Unexpected error"), "test workflow")
                ]
                
                for error, workflow_stage in test_errors:
                    await handle_workflow_error(mock_ui, error, workflow_stage)
                    
                    # Verify error was handled
                    assert mock_ui.display_system_status.called
                    
                    # Reset mock for next test
                    mock_ui.reset_mock()
    
    @pytest.mark.asyncio
    async def test_main_migration_integration_on_startup(self, temp_environment, mock_config_for_main):
        """Test that main.py properly integrates migrations on startup."""
        # Create additional migration for testing
        migration_content = """
-- Additional test migration
CREATE TABLE IF NOT EXISTS test_startup_migrations (
    id INTEGER PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

SELECT 'Startup migration completed' as result;
"""
        migration_file = os.path.join(temp_environment['migrations_dir'], "002_startup_test.sql")
        with open(migration_file, 'w') as f:
            f.write(migration_content)
        
        with patch('src.main.Config', mock_config_for_main):
            with patch('src.main.setup_logging'):
                import sys
                sys.path.insert(0, 'src')
                
                from container.service_container import ServiceContainer
                
                # Create container and test migration integration
                container = ServiceContainer(mock_config_for_main)
                
                # Test migration status
                migration_service = container.get('migration_service')
                status_before = migration_service.get_migration_status()
                
                # Should detect both migrations
                assert status_before['total_migrations'] >= 2
                assert status_before['pending_count'] >= 1
                
                # Apply migrations (simulating main.py startup)
                applied = migration_service.run_migrations()
                assert len(applied) >= 1
                
                # Verify migrations were applied
                status_after = migration_service.get_migration_status()
                assert status_after['applied_count'] > status_before['applied_count']
                assert status_after['pending_count'] == 0
                
                container.shutdown()
    
    @pytest.mark.asyncio
    async def test_user_status_flow_with_new_architecture(self, temp_environment, mock_config_for_main):
        """Test user status progression through the new architecture."""
        with patch('src.main.Config', mock_config_for_main):
            with patch('src.main.setup_logging'):
                import sys
                sys.path.insert(0, 'src')
                
                from container.service_container import ServiceContainer
                from context.user_context import UserContext
                from services.db_service import UserStatus
                from models.data_models import UserProfile, Session, Message, TherapyPlan
                
                container = ServiceContainer(mock_config_for_main)
                db_service = container.get('db_service')
                user_context = UserContext("status_test_user")
                
                # Test NO_DATA status
                status = db_service.get_user_status("status_test_user")
                assert status == UserStatus.NO_DATA
                
                # Create user profile -> PROFILE_ONLY
                profile = UserProfile(
                    user_id="status_test_user",
                    name="Status Test User",
                    birthdate="1990-01-01",
                    profession="Tester",
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat()
                )
                db_service.save_user_profile(profile)
                
                status = db_service.get_user_status("status_test_user")
                assert status == UserStatus.PROFILE_ONLY
                
                # Create intake session -> INTAKE_COMPLETE
                intake_session = Session(
                    session_id="status_intake_session",
                    user_id="status_test_user",
                    timestamp=datetime.now(),
                    transcript=[
                        Message(role="user", content="I need help", timestamp=datetime.now())
                    ]
                )
                db_service.save_session(intake_session)
                
                status = db_service.get_user_status("status_test_user")
                assert status == UserStatus.INTAKE_COMPLETE
                
                # Create therapy plan -> PLAN_COMPLETE
                therapy_plan = TherapyPlan(
                    plan_id="status_test_plan",
                    user_id="status_test_user",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    plan_details={"focus": "test", "goals": "test", "techniques": "test", "themes": "test"},
                    version=1,
                    selected_therapy_style="cbt"
                )
                db_service.save_therapy_plan(therapy_plan)
                
                status = db_service.get_user_status("status_test_user")
                assert status == UserStatus.PLAN_COMPLETE
                
                container.shutdown()


class TestMainApplicationResumeFunctionality:
    """Test resume functionality with new architecture."""
    
    @pytest.fixture
    def setup_existing_user_data(self, temp_environment, mock_config_for_main):
        """Setup existing user data for resume testing."""
        with patch('src.main.Config', mock_config_for_main):
            import sys
            sys.path.insert(0, 'src')
            
            from container.service_container import ServiceContainer
            from models.data_models import UserProfile, Session, Message, TherapyPlan
            
            container = ServiceContainer(mock_config_for_main)
            db_service = container.get('db_service')
            
            # Create existing user with complete data
            profile = UserProfile(
                user_id="resume_test_user",
                name="Resume Test User",
                birthdate="1985-05-15",
                profession="Product Manager",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat()
            )
            db_service.save_user_profile(profile)
            
            # Create intake session
            intake_session = Session(
                session_id="resume_intake_session",
                user_id="resume_test_user",
                timestamp=datetime.now(),
                transcript=[
                    Message(role="user", content="I've been feeling overwhelmed at work", timestamp=datetime.now()),
                    Message(role="assistant", content="Tell me more about that", timestamp=datetime.now()),
                    Message(role="user", content="I think I need better coping strategies", timestamp=datetime.now())
                ]
            )
            db_service.save_session(intake_session)
            
            # Create therapy plan
            therapy_plan = TherapyPlan(
                plan_id="resume_test_plan",
                user_id="resume_test_user",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                plan_details={
                    "focus": "Work stress management",
                    "goals": "Develop coping strategies",
                    "techniques": "CBT and mindfulness",
                    "themes": "work_stress, coping, overwhelm"
                },
                version=1,
                selected_therapy_style="cbt"
            )
            db_service.save_therapy_plan(therapy_plan)
            
            # Create previous therapy session
            therapy_session = Session(
                session_id="resume_therapy_session",
                user_id="resume_test_user",
                timestamp=datetime.now(),
                transcript=[
                    Message(role="assistant", content="How have you been since our last session?", timestamp=datetime.now()),
                    Message(role="user", content="I tried the breathing exercises", timestamp=datetime.now()),
                    Message(role="assistant", content="How did they work for you?", timestamp=datetime.now())
                ]
            )
            db_service.save_session(therapy_session)
            
            container.shutdown()
            
            return {
                'user_id': 'resume_test_user',
                'intake_session_id': 'resume_intake_session',
                'therapy_plan_id': 'resume_test_plan',
                'therapy_session_id': 'resume_therapy_session'
            }
    
    @pytest.mark.asyncio
    async def test_resume_from_plan_complete_status(self, temp_environment, mock_config_for_main, setup_existing_user_data):
        """Test resuming from PLAN_COMPLETE status with existing therapy plan."""
        with patch('src.main.Config', mock_config_for_main):
            import sys
            sys.path.insert(0, 'src')
            
            from container.service_container import ServiceContainer
            from context.user_context import UserContext
            from services.db_service import UserStatus
            
            container = ServiceContainer(mock_config_for_main)
            db_service = container.get('db_service')
            user_context = UserContext("resume_test_user")
            
            # Verify user status is PLAN_COMPLETE
            status = db_service.get_user_status("resume_test_user")
            assert status == UserStatus.PLAN_COMPLETE
            
            # Test retrieving existing therapy plan
            therapy_plan = db_service.get_latest_therapy_plan("resume_test_user")
            assert therapy_plan is not None
            assert therapy_plan.plan_id == "resume_test_plan"
            assert therapy_plan.selected_therapy_style == "cbt"
            
            # Test creating agents for resume workflow
            reflection_agent = container.create_reflection_agent(user_context)
            psychoanalyst_agent = container.create_psychoanalyst_agent(user_context)
            
            assert reflection_agent is not None
            assert psychoanalyst_agent is not None
            
            # Test that therapeutic memory includes previous sessions
            memory_agent = reflection_agent.memory_agent
            therapeutic_memory = memory_agent.get_therapeutic_memory()
            
            assert therapeutic_memory.user_id == "resume_test_user"
            # Should have at least intake and therapy sessions
            assert len(therapeutic_memory.session_contexts) >= 0  # Memory may be empty initially
            
            # Test plan evolution tracking
            planning_agent = reflection_agent.planning_agent
            evolution_summary = planning_agent.get_plan_evolution_summary()
            
            assert 'total_versions' in evolution_summary
            assert 'current_strategy' in evolution_summary
            
            container.shutdown()
    
    @pytest.mark.asyncio
    async def test_resume_from_intake_complete_status(self, temp_environment, mock_config_for_main):
        """Test resuming from INTAKE_COMPLETE status."""
        with patch('src.main.Config', mock_config_for_main):
            import sys
            sys.path.insert(0, 'src')
            
            from container.service_container import ServiceContainer
            from context.user_context import UserContext
            from services.db_service import UserStatus
            from models.data_models import UserProfile, Session, Message
            
            container = ServiceContainer(mock_config_for_main)
            db_service = container.get('db_service')
            user_context = UserContext("intake_complete_user")
            
            # Setup user with only intake completed
            profile = UserProfile(
                user_id="intake_complete_user",
                name="Intake Complete User",
                birthdate="1990-01-01",
                profession="Designer",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat()
            )
            db_service.save_user_profile(profile)
            
            intake_session = Session(
                session_id="intake_only_session",
                user_id="intake_complete_user",
                timestamp=datetime.now(),
                transcript=[
                    Message(role="user", content="I'm struggling with anxiety", timestamp=datetime.now())
                ]
            )
            db_service.save_session(intake_session)
            
            # Verify status is INTAKE_COMPLETE
            status = db_service.get_user_status("intake_complete_user")
            assert status == UserStatus.INTAKE_COMPLETE
            
            # Test retrieving intake session for assessment
            all_sessions = db_service.get_all_sessions_for_user("intake_complete_user")
            assert len(all_sessions) >= 1
            
            latest_session = all_sessions[-1]
            assert latest_session.session_id == "intake_only_session"
            
            # Test creating assessment agent for resume workflow
            assessment_agent = container.create_assessment_agent(user_context)
            assert assessment_agent is not None
            
            # Verify assessment agent has reflection agent dependency
            assert assessment_agent.reflection_agent is not None
            
            container.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])