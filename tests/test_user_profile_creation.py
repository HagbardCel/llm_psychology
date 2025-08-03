#!/usr/bin/env python3
"""
Test script to verify user profile creation and database writing functionality.
This script tests the _collect_user_profile method directly.
"""

import sys
import os
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import Config
from services.db_service import DatabaseService
from services.llm_service import LLMService
from agents.intake_agent import IntakeAgent
from utils.data_models import UserProfile

class MockUI:
    """Mock UI class to simulate user input for testing."""
    
    def __init__(self):
        self.inputs = [
            "Test User",  # name
            "1990-01-01",  # birthdate
            "Software Engineer"  # profession
        ]
        self.input_index = 0
        self.displayed_messages = []
    
    async def display_system_status(self, message):
        print(f"SYSTEM: {message}")
        self.displayed_messages.append(("SYSTEM", message))
    
    async def get_user_input(self, prompt=None):
        if self.input_index < len(self.inputs):
            user_input = self.inputs[self.input_index]
            self.input_index += 1
            print(f"INPUT REQUESTED: {prompt}")
            print(f"USER INPUT: {user_input}")
            return user_input
        return ""

async def test_user_profile_creation():
    """Test the user profile creation functionality."""
    print("=== Testing User Profile Creation ===\n")
    
    # Initialize services
    db_service = DatabaseService(Config.DATABASE_PATH)
    
    # Create mock LLM service
    llm_service = Mock()
    llm_service.generate_response = Mock(return_value="Welcome message")
    
    # Create mock UI
    mock_ui = MockUI()
    
    # Create intake agent
    intake_agent = IntakeAgent(llm_service, db_service)
    
    try:
        # Test the _collect_user_profile method directly
        print("Calling _collect_user_profile method...")
        user_profile = await intake_agent._collect_user_profile(mock_ui)
        
        print(f"\nProfile created successfully!")
        print(f"User ID: {user_profile.user_id}")
        print(f"Name: {user_profile.name}")
        print(f"Birthdate: {user_profile.birthdate}")
        print(f"Profession: {user_profile.profession}")
        print(f"Created at: {user_profile.created_at}")
        
        # Verify the profile was saved to database
        print("\n=== Verifying Database Write ===")
        retrieved_profile = db_service.get_user_profile("default_user")
        
        if retrieved_profile:
            print("✅ Profile found in database!")
            print(f"   Name: {retrieved_profile.name}")
            print(f"   Birthdate: {retrieved_profile.birthdate}")
            print(f"   Profession: {retrieved_profile.profession}")
        else:
            print("❌ Profile NOT found in database!")
            
        # Check database directly
        print("\n=== Direct Database Verification ===")
        try:
            import sqlite3
            conn = sqlite3.connect(Config.DATABASE_PATH)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM user_profiles")
            count = cursor.fetchone()[0]
            print(f"Total profiles in database: {count}")
            
            if count > 0:
                cursor.execute("SELECT user_id, name, birthdate, profession FROM user_profiles")
                rows = cursor.fetchall()
                for row in rows:
                    print(f"   Profile - ID: {row[0]}, Name: {row[1]}, Birthdate: {row[2]}, Profession: {row[3]}")
            else:
                print("   No profiles found in database")
                
            conn.close()
        except Exception as e:
            print(f"Error checking database directly: {e}")
            
        print("\n=== Test Complete ===")
        
    except Exception as e:
        print(f"Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_user_profile_creation())
