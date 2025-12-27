#!/usr/bin/env python3
"""
Deployment Validation Script

This script validates that the psychoanalyst application is ready for deployment
by checking all critical components and dependencies.
"""

import os
import importlib
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Any
import json
import sys


class DeploymentValidator:
    """Validates deployment readiness of the psychoanalyst application."""

    def __init__(self):
        self.results = []
        self.errors = []
        self.warnings = []

    def log_result(
        self, test_name: str, status: str, message: str = "", details: Any = None
    ):
        """Log a test result."""
        self.results.append(
            {
                "test": test_name,
                "status": status,
                "message": message,
                "details": details,
            }
        )

        if status == "ERROR":
            self.errors.append(f"{test_name}: {message}")
        elif status == "WARNING":
            self.warnings.append(f"{test_name}: {message}")

    def validate_python_version(self) -> bool:
        """Validate Python version requirements."""
        test_name = "Python Version"

        try:
            version = sys.version_info
            if version.major == 3 and version.minor >= 11:
                self.log_result(
                    test_name,
                    "PASS",
                    f"Python {version.major}.{version.minor}.{version.micro}",
                )
                return True
            else:
                self.log_result(
                    test_name,
                    "ERROR",
                    f"Python 3.11+ required, found {version.major}.{version.minor}.{version.micro}",
                )
                return False
        except Exception as e:
            self.log_result(test_name, "ERROR", f"Failed to check Python version: {e}")
            return False

    def validate_core_imports(self) -> bool:
        """Validate that all core modules can be imported."""
        test_name = "Core Module Imports"

        required_modules = [
            "config",
            "container.service_container",
            "context.user_context",
            "models.data_models",
            "services.db_service",
            "services.llm_service",
            "services.rag_service",
            "services.migration_service",
            "agents.memory_agent",
            "agents.planning_agent",
            "agents.reflection_agent",
            "agents.intake_agent",
            "agents.assessment_agent",
            "agents.psychoanalyst_agent",
            "exceptions",
        ]

        failed_imports = []

        for module_name in required_modules:
            try:
                importlib.import_module(module_name)
            except Exception as e:
                failed_imports.append(f"{module_name}: {e}")

        if not failed_imports:
            self.log_result(
                test_name,
                "PASS",
                f"All {len(required_modules)} core modules imported successfully",
            )
            return True
        else:
            self.log_result(
                test_name, "ERROR", "Failed to import core modules", failed_imports
            )
            return False

    def validate_dependencies(self) -> bool:
        """Validate that all required dependencies are available."""
        test_name = "Required Dependencies"

        required_packages = [
            "sqlite3",
            "asyncio",
            "unittest.mock",
            "datetime",
            "logging",
            "pathlib",
            "threading",
            "queue",
            "statistics",
            "concurrent.futures",
        ]

        missing_packages = []

        for package in required_packages:
            try:
                importlib.import_module(package)
            except ImportError:
                missing_packages.append(package)

        if not missing_packages:
            self.log_result(
                test_name,
                "PASS",
                f"All {len(required_packages)} required packages available",
            )
            return True
        else:
            self.log_result(
                test_name, "ERROR", "Missing required packages", missing_packages
            )
            return False

    def validate_file_structure(self) -> bool:
        """Validate that required files and directories exist."""
        test_name = "File Structure"

        required_paths = [
            "src/",
            "src/main.py",
            "src/config.py",
            "src/container/",
            "src/container/service_container.py",
            "src/agents/",
            "src/services/",
            "src/models/",
            "src/context/",
            "src/exceptions.py",
            "migrations/",
            "data/",
            "tests/",
            "requirements.txt",
            "Makefile",
            "README.md",
        ]

        missing_paths = []

        for path in required_paths:
            if not Path(path).exists():
                missing_paths.append(path)

        if not missing_paths:
            self.log_result(
                test_name, "PASS", f"All {len(required_paths)} required paths exist"
            )
            return True
        else:
            self.log_result(
                test_name, "ERROR", "Missing required files/directories", missing_paths
            )
            return False

    def validate_configuration(self) -> bool:
        """Validate configuration setup."""
        test_name = "Configuration"

        try:
            from psychoanalyst_app.config import Config

            # Check critical configuration attributes
            required_config = [
                "APP_NAME",
                "VERSION",
                "DATABASE_PATH",
                "DOMAIN_KNOWLEDGE_PATH",
                "VECTOR_DB_PATH",
            ]

            missing_config = []
            for attr in required_config:
                if not hasattr(Config, attr):
                    missing_config.append(attr)

            if missing_config:
                self.log_result(
                    test_name,
                    "ERROR",
                    "Missing configuration attributes",
                    missing_config,
                )
                return False

            # Check API key configuration (should be placeholder in repo)
            if hasattr(Config, "GOOGLE_API_KEY"):
                if Config.GOOGLE_API_KEY == "your_actual_google_gemini_api_key_here":
                    self.log_result(
                        test_name,
                        "WARNING",
                        "API key not configured (expected for repository)",
                    )
                else:
                    self.log_result(
                        test_name, "PASS", "API key appears to be configured"
                    )

            self.log_result(test_name, "PASS", "Configuration structure is valid")
            return True

        except Exception as e:
            self.log_result(
                test_name, "ERROR", f"Failed to validate configuration: {e}"
            )
            return False

    def validate_service_container(self) -> bool:
        """Validate ServiceContainer functionality."""
        test_name = "ServiceContainer"

        try:
            from psychoanalyst_app.container.service_container import ServiceContainer
            from unittest.mock import Mock
            import tempfile

            # Create test configuration
            class TestConfig:
                DATABASE_PATH = tempfile.mktemp(suffix=".db")
                MIGRATIONS_DIR = tempfile.mkdtemp()
                GOOGLE_API_KEY = "test_key"
                MODEL_NAME = "test_model"
                DOMAIN_KNOWLEDGE_PATH = tempfile.mkdtemp()
                VECTOR_DB_PATH = tempfile.mkdtemp()
                DATABASE_POOL_SIZE = 5

            # Test container creation
            container = ServiceContainer(TestConfig)

            # Test service registration
            required_services = [
                "db_service",
                "llm_service",
                "rag_service",
                "migration_service",
            ]
            for service in required_services:
                if not container.is_registered(service):
                    self.log_result(
                        test_name, "ERROR", f"Service {service} not registered"
                    )
                    return False

            # Test agent creation
            from psychoanalyst_app.context.user_context import UserContext

            user_context = UserContext("test_user")

            # Mock services to avoid external dependencies
            mock_llm = Mock()
            mock_rag = Mock()
            container.register("llm_service", mock_llm)
            container.register("rag_service", mock_rag)

            # Test agent creation methods
            agent_methods = [
                "create_intake_agent",
                "create_assessment_agent",
                "create_psychoanalyst_agent",
                "create_reflection_agent",
                "create_memory_agent",
                "create_planning_agent",
            ]

            for method_name in agent_methods:
                try:
                    method = getattr(container, method_name)
                    agent = method(user_context)
                    if agent is None:
                        self.log_result(
                            test_name, "ERROR", f"{method_name} returned None"
                        )
                        return False
                except Exception as e:
                    self.log_result(test_name, "ERROR", f"{method_name} failed: {e}")
                    return False

            # Test health check
            health = container.health_check()
            if "status" not in health:
                self.log_result(test_name, "ERROR", "Health check missing status")
                return False

            # Cleanup
            container.shutdown()

            self.log_result(test_name, "PASS", "ServiceContainer fully functional")
            return True

        except Exception as e:
            self.log_result(
                test_name, "ERROR", f"ServiceContainer validation failed: {e}"
            )
            return False

    def validate_database_setup(self) -> bool:
        """Validate database functionality."""
        test_name = "Database Setup"

        try:
            from psychoanalyst_app.services.db_service import DatabaseService
            import tempfile

            # Create temporary database
            temp_db = tempfile.mktemp(suffix=".db")

            # Test database service creation
            db_service = DatabaseService(temp_db)

            # Test basic operations
            from psychoanalyst_app.models.data_models import UserProfile
            from datetime import datetime

            test_profile = UserProfile(
                user_id="validation_test_user",
                name="Test User",
                data_of_birth="1990-01-01",
                profession="Validator",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )

            # Test save and retrieve
            success = db_service.save_user_profile(test_profile)
            if not success:
                self.log_result(test_name, "ERROR", "Failed to save user profile")
                return False

            retrieved_profile = db_service.get_user_profile("validation_test_user")
            if retrieved_profile is None:
                self.log_result(test_name, "ERROR", "Failed to retrieve user profile")
                return False

            # Test user status
            status = db_service.get_user_status("validation_test_user")
            if status is None:
                self.log_result(test_name, "ERROR", "Failed to get user status")
                return False

            # Cleanup
            os.unlink(temp_db)

            self.log_result(test_name, "PASS", "Database operations working correctly")
            return True

        except Exception as e:
            self.log_result(test_name, "ERROR", f"Database validation failed: {e}")
            return False

    def validate_migration_system(self) -> bool:
        """Validate migration system functionality."""
        test_name = "Migration System"

        try:
            from psychoanalyst_app.services.migration_service import MigrationService
            from psychoanalyst_app.services.db_service import DatabaseService
            import tempfile
            import shutil

            # Setup test environment
            temp_db = tempfile.mktemp(suffix=".db")
            temp_migrations_dir = tempfile.mkdtemp()

            # Create test migration
            migration_content = """
-- Test migration for validation
CREATE TABLE IF NOT EXISTS validation_test (
    id INTEGER PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

SELECT 'Validation migration completed' as result;
"""
            migration_file = os.path.join(
                temp_migrations_dir, "001_validation_test.sql"
            )
            with open(migration_file, "w") as f:
                f.write(migration_content)

            # Test migration service
            db_service = DatabaseService(temp_db)
            migration_service = MigrationService(db_service, temp_migrations_dir)

            # Test migration status
            status = migration_service.get_migration_status()
            if status["total_migrations"] != 1:
                self.log_result(
                    test_name,
                    "ERROR",
                    f"Expected 1 migration, found {status['total_migrations']}",
                )
                return False

            # Test migration execution
            applied = migration_service.run_migrations()
            if len(applied) != 1:
                self.log_result(
                    test_name,
                    "ERROR",
                    f"Expected 1 applied migration, got {len(applied)}",
                )
                return False

            # Verify migration was applied
            status_after = migration_service.get_migration_status()
            if status_after["applied_count"] != 1:
                self.log_result(test_name, "ERROR", "Migration not marked as applied")
                return False

            # Cleanup
            os.unlink(temp_db)
            shutil.rmtree(temp_migrations_dir)

            self.log_result(test_name, "PASS", "Migration system working correctly")
            return True

        except Exception as e:
            self.log_result(
                test_name, "ERROR", f"Migration system validation failed: {e}"
            )
            return False

    def validate_agent_coordination(self) -> bool:
        """Validate that agent coordination works correctly."""
        test_name = "Agent Coordination"

        try:
            from psychoanalyst_app.container.service_container import ServiceContainer
            from psychoanalyst_app.context.user_context import UserContext
            from psychoanalyst_app.models.data_models import Session, Message
            from datetime import datetime
            from unittest.mock import Mock
            import tempfile

            # Setup container with mocks
            class TestConfig:
                DATABASE_PATH = tempfile.mktemp(suffix=".db")
                MIGRATIONS_DIR = tempfile.mkdtemp()
                GOOGLE_API_KEY = "test_key"
                MODEL_NAME = "test_model"
                DOMAIN_KNOWLEDGE_PATH = tempfile.mkdtemp()
                VECTOR_DB_PATH = tempfile.mkdtemp()
                DATABASE_POOL_SIZE = 5

            container = ServiceContainer(TestConfig)

            # Mock services
            mock_llm = Mock()
            mock_llm.generate_response.return_value = "Test response"
            mock_llm.generate_structured_response.return_value = {
                "raw_response": '{"key_themes": ["test"], "emotional_state": "neutral", "insights": ["test"], "progress_indicators": ["test"]}'
            }
            container.register("llm_service", mock_llm)

            mock_rag = Mock()
            mock_rag.retrieve_relevant_knowledge.return_value = [
                {"content": "Test knowledge", "source": "test.md"}
            ]
            container.register("rag_service", mock_rag)

            # Test agent coordination
            user_context = UserContext("coordination_test_user")

            # Create test session
            test_session = Session(
                session_id="coordination_test_session",
                user_id="coordination_test_user",
                timestamp=datetime.now(),
                transcript=[
                    Message(
                        role="user",
                        content="I need help with stress",
                        timestamp=datetime.now(),
                    )
                ],
            )

            # Test MemoryAgent
            memory_agent = container.create_memory_agent(user_context)
            session_context = memory_agent.analyze_session_context(test_session)
            if session_context is None:
                self.log_result(
                    test_name, "ERROR", "MemoryAgent failed to analyze session"
                )
                return False

            # Test PlanningAgent
            planning_agent = container.create_planning_agent(user_context)
            therapy_plan = planning_agent.create_initial_plan(test_session, "cbt")
            if therapy_plan is None:
                self.log_result(
                    test_name, "ERROR", "PlanningAgent failed to create plan"
                )
                return False

            # Test ReflectionAgent coordination
            reflection_agent = container.create_reflection_agent(user_context)
            comprehensive_reflection = (
                reflection_agent.generate_comprehensive_reflection(
                    test_session, therapy_plan
                )
            )
            if comprehensive_reflection is None:
                self.log_result(
                    test_name, "ERROR", "ReflectionAgent failed to generate reflection"
                )
                return False

            # Verify coordination
            if "agents_used" not in comprehensive_reflection:
                self.log_result(
                    test_name, "ERROR", "Reflection missing agents_used field"
                )
                return False

            expected_agents = ["MemoryAgent", "PlanningAgent", "ReflectionAgent"]
            agents_used = comprehensive_reflection["agents_used"]
            for agent in expected_agents:
                if agent not in agents_used:
                    self.log_result(
                        test_name, "ERROR", f"Missing {agent} in coordination"
                    )
                    return False

            # Cleanup
            container.shutdown()

            self.log_result(test_name, "PASS", "Agent coordination working correctly")
            return True

        except Exception as e:
            self.log_result(
                test_name, "ERROR", f"Agent coordination validation failed: {e}"
            )
            return False

    def validate_error_handling(self) -> bool:
        """Validate error handling mechanisms."""
        test_name = "Error Handling"

        try:
            # Test exception imports
            from psychoanalyst_app.exceptions import (
                PsychoanalystError,
                DatabaseError,
                AgentError,
                LLMServiceError,
                RAGServiceError,
                ConfigurationError,
                MemoryError,
                PlanningError,
                ReflectionError,
            )

            # Test exception hierarchy
            test_exceptions = [
                (DatabaseError, PsychoanalystError),
                (AgentError, PsychoanalystError),
                (MemoryError, AgentError),
                (PlanningError, AgentError),
                (ReflectionError, AgentError),
            ]

            for child_exc, parent_exc in test_exceptions:
                if not issubclass(child_exc, parent_exc):
                    self.log_result(
                        test_name,
                        "ERROR",
                        f"{child_exc.__name__} not subclass of {parent_exc.__name__}",
                    )
                    return False

            # Test error handling function
            from psychoanalyst_app.main import handle_workflow_error
            from psychoanalyst_app.ui.textual_ui import ConsoleUI
            from unittest.mock import AsyncMock

            # This should not raise an exception
            mock_ui = AsyncMock()

            # Test different error types
            test_errors = [
                AgentError("Test agent error"),
                DatabaseError("Test database error"),
                LLMServiceError("Test LLM error"),
                Exception("Test generic error"),
            ]

            for error in test_errors:
                try:
                    # This is an async function, but we're just testing it doesn't crash
                    import asyncio

                    asyncio.run(handle_workflow_error(mock_ui, error, "test_workflow"))
                except Exception as e:
                    self.log_result(
                        test_name,
                        "ERROR",
                        f"Error handler failed for {type(error).__name__}: {e}",
                    )
                    return False

            self.log_result(
                test_name, "PASS", "Error handling mechanisms working correctly"
            )
            return True

        except Exception as e:
            self.log_result(
                test_name, "ERROR", f"Error handling validation failed: {e}"
            )
            return False

    def run_all_validations(self) -> Dict[str, Any]:
        """Run all validation tests."""
        print("🔍 Running Deployment Validation Tests...")
        print("=" * 50)

        validations = [
            self.validate_python_version,
            self.validate_core_imports,
            self.validate_dependencies,
            self.validate_file_structure,
            self.validate_configuration,
            self.validate_service_container,
            self.validate_database_setup,
            self.validate_migration_system,
            self.validate_agent_coordination,
            self.validate_error_handling,
        ]

        passed = 0
        failed = 0

        for validation in validations:
            try:
                if validation():
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                self.log_result(
                    validation.__name__, "ERROR", f"Validation crashed: {e}"
                )
                failed += 1

        # Generate summary
        summary = {
            "total_tests": len(validations),
            "passed": passed,
            "failed": failed,
            "warnings": len(self.warnings),
            "errors": len(self.errors),
            "overall_status": "PASS" if failed == 0 else "FAIL",
            "deployment_ready": failed == 0 and len(self.errors) == 0,
        }

        return summary

    def print_report(self, summary: Dict[str, Any]):
        """Print validation report."""
        print("\n" + "=" * 60)
        print("📋 DEPLOYMENT VALIDATION REPORT")
        print("=" * 60)

        # Test results
        print(f"\n📊 TEST SUMMARY")
        print(f"  Total Tests: {summary['total_tests']}")
        print(f"  Passed: {summary['passed']}")
        print(f"  Failed: {summary['failed']}")
        print(f"  Warnings: {summary['warnings']}")
        print(f"  Errors: {summary['errors']}")

        # Detailed results
        print(f"\n📝 DETAILED RESULTS")
        for result in self.results:
            status_emoji = {"PASS": "✅", "WARNING": "⚠️", "ERROR": "❌"}.get(
                result["status"], "❓"
            )

            print(f"  {status_emoji} {result['test']}: {result['status']}")
            if result["message"]:
                print(f"      {result['message']}")

        # Warnings
        if self.warnings:
            print(f"\n⚠️  WARNINGS")
            for warning in self.warnings:
                print(f"  - {warning}")

        # Errors
        if self.errors:
            print(f"\n❌ ERRORS")
            for error in self.errors:
                print(f"  - {error}")

        # Deployment status
        print(f"\n🚀 DEPLOYMENT STATUS")
        if summary["deployment_ready"]:
            print("  ✅ READY FOR DEPLOYMENT")
            print("     All critical tests passed. System is production-ready.")
        else:
            print("  ❌ NOT READY FOR DEPLOYMENT")
            print("     Critical issues must be resolved before deployment.")

            if self.errors:
                print("\n   Action Items:")
                print("   - Resolve all ERROR conditions")
                print("   - Address any WARNING conditions")
                print("   - Re-run validation after fixes")

        print("\n" + "=" * 60)

    def generate_json_report(self, summary: Dict[str, Any]) -> str:
        """Generate JSON report for automated processing."""
        report = {
            "validation_timestamp": datetime.now().isoformat(),
            "summary": summary,
            "results": self.results,
            "warnings": self.warnings,
            "errors": self.errors,
        }

        return json.dumps(report, indent=2)


def main():
    """Main validation function."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate deployment readiness")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--output", type=str, help="Save report to file")
    args = parser.parse_args()

    validator = DeploymentValidator()
    summary = validator.run_all_validations()

    if args.json:
        report = validator.generate_json_report(summary)
        if args.output:
            with open(args.output, "w") as f:
                f.write(report)
            print(f"JSON report saved to {args.output}")
        else:
            print(report)
    else:
        validator.print_report(summary)

        if args.output:
            with open(args.output, "w") as f:
                f.write("Deployment Validation Report\n")
                f.write("=" * 30 + "\n\n")
                for result in validator.results:
                    f.write(f"{result['test']}: {result['status']}\n")
                    if result["message"]:
                        f.write(f"  {result['message']}\n")
                f.write(f"\nOverall Status: {summary['overall_status']}\n")
                f.write(f"Deployment Ready: {summary['deployment_ready']}\n")
            print(f"Report saved to {args.output}")

    # Exit with appropriate code
    exit_code = 0 if summary["deployment_ready"] else 1
    return exit_code


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
