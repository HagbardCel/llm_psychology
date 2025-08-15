#!/usr/bin/env python3
"""
Test runner script for the psychoanalyst application.
This script provides convenient ways to run different types of tests.
"""

import subprocess
import sys
import argparse
from pathlib import Path

def run_command(command, cwd=None):
    """Run a command and return the result."""
    try:
        result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def run_all_tests():
    """Run all tests."""
    print("Running all tests...")
    success, stdout, stderr = run_command("pytest -v")
    print(stdout)
    if stderr:
        print("Errors:", stderr)
    return success

def run_unit_tests():
    """Run unit tests only."""
    print("Running unit tests...")
    success, stdout, stderr = run_command("pytest -v -m unit")
    print(stdout)
    if stderr:
        print("Errors:", stderr)
    return success

def run_integration_tests():
    """Run integration tests only."""
    print("Running integration tests...")
    success, stdout, stderr = run_command("pytest -v -m integration")
    print(stdout)
    if stderr:
        print("Errors:", stderr)
    return success

def run_tests_by_service(service_name):
    """Run tests for a specific service."""
    print(f"Running tests for service: {service_name}")
    success, stdout, stderr = run_command(f"pytest -v -k {service_name}")
    print(stdout)
    if stderr:
        print("Errors:", stderr)
    return success

def run_tests_by_agent(agent_name):
    """Run tests for a specific agent."""
    print(f"Running tests for agent: {agent_name}")
    success, stdout, stderr = run_command(f"pytest -v -k {agent_name}")
    print(stdout)
    if stderr:
        print("Errors:", stderr)
    return success

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Run psychoanalyst tests')
    parser.add_argument('--all', action='store_true', help='Run all tests')
    parser.add_argument('--unit', action='store_true', help='Run unit tests only')
    parser.add_argument('--integration', action='store_true', help='Run integration tests only')
    parser.add_argument('--service', type=str, help='Run tests for specific service (db, llm, rag, style)')
    parser.add_argument('--agent', type=str, help='Run tests for specific agent (intake, assessment, psychoanalyst, reflection)')
    
    args = parser.parse_args()
    
    # If no arguments provided, show help
    if not any([args.all, args.unit, args.integration, args.service, args.agent]):
        parser.print_help()
        return 0
    
    success = True
    
    if args.all:
        success &= run_all_tests()
    
    if args.unit:
        success &= run_unit_tests()
    
    if args.integration:
        success &= run_integration_tests()
    
    if args.service:
        success &= run_tests_by_service(args.service)
    
    if args.agent:
        success &= run_tests_by_agent(args.agent)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
