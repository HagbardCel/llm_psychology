#!/usr/bin/env python3
"""
Test script to verify devcontainer functionality.
This script can be used to test that the devcontainer is working correctly.
"""

import sys
import os

def test_basic_functionality():
    """Test basic Python functionality and imports."""
    try:
        # Test basic imports
        import json
        import sqlite3
        from pathlib import Path
        
        # Test that we can access the src directory
        src_path = Path(__file__).parent.parent / "src"
        if not src_path.exists():
            print("❌ ERROR: src directory not found")
            return False
            
        # Test that we can import our own modules
        try:
            from src.config import Config
            print("✅ Successfully imported src.config")
        except ImportError as e:
            print(f"⚠️  Warning: Could not import src.config: {e}")
            
        # Test basic Python functionality
        test_dict = {"status": "ok", "message": "Devcontainer is working"}
        json_str = json.dumps(test_dict)
        parsed_dict = json.loads(json_str)
        
        if parsed_dict["status"] == "ok":
            print("✅ Basic Python functionality working")
            return True
        else:
            print("❌ ERROR: Basic Python functionality failed")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def test_file_permissions():
    """Test file permissions and access."""
    try:
        # Test writing to a temporary file
        test_file = "/tmp/devcontainer_test.txt"
        with open(test_file, "w") as f:
            f.write("Devcontainer test successful")
        
        # Test reading the file
        with open(test_file, "r") as f:
            content = f.read()
            
        # Clean up
        os.remove(test_file)
        
        if content == "Devcontainer test successful":
            print("✅ File permissions and access working")
            return True
        else:
            print("❌ ERROR: File permissions test failed")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: File permissions test failed: {e}")
        return False

def test_dedicated_dev_service():
    """Test that the dedicated dev service is properly configured."""
    try:
        import subprocess
        
        print("🔍 Testing dedicated dev service configuration...")
        
        # Check that the dev service exists in docker-compose.yml
        docker_compose_path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")
        with open(docker_compose_path, "r") as f:
            content = f.read()
            
        if "dev:" not in content:
            print("❌ ERROR: 'dev' service not found in docker-compose.yml")
            return False
            
        if "command: tail -f /dev/null" not in content:
            print("❌ ERROR: dev service doesn't have the correct command to keep it running")
            return False
            
        print("✅ Dedicated dev service is properly configured")
        return True
        
    except Exception as e:
        print(f"❌ ERROR: Dedicated dev service test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🧪 Running devcontainer tests...")
    print()
    
    tests = [
        test_basic_functionality,
        test_file_permissions,
        test_dedicated_dev_service,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ ERROR: {test.__name__} failed with exception: {e}")
            failed += 1
        print()
    
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! Devcontainer is working correctly.")
        return 0
    else:
        print("💥 Some tests failed. Please check the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
