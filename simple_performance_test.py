#!/usr/bin/env python3
"""
Simple Performance Test for ServiceContainer Architecture

This script provides a straightforward performance validation of the new architecture.
"""

import sys
import os
import time
import statistics
import tempfile
from datetime import datetime
from unittest.mock import Mock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from container.service_container import ServiceContainer
from context.user_context import UserContext
from models.data_models import Session, Message


def create_test_config():
    """Create test configuration with temporary resources."""
    class TestConfig:
        DATABASE_PATH = tempfile.mktemp(suffix='.db')
        MIGRATIONS_DIR = tempfile.mkdtemp()
        GOOGLE_API_KEY = 'performance_test_key'
        MODEL_NAME = 'gemini-2.5-flash'
        DOMAIN_KNOWLEDGE_PATH = tempfile.mkdtemp()
        VECTOR_DB_PATH = tempfile.mkdtemp()
        DATABASE_POOL_SIZE = 10
    
    return TestConfig


def setup_container_with_mocks(config):
    """Setup ServiceContainer with mocked services."""
    container = ServiceContainer(config)
    
    # Mock LLM service
    mock_llm = Mock()
    mock_llm.generate_response.return_value = "Mock therapeutic response"
    mock_llm.generate_structured_response.return_value = {
        'raw_response': '{"key_themes": ["anxiety", "stress"], "emotional_state": "concerned", "insights": ["self_awareness"], "progress_indicators": ["improvement"]}'
    }
    container.register('llm_service', mock_llm)
    
    # Mock RAG service
    mock_rag = Mock()
    mock_rag.retrieve_relevant_knowledge.return_value = [
        {"content": "CBT techniques for anxiety management", "source": "cbt.md"}
    ]
    container.register('rag_service', mock_rag)
    
    return container


def create_test_session(user_id: str) -> Session:
    """Create a test therapy session."""
    return Session(
        session_id=f"{user_id}_test_session",
        user_id=user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(role="user", content="I've been feeling overwhelmed with work stress", timestamp=datetime.now()),
            Message(role="assistant", content="Can you tell me more about what's causing the stress?", timestamp=datetime.now()),
            Message(role="user", content="I think I need better coping strategies", timestamp=datetime.now())
        ]
    )


def test_agent_creation_performance(container, num_iterations=10):
    """Test agent creation performance."""
    print(f"\nTesting agent creation performance ({num_iterations} iterations)...")
    
    creation_times = []
    
    for i in range(num_iterations):
        user_context = UserContext(f"perf_test_user_{i}")
        
        start_time = time.time()
        
        # Create all agent types
        memory_agent = container.create_memory_agent(user_context)
        planning_agent = container.create_planning_agent(user_context)
        reflection_agent = container.create_reflection_agent(user_context)
        
        creation_time = time.time() - start_time
        creation_times.append(creation_time)
    
    avg_time = statistics.mean(creation_times)
    max_time = max(creation_times)
    min_time = min(creation_times)
    
    print(f"  Average creation time: {avg_time:.3f}s")
    print(f"  Min creation time: {min_time:.3f}s")
    print(f"  Max creation time: {max_time:.3f}s")
    
    # Performance assessment
    if avg_time < 0.1:
        assessment = "Excellent"
    elif avg_time < 0.3:
        assessment = "Good"
    elif avg_time < 0.5:
        assessment = "Acceptable"
    else:
        assessment = "Poor"
    
    print(f"  Assessment: {assessment}")
    
    return {
        'avg_time': avg_time,
        'max_time': max_time,
        'min_time': min_time,
        'assessment': assessment
    }


def test_memory_agent_performance(container, num_sessions=10):
    """Test MemoryAgent performance with multiple sessions."""
    print(f"\nTesting MemoryAgent performance ({num_sessions} sessions)...")
    
    user_context = UserContext("memory_performance_user")
    memory_agent = container.create_memory_agent(user_context)
    
    analysis_times = []
    
    for i in range(num_sessions):
        test_session = create_test_session(f"memory_user_{i}")
        
        start_time = time.time()
        session_context = memory_agent.analyze_session_context(test_session)
        analysis_time = time.time() - start_time
        
        analysis_times.append(analysis_time)
        
        # Verify the analysis worked
        assert session_context is not None
        assert hasattr(session_context, 'key_themes')
        assert hasattr(session_context, 'emotional_state')
    
    # Test pattern identification
    start_time = time.time()
    patterns = memory_agent.identify_patterns()
    pattern_time = time.time() - start_time
    
    # Test memory retrieval
    start_time = time.time()
    memory = memory_agent.get_therapeutic_memory()
    memory_time = time.time() - start_time
    
    avg_analysis_time = statistics.mean(analysis_times)
    max_analysis_time = max(analysis_times)
    
    print(f"  Average analysis time: {avg_analysis_time:.3f}s")
    print(f"  Max analysis time: {max_analysis_time:.3f}s")
    print(f"  Pattern identification time: {pattern_time:.3f}s")
    print(f"  Memory retrieval time: {memory_time:.3f}s")
    
    # Performance assessment
    if avg_analysis_time < 0.1:
        assessment = "Excellent"
    elif avg_analysis_time < 0.3:
        assessment = "Good"
    elif avg_analysis_time < 0.5:
        assessment = "Acceptable"
    else:
        assessment = "Poor"
    
    print(f"  Assessment: {assessment}")
    
    return {
        'avg_analysis_time': avg_analysis_time,
        'max_analysis_time': max_analysis_time,
        'pattern_time': pattern_time,
        'memory_time': memory_time,
        'assessment': assessment
    }


def test_planning_agent_performance(container, num_plans=5):
    """Test PlanningAgent performance."""
    print(f"\nTesting PlanningAgent performance ({num_plans} plans)...")
    
    user_context = UserContext("planning_performance_user")
    planning_agent = container.create_planning_agent(user_context)
    
    plan_creation_times = []
    assessment_times = []
    
    current_plan = None
    
    for i in range(num_plans):
        test_session = create_test_session(f"planning_user_{i}")
        
        if current_plan is None:
            # Create initial plan
            start_time = time.time()
            current_plan = planning_agent.create_initial_plan(test_session, "cbt")
            creation_time = time.time() - start_time
            plan_creation_times.append(creation_time)
        else:
            # Update existing plan
            start_time = time.time()
            updated_plan = planning_agent.update_plan(test_session, current_plan)
            creation_time = time.time() - start_time
            plan_creation_times.append(creation_time)
            if updated_plan != current_plan:
                current_plan = updated_plan
        
        # Test plan assessment
        start_time = time.time()
        assessment = planning_agent.assess_plan_effectiveness(current_plan)
        assessment_time = time.time() - start_time
        assessment_times.append(assessment_time)
        
        # Verify results
        assert current_plan is not None
        assert assessment is not None
        assert 'effectiveness_score' in assessment
    
    avg_creation_time = statistics.mean(plan_creation_times)
    avg_assessment_time = statistics.mean(assessment_times)
    max_creation_time = max(plan_creation_times)
    
    print(f"  Average plan creation time: {avg_creation_time:.3f}s")
    print(f"  Max plan creation time: {max_creation_time:.3f}s")
    print(f"  Average assessment time: {avg_assessment_time:.3f}s")
    
    # Performance assessment
    if avg_creation_time < 0.5:
        assessment = "Excellent"
    elif avg_creation_time < 1.0:
        assessment = "Good"
    elif avg_creation_time < 2.0:
        assessment = "Acceptable"
    else:
        assessment = "Poor"
    
    print(f"  Assessment: {assessment}")
    
    return {
        'avg_creation_time': avg_creation_time,
        'max_creation_time': max_creation_time,
        'avg_assessment_time': avg_assessment_time,
        'assessment': assessment
    }


def test_reflection_agent_coordination(container, num_reflections=5):
    """Test ReflectionAgent coordination performance."""
    print(f"\nTesting ReflectionAgent coordination ({num_reflections} reflections)...")
    
    user_context = UserContext("reflection_performance_user")
    reflection_agent = container.create_reflection_agent(user_context)
    
    reflection_times = []
    insight_times = []
    
    for i in range(num_reflections):
        test_session = create_test_session(f"reflection_user_{i}")
        
        # Create a therapy plan first
        therapy_plan = reflection_agent.create_initial_plan(test_session, "cbt")
        
        # Test comprehensive reflection
        start_time = time.time()
        comprehensive_reflection = reflection_agent.generate_comprehensive_reflection(test_session, therapy_plan)
        reflection_time = time.time() - start_time
        reflection_times.append(reflection_time)
        
        # Test therapeutic insights
        start_time = time.time()
        insights = reflection_agent.get_therapeutic_insights()
        insight_time = time.time() - start_time
        insight_times.append(insight_time)
        
        # Verify results
        assert comprehensive_reflection is not None
        assert 'session_context' in comprehensive_reflection
        assert 'therapeutic_memory' in comprehensive_reflection
        assert 'plan_assessment' in comprehensive_reflection
        assert 'agents_used' in comprehensive_reflection
        assert len(comprehensive_reflection['agents_used']) == 3
        assert insights is not None
    
    avg_reflection_time = statistics.mean(reflection_times)
    avg_insight_time = statistics.mean(insight_times)
    max_reflection_time = max(reflection_times)
    
    print(f"  Average reflection time: {avg_reflection_time:.3f}s")
    print(f"  Max reflection time: {max_reflection_time:.3f}s")
    print(f"  Average insight time: {avg_insight_time:.3f}s")
    
    # Performance assessment
    if avg_reflection_time < 0.5:
        assessment = "Excellent"
    elif avg_reflection_time < 1.0:
        assessment = "Good"
    elif avg_reflection_time < 2.0:
        assessment = "Acceptable"
    else:
        assessment = "Poor"
    
    print(f"  Assessment: {assessment}")
    
    return {
        'avg_reflection_time': avg_reflection_time,
        'max_reflection_time': max_reflection_time,
        'avg_insight_time': avg_insight_time,
        'assessment': assessment
    }


def main():
    """Main performance test function."""
    print("🚀 ServiceContainer Architecture Performance Test")
    print("=" * 60)
    
    # Setup test environment
    config = create_test_config()
    container = setup_container_with_mocks(config)
    
    try:
        # Run performance tests
        results = {}
        
        results['agent_creation'] = test_agent_creation_performance(container)
        results['memory_agent'] = test_memory_agent_performance(container)
        results['planning_agent'] = test_planning_agent_performance(container)
        results['reflection_agent'] = test_reflection_agent_coordination(container)
        
        # Overall assessment
        print("\n" + "=" * 60)
        print("📊 PERFORMANCE SUMMARY")
        print("=" * 60)
        
        assessments = [result['assessment'] for result in results.values()]
        assessment_scores = {'Excellent': 4, 'Good': 3, 'Acceptable': 2, 'Poor': 1}
        avg_score = statistics.mean([assessment_scores[a] for a in assessments])
        
        if avg_score >= 3.5:
            overall = "Excellent"
            emoji = "🟢"
        elif avg_score >= 2.5:
            overall = "Good"
            emoji = "🟡"
        elif avg_score >= 1.5:
            overall = "Acceptable"
            emoji = "🟠"
        else:
            overall = "Poor"
            emoji = "🔴"
        
        print(f"Agent Creation:       {results['agent_creation']['assessment']}")
        print(f"Memory Agent:         {results['memory_agent']['assessment']}")
        print(f"Planning Agent:       {results['planning_agent']['assessment']}")
        print(f"Reflection Agent:     {results['reflection_agent']['assessment']}")
        print(f"\nOverall Performance:  {emoji} {overall}")
        
        if overall in ['Excellent', 'Good']:
            print("\n✅ Performance validation successful!")
            print("   The new architecture meets performance requirements.")
            return 0
        else:
            print("\n⚠️  Performance improvements recommended.")
            print("   Consider optimizing identified bottlenecks.")
            return 1
        
    except Exception as e:
        print(f"\n❌ Performance test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    finally:
        container.shutdown()


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)