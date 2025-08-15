#!/usr/bin/env python3
"""
Test script to verify the devcontainer setup is working correctly.
This script tests that the dedicated dev service is properly configured.
"""

import subprocess
import sys
import time

def test_dev_service():
    """Test that the dev service starts and stays running."""
    try:
        print("🧪 Testing devcontainer setup...")
        
        # Start the dev service
        print("🚀 Starting dev service...")
        result = subprocess.run(
            ["docker-compose", "up", "-d", "dev"],
            cwd=".",
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"❌ Failed to start dev service: {result.stderr}")
            return False
            
        print("✅ Dev service started successfully")
        
        # Wait a moment for the service to be fully ready
        time.sleep(2)
        
        # Test that we can execute commands in the dev container
        print("🔍 Testing Python execution in dev container...")
        result = subprocess.run(
            ["docker-compose", "exec", "dev", "python", "-c", "print('Hello from dev container!')"],
            cwd=".",
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"❌ Failed to execute command in dev container: {result.stderr}")
            return False
            
        print(f"✅ Command executed successfully: {result.stdout.strip()}")
        
        # Test that we can access the source code
        print("🔍 Testing source code access...")
        result = subprocess.run(
            ["docker-compose", "exec", "dev", "ls", "-la", "/app/src/main.py"],
            cwd=".",
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"❌ Failed to access source code: {result.stderr}")
            return False
            
        print("✅ Source code is accessible")
        
        # Clean up
        print("🧹 Cleaning up...")
        subprocess.run(
            ["docker-compose", "down"],
            cwd=".",
            capture_output=True
        )
        
        print("🎉 All tests passed! Devcontainer setup is working correctly.")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        # Clean up on error
        subprocess.run(
            ["docker-compose", "down"],
            cwd=".",
            capture_output=True
        )
        return False

if __name__ == "__main__":
    success = test_dev_service()
    sys.exit(0 if success else 1)
