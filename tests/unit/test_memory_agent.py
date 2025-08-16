"""
Unit tests for MemoryAgent.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from agents.memory_agent import MemoryAgent, SessionContext, TherapeuticMemory
from context.user_context import UserContext
from models.data_models import Session, Message, Topic
from exceptions import MemoryError


class TestSessionContext:
    """Test SessionContext data structure."""
    
    def test_session_context_creation(self):
        """Test creating session context."""
        context = SessionContext(
            session_id="test_session",
            key_themes=["anxiety", "work_stress"],
            emotional_state="anxious",
            insights=["recognizes pattern"],
            progress_indicators=["increased awareness"]
        )
        
        assert context.session_id == "test_session"
        assert context.key_themes == ["anxiety", "work_stress"]
        assert context.emotional_state == "anxious"
        assert context.insights == ["recognizes pattern"]
        assert context.progress_indicators == ["increased awareness"]
        assert isinstance(context.timestamp, datetime)


class TestTherapeuticMemory:
    """Test TherapeuticMemory data structure."""
    
    def test_therapeutic_memory_creation(self):
        """Test creating therapeutic memory."""
        memory = TherapeuticMemory("test_user")
        
        assert memory.user_id == "test_user"
        assert memory.session_contexts == []
        assert dict(memory.recurring_themes) == {}
        assert memory.emotional_patterns == []
        assert memory.progress_timeline == []
        assert memory.relationship_quality == "building"
    
    def test_add_session_context(self):
        """Test adding session context to memory."""
        memory = TherapeuticMemory("test_user")
        
        context = SessionContext(
            session_id="test_session",
            key_themes=["anxiety", "work"],
            emotional_state="stressed",
            insights=["pattern recognition"],
            progress_indicators=["self-awareness"]
        )
        
        memory.add_session_context(context)
        
        assert len(memory.session_contexts) == 1
        assert memory.session_contexts[0] == context
        assert memory.recurring_themes["anxiety"] == 1
        assert memory.recurring_themes["work"] == 1
        assert memory.emotional_patterns == ["stressed"]
        assert len(memory.progress_timeline) == 1


class TestMemoryAgent:
    """Test MemoryAgent functionality."""
    
    @pytest.fixture
    def mock_services(self):
        """Create mock services."""
        return {
            'llm_service': Mock(),
            'db_service': Mock(),
            'rag_service': Mock()
        }
    
    @pytest.fixture
    def user_context(self):
        """Create user context."""
        return UserContext("test_user")
    
    @pytest.fixture
    def memory_agent(self, mock_services, user_context):
        """Create memory agent with mocked services."""
        return MemoryAgent(
            llm_service=mock_services['llm_service'],
            db_service=mock_services['db_service'],
            rag_service=mock_services['rag_service'],
            user_context=user_context
        )
    
    @pytest.fixture
    def sample_session(self):
        """Create sample session."""
        return Session(
            session_id="test_session",
            user_id="test_user",
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="I'm feeling anxious about work", timestamp=datetime.now()),
                Message(role="assistant", content="Tell me more about this anxiety", timestamp=datetime.now())
            ],
            topics=[Topic(name="anxiety", status="active")]
        )
    
    def test_memory_agent_initialization(self, memory_agent, user_context):
        """Test memory agent initialization."""
        assert memory_agent.user_context == user_context
        assert memory_agent._memory_cache is None
        assert memory_agent._cache_timestamp is None
    
    def test_analyze_session_context(self, memory_agent, mock_services, sample_session):
        """Test session context analysis."""
        # Mock RAG service response
        mock_services['rag_service'].retrieve_relevant_knowledge.return_value = [
            {'source': 'test_source', 'content': 'test knowledge'}
        ]
        
        # Mock LLM service response
        mock_services['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"key_themes": ["anxiety", "work"], "emotional_state": "anxious", "insights": ["pattern"], "progress_indicators": ["awareness"]}'
        }
        
        context = memory_agent.analyze_session_context(sample_session)
        
        assert isinstance(context, SessionContext)
        assert context.session_id == "test_session"
        assert "anxiety" in context.key_themes
        assert "work" in context.key_themes
        assert context.emotional_state == "anxious"
        assert "pattern" in context.insights
        assert "awareness" in context.progress_indicators
    
    def test_analyze_session_context_error_handling(self, memory_agent, mock_services, sample_session):
        """Test session context analysis with LLM error."""
        # Mock services to raise exception
        mock_services['rag_service'].retrieve_relevant_knowledge.side_effect = Exception("RAG error")
        
        with pytest.raises(MemoryError):
            memory_agent.analyze_session_context(sample_session)
    
    def test_get_therapeutic_memory(self, memory_agent, mock_services, sample_session):
        """Test getting therapeutic memory."""
        # Mock database service
        mock_services['db_service'].get_all_sessions_for_user.return_value = [sample_session]
        
        # Mock RAG service
        mock_services['rag_service'].retrieve_relevant_knowledge.return_value = []
        
        # Mock LLM service
        mock_services['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"key_themes": ["anxiety"], "emotional_state": "anxious", "insights": [], "progress_indicators": []}'
        }
        
        memory = memory_agent.get_therapeutic_memory()
        
        assert isinstance(memory, TherapeuticMemory)
        assert memory.user_id == "test_user"
        assert len(memory.session_contexts) == 1
        assert memory.relationship_quality == "building"
    
    def test_get_therapeutic_memory_caching(self, memory_agent, mock_services):
        """Test therapeutic memory caching."""
        # Mock database service
        mock_services['db_service'].get_all_sessions_for_user.return_value = []
        
        # First call
        memory1 = memory_agent.get_therapeutic_memory()
        
        # Second call should use cache
        memory2 = memory_agent.get_therapeutic_memory()
        
        assert memory1 is memory2
        # Database should only be called once
        assert mock_services['db_service'].get_all_sessions_for_user.call_count == 1
    
    def test_get_recent_context(self, memory_agent, mock_services, sample_session):
        """Test getting recent context."""
        # Mock database service
        mock_services['db_service'].get_all_sessions_for_user.return_value = [sample_session]
        
        # Mock RAG service
        mock_services['rag_service'].retrieve_relevant_knowledge.return_value = []
        
        # Mock LLM service
        mock_services['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"key_themes": ["anxiety"], "emotional_state": "anxious", "insights": ["test"], "progress_indicators": []}'
        }
        
        context = memory_agent.get_recent_context(num_sessions=3)
        
        assert 'sessions' in context
        assert 'themes' in context
        assert 'emotional_progression' in context
        assert 'insights' in context
        assert 'context_summary' in context
        
        assert len(context['sessions']) == 1
        assert 'anxiety' in context['themes']
        assert 'anxious' in context['emotional_progression']
    
    def test_get_recent_context_no_sessions(self, memory_agent, mock_services):
        """Test getting recent context with no sessions."""
        # Mock database service to return no sessions
        mock_services['db_service'].get_all_sessions_for_user.return_value = []
        
        context = memory_agent.get_recent_context()
        
        assert context['sessions'] == []
        assert context['themes'] == []
        assert context['emotional_progression'] == []
        assert context['insights'] == []
        assert 'No recent sessions available' in context['context_summary']
    
    def test_identify_patterns(self, memory_agent, mock_services, sample_session):
        """Test pattern identification."""
        # Mock database service
        mock_services['db_service'].get_all_sessions_for_user.return_value = [sample_session]
        
        # Mock RAG service
        mock_services['rag_service'].retrieve_relevant_knowledge.return_value = []
        
        # Mock LLM service
        mock_services['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"key_themes": ["anxiety", "work"], "emotional_state": "anxious", "insights": [], "progress_indicators": ["awareness"]}'
        }
        
        patterns = memory_agent.identify_patterns()
        
        assert 'theme_patterns' in patterns
        assert 'emotional_patterns' in patterns
        assert 'progress_patterns' in patterns
        assert 'relationship_quality' in patterns
        assert 'total_sessions' in patterns
        
        assert patterns['total_sessions'] == 1
    
    def test_get_continuity_context(self, memory_agent, mock_services):
        """Test getting continuity context."""
        # Mock database service
        mock_services['db_service'].get_all_sessions_for_user.return_value = []
        
        # Mock therapeutic memory
        memory_agent._memory_cache = TherapeuticMemory("test_user")
        memory_agent._memory_cache.recurring_themes = {"anxiety": 3, "work": 2}
        memory_agent._memory_cache.relationship_quality = "developing"
        memory_agent._cache_timestamp = datetime.now()
        
        context = memory_agent.get_continuity_context(["anxiety", "stress"])
        
        assert isinstance(context, str)
        assert "anxiety" in context or "developing" in context
    
    def test_health_check_healthy(self, memory_agent, mock_services):
        """Test health check when healthy."""
        # Mock services to work correctly
        mock_services['db_service'].get_all_sessions_for_user.return_value = []
        
        result = memory_agent.health_check()
        assert result is True
    
    def test_health_check_unhealthy(self, memory_agent, mock_services):
        """Test health check when unhealthy."""
        # Mock database service to fail
        mock_services['db_service'].get_all_sessions_for_user.side_effect = Exception("DB error")
        
        result = memory_agent.health_check()
        assert result is False
    
    def test_string_representations(self, memory_agent):
        """Test string representations."""
        str_repr = str(memory_agent)
        assert "MemoryAgent" in str_repr
        assert "test_user" in str_repr
        
        repr_str = repr(memory_agent)
        assert "MemoryAgent" in repr_str
        assert "test_user" in repr_str
        assert "not_cached" in repr_str


class TestMemoryAgentErrorHandling:
    """Test MemoryAgent error handling."""
    
    @pytest.fixture
    def memory_agent_with_failing_services(self):
        """Create memory agent with failing services."""
        failing_llm = Mock()
        failing_llm.generate_structured_response.side_effect = Exception("LLM failed")
        
        failing_db = Mock()
        failing_db.get_all_sessions_for_user.side_effect = Exception("DB failed")
        
        failing_rag = Mock()
        failing_rag.retrieve_relevant_knowledge.side_effect = Exception("RAG failed")
        
        return MemoryAgent(
            llm_service=failing_llm,
            db_service=failing_db,
            rag_service=failing_rag,
            user_context=UserContext("test_user")
        )
    
    def test_get_therapeutic_memory_error(self, memory_agent_with_failing_services):
        """Test therapeutic memory retrieval with service errors."""
        with pytest.raises(MemoryError):
            memory_agent_with_failing_services.get_therapeutic_memory()
    
    def test_get_recent_context_error(self, memory_agent_with_failing_services):
        """Test recent context retrieval with service errors."""
        with pytest.raises(MemoryError):
            memory_agent_with_failing_services.get_recent_context()
    
    def test_identify_patterns_error(self, memory_agent_with_failing_services):
        """Test pattern identification with service errors."""
        with pytest.raises(MemoryError):
            memory_agent_with_failing_services.identify_patterns()


class TestMemoryAgentIntegration:
    """Integration tests for MemoryAgent with realistic data."""
    
    @pytest.fixture
    def realistic_sessions(self):
        """Create realistic session data."""
        sessions = []
        
        # Session 1: Initial anxiety discussion
        sessions.append(Session(
            session_id="session_1",
            user_id="test_user",
            timestamp=datetime.now() - timedelta(days=14),
            transcript=[
                Message(role="user", content="I've been feeling really anxious about work lately", timestamp=datetime.now()),
                Message(role="assistant", content="Can you tell me more about what specifically makes you anxious?", timestamp=datetime.now()),
                Message(role="user", content="The deadlines and my boss's expectations", timestamp=datetime.now())
            ],
            topics=[Topic(name="work_anxiety", status="active")]
        ))
        
        # Session 2: Exploring patterns
        sessions.append(Session(
            session_id="session_2", 
            user_id="test_user",
            timestamp=datetime.now() - timedelta(days=7),
            transcript=[
                Message(role="user", content="I noticed I get anxious every Sunday thinking about Monday", timestamp=datetime.now()),
                Message(role="assistant", content="That's an important pattern you've identified", timestamp=datetime.now())
            ],
            topics=[Topic(name="pattern_recognition", status="active")]
        ))
        
        # Session 3: Progress and coping
        sessions.append(Session(
            session_id="session_3",
            user_id="test_user", 
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="I tried the breathing exercises and they helped", timestamp=datetime.now()),
                Message(role="assistant", content="That's great progress", timestamp=datetime.now())
            ],
            topics=[Topic(name="coping_strategies", status="active")]
        ))
        
        return sessions
    
    def test_memory_building_with_realistic_data(self, realistic_sessions):
        """Test memory building with realistic session progression."""
        # Mock services
        llm_service = Mock()
        db_service = Mock()
        rag_service = Mock()
        
        db_service.get_all_sessions_for_user.return_value = realistic_sessions
        rag_service.retrieve_relevant_knowledge.return_value = []
        
        # Mock different LLM responses for each session
        llm_responses = [
            '{"key_themes": ["work", "anxiety"], "emotional_state": "anxious", "insights": [], "progress_indicators": []}',
            '{"key_themes": ["patterns", "awareness"], "emotional_state": "thoughtful", "insights": ["sunday_pattern"], "progress_indicators": ["self_awareness"]}',
            '{"key_themes": ["coping", "progress"], "emotional_state": "hopeful", "insights": ["breathing_works"], "progress_indicators": ["skill_development"]}'
        ]
        
        llm_service.generate_structured_response.side_effect = [
            {'raw_response': response} for response in llm_responses
        ]
        
        # Create memory agent
        memory_agent = MemoryAgent(
            llm_service=llm_service,
            db_service=db_service,
            rag_service=rag_service,
            user_context=UserContext("test_user")
        )
        
        # Build therapeutic memory
        memory = memory_agent.get_therapeutic_memory()
        
        # Verify memory structure
        assert len(memory.session_contexts) == 3
        assert memory.user_id == "test_user"
        assert memory.relationship_quality == "developing"  # 3 sessions
        
        # Verify theme tracking
        assert "work" in memory.recurring_themes
        assert "anxiety" in memory.recurring_themes
        assert "patterns" in memory.recurring_themes
        
        # Verify emotional progression
        assert len(memory.emotional_patterns) == 3
        assert "anxious" in memory.emotional_patterns
        assert "hopeful" in memory.emotional_patterns
        
        # Verify progress timeline
        assert len(memory.progress_timeline) == 3
        assert any("self_awareness" in entry['indicators'] for entry in memory.progress_timeline)
        assert any("skill_development" in entry['indicators'] for entry in memory.progress_timeline)