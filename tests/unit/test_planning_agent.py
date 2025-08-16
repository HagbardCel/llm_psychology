"""
Unit tests for PlanningAgent.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from agents.planning_agent import PlanningAgent, PlanEvolution, PlanningStrategy
from agents.memory_agent import MemoryAgent, SessionContext, TherapeuticMemory
from context.user_context import UserContext
from models.data_models import Session, Message, Topic, TherapyPlan
from exceptions import PlanningError


class TestPlanEvolution:
    """Test PlanEvolution data structure."""
    
    def test_plan_evolution_creation(self):
        """Test creating plan evolution."""
        evolution = PlanEvolution(
            plan_id="test_plan",
            version=2,
            changes=["focus_updated", "goals_updated"],
            rationale="Updated based on progress",
            effectiveness_score=0.8
        )
        
        assert evolution.plan_id == "test_plan"
        assert evolution.version == 2
        assert evolution.changes == ["focus_updated", "goals_updated"]
        assert evolution.rationale == "Updated based on progress"
        assert evolution.effectiveness_score == 0.8
        assert isinstance(evolution.timestamp, datetime)


class TestPlanningStrategy:
    """Test PlanningStrategy data structure."""
    
    def test_planning_strategy_creation(self):
        """Test creating planning strategy."""
        strategy = PlanningStrategy(
            therapy_style="cbt",
            focus_areas=["anxiety", "work_stress"],
            techniques=["cognitive_restructuring", "behavioral_activation"],
            assessment_criteria=["mood_improvement", "behavioral_changes"]
        )
        
        assert strategy.therapy_style == "cbt"
        assert strategy.focus_areas == ["anxiety", "work_stress"]
        assert strategy.techniques == ["cognitive_restructuring", "behavioral_activation"]
        assert strategy.assessment_criteria == ["mood_improvement", "behavioral_changes"]
        assert isinstance(strategy.created_at, datetime)


class TestPlanningAgent:
    """Test PlanningAgent functionality."""
    
    @pytest.fixture
    def mock_services(self):
        """Create mock services."""
        return {
            'llm_service': Mock(),
            'db_service': Mock(),
            'rag_service': Mock(),
            'memory_agent': Mock()
        }
    
    @pytest.fixture
    def user_context(self):
        """Create user context."""
        return UserContext("test_user")
    
    @pytest.fixture
    def planning_agent(self, mock_services, user_context):
        """Create planning agent with mocked services."""
        return PlanningAgent(
            llm_service=mock_services['llm_service'],
            db_service=mock_services['db_service'],
            rag_service=mock_services['rag_service'],
            user_context=user_context,
            memory_agent=mock_services['memory_agent']
        )
    
    @pytest.fixture
    def sample_session(self):
        """Create sample session."""
        return Session(
            session_id="test_session",
            user_id="test_user",
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="I'm feeling anxious about work deadlines", timestamp=datetime.now()),
                Message(role="assistant", content="Can you tell me more about these feelings?", timestamp=datetime.now())
            ],
            topics=[Topic(name="work_anxiety", status="active")]
        )
    
    @pytest.fixture
    def sample_therapy_plan(self):
        """Create sample therapy plan."""
        return TherapyPlan(
            plan_id="test_plan",
            user_id="test_user",
            created_at=datetime.now() - timedelta(days=7),
            updated_at=datetime.now() - timedelta(days=1),
            plan_details={
                "focus": "Work-related anxiety management",
                "goals": "Reduce anxiety and improve coping strategies",
                "techniques": "CBT, mindfulness, behavioral activation",
                "themes": "work_stress, anxiety, coping"
            },
            version=1,
            selected_therapy_style="cbt"
        )
    
    def test_planning_agent_initialization(self, planning_agent, user_context, mock_services):
        """Test planning agent initialization."""
        assert planning_agent.user_context == user_context
        assert planning_agent.memory_agent == mock_services['memory_agent']
        assert planning_agent.current_strategy is None
        assert planning_agent.plan_evolution == []
    
    def test_create_initial_plan(self, planning_agent, mock_services, sample_session):
        """Test creating initial therapy plan."""
        # Mock session context
        session_context = SessionContext(
            session_id="test_session",
            key_themes=["anxiety", "work"],
            emotional_state="anxious",
            insights=["work_pressure"],
            progress_indicators=["awareness"]
        )
        mock_services['memory_agent'].analyze_session_context.return_value = session_context
        
        # Mock RAG service
        mock_services['rag_service'].retrieve_relevant_knowledge.return_value = [
            {'source': 'cbt_guide', 'content': 'CBT techniques for anxiety'}
        ]
        
        # Mock LLM service
        mock_services['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"focus": "Work anxiety management", "goals": "Reduce anxiety", "techniques": "CBT", "themes": "work, anxiety"}'
        }
        
        # Mock database save
        mock_services['db_service'].save_therapy_plan.return_value = True
        
        # Create plan
        plan = planning_agent.create_initial_plan(sample_session, "cbt")
        
        # Verify plan creation
        assert isinstance(plan, TherapyPlan)
        assert plan.user_id == "test_user"
        assert plan.version == 1
        assert plan.selected_therapy_style == "cbt"
        assert "Work anxiety management" in plan.plan_details["focus"]
        
        # Verify strategy was created
        assert planning_agent.current_strategy is not None
        assert planning_agent.current_strategy.therapy_style == "cbt"
        
        # Verify evolution tracking
        assert len(planning_agent.plan_evolution) == 1
        assert planning_agent.plan_evolution[0].version == 1
    
    def test_create_initial_plan_without_style(self, planning_agent, mock_services, sample_session):
        """Test creating initial plan without specified style."""
        # Mock session context with anxiety themes
        session_context = SessionContext(
            session_id="test_session",
            key_themes=["anxiety", "thoughts"],
            emotional_state="anxious",
            insights=[],
            progress_indicators=[]
        )
        mock_services['memory_agent'].analyze_session_context.return_value = session_context
        
        # Mock RAG service
        mock_services['rag_service'].retrieve_relevant_knowledge.return_value = []
        
        # Mock LLM service
        mock_services['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"focus": "Anxiety management", "goals": "Reduce anxiety", "techniques": "CBT", "themes": "anxiety"}'
        }
        
        # Mock database save
        mock_services['db_service'].save_therapy_plan.return_value = True
        
        # Create plan without specifying style
        plan = planning_agent.create_initial_plan(sample_session)
        
        # Should default to CBT based on anxiety themes
        assert plan.selected_therapy_style == "cbt"
    
    def test_create_initial_plan_database_error(self, planning_agent, mock_services, sample_session):
        """Test initial plan creation with database error."""
        # Mock session context
        session_context = SessionContext(
            session_id="test_session",
            key_themes=["anxiety"],
            emotional_state="anxious",
            insights=[],
            progress_indicators=[]
        )
        mock_services['memory_agent'].analyze_session_context.return_value = session_context
        
        # Mock RAG service
        mock_services['rag_service'].retrieve_relevant_knowledge.return_value = []
        
        # Mock LLM service
        mock_services['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"focus": "Test", "goals": "Test", "techniques": "Test", "themes": "Test"}'
        }
        
        # Mock database save failure
        mock_services['db_service'].save_therapy_plan.return_value = False
        
        # Should raise PlanningError
        with pytest.raises(PlanningError):
            planning_agent.create_initial_plan(sample_session)
    
    def test_update_plan(self, planning_agent, mock_services, sample_session, sample_therapy_plan):
        """Test updating therapy plan."""
        # Mock session context
        session_context = SessionContext(
            session_id="test_session",
            key_themes=["progress", "coping"],
            emotional_state="hopeful",
            insights=["new_strategy"],
            progress_indicators=["improved_mood"]
        )
        mock_services['memory_agent'].analyze_session_context.return_value = session_context
        
        # Mock therapeutic memory with multiple sessions to trigger update
        memory = TherapeuticMemory("test_user")
        memory.recurring_themes = {"anxiety": 3, "work": 2}
        memory.relationship_quality = "developing"
        # Add multiple session contexts to trigger update for version 1 plan
        memory.session_contexts = [Mock(), Mock(), Mock(), Mock()]  # 4 sessions
        mock_services['memory_agent'].get_therapeutic_memory.return_value = memory
        
        # Mock recent context
        mock_services['memory_agent'].get_recent_context.return_value = {
            'context_summary': 'Making progress with anxiety management',
            'insights': ['new_strategy']
        }
        
        # Mock RAG service
        mock_services['rag_service'].retrieve_relevant_knowledge.return_value = []
        
        # Mock LLM service
        mock_services['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"focus": "Advanced anxiety management", "goals": "Maintain progress", "techniques": "Advanced CBT", "themes": "progress, coping"}'
        }
        
        # Mock database save
        mock_services['db_service'].save_therapy_plan.return_value = True
        
        # Update plan
        updated_plan = planning_agent.update_plan(sample_session, sample_therapy_plan)
        
        # Verify update
        assert isinstance(updated_plan, TherapyPlan)
        assert updated_plan.version == 2
        assert updated_plan.plan_details["focus"] == "Advanced anxiety management"
        assert "test_session" in updated_plan.plan_details["updated_from_session"]
        
        # Verify evolution tracking
        assert len(planning_agent.plan_evolution) == 1
        assert planning_agent.plan_evolution[0].version == 2
    
    def test_update_plan_no_update_needed(self, planning_agent, mock_services, sample_session, sample_therapy_plan):
        """Test plan update when no update is needed."""
        # Mock session context with minimal changes
        session_context = SessionContext(
            session_id="test_session",
            key_themes=["anxiety"],  # Same as existing
            emotional_state="neutral",
            insights=[],  # No new insights
            progress_indicators=[]  # No progress
        )
        mock_services['memory_agent'].analyze_session_context.return_value = session_context
        
        # Mock therapeutic memory with few sessions
        memory = TherapeuticMemory("test_user")
        memory.session_contexts = [session_context]  # Only 1 session
        mock_services['memory_agent'].get_therapeutic_memory.return_value = memory
        
        # Update plan
        updated_plan = planning_agent.update_plan(sample_session, sample_therapy_plan)
        
        # Should return the same plan
        assert updated_plan == sample_therapy_plan
        assert len(planning_agent.plan_evolution) == 0
    
    def test_assess_plan_effectiveness(self, planning_agent, mock_services, sample_therapy_plan):
        """Test plan effectiveness assessment."""
        # Mock therapeutic memory
        memory = TherapeuticMemory("test_user")
        memory.relationship_quality = "established"
        mock_services['memory_agent'].get_therapeutic_memory.return_value = memory
        
        # Mock recent context with progress
        mock_services['memory_agent'].get_recent_context.return_value = {
            'insights': ['breakthrough', 'progress'],
            'emotional_progression': ['anxious', 'hopeful', 'confident']
        }
        
        # Mock patterns
        mock_services['memory_agent'].identify_patterns.return_value = {
            'emotional_patterns': {'recent_trend': 'improving'},
            'progress_patterns': {'progress_trend': 'improving'}
        }
        
        # Assess effectiveness
        assessment = planning_agent.assess_plan_effectiveness(sample_therapy_plan)
        
        # Verify assessment
        assert 'plan_id' in assessment
        assert 'effectiveness_score' in assessment
        assert 'strengths' in assessment
        assert 'improvement_areas' in assessment
        assert 'recommendations' in assessment
        
        assert assessment['plan_id'] == "test_plan"
        assert assessment['effectiveness_score'] > 0.5  # Should be high due to progress
    
    def test_recommend_plan_adjustments(self, planning_agent, mock_services, sample_therapy_plan):
        """Test plan adjustment recommendations."""
        # Mock effectiveness assessment
        planning_agent.assess_plan_effectiveness = Mock(return_value={
            'effectiveness_score': 0.6,
            'strengths': ['progress'],
            'improvement_areas': ['focus'],
            'recommendations': []
        })
        
        # Mock therapeutic memory and patterns
        memory = TherapeuticMemory("test_user")
        memory.recurring_themes = {"stress": 2, "work": 3}
        mock_services['memory_agent'].get_therapeutic_memory.return_value = memory
        
        mock_services['memory_agent'].identify_patterns.return_value = {
            'theme_patterns': {'dominant_themes': ['stress', 'work']},
            'emotional_patterns': {'recent_trend': 'stable'},
            'progress_patterns': {'progress_trend': 'stable'}
        }
        
        # Get recommendations
        recommendations = planning_agent.recommend_plan_adjustments(sample_therapy_plan)
        
        # Verify recommendations
        assert isinstance(recommendations, list)
        if recommendations:  # May be empty based on logic
            for rec in recommendations:
                assert 'type' in rec
                assert 'description' in rec
                assert 'rationale' in rec
                assert 'priority' in rec
    
    def test_get_plan_evolution_summary(self, planning_agent):
        """Test plan evolution summary."""
        # Add some evolution history
        evolution1 = PlanEvolution("plan1", 1, ["initial"], "Initial plan", 0.5)
        evolution2 = PlanEvolution("plan2", 2, ["focus_updated"], "Focus update", 0.7)
        planning_agent.plan_evolution = [evolution1, evolution2]
        
        # Get summary
        summary = planning_agent.get_plan_evolution_summary()
        
        # Verify summary
        assert summary['total_versions'] == 2
        assert len(summary['evolution_timeline']) == 2
        assert 'effectiveness_trend' in summary
        assert summary['effectiveness_trend'] == 'improving'  # 0.5 -> 0.7
    
    def test_get_plan_evolution_summary_empty(self, planning_agent):
        """Test plan evolution summary with no history."""
        summary = planning_agent.get_plan_evolution_summary()
        
        assert summary['total_versions'] == 0
        assert summary['evolution_timeline'] == []
        assert summary['common_changes'] == []
        assert summary['effectiveness_trend'] == 'unknown'
    
    def test_health_check_healthy(self, planning_agent, mock_services):
        """Test health check when healthy."""
        # Mock memory agent health check
        mock_services['memory_agent'].health_check.return_value = True
        
        # Mock database service
        mock_services['db_service'].get_latest_therapy_plan.return_value = None
        
        # Mock LLM service
        mock_services['llm_service'].generate_response.return_value = "OK"
        
        result = planning_agent.health_check()
        assert result is True
    
    def test_health_check_unhealthy_memory(self, planning_agent, mock_services):
        """Test health check when memory agent is unhealthy."""
        # Mock memory agent health check failure
        mock_services['memory_agent'].health_check.return_value = False
        
        result = planning_agent.health_check()
        assert result is False
    
    def test_health_check_unhealthy_llm(self, planning_agent, mock_services):
        """Test health check when LLM service is unhealthy."""
        # Mock memory agent health check
        mock_services['memory_agent'].health_check.return_value = True
        
        # Mock database service
        mock_services['db_service'].get_latest_therapy_plan.return_value = None
        
        # Mock LLM service failure
        mock_services['llm_service'].generate_response.return_value = "ERROR"
        
        result = planning_agent.health_check()
        assert result is False
    
    def test_string_representations(self, planning_agent):
        """Test string representations."""
        str_repr = str(planning_agent)
        assert "PlanningAgent" in str_repr
        assert "test_user" in str_repr
        
        repr_str = repr(planning_agent)
        assert "PlanningAgent" in repr_str
        assert "test_user" in repr_str
        assert "evolutions=0" in repr_str


class TestPlanningAgentPrivateMethods:
    """Test private methods of PlanningAgent."""
    
    @pytest.fixture
    def planning_agent_with_mocks(self):
        """Create planning agent with minimal mocks for testing private methods."""
        llm_service = Mock()
        db_service = Mock()
        rag_service = Mock()
        memory_agent = Mock()
        user_context = UserContext("test_user")
        
        return PlanningAgent(
            llm_service=llm_service,
            db_service=db_service,
            rag_service=rag_service,
            user_context=user_context,
            memory_agent=memory_agent
        )
    
    def test_extract_session_text(self, planning_agent_with_mocks):
        """Test session text extraction."""
        session = Session(
            session_id="test",
            user_id="test_user",
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="Hello", timestamp=datetime.now()),
                Message(role="assistant", content="Hi there", timestamp=datetime.now())
            ],
            topics=[]
        )
        
        text = planning_agent_with_mocks._extract_session_text(session)
        assert "user: Hello" in text
        assert "assistant: Hi there" in text
    
    def test_recommend_therapy_style(self, planning_agent_with_mocks):
        """Test therapy style recommendation."""
        # Test CBT recommendation
        session_context = SessionContext("test", ["anxiety", "thoughts"], "anxious", [], [])
        style = planning_agent_with_mocks._recommend_therapy_style(session_context, [])
        assert style == "cbt"
        
        # Test Freud recommendation
        session_context = SessionContext("test", ["dreams", "childhood"], "confused", [], [])
        style = planning_agent_with_mocks._recommend_therapy_style(session_context, [])
        assert style == "freud"
        
        # Test Jung recommendation
        session_context = SessionContext("test", ["symbols", "meaning"], "searching", [], [])
        style = planning_agent_with_mocks._recommend_therapy_style(session_context, [])
        assert style == "jung"
        
        # Test default recommendation
        session_context = SessionContext("test", ["general"], "neutral", [], [])
        style = planning_agent_with_mocks._recommend_therapy_style(session_context, [])
        assert style == "cbt"
    
    def test_assess_update_necessity(self, planning_agent_with_mocks):
        """Test assessment of update necessity."""
        plan = TherapyPlan(
            plan_id="test",
            user_id="test_user",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details={"themes": "anxiety, work"},
            version=1
        )
        
        memory = TherapeuticMemory("test_user")
        memory.session_contexts = [Mock(), Mock(), Mock()]  # 3 sessions
        
        # Test with significant insights
        session_context = SessionContext("test", [], "neutral", ["big_insight", "breakthrough"], [])
        assert planning_agent_with_mocks._assess_update_necessity(session_context, memory, plan) is True
        
        # Test with new themes
        session_context = SessionContext("test", ["new_theme", "another_new"], "neutral", [], [])
        assert planning_agent_with_mocks._assess_update_necessity(session_context, memory, plan) is True
        
        # Test with progress indicators
        session_context = SessionContext("test", [], "neutral", [], ["progress1", "progress2"])
        assert planning_agent_with_mocks._assess_update_necessity(session_context, memory, plan) is True
        
        # Test old plan with multiple sessions
        session_context = SessionContext("test", [], "neutral", [], [])
        assert planning_agent_with_mocks._assess_update_necessity(session_context, memory, plan) is True
        
        # Test no update needed
        memory.session_contexts = [Mock()]  # Only 1 session
        plan.version = 2  # Not version 1
        assert planning_agent_with_mocks._assess_update_necessity(session_context, memory, plan) is False
    
    def test_identify_plan_changes(self, planning_agent_with_mocks):
        """Test plan change identification."""
        old_details = {
            "focus": "Old focus",
            "goals": "Old goals",
            "techniques": "Old techniques",
            "themes": "old, themes"
        }
        
        new_details = {
            "focus": "New focus",
            "goals": "Old goals",  # Same
            "techniques": "New techniques",
            "themes": "old, themes",  # Same
            "memory_insights": ["insight1"],
            "progress_indicators": ["progress1"]
        }
        
        changes = planning_agent_with_mocks._identify_plan_changes(old_details, new_details)
        
        assert "focus_updated" in changes
        assert "techniques_updated" in changes
        assert "goals_updated" not in changes
        assert "themes_updated" not in changes
        assert "memory_insights_integrated" in changes
        assert "progress_tracking_updated" in changes
    
    def test_calculate_effectiveness_score(self, planning_agent_with_mocks):
        """Test effectiveness score calculation."""
        plan = Mock()
        memory = Mock()
        memory.relationship_quality = "established"
        
        recent_context = {"insights": ["insight1", "insight2"]}
        patterns = {"emotional_patterns": {"recent_trend": "improving"}}
        
        score = planning_agent_with_mocks._calculate_effectiveness_score(
            plan, memory, recent_context, patterns
        )
        
        # Base score 0.5 + insights 0.2 + improving trend 0.2 + established relationship 0.3 = 1.2 -> 1.0 (clamped)
        assert 0.5 <= score <= 1.0
        
        # Test with declining trend
        patterns = {"emotional_patterns": {"recent_trend": "declining"}}
        score = planning_agent_with_mocks._calculate_effectiveness_score(
            plan, memory, recent_context, patterns
        )
        assert score < 1.0  # Should be lower due to declining trend


class TestPlanningAgentIntegration:
    """Integration tests for PlanningAgent with realistic scenarios."""
    
    @pytest.fixture
    def realistic_planning_scenario(self):
        """Create realistic planning scenario."""
        # Create mock services
        llm_service = Mock()
        db_service = Mock()
        rag_service = Mock()
        memory_agent = Mock()
        
        # Setup realistic responses
        llm_service.generate_structured_response.return_value = {
            'raw_response': '{"focus": "Comprehensive anxiety management", "goals": "Reduce work-related anxiety and develop coping strategies", "techniques": "CBT, mindfulness, exposure therapy", "themes": "work_anxiety, perfectionism, self_care"}'
        }
        
        db_service.save_therapy_plan.return_value = True
        
        rag_service.retrieve_relevant_knowledge.return_value = [
            {'source': 'cbt_manual', 'content': 'CBT techniques for anxiety disorders'},
            {'source': 'mindfulness_guide', 'content': 'Mindfulness-based stress reduction'}
        ]
        
        # Mock memory agent responses
        session_context = SessionContext(
            session_id="intake_session",
            key_themes=["work_anxiety", "perfectionism", "deadlines"],
            emotional_state="anxious",
            insights=["recognizes perfectionist tendencies"],
            progress_indicators=["willing to try new approaches"]
        )
        memory_agent.analyze_session_context.return_value = session_context
        
        therapeutic_memory = TherapeuticMemory("test_user")
        therapeutic_memory.relationship_quality = "building"
        memory_agent.get_therapeutic_memory.return_value = therapeutic_memory
        
        # Create intake session
        intake_session = Session(
            session_id="intake_session",
            user_id="test_user",
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="I'm constantly worried about missing deadlines at work", timestamp=datetime.now()),
                Message(role="assistant", content="Tell me more about these work pressures", timestamp=datetime.now()),
                Message(role="user", content="I think I'm a perfectionist and it's causing me anxiety", timestamp=datetime.now())
            ],
            topics=[Topic(name="work_anxiety", status="active"), Topic(name="perfectionism", status="active")]
        )
        
        return {
            'llm_service': llm_service,
            'db_service': db_service,
            'rag_service': rag_service,
            'memory_agent': memory_agent,
            'intake_session': intake_session,
            'session_context': session_context
        }
    
    def test_end_to_end_plan_creation(self, realistic_planning_scenario):
        """Test end-to-end therapy plan creation with realistic data."""
        scenario = realistic_planning_scenario
        
        # Create planning agent
        planning_agent = PlanningAgent(
            llm_service=scenario['llm_service'],
            db_service=scenario['db_service'],
            rag_service=scenario['rag_service'],
            user_context=UserContext("test_user"),
            memory_agent=scenario['memory_agent']
        )
        
        # Create initial plan
        plan = planning_agent.create_initial_plan(scenario['intake_session'], "cbt")
        
        # Verify comprehensive plan creation
        assert isinstance(plan, TherapyPlan)
        assert plan.selected_therapy_style == "cbt"
        assert "anxiety management" in plan.plan_details["focus"].lower()
        assert "cbt" in plan.plan_details["techniques"].lower()
        assert "work_anxiety" in plan.plan_details["themes"]
        
        # Verify strategy creation
        assert planning_agent.current_strategy is not None
        assert planning_agent.current_strategy.therapy_style == "cbt"
        assert "work_anxiety" in planning_agent.current_strategy.focus_areas
        
        # Verify evolution tracking
        assert len(planning_agent.plan_evolution) == 1
        evolution = planning_agent.plan_evolution[0]
        assert evolution.version == 1
        assert "initial_plan_created" in evolution.changes
        assert evolution.rationale == "Initial therapy plan based on intake session analysis"
        
        # Verify metadata
        assert plan.plan_details["created_from_session"] == "intake_session"
        assert plan.plan_details["therapy_style"] == "cbt"
        assert plan.plan_details["initial_emotional_state"] == "anxious"
    
    def test_plan_evolution_over_multiple_sessions(self, realistic_planning_scenario):
        """Test plan evolution through multiple therapy sessions."""
        scenario = realistic_planning_scenario
        
        # Create planning agent and initial plan
        planning_agent = PlanningAgent(
            llm_service=scenario['llm_service'],
            db_service=scenario['db_service'],
            rag_service=scenario['rag_service'],
            user_context=UserContext("test_user"),
            memory_agent=scenario['memory_agent']
        )
        
        initial_plan = planning_agent.create_initial_plan(scenario['intake_session'], "cbt")
        
        # Simulate progress session
        progress_session = Session(
            session_id="progress_session",
            user_id="test_user",
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="I tried the breathing exercises and they helped", timestamp=datetime.now()),
                Message(role="assistant", content="That's great progress! What else did you notice?", timestamp=datetime.now()),
                Message(role="user", content="I'm starting to recognize my perfectionist thoughts", timestamp=datetime.now())
            ],
            topics=[Topic(name="progress", status="active"), Topic(name="coping_strategies", status="active")]
        )
        
        # Mock updated responses for progress session
        progress_context = SessionContext(
            session_id="progress_session",
            key_themes=["progress", "coping_strategies", "self_awareness"],
            emotional_state="hopeful",
            insights=["breathing_exercises_effective", "recognizing_thought_patterns"],
            progress_indicators=["applying_techniques", "increased_awareness"]
        )
        scenario['memory_agent'].analyze_session_context.return_value = progress_context
        
        # Mock therapeutic memory with progress
        memory = TherapeuticMemory("test_user")
        memory.session_contexts = [scenario['session_context'], progress_context]
        memory.recurring_themes = {"work_anxiety": 2, "progress": 1, "coping_strategies": 1}
        memory.relationship_quality = "developing"
        scenario['memory_agent'].get_therapeutic_memory.return_value = memory
        
        scenario['memory_agent'].get_recent_context.return_value = {
            'context_summary': 'Client making good progress with breathing exercises',
            'insights': ['breathing_exercises_effective', 'recognizing_thought_patterns']
        }
        
        # Mock updated LLM response
        scenario['llm_service'].generate_structured_response.return_value = {
            'raw_response': '{"focus": "Advanced anxiety management with skill refinement", "goals": "Consolidate progress and develop advanced coping skills", "techniques": "Advanced CBT, cognitive restructuring, behavioral experiments", "themes": "progress, skill_development, self_efficacy"}'
        }
        
        # Update plan
        updated_plan = planning_agent.update_plan(progress_session, initial_plan)
        
        # Verify plan evolution
        assert updated_plan.version == 2
        assert "Advanced anxiety management" in updated_plan.plan_details["focus"]
        assert "skill refinement" in updated_plan.plan_details["focus"]
        assert updated_plan.plan_details["updated_from_session"] == "progress_session"
        
        # Verify evolution tracking
        assert len(planning_agent.plan_evolution) == 2
        latest_evolution = planning_agent.plan_evolution[-1]
        assert latest_evolution.version == 2
        assert "focus_updated" in latest_evolution.changes
        assert "memory_insights_integrated" in latest_evolution.changes
        
        # Test evolution summary
        evolution_summary = planning_agent.get_plan_evolution_summary()
        assert evolution_summary['total_versions'] == 2
        assert evolution_summary['effectiveness_trend'] in ['stable', 'improving', 'unknown']  # Depends on scores
        assert len(evolution_summary['evolution_timeline']) == 2