#!/usr/bin/env python3
"""
Test script to verify database writing functionality.
"""

import sys
import os
import sqlite3
from datetime import datetime

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from utils.data_models import Session, Message, TherapyPlan, UserProfile
from services.db_service import DatabaseService

def test_database_writing():
    """Test that database writing works correctly."""
    print("Testing database writing functionality...")
    
    # Initialize database service
    db_service = DatabaseService("src/data/psychoanalyst.db")
    
    # Test 1: Save and retrieve user profile
    print("\n1. Testing user profile saving...")
    user_profile = UserProfile(
        user_id="test_user_123",
        name="Test User",
        birthdate=datetime.now(),
        profession="Software Engineer",
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    
    result = db_service.save_user_profile(user_profile)
    print(f"   Save result: {result}")
    
    retrieved_profile = db_service.get_user_profile("test_user_123")
    if retrieved_profile:
        print(f"   Retrieved profile: {retrieved_profile.name}")
    else:
        print("   Failed to retrieve profile")
    
    # Test 2: Save and retrieve session
    print("\n2. Testing session saving...")
    session = Session(
        session_id="test_session_123",
        user_id="test_user_123",
        timestamp=datetime.now(),
        transcript=[
            Message(role="user", content="Hello, I'd like to discuss my thoughts.", timestamp=datetime.now()),
            Message(role="assistant", content="Hello! I'm here to help you explore your thoughts and feelings.", timestamp=datetime.now()),
            Message(role="user", content="I've been feeling stressed about work lately.", timestamp=datetime.now()),
            Message(role="assistant", content="I understand. Work stress can be challenging. Can you tell me more about what's been bothering you?", timestamp=datetime.now())
        ]
    )
    
    result = db_service.save_session(session)
    print(f"   Save result: {result}")
    
    retrieved_session = db_service.get_session("test_session_123")
    if retrieved_session:
        print(f"   Retrieved session with {len(retrieved_session.transcript)} messages")
        print(f"   First message: {retrieved_session.transcript[0].content[:50]}...")
    else:
        print("   Failed to retrieve session")
    
    # Test 3: Save and retrieve therapy plan
    print("\n3. Testing therapy plan saving...")
    therapy_plan = TherapyPlan(
        plan_id="test_plan_123",
        user_id="test_user_123",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        plan_details={
            "focus": "Work-related stress and anxiety management",
            "goals": "Develop coping strategies and identify stress triggers",
            "techniques": "Cognitive restructuring and mindfulness exercises",
            "themes": "Work stress, anxiety, coping mechanisms"
        },
        version=1
    )
    
    result = db_service.save_therapy_plan(therapy_plan)
    print(f"   Save result: {result}")
    
    retrieved_plan = db_service.get_latest_therapy_plan("test_user_123")
    if retrieved_plan:
        print(f"   Retrieved plan version {retrieved_plan.version}")
        print(f"   Plan focus: {retrieved_plan.plan_details.get('focus', 'N/A')}")
    else:
        print("   Failed to retrieve therapy plan")
    
    # Test 4: Get all sessions for user
    print("\n4. Testing retrieval of all sessions...")
    all_sessions = db_service.get_all_sessions_for_user("test_user_123")
    print(f"   Found {len(all_sessions)} sessions for user")
    
    print("\n=== Database Writing Test Complete ===")
    
    # Show final database contents
    print("\nFinal database contents:")
    try:
        conn = sqlite3.connect("src/data/psychoanalyst.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM sessions")
        session_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM therapy_plans")
        plan_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_profiles")
        profile_count = cursor.fetchone()[0]
        
        print(f"   Sessions: {session_count}")
        print(f"   Therapy Plans: {plan_count}")
        print(f"   User Profiles: {profile_count}")
        
        conn.close()
    except Exception as e:
        print(f"   Error checking final counts: {e}")

if __name__ == "__main__":
    test_database_writing()
