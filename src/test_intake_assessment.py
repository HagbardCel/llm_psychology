#!/usr/bin/env python3
"""
Test script for the improved intake agent with time and topic tracking.
"""

import sys
import os
import asyncio

# Add the current directory to the Python path
sys.path.append(os.path.dirname(__file__))

from config import Config
from services.db_service import DatabaseService
from services.llm_service import LLMService
from agents.intake_agent import IntakeAgent
from ui.textual_ui import ConsoleUI

async def test_intake_assessment():
    """Test the intake assessment with time and topic tracking."""
    # Initialize UI
    ui = ConsoleUI()
    
    try:
        # Display test start message
        await ui.display_system_status("Testing Intake Assessment with Time and Topic Tracking")
        await ui.display_system_status(f"Session duration: {Config.SESSION_DURATION_MINUTES} minutes")
        await ui.display_system_status(f"Topics to cover: {', '.join(Config.INTAKE_TOPICS)}")
        await ui.display_system_status("")
        
        # Check if API key is provided
        if not Config.GOOGLE_API_KEY or Config.GOOGLE_API_KEY == "your_actual_google_gemini_api_key_here":
            await ui.display_system_status("ERROR: Please configure your Google Gemini API key in the .env file.")
            await ui.display_system_status("See README.md for setup instructions.")
            return
        
        # Initialize services
        db_service = DatabaseService(Config.DATABASE_PATH)
        llm_service = LLMService(Config.GOOGLE_API_KEY)
        
        # Create intake agent
        intake_agent = IntakeAgent(llm_service, db_service)
        
        # Conduct intake assessment
        await ui.display_system_status("Starting intake assessment...")
        session = await intake_agent.conduct_intake(ui)
        
        # Display session summary
        await ui.display_system_status("\n=== SESSION SUMMARY ===")
        await ui.display_system_status(f"Session ID: {session.session_id}")
        await ui.display_system_status(f"Total messages: {len(session.transcript)}")
        
        # Display topic coverage
        covered_topics = [topic.name for topic in session.topics if topic.status in ["covered", "partially_covered"]]
        pending_topics = [topic.name for topic in session.topics if topic.status == "pending"]
        
        await ui.display_system_status(f"\nTopics covered: {len(covered_topics)}")
        for topic in covered_topics:
            await ui.display_system_status(f"  ✓ {topic}")
        
        await ui.display_system_status(f"\nTopics pending: {len(pending_topics)}")
        for topic in pending_topics:
            await ui.display_system_status(f"  ○ {topic}")
        
        await ui.display_system_status("\nIntake assessment test completed successfully!")
        
    except Exception as e:
        await ui.display_system_status(f"Error during test: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_intake_assessment())
