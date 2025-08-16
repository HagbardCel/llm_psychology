"""
Performance validation tests for the new ServiceContainer architecture.

These tests validate:
- ServiceContainer performance with multiple agent creations
- Database performance with connection pooling
- Memory agent pattern analysis performance
- Planning agent plan evolution performance
- Large session data handling
- Concurrent user simulation
"""

import pytest
import time
import asyncio
import concurrent.futures
import statistics
from unittest.mock import Mock, patch
import tempfile
import os
from datetime import datetime, timedelta

class TestServiceContainerPerformance:
    """Performance tests for ServiceContainer operations."""
    
    @pytest.fixture
    def performance_config(self):
        """Create configuration optimized for performance testing."""
        temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        temp_db.close()
        
        class PerformanceConfig:
            DATABASE_PATH = temp_db.name
            MIGRATIONS_DIR = tempfile.mkdtemp()
            GOOGLE_API_KEY = "performance_test_key"
            MODEL_NAME = "gemini-2.5-flash"
            DOMAIN_KNOWLEDGE_PATH = tempfile.mkdtemp()
            VECTOR_DB_PATH = tempfile.mkdtemp()
            DATABASE_POOL_SIZE = 10  # Larger pool for performance testing
        
        yield PerformanceConfig
        
        # Cleanup
        os.unlink(temp_db.name)
        import shutil
        shutil.rmtree(PerformanceConfig.MIGRATIONS_DIR)
        shutil.rmtree(PerformanceConfig.DOMAIN_KNOWLEDGE_PATH)
        shutil.rmtree(PerformanceConfig.VECTOR_DB_PATH)
    
    @pytest.fixture
    def performance_container(self, performance_config):
        """Create ServiceContainer with performance optimizations."""
        from container.service_container import ServiceContainer
        
        container = ServiceContainer(performance_config)
        
        # Mock LLM service for fast responses
        mock_llm = Mock()
        mock_llm.generate_response.return_value = "Fast mock response"
        mock_llm.generate_structured_response.return_value = {
            'raw_response': '{"focus": "test", "goals": "test", "techniques": "test", "themes": "test"}'
        }
        container.register('llm_service', mock_llm)
        
        # Mock RAG service for fast responses
        mock_rag = Mock()
        mock_rag.retrieve_relevant_knowledge.return_value = [
            {"content": "Fast knowledge", "source": "test.md"}
        ]
        container.register('rag_service', mock_rag)
        
        return container
    
    def test_service_container_creation_performance(self, performance_config):
        """Test ServiceContainer creation performance."""
        from container.service_container import ServiceContainer
        
        creation_times = []
        
        for _ in range(10):
            start_time = time.time()
            container = ServiceContainer(performance_config)
            creation_time = time.time() - start_time
            creation_times.append(creation_time)
            container.shutdown()
        
        avg_creation_time = statistics.mean(creation_times)
        max_creation_time = max(creation_times)
        
        # Performance assertions
        assert avg_creation_time < 1.0, f"Average creation time {avg_creation_time:.3f}s too slow"
        assert max_creation_time < 2.0, f"Max creation time {max_creation_time:.3f}s too slow"
        
        print(f"ServiceContainer creation - Avg: {avg_creation_time:.3f}s, Max: {max_creation_time:.3f}s")
    
    def test_agent_creation_performance(self, performance_container):
        """Test agent creation performance through ServiceContainer."""
        from context.user_context import UserContext
        
        user_context = UserContext("performance_test_user")
        agent_creation_times = {}
        
        # Test each agent type
        agent_types = [
            ('intake', 'create_intake_agent'),
            ('assessment', 'create_assessment_agent'), 
            ('psychoanalyst', 'create_psychoanalyst_agent'),
            ('reflection', 'create_reflection_agent'),
            ('memory', 'create_memory_agent'),
            ('planning', 'create_planning_agent')
        ]
        
        for agent_name, method_name in agent_types:
            times = []
            
            for _ in range(5):
                start_time = time.time()
                agent = getattr(performance_container, method_name)(user_context)
                creation_time = time.time() - start_time
                times.append(creation_time)
                
                assert agent is not None
            
            avg_time = statistics.mean(times)
            agent_creation_times[agent_name] = avg_time
            
            # Performance assertions
            assert avg_time < 0.5, f"{agent_name} agent creation too slow: {avg_time:.3f}s"
        
        print(f"Agent creation times: {agent_creation_times}")
    
    def test_database_connection_pool_performance(self, performance_container):
        """Test database connection pool performance under load."""
        db_service = performance_container.get('db_service')
        
        def database_operation():
            start_time = time.time()
            # Simulate database operation
            status = db_service.get_user_status("perf_test_user")
            return time.time() - start_time
        
        # Test concurrent database operations
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(database_operation) for _ in range(50)]
            operation_times = [future.result() for future in futures]
        
        avg_operation_time = statistics.mean(operation_times)
        max_operation_time = max(operation_times)
        
        # Performance assertions
        assert avg_operation_time < 0.1, f"Average DB operation too slow: {avg_operation_time:.3f}s"
        assert max_operation_time < 0.5, f"Max DB operation too slow: {max_operation_time:.3f}s"
        
        print(f"Database operations - Avg: {avg_operation_time:.3f}s, Max: {max_operation_time:.3f}s")


class TestMemoryAgentPerformance:
    """Performance tests for MemoryAgent operations."""
    
    @pytest.fixture
    def memory_agent_with_data(self, performance_container):
        """Create MemoryAgent with test data."""
        from context.user_context import UserContext
        from models.data_models import Session, Message
        
        user_context = UserContext("memory_performance_user")
        memory_agent = performance_container.create_memory_agent(user_context)
        
        # Create multiple sessions for performance testing
        sessions = []
        for i in range(20):
            session = Session(
                session_id=f"perf_session_{i}",
                user_id="memory_performance_user",
                timestamp=datetime.now() - timedelta(days=i),
                transcript=[
                    Message(role="user", content=f"User message {i} about stress and anxiety", timestamp=datetime.now()),
                    Message(role="assistant", content=f"Assistant response {i} about coping strategies", timestamp=datetime.now())
                ]
            )
            sessions.append(session)
        
        return memory_agent, sessions
    
    def test_session_context_analysis_performance(self, memory_agent_with_data):
        """Test performance of session context analysis."""
        memory_agent, sessions = memory_agent_with_data
        
        analysis_times = []
        
        for session in sessions[:10]:  # Test with 10 sessions
            start_time = time.time()
            context = memory_agent.analyze_session_context(session)
            analysis_time = time.time() - start_time
            analysis_times.append(analysis_time)
            
            assert context is not None
            assert context.session_id == session.session_id
        
        avg_analysis_time = statistics.mean(analysis_times)
        max_analysis_time = max(analysis_times)
        
        # Performance assertions
        assert avg_analysis_time < 0.5, f"Session analysis too slow: {avg_analysis_time:.3f}s"
        assert max_analysis_time < 1.0, f"Max session analysis too slow: {max_analysis_time:.3f}s"
        
        print(f"Session analysis - Avg: {avg_analysis_time:.3f}s, Max: {max_analysis_time:.3f}s")
    
    def test_pattern_identification_performance(self, memory_agent_with_data):
        """Test performance of pattern identification with multiple sessions."""
        memory_agent, sessions = memory_agent_with_data
        
        # Simulate analyzed sessions in memory
        for session in sessions:
            memory_agent.analyze_session_context(session)
        
        start_time = time.time()
        patterns = memory_agent.identify_patterns()
        pattern_time = time.time() - start_time
        
        assert isinstance(patterns, dict)
        assert pattern_time < 1.0, f"Pattern identification too slow: {pattern_time:.3f}s"
        
        print(f"Pattern identification time: {pattern_time:.3f}s")
    
    def test_therapeutic_memory_retrieval_performance(self, memory_agent_with_data):
        """Test performance of therapeutic memory retrieval."""
        memory_agent, sessions = memory_agent_with_data
        
        # Build up memory with multiple sessions
        for session in sessions:
            memory_agent.analyze_session_context(session)
        
        retrieval_times = []
        
        for _ in range(10):
            start_time = time.time()
            memory = memory_agent.get_therapeutic_memory()
            retrieval_time = time.time() - start_time
            retrieval_times.append(retrieval_time)
            
            assert memory is not None
            assert memory.user_id == "memory_performance_user"
        
        avg_retrieval_time = statistics.mean(retrieval_times)
        
        assert avg_retrieval_time < 0.1, f"Memory retrieval too slow: {avg_retrieval_time:.3f}s"
        
        print(f"Memory retrieval - Avg: {avg_retrieval_time:.3f}s")


class TestPlanningAgentPerformance:
    """Performance tests for PlanningAgent operations."""
    
    @pytest.fixture
    def planning_agent_with_plans(self, performance_container):
        """Create PlanningAgent with multiple therapy plans."""
        from context.user_context import UserContext
        from models.data_models import Session, Message
        
        user_context = UserContext("planning_performance_user")
        planning_agent = performance_container.create_planning_agent(user_context)
        
        # Create test session for plan creation
        test_session = Session(
            session_id="planning_test_session",
            user_id="planning_performance_user",
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="I'm dealing with work anxiety and stress", timestamp=datetime.now()),
                Message(role="assistant", content="Tell me more about your work situation", timestamp=datetime.now())
            ]
        )
        
        return planning_agent, test_session
    
    def test_initial_plan_creation_performance(self, planning_agent_with_plans):
        """Test performance of initial therapy plan creation."""
        planning_agent, test_session = planning_agent_with_plans
        
        creation_times = []
        
        for i in range(5):
            start_time = time.time()
            plan = planning_agent.create_initial_plan(test_session, "cbt")
            creation_time = time.time() - start_time
            creation_times.append(creation_time)
            
            assert plan is not None
            assert plan.selected_therapy_style == "cbt"
        
        avg_creation_time = statistics.mean(creation_times)
        max_creation_time = max(creation_times)
        
        # Performance assertions
        assert avg_creation_time < 1.0, f"Plan creation too slow: {avg_creation_time:.3f}s"
        assert max_creation_time < 2.0, f"Max plan creation too slow: {max_creation_time:.3f}s"
        
        print(f"Plan creation - Avg: {avg_creation_time:.3f}s, Max: {max_creation_time:.3f}s")
    
    def test_plan_effectiveness_assessment_performance(self, planning_agent_with_plans):
        """Test performance of plan effectiveness assessment."""
        planning_agent, test_session = planning_agent_with_plans
        
        # Create a therapy plan first
        plan = planning_agent.create_initial_plan(test_session, "cbt")
        
        assessment_times = []
        
        for _ in range(10):
            start_time = time.time()
            assessment = planning_agent.assess_plan_effectiveness(plan)
            assessment_time = time.time() - start_time
            assessment_times.append(assessment_time)
            
            assert 'effectiveness_score' in assessment
            assert 'strengths' in assessment
        
        avg_assessment_time = statistics.mean(assessment_times)
        
        assert avg_assessment_time < 0.5, f"Plan assessment too slow: {avg_assessment_time:.3f}s"
        
        print(f"Plan assessment - Avg: {avg_assessment_time:.3f}s")
    
    def test_plan_evolution_tracking_performance(self, planning_agent_with_plans):
        """Test performance of plan evolution tracking with multiple versions."""
        planning_agent, test_session = planning_agent_with_plans
        
        # Create initial plan
        current_plan = planning_agent.create_initial_plan(test_session, "cbt")
        
        # Create multiple plan updates to build evolution history
        for i in range(10):
            start_time = time.time()
            updated_plan = planning_agent.update_plan(test_session, current_plan)
            update_time = time.time() - start_time
            
            # Track if update actually occurred
            if updated_plan != current_plan:
                current_plan = updated_plan
            
            # Each update should be reasonably fast
            assert update_time < 1.0, f"Plan update {i} too slow: {update_time:.3f}s"
        
        # Test evolution summary performance
        start_time = time.time()
        evolution_summary = planning_agent.get_plan_evolution_summary()
        summary_time = time.time() - start_time
        
        assert evolution_summary['total_versions'] >= 1
        assert summary_time < 0.1, f"Evolution summary too slow: {summary_time:.3f}s"
        
        print(f"Plan evolution summary time: {summary_time:.3f}s")


class TestConcurrentUserSimulation:
    """Test system performance under concurrent user load."""
    
    @pytest.fixture
    def load_test_environment(self):
        """Create environment for load testing."""
        temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        temp_db.close()
        
        class LoadTestConfig:
            DATABASE_PATH = temp_db.name
            MIGRATIONS_DIR = tempfile.mkdtemp()
            GOOGLE_API_KEY = "load_test_key"
            MODEL_NAME = "gemini-2.5-flash"
            DOMAIN_KNOWLEDGE_PATH = tempfile.mkdtemp()
            VECTOR_DB_PATH = tempfile.mkdtemp()
            DATABASE_POOL_SIZE = 20  # Large pool for concurrent testing
        
        yield LoadTestConfig
        
        # Cleanup
        os.unlink(temp_db.name)
        import shutil
        shutil.rmtree(LoadTestConfig.MIGRATIONS_DIR)
        shutil.rmtree(LoadTestConfig.DOMAIN_KNOWLEDGE_PATH)
        shutil.rmtree(LoadTestConfig.VECTOR_DB_PATH)
    
    def simulate_user_workflow(self, container, user_id):
        """Simulate a complete user workflow."""
        from context.user_context import UserContext
        from models.data_models import Session, Message
        
        try:
            start_time = time.time()
            
            user_context = UserContext(user_id)
            
            # Create agents
            memory_agent = container.create_memory_agent(user_context)
            planning_agent = container.create_planning_agent(user_context)
            reflection_agent = container.create_reflection_agent(user_context)
            
            # Simulate session
            test_session = Session(
                session_id=f"{user_id}_session",
                user_id=user_id,
                timestamp=datetime.now(),
                transcript=[
                    Message(role="user", content=f"User {user_id} needs help with stress", timestamp=datetime.now())
                ]
            )
            
            # Analyze session
            session_context = memory_agent.analyze_session_context(test_session)
            
            # Create plan
            therapy_plan = planning_agent.create_initial_plan(test_session, "cbt")
            
            # Generate reflection
            reflection = reflection_agent.generate_comprehensive_reflection(test_session, therapy_plan)
            
            workflow_time = time.time() - start_time
            return {
                'user_id': user_id,
                'success': True,
                'workflow_time': workflow_time,
                'error': None
            }
            
        except Exception as e:
            workflow_time = time.time() - start_time
            return {
                'user_id': user_id,
                'success': False,
                'workflow_time': workflow_time,
                'error': str(e)
            }
    
    def test_concurrent_user_workflows(self, load_test_environment):
        """Test system performance with concurrent users."""
        from container.service_container import ServiceContainer
        
        container = ServiceContainer(load_test_environment)
        
        # Mock services for fast responses
        mock_llm = Mock()
        mock_llm.generate_response.return_value = "Fast response"
        mock_llm.generate_structured_response.return_value = {
            'raw_response': '{"focus": "test", "goals": "test", "techniques": "test", "themes": "test"}'
        }
        container.register('llm_service', mock_llm)
        
        mock_rag = Mock()
        mock_rag.retrieve_relevant_knowledge.return_value = [{"content": "Knowledge", "source": "test.md"}]
        container.register('rag_service', mock_rag)
        
        # Simulate concurrent users
        num_users = 10
        max_workers = 5
        
        user_ids = [f"load_test_user_{i}" for i in range(num_users)]
        
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self.simulate_user_workflow, container, user_id)
                for user_id in user_ids
            ]
            results = [future.result() for future in futures]
        
        total_time = time.time() - start_time
        
        # Analyze results
        successful_workflows = [r for r in results if r['success']]
        failed_workflows = [r for r in results if not r['success']]
        
        workflow_times = [r['workflow_time'] for r in successful_workflows]
        avg_workflow_time = statistics.mean(workflow_times) if workflow_times else 0
        max_workflow_time = max(workflow_times) if workflow_times else 0
        
        # Performance assertions
        success_rate = len(successful_workflows) / len(results)
        assert success_rate >= 0.9, f"Success rate too low: {success_rate:.2%}"
        assert avg_workflow_time < 2.0, f"Average workflow too slow: {avg_workflow_time:.3f}s"
        assert total_time < 30.0, f"Total execution too slow: {total_time:.3f}s"
        
        print(f"Concurrent load test results:")
        print(f"  Users: {num_users}, Workers: {max_workers}")
        print(f"  Success rate: {success_rate:.2%}")
        print(f"  Average workflow time: {avg_workflow_time:.3f}s")
        print(f"  Max workflow time: {max_workflow_time:.3f}s")
        print(f"  Total execution time: {total_time:.3f}s")
        
        if failed_workflows:
            print(f"  Failed workflows: {len(failed_workflows)}")
            for failure in failed_workflows[:3]:  # Show first 3 failures
                print(f"    {failure['user_id']}: {failure['error']}")
        
        container.shutdown()
    
    def test_memory_usage_under_load(self, load_test_environment):
        """Test memory usage under sustained load."""
        import psutil
        import gc
        from container.service_container import ServiceContainer
        
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        container = ServiceContainer(load_test_environment)
        
        # Mock services
        mock_llm = Mock()
        mock_llm.generate_response.return_value = "Response"
        mock_llm.generate_structured_response.return_value = {'raw_response': '{"test": "data"}'}
        container.register('llm_service', mock_llm)
        
        mock_rag = Mock()
        mock_rag.retrieve_relevant_knowledge.return_value = [{"content": "Knowledge", "source": "test.md"}]
        container.register('rag_service', mock_rag)
        
        # Sustained load test
        memory_measurements = []
        
        for i in range(50):
            # Simulate user workflow
            self.simulate_user_workflow(container, f"memory_test_user_{i}")
            
            # Measure memory every 10 iterations
            if i % 10 == 0:
                gc.collect()  # Force garbage collection
                current_memory = process.memory_info().rss / 1024 / 1024  # MB
                memory_measurements.append(current_memory)
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        max_memory = max(memory_measurements) if memory_measurements else final_memory
        
        print(f"Memory usage test:")
        print(f"  Initial memory: {initial_memory:.1f} MB")
        print(f"  Final memory: {final_memory:.1f} MB")
        print(f"  Memory increase: {memory_increase:.1f} MB")
        print(f"  Max memory: {max_memory:.1f} MB")
        
        # Memory assertions (reasonable limits)
        assert memory_increase < 100, f"Memory increase too high: {memory_increase:.1f} MB"
        assert max_memory < initial_memory + 150, f"Peak memory too high: {max_memory:.1f} MB"
        
        container.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])