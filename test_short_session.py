#!/usr/bin/env python3
"""
Test script to run a short 1-minute session to verify database writing works.
"""

import sys
import os
import asyncio

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from config import Config
from services.db_service import DatabaseService
from services.rag_service import RAGService
from services.llm_service import LLMService
from agents.intake_agent import IntakeAgent
from agents.reflection_agent import ReflectionAgent
from agents.psychoanalyst_agent import PsychoanalystAgent
from ui.textual_ui import ConsoleUI

async def test_short_session():
    """Test a short 1-minute session."""
    print("Starting 1-minute test session...")
    
    # Override session duration to 1 minute
    Config.SESSION_DURATION_MINUTES = 1
    
    # Initialize UI
    ui = ConsoleUI()
    
    try:
        # Display startup message
        await ui.display_system_status(f"Starting {Config.APP_NAME} v{Config.VERSION}")
        await ui.display_system_status("Running 1-minute test session")
        
        # Check if API key is provided
        if not Config.GOOGLE_API_KEY or Config.GOOGLE_API_KEY == "your_actual_google_gemini_api_key_here":
            await ui.display_system_status("ERROR: Please configure your Google Gemini API key in the .env file.")
            await ui.display_system_status("See README.md for setup instructions.")
            return
        
        # Initialize services
        db_service = DatabaseService(Config.DATABASE_PATH)
        rag_service = RAGService(Config.DOMAIN_KNOWLEDGE_PATH, Config.VECTOR_DB_PATH)
        llm_service = LLMService(Config.GOOGLE_API_KEY)
        
        # Check if therapy plan exists
        latest_plan = db_service.get_latest_therapy_plan()
        
        if latest_plan is None:
            # First-time run: Intake workflow
            await ui.display_system_status("No existing therapy plan found. Starting intake process...")
            intake_agent = IntakeAgent(llm_service, db_service)
            intake_session = await intake_agent.conduct_intake(ui)
            
            # Reflection agent creates initial plan
            reflection_agent = ReflectionAgent(llm_service, db_service, rag_service)
            initial_plan = reflection_agent.create_initial_plan(intake_session)
            await ui.display_system_status("Initial therapy plan created.")
        else:
            # Load existing plan
            await ui.display_system_status("Existing therapy plan found. Loading...")
            initial_plan = latest_plan
        
        # Initialize agents
        psychoanalyst_agent = PsychoanalystAgent(llm_service, db_service, rag_service)
        reflection_agent = ReflectionAgent(llm_service, db_service, rag_service)
        
        # Conduct a 1-minute session
        await ui.display_system_status("Starting 1-minute therapy session...")
        session_transcript = await psychoanalyst_agent.conduct_session(initial_plan, 1, ui)
        
        # Reflection agent updates plan
        reflection_agent.update_plan(session_transcript, initial_plan)
        
        await ui.display_system_status("Test session completed successfully!")
        
        # Verify data was saved
        all_sessions = db_service.get_all_sessions_for_user("default_user")
        await ui.display_system_status(f"Total sessions for user: {len(all_sessions)}")
        
    except Exception as e:
        await ui.display_system_status(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_short_session())
