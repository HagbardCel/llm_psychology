#!/usr/bin/env python3
"""
Load Testing Runner for ServiceContainer Architecture

This script provides practical load testing for the new architecture:
- Tests ServiceContainer performance under load
- Validates database connection pooling
- Tests agent creation and coordination performance
- Provides performance benchmarks and recommendations
"""

import concurrent.futures
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime
from typing import Any

import psutil

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import Mock

from container.service_container import ServiceContainer
from context.user_context import UserContext
from models.data_models import Message, Session


class LoadTestRunner:
    """Load testing runner for the psychoanalyst application."""

    def __init__(self, num_users: int = 10, num_workers: int = 5):
        """
        Initialize load test runner.

        Args:
            num_users: Number of concurrent users to simulate
            num_workers: Number of worker threads
        """
        self.num_users = num_users
        self.num_workers = num_workers
        self.results = []
        self.container = None

        # Setup test environment
        self.setup_test_environment()

    def setup_test_environment(self):
        """Setup test environment with temporary resources."""
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()

        # Create temporary directories
        self.temp_migrations_dir = tempfile.mkdtemp()
        self.temp_domain_dir = tempfile.mkdtemp()
        self.temp_vector_dir = tempfile.mkdtemp()

        # Create test configuration
        # Create test configuration using settings model
        from config import settings

        # Create a modified copy of settings for the load test
        self.config = settings.model_copy(
            update={
                "DATABASE_PATH": self.temp_db.name,
                "GOOGLE_API_KEY": "load_test_api_key",
                "EMBEDDING_MODEL_NAME": "gemini-2.5-flash",
                # Assuming this maps to MODEL_NAME or similar
                "DOMAIN_KNOWLEDGE_PATH": self.temp_domain_dir,
                "VECTOR_DB_PATH": self.temp_vector_dir,
                "DATABASE_POOL_SIZE": max(10, self.num_workers * 2),
            }
        )

        print("Load test environment setup:")
        print(f"  Database: {self.temp_db.name}")
        print(f"  Pool size: {self.config.DATABASE_POOL_SIZE}")
        print(f"  Users: {self.num_users}")
        print(f"  Workers: {self.num_workers}")

    def setup_container(self):
        """Setup ServiceContainer with mocked services for testing."""
        self.container = ServiceContainer(self.config)

        # Mock LLM service for consistent, fast responses
        mock_llm = Mock()
        mock_llm.generate_response.return_value = (
            "Mock therapeutic response for load testing"
        )
        mock_llm.generate_structured_response.return_value = {
            "raw_response": (
                '{"key_themes": ["stress", "anxiety"], '
                '"emotional_state": "concerned", '
                '"insights": ["recognizing_patterns"], '
                '"progress_indicators": ["self_awareness"]}'
            )
        }
        mock_llm.generate_structured_data.return_value = {
            "raw_response": mock_llm.generate_structured_response.return_value["raw_response"],
            "data": {
                "key_themes": ["stress", "anxiety"],
                "emotional_state": "concerned",
                "insights": ["recognizing_patterns"],
                "progress_indicators": ["self_awareness"],
            },
        }
        self.container.register("llm_service", mock_llm)

        # Mock RAG service for fast knowledge retrieval
        mock_rag = Mock()
        mock_rag.retrieve_relevant_knowledge.return_value = [
            {"content": "CBT techniques for stress management", "source": "cbt.md"},
            {
                "content": "Mindfulness approaches for anxiety",
                "source": "mindfulness.md",
            },
        ]
        self.container.register("rag_service", mock_rag)

        print("ServiceContainer setup complete with mocked services")

    def simulate_user_session(self, user_id: str) -> dict[str, Any]:
        """
        Simulate a complete user therapy session.

        Args:
            user_id: Unique identifier for the user

        Returns:
            Dict containing session results and performance metrics
        """
        start_time = time.time()
        result = {
            "user_id": user_id,
            "success": False,
            "total_time": 0,
            "agent_creation_time": 0,
            "memory_analysis_time": 0,
            "planning_time": 0,
            "reflection_time": 0,
            "error": None,
        }

        try:
            # Step 1: Agent Creation
            agent_start = time.time()

            user_context = UserContext(user_id)
            memory_agent = self.container.create_memory_agent(user_context)
            planning_agent = self.container.create_planning_agent(user_context)
            reflection_agent = self.container.create_reflection_agent(user_context)

            result["agent_creation_time"] = time.time() - agent_start

            # Step 2: Create test session data
            test_session = Session(
                session_id=f"{user_id}_session_{int(time.time())}",
                user_id=user_id,
                timestamp=datetime.now(),
                transcript=[
                    Message(
                        role="user",
                        content="I've been feeling overwhelmed with work stress lately",
                        timestamp=datetime.now(),
                    ),
                    Message(
                        role="assistant",
                        content="Can you tell me more about what's been stressing you?",
                        timestamp=datetime.now(),
                    ),
                    Message(
                        role="user",
                        content="I think I need better coping strategies for deadlines",
                        timestamp=datetime.now(),
                    ),
                ],
            )

            # Step 3: Memory Analysis
            memory_start = time.time()
            session_context = memory_agent.analyze_session_context(test_session)
            _ = memory_agent.get_therapeutic_memory()  # noqa: F841
            _ = memory_agent.identify_patterns()  # noqa: F841
            result["memory_analysis_time"] = time.time() - memory_start

            # Step 4: Planning Operations
            planning_start = time.time()
            therapy_plan = planning_agent.create_initial_plan(test_session, "cbt")
            _ = planning_agent.assess_plan_effectiveness(therapy_plan)  # noqa
            _ = planning_agent.recommend_plan_adjustments(therapy_plan)  # noqa
            result["planning_time"] = time.time() - planning_start

            # Step 5: Reflection Coordination
            reflection_start = time.time()
            comprehensive_reflection = (
                reflection_agent.generate_comprehensive_reflection(
                    test_session, therapy_plan
                )
            )
            _ = reflection_agent.get_therapeutic_insights()  # noqa: F841
            result["reflection_time"] = time.time() - reflection_start

            # Verify results
            assert session_context is not None
            assert therapy_plan is not None
            assert comprehensive_reflection is not None
            assert "memory_insights" in comprehensive_reflection
            assert "planning_insights" in comprehensive_reflection
            assert len(comprehensive_reflection["agents_used"]) == 3

            result["success"] = True
            result["total_time"] = time.time() - start_time

        except Exception as e:
            result["total_time"] = time.time() - start_time
            result["error"] = str(e)
            print(f"Error in user session {user_id}: {e}")

        return result

    def run_load_test(self) -> dict[str, Any]:
        """
        Run the complete load test.

        Returns:
            Dict containing comprehensive load test results
        """
        print(
            f"\nStarting load test with {self.num_users} users and "
            f"{self.num_workers} workers..."
        )

        # Setup container
        self.setup_container()

        # Get initial system stats
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        initial_cpu = process.cpu_percent()

        # Generate user IDs
        user_ids = [f"load_test_user_{i:03d}" for i in range(self.num_users)]

        # Run concurrent user sessions
        start_time = time.time()

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.num_workers
        ) as executor:
            print(f"Submitting {len(user_ids)} user sessions...")
            futures = [
                executor.submit(self.simulate_user_session, user_id)
                for user_id in user_ids
            ]

            print("Waiting for sessions to complete...")
            self.results = [future.result() for future in futures]

        total_execution_time = time.time() - start_time

        # Get final system stats
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        final_cpu = process.cpu_percent()

        # Analyze results
        return self.analyze_results(
            total_execution_time, initial_memory, final_memory, initial_cpu, final_cpu
        )

    def analyze_results(
        self,
        total_time: float,
        initial_memory: float,
        final_memory: float,
        initial_cpu: float,
        final_cpu: float,
    ) -> dict[str, Any]:
        """Analyze load test results and generate performance report."""
        successful_sessions = [r for r in self.results if r["success"]]
        failed_sessions = [r for r in self.results if not r["success"]]

        if not successful_sessions:
            return {
                "success": False,
                "error": "All sessions failed",
                "failed_count": len(failed_sessions),
            }

        # Calculate performance metrics
        total_times = [r["total_time"] for r in successful_sessions]
        agent_creation_times = [r["agent_creation_time"] for r in successful_sessions]
        memory_analysis_times = [r["memory_analysis_time"] for r in successful_sessions]
        planning_times = [r["planning_time"] for r in successful_sessions]
        reflection_times = [r["reflection_time"] for r in successful_sessions]

        def calculate_stats(times: list[float]) -> dict[str, float]:
            if not times:
                return {"avg": 0, "min": 0, "max": 0, "median": 0, "p95": 0}
            return {
                "avg": statistics.mean(times),
                "min": min(times),
                "max": max(times),
                "median": statistics.median(times),
                "p95": (
                    sorted(times)[int(len(times) * 0.95)]
                    if len(times) > 1
                    else times[0]
                ),
            }

        analysis = {
            "success": True,
            "execution_summary": {
                "total_users": self.num_users,
                "successful_sessions": len(successful_sessions),
                "failed_sessions": len(failed_sessions),
                "success_rate": len(successful_sessions) / self.num_users,
                "total_execution_time": total_time,
                "sessions_per_second": self.num_users / total_time,
            },
            "performance_metrics": {
                "total_session_time": calculate_stats(total_times),
                "agent_creation_time": calculate_stats(agent_creation_times),
                "memory_analysis_time": calculate_stats(memory_analysis_times),
                "planning_time": calculate_stats(planning_times),
                "reflection_time": calculate_stats(reflection_times),
            },
            "system_resources": {
                "memory_usage_mb": {
                    "initial": initial_memory,
                    "final": final_memory,
                    "increase": final_memory - initial_memory,
                },
                "cpu_usage_percent": {"initial": initial_cpu, "final": final_cpu},
            },
            "performance_assessment": {},
        }

        # Performance assessment
        avg_total_time = analysis["performance_metrics"]["total_session_time"]["avg"]
        success_rate = analysis["execution_summary"]["success_rate"]
        memory_increase = analysis["system_resources"]["memory_usage_mb"]["increase"]

        assessment = analysis["performance_assessment"]

        # Response time assessment
        if avg_total_time < 1.0:
            assessment["response_time"] = "Excellent"
        elif avg_total_time < 2.0:
            assessment["response_time"] = "Good"
        elif avg_total_time < 5.0:
            assessment["response_time"] = "Acceptable"
        else:
            assessment["response_time"] = "Poor"

        # Success rate assessment
        if success_rate >= 0.99:
            assessment["reliability"] = "Excellent"
        elif success_rate >= 0.95:
            assessment["reliability"] = "Good"
        elif success_rate >= 0.90:
            assessment["reliability"] = "Acceptable"
        else:
            assessment["reliability"] = "Poor"

        # Memory usage assessment
        if memory_increase < 50:
            assessment["memory_efficiency"] = "Excellent"
        elif memory_increase < 100:
            assessment["memory_efficiency"] = "Good"
        elif memory_increase < 200:
            assessment["memory_efficiency"] = "Acceptable"
        else:
            assessment["memory_efficiency"] = "Poor"

        # Overall assessment
        assessments = list(assessment.values())
        if all(a in ["Excellent", "Good"] for a in assessments):
            assessment["overall"] = "Excellent"
        elif all(a in ["Excellent", "Good", "Acceptable"] for a in assessments):
            assessment["overall"] = "Good"
        else:
            assessment["overall"] = "Needs Improvement"

        return analysis

    def print_report(self, analysis: dict[str, Any]):
        """Print formatted load test report."""
        print("\n" + "=" * 80)
        print("LOAD TEST RESULTS")
        print("=" * 80)

        if not analysis["success"]:
            print(f"❌ Load test failed: {analysis.get('error', 'Unknown error')}")
            return

        exec_summary = analysis["execution_summary"]
        perf_metrics = analysis["performance_metrics"]
        resources = analysis["system_resources"]
        assessment = analysis["performance_assessment"]

        # Execution Summary
        print("\n📊 EXECUTION SUMMARY")
        print(f"  Total Users:           {exec_summary['total_users']}")
        print(f"  Successful Sessions:   {exec_summary['successful_sessions']}")
        print(f"  Failed Sessions:       {exec_summary['failed_sessions']}")
        print(f"  Success Rate:          {exec_summary['success_rate']:.1%}")
        print(f"  Total Execution Time:  {exec_summary['total_execution_time']:.2f}s")
        print(f"  Sessions per Second:   {exec_summary['sessions_per_second']:.2f}")

        # Performance Metrics
        print("\n⚡ PERFORMANCE METRICS")

        def print_metric(name: str, stats: dict[str, float]):
            print(f"  {name}:")
            print(f"    Average: {stats['avg']:.3f}s")
            print(f"    Median:  {stats['median']:.3f}s")
            print(f"    Min:     {stats['min']:.3f}s")
            print(f"    Max:     {stats['max']:.3f}s")
            print(f"    95th %:  {stats['p95']:.3f}s")

        print_metric("Total Session Time", perf_metrics["total_session_time"])
        print_metric("Agent Creation", perf_metrics["agent_creation_time"])
        print_metric("Memory Analysis", perf_metrics["memory_analysis_time"])
        print_metric("Planning Operations", perf_metrics["planning_time"])
        print_metric("Reflection Coordination", perf_metrics["reflection_time"])

        # System Resources
        print("\n💾 SYSTEM RESOURCES")
        memory = resources["memory_usage_mb"]
        cpu = resources["cpu_usage_percent"]
        print("  Memory Usage:")
        print(f"    Initial:  {memory['initial']:.1f} MB")
        print(f"    Final:    {memory['final']:.1f} MB")
        print(f"    Increase: {memory['increase']:.1f} MB")
        print("  CPU Usage:")
        print(f"    Initial:  {cpu['initial']:.1f}%")
        print(f"    Final:    {cpu['final']:.1f}%")

        # Performance Assessment
        print("\n🎯 PERFORMANCE ASSESSMENT")

        def get_emoji(rating: str) -> str:
            return {
                "Excellent": "🟢",
                "Good": "🟡",
                "Acceptable": "🟠",
                "Poor": "🔴",
            }.get(rating, "❓")

        print(
            f"  Response Time:     {get_emoji(assessment['response_time'])} "
            f"{assessment['response_time']}"
        )
        print(
            f"  Reliability:       {get_emoji(assessment['reliability'])} "
            f"{assessment['reliability']}"
        )
        print(
            f"  Memory Efficiency: "
            f"{get_emoji(assessment['memory_efficiency'])} "
            f"{assessment['memory_efficiency']}"
        )
        print(
            f"  Overall Rating:    {get_emoji(assessment['overall'])} "
            f"{assessment['overall']}"
        )

        # Recommendations
        print("\n💡 RECOMMENDATIONS")

        if assessment["overall"] == "Excellent":
            print("  ✅ System performance is excellent under current load")
            print("  ✅ Consider testing with higher loads to find capacity limits")
        elif assessment["overall"] == "Good":
            print("  ✅ System performance is good for production use")
            print("  💡 Monitor performance in production environment")
        else:
            print("  ⚠️  Performance improvements recommended:")

            if assessment["response_time"] in ["Acceptable", "Poor"]:
                print("     - Optimize agent coordination and LLM response times")
                print("     - Consider caching frequently accessed data")

            if assessment["reliability"] in ["Acceptable", "Poor"]:
                print("     - Investigate and fix causes of session failures")
                print("     - Improve error handling and recovery mechanisms")

            if assessment["memory_efficiency"] in ["Acceptable", "Poor"]:
                print(
                    "     - Review memory usage patterns and optimize data structures"
                )
                print("     - Implement memory cleanup strategies")

        print("\n" + "=" * 80)

    def cleanup(self):
        """Cleanup test environment."""
        if self.container:
            self.container.shutdown()

        # Remove temporary files
        try:
            os.unlink(self.temp_db.name)
            import shutil

            shutil.rmtree(self.temp_migrations_dir)
            shutil.rmtree(self.temp_domain_dir)
            shutil.rmtree(self.temp_vector_dir)
        except Exception:  # noqa: S110
            pass


def main():
    """Main entry point for load testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Load test the psychoanalyst application"
    )
    parser.add_argument(
        "--users", type=int, default=10, help="Number of concurrent users (default: 10)"
    )
    parser.add_argument(
        "--workers", type=int, default=5, help="Number of worker threads (default: 5)"
    )
    parser.add_argument(
        "--quick", action="store_true", help="Run quick test with fewer users"
    )

    args = parser.parse_args()

    if args.quick:
        num_users = 5
        num_workers = 3
    else:
        num_users = args.users
        num_workers = args.workers

    # Validate arguments
    if num_workers > num_users:
        num_workers = num_users

    print("Psychoanalyst Application Load Test")
    print("=" * 50)

    runner = LoadTestRunner(num_users=num_users, num_workers=num_workers)

    try:
        # Run load test
        analysis = runner.run_load_test()

        # Print results
        runner.print_report(analysis)

        # Return appropriate exit code
        if analysis["success"] and analysis["performance_assessment"]["overall"] in [
            "Excellent",
            "Good",
        ]:
            exit_code = 0
        else:
            exit_code = 1

        return exit_code

    except KeyboardInterrupt:
        print("\n\nLoad test interrupted by user")
        return 130
    except Exception as e:
        print(f"\n\nLoad test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        runner.cleanup()


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
