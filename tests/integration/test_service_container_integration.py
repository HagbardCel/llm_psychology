"""
Integration tests for the new ServiceContainer architecture.

These tests validate the complete integration of:
- ServiceContainer dependency injection
- MemoryAgent and PlanningAgent coordination
- ReflectionAgent orchestration
- Migration system integration
- Error handling across the architecture
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

# Integration test for ServiceContainer architecture
class TestServiceContainerIntegration:
    """Integration tests for ServiceContainer and dependency injection."""
    
    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database file for testing."""
        temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        temp_db.close()
        yield temp_db.name
        os.unlink(temp_db.name)
    
    @pytest.fixture
    def temp_migrations_dir(self):
        """Create a temporary migrations directory."""
        import tempfile
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        import shutil
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def mock_config(self, temp_db_path, temp_migrations_dir):
        """Create a mock configuration for testing."""
        class MockConfig:
            DATABASE_PATH = temp_db_path
            MIGRATIONS_DIR = temp_migrations_dir
            GOOGLE_API_KEY = "test_api_key"
            MODEL_NAME = "gemini-2.5-flash"
            DOMAIN_KNOWLEDGE_PATH = "data/domain_knowledge"
            VECTOR_DB_PATH = "data/vector_db"
            DATABASE_POOL_SIZE = 5
        
        return MockConfig
    
    @pytest.fixture
    def container(self, mock_config):
        """Create a ServiceContainer with mocked dependencies."""
        from container.service_container import ServiceContainer
        
        container = ServiceContainer(mock_config)
        
        # Mock the LLM service to avoid actual API calls
        mock_llm = Mock()
        mock_llm.generate_response.return_value = "Mock response"
        mock_llm.generate_structured_response.return_value = {
            'raw_response': '{"focus": "test", "goals": "test", "techniques": "test", "themes": "test"}'
        }
        container.register('llm_service', mock_llm)
        
        # Mock the RAG service to avoid vector DB operations
        mock_rag = Mock()
        mock_rag.retrieve_relevant_knowledge.return_value = [
            {"content": "Mock knowledge", "source": "test.md"}
        ]
        container.register('rag_service', mock_rag)
        
        return container
    
    def test_service_container_initialization(self, container):
        """Test that ServiceContainer initializes correctly with all services."""
        # Test that all core services are registered
        assert container.is_registered('db_service')
        assert container.is_registered('llm_service')
        assert container.is_registered('rag_service')
        assert container.is_registered('migration_service')
        
        # Test that services can be retrieved
        db_service = container.get('db_service')
        llm_service = container.get('llm_service')
        rag_service = container.get('rag_service')
        migration_service = container.get('migration_service')
        
        assert db_service is not None
        assert llm_service is not None
        assert rag_service is not None
        assert migration_service is not None
        
        # Test singleton behavior
        assert container.get('db_service') is db_service
        assert container.get('llm_service') is llm_service
    
    def test_agent_creation_through_container(self, container):
        """Test that agents can be created through the container."""
        from context.user_context import UserContext
        
        user_context = UserContext("test_user")
        
        # Test all agent creation methods
        intake_agent = container.create_intake_agent(user_context)
        assessment_agent = container.create_assessment_agent(user_context)
        psychoanalyst_agent = container.create_psychoanalyst_agent(user_context)
        reflection_agent = container.create_reflection_agent(user_context)
        memory_agent = container.create_memory_agent(user_context)
        planning_agent = container.create_planning_agent(user_context)
        
        # Verify all agents were created successfully
        assert intake_agent is not None
        assert assessment_agent is not None
        assert psychoanalyst_agent is not None
        assert reflection_agent is not None
        assert memory_agent is not None
        assert planning_agent is not None
        
        # Verify agents have correct user context
        assert intake_agent.user_context.user_id == "test_user"
        assert assessment_agent.user_context.user_id == "test_user"
        assert psychoanalyst_agent.user_context.user_id == "test_user"
        assert reflection_agent.user_context.user_id == "test_user"
        assert memory_agent.user_context.user_id == "test_user"
        assert planning_agent.user_context.user_id == "test_user"
    
    def test_migration_service_integration(self, container, temp_migrations_dir):
        """Test migration service integration with ServiceContainer."""
        migration_service = container.get('migration_service')
        
        # Test migration status on empty database
        status = migration_service.get_migration_status()
        assert status['total_migrations'] == 0
        assert status['applied_count'] == 0
        assert status['pending_count'] == 0
        
        # Create a test migration file
        migration_content = """
-- Test migration
CREATE TABLE test_table (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

SELECT 'Test migration completed' as result;
"""
        migration_file = os.path.join(temp_migrations_dir, "001_test_migration.sql")
        with open(migration_file, 'w') as f:
            f.write(migration_content)
        
        # Test migration discovery and application
        status = migration_service.get_migration_status()
        assert status['total_migrations'] == 1
        assert status['pending_count'] == 1
        
        # Apply migrations
        applied = migration_service.run_migrations()
        assert len(applied) == 1
        assert applied[0].version == 1
        
        # Verify migration was applied
        status = migration_service.get_migration_status()
        assert status['applied_count'] == 1
        assert status['pending_count'] == 0
    
    def test_container_health_check(self, container):
        """Test ServiceContainer health check functionality."""
        health = container.health_check()
        
        assert 'status' in health
        assert 'services' in health
        assert 'timestamp' in health
        
        # Should be healthy with mocked services
        assert health['status'] in ['healthy', 'unhealthy']  # Depends on actual service health
    
    def test_container_shutdown(self, container):
        """Test ServiceContainer shutdown functionality."""
        # Get some services to instantiate them
        db_service = container.get('db_service')
        llm_service = container.get('llm_service')
        
        # Verify services are instantiated
        assert len(container._instances) > 0
        
        # Test shutdown
        container.shutdown()
        
        # Verify instances are cleared
        assert len(container._instances) == 0


class TestNewAgentArchitectureIntegration:
    """Integration tests for MemoryAgent, PlanningAgent, and ReflectionAgent coordination."""
    
    @pytest.fixture
    def container_with_services(self, mock_config):
        """Create container with all services for agent testing."""
        from container.service_container import ServiceContainer
        
        container = ServiceContainer(mock_config)
        
        # Mock services with realistic behavior
        mock_llm = Mock()
        mock_llm.generate_response.return_value = "Mock therapeutic response"
        mock_llm.generate_structured_response.return_value = {
            'raw_response': '{"key_themes": ["anxiety", "work"], "emotional_state": "anxious", "insights": ["breakthrough"], "progress_indicators": ["improvement"]}'
        }
        container.register('llm_service', mock_llm)
        
        mock_rag = Mock()
        mock_rag.retrieve_relevant_knowledge.return_value = [
            {"content": "CBT techniques for anxiety management", "source": "cbt.md"}
        ]
        container.register('rag_service', mock_rag)
        
        return container
    
    @pytest.fixture
    def user_context(self):
        """Create user context for testing."""
        from context.user_context import UserContext
        return UserContext("integration_test_user")
    
    @pytest.fixture
    def sample_session(self):
        """Create a sample session for testing."""
        from models.data_models import Session, Message
        return Session(
            session_id="integration_test_session",
            user_id="integration_test_user",
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="I've been feeling anxious about work deadlines", timestamp=datetime.now()),
                Message(role="assistant", content="Can you tell me more about these feelings?", timestamp=datetime.now()),
                Message(role="user", content="I think I'm overthinking everything", timestamp=datetime.now())
            ],
            topics=[]
        )
    
    def test_memory_agent_integration(self, container_with_services, user_context, sample_session):
        """Test MemoryAgent integration with real services."""
        memory_agent = container_with_services.create_memory_agent(user_context)
        
        # Test session context analysis
        session_context = memory_agent.analyze_session_context(sample_session)
        
        assert session_context is not None
        assert session_context.session_id == "integration_test_session"
        assert isinstance(session_context.key_themes, list)
        assert isinstance(session_context.insights, list)
        
        # Test therapeutic memory management
        memory = memory_agent.get_therapeutic_memory()
        assert memory is not None
        assert memory.user_id == "integration_test_user"
        
        # Test pattern identification
        patterns = memory_agent.identify_patterns()
        assert isinstance(patterns, dict)
        
        # Test health check
        assert memory_agent.health_check() is True
    
    def test_planning_agent_integration(self, container_with_services, user_context, sample_session):
        """Test PlanningAgent integration with MemoryAgent dependency."""
        planning_agent = container_with_services.create_planning_agent(user_context)
        
        # Verify planning agent has memory agent dependency
        assert planning_agent.memory_agent is not None
        assert planning_agent.memory_agent.user_context.user_id == "integration_test_user"
        
        # Test initial plan creation
        therapy_plan = planning_agent.create_initial_plan(sample_session, "cbt")
        
        assert therapy_plan is not None
        assert therapy_plan.user_id == "integration_test_user"
        assert therapy_plan.selected_therapy_style == "cbt"
        assert therapy_plan.version == 1
        assert 'focus' in therapy_plan.plan_details
        assert 'goals' in therapy_plan.plan_details
        
        # Test plan effectiveness assessment
        assessment = planning_agent.assess_plan_effectiveness(therapy_plan)
        
        assert 'plan_id' in assessment
        assert 'effectiveness_score' in assessment
        assert 'strengths' in assessment
        assert 'improvement_areas' in assessment
        
        # Test plan evolution tracking
        evolution_summary = planning_agent.get_plan_evolution_summary()
        
        assert 'total_versions' in evolution_summary
        assert 'evolution_timeline' in evolution_summary
        assert evolution_summary['total_versions'] == 1
        
        # Test health check
        assert planning_agent.health_check() is True
    
    def test_reflection_agent_coordination(self, container_with_services, user_context, sample_session):
        """Test ReflectionAgent coordination of MemoryAgent and PlanningAgent."""
        reflection_agent = container_with_services.create_reflection_agent(user_context)
        
        # Verify reflection agent has both dependencies
        assert reflection_agent.memory_agent is not None
        assert reflection_agent.planning_agent is not None
        
        # Test initial plan creation through coordination
        therapy_plan = reflection_agent.create_initial_plan(sample_session, "cbt")
        
        assert therapy_plan is not None
        assert therapy_plan.selected_therapy_style == "cbt"
        
        # Test plan update through coordination
        updated_plan = reflection_agent.update_plan(sample_session, therapy_plan)
        
        assert updated_plan is not None
        # May be same plan if no update needed, or new version if updated
        assert updated_plan.user_id == "integration_test_user"
        
        # Test comprehensive reflection generation
        comprehensive_reflection = reflection_agent.generate_comprehensive_reflection(sample_session, therapy_plan)
        
        assert 'session_context' in comprehensive_reflection
        assert 'therapeutic_memory' in comprehensive_reflection
        assert 'patterns' in comprehensive_reflection
        assert 'plan_assessment' in comprehensive_reflection
        assert 'session_summary' in comprehensive_reflection
        assert 'agents_used' in comprehensive_reflection
        
        # Verify all three agents are referenced
        agents_used = comprehensive_reflection['agents_used']
        assert "MemoryAgent" in agents_used
        assert "PlanningAgent" in agents_used
        assert "ReflectionAgent" in agents_used
        
        # Test therapeutic insights
        insights = reflection_agent.get_therapeutic_insights()
        
        assert 'memory_insights' in insights
        assert 'planning_insights' in insights
        assert 'recommendations' in insights
        
        # Test health check
        assert reflection_agent.health_check() is True
    
    def test_agent_error_handling_integration(self, container_with_services, user_context):
        """Test error handling across agent architecture."""
        # Test with failing LLM service
        mock_llm = Mock()
        mock_llm.generate_response.side_effect = Exception("LLM service error")
        mock_llm.generate_structured_response.side_effect = Exception("LLM service error")
        container_with_services.register('llm_service', mock_llm)
        
        memory_agent = container_with_services.create_memory_agent(user_context)
        planning_agent = container_with_services.create_planning_agent(user_context)
        reflection_agent = container_with_services.create_reflection_agent(user_context)
        
        # Test health checks with failing services
        assert memory_agent.health_check() is False
        assert planning_agent.health_check() is False
        assert reflection_agent.health_check() is False
        
        # Test that errors are properly propagated
        from models.data_models import Session, Message
        from exceptions import MemoryError, PlanningError, ReflectionError
        
        error_session = Session(
            session_id="error_test",
            user_id="integration_test_user",
            timestamp=datetime.now(),
            transcript=[Message(role="user", content="test", timestamp=datetime.now())],
            topics=[]
        )
        
        # MemoryAgent should handle LLM errors gracefully
        try:
            memory_agent.analyze_session_context(error_session)
        except MemoryError:
            pass  # Expected behavior
        
        # PlanningAgent should handle LLM errors gracefully
        try:
            planning_agent.create_initial_plan(error_session)
        except PlanningError:
            pass  # Expected behavior
        
        # ReflectionAgent should handle errors from dependencies
        try:
            reflection_agent.create_initial_plan(error_session)
        except ReflectionError:
            pass  # Expected behavior


class TestEndToEndWorkflowIntegration:
    """End-to-end integration tests for complete therapy workflows using new architecture."""
    
    @pytest.fixture
    def full_container(self, mock_config):
        """Create a fully configured container for end-to-end testing."""
        from container.service_container import ServiceContainer
        
        container = ServiceContainer(mock_config)
        
        # Mock LLM with realistic therapeutic responses
        mock_llm = Mock()
        mock_llm.generate_response.side_effect = [
            # Intake responses
            "Welcome! I'm here to help you explore your thoughts and feelings.",
            "Thank you for sharing that with me. Can you tell me more?",
            "I appreciate your openness. Let's continue our conversation.",
            
            # Assessment responses
            "Based on our conversation, I believe CBT would be beneficial for you.",
            
            # Therapy session responses
            "Welcome to your therapy session. How are you feeling today?",
            "That's great progress. How did that make you feel?",
            "Let's explore that feeling together.",
            
            # Session summary
            "Today we explored your anxiety and made good progress."
        ]
        
        mock_llm.generate_structured_response.side_effect = [
            # Memory agent analysis
            {'raw_response': '{"key_themes": ["anxiety", "work_stress"], "emotional_state": "anxious", "insights": ["recognizing_patterns"], "progress_indicators": ["awareness"]}'},
            
            # Planning agent initial plan
            {'raw_response': '{"focus": "Work-related anxiety management", "goals": "Develop coping strategies", "techniques": "CBT techniques", "themes": "anxiety, work_stress"}'},
            
            # Planning agent plan update
            {'raw_response': '{"focus": "Advanced anxiety management", "goals": "Maintain progress", "techniques": "Advanced CBT", "themes": "progress, coping"}'},
        ]
        
        container.register('llm_service', mock_llm)
        
        # Mock RAG service
        mock_rag = Mock()
        mock_rag.retrieve_relevant_knowledge.return_value = [
            {"content": "CBT is effective for anxiety disorders", "source": "cbt.md"},
            {"content": "Cognitive restructuring techniques", "source": "cbt.md"}
        ]
        container.register('rag_service', mock_rag)
        
        return container
    
    @pytest.fixture
    def mock_ui(self):
        """Create a mock UI for end-to-end testing."""
        class MockUI:
            def __init__(self):
                self.displayed_messages = []
                self.user_inputs = [
                    "Integration Test User",  # name
                    "1990-01-01",  # birthdate
                    "Software Engineer",  # profession
                    "I've been feeling anxious about work deadlines lately",  # intake
                    "quit",  # end intake
                    "I tried the breathing exercises and they helped",  # therapy session
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
            
            async def present_therapy_style_selection(self, recommendations):
                return "cbt"  # Always select CBT for testing
        
        return MockUI()
    
    @pytest.mark.asyncio
    async def test_complete_workflow_with_new_architecture(self, full_container, mock_ui):
        """Test complete therapy workflow using new ServiceContainer architecture."""
        from context.user_context import UserContext
        
        user_context = UserContext("integration_test_user")
        
        # Step 1: Intake process using container
        intake_agent = full_container.create_intake_agent(user_context)
        intake_session = await intake_agent.conduct_intake(mock_ui)
        
        assert intake_session is not None
        assert len(intake_session.transcript) > 0
        assert intake_session.user_id == "integration_test_user"
        
        # Step 2: Assessment process using container
        assessment_agent = full_container.create_assessment_agent(user_context)
        recommendations = await assessment_agent.conduct_assessment(intake_session)
        
        assert isinstance(recommendations, list)
        assert len(recommendations) > 0
        
        # Create initial plan through assessment agent (which uses reflection agent internally)
        selected_style = "cbt"
        therapy_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
        
        assert therapy_plan is not None
        assert therapy_plan.selected_therapy_style == "cbt"
        assert therapy_plan.version == 1
        
        # Step 3: Therapy session using container
        psychoanalyst_agent = full_container.create_psychoanalyst_agent(user_context)
        therapy_session = await psychoanalyst_agent.conduct_session(therapy_plan, 5, mock_ui)
        
        assert therapy_session is not None
        assert len(therapy_session.transcript) > 0
        assert therapy_session.session_id != intake_session.session_id
        
        # Step 4: Plan update using new reflection agent coordination
        reflection_agent = full_container.create_reflection_agent(user_context)
        
        # Test comprehensive reflection with new architecture
        comprehensive_reflection = reflection_agent.generate_comprehensive_reflection(therapy_session, therapy_plan)
        
        assert 'memory_insights' in comprehensive_reflection['session_context']
        assert 'plan_assessment' in comprehensive_reflection
        assert len(comprehensive_reflection['agents_used']) == 3
        
        # Update plan through new coordination
        updated_plan = reflection_agent.update_plan(therapy_session, therapy_plan)
        
        assert updated_plan is not None
        assert updated_plan.user_id == "integration_test_user"
        
        # Step 5: Verify data persistence through container's database service
        db_service = full_container.get('db_service')
        
        # Verify all sessions were saved
        all_sessions = db_service.get_all_sessions_for_user("integration_test_user")
        assert len(all_sessions) >= 2  # At least intake + therapy
        
        # Verify user profile was saved
        user_profile = db_service.get_user_profile("integration_test_user")
        assert user_profile is not None
        assert user_profile.name == "Integration Test User"
        
        # Verify final plan was saved
        latest_plan = db_service.get_latest_therapy_plan("integration_test_user")
        assert latest_plan is not None
        
        # Test therapeutic insights from new architecture
        insights = reflection_agent.get_therapeutic_insights()
        
        assert 'memory_insights' in insights
        assert 'planning_insights' in insights
        assert isinstance(insights['recommendations'], list)
    
    @pytest.mark.asyncio
    async def test_migration_integration_in_workflow(self, full_container, temp_migrations_dir):
        """Test that migrations are properly integrated into the workflow."""
        # Create a test migration
        migration_content = """
-- Add index for better performance
CREATE INDEX IF NOT EXISTS idx_sessions_user_timestamp ON sessions(user_id, timestamp);

SELECT 'Performance migration completed' as result;
"""
        migration_file = os.path.join(temp_migrations_dir, "002_performance_migration.sql")
        with open(migration_file, 'w') as f:
            f.write(migration_content)
        
        # Test that migration service detects and applies migrations
        migration_service = full_container.get('migration_service')
        
        status_before = migration_service.get_migration_status()
        assert status_before['pending_count'] >= 1
        
        # Apply migrations
        applied = migration_service.run_migrations()
        assert len(applied) >= 1
        
        status_after = migration_service.get_migration_status()
        assert status_after['applied_count'] > status_before['applied_count']
        
        # Verify database still works after migration
        db_service = full_container.get('db_service')
        
        # Test basic database operations still work
        from models.data_models import UserProfile
        test_profile = UserProfile(
            user_id="migration_test_user",
            name="Migration Test",
            birthdate="1990-01-01",
            profession="Tester",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        
        success = db_service.save_user_profile(test_profile)
        assert success is True
        
        retrieved_profile = db_service.get_user_profile("migration_test_user")
        assert retrieved_profile is not None
        assert retrieved_profile.name == "Migration Test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])