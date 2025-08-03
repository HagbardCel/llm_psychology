#!/usr/bin/env python3
"""
Test script to run a short session to verify database writing works.
This script uses the test configuration and can clear the test database.
"""

import sys
import os
import asyncio
import argparse

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set test environment
os.environ['APP_ENV'] = 'testing'

from config import Config
from services.db_service import DatabaseService
from services.rag_service import RAGService
from services.llm_service import LLMService
from agents.intake_agent import IntakeAgent
from agents.assessment_agent import AssessmentAgent  # Add this import
from agents.reflection_agent import ReflectionAgent
from agents.psychoanalyst_agent import PsychoanalystAgent
from ui.textual_ui import ConsoleUI

async def test_short_session(clear_database: bool = True):
    """Test a short session using test configuration."""
    print("Starting test session...")
    
    # Initialize UI
    ui = ConsoleUI()
    
    try:
        # Display startup message
        await ui.display_system_status(f"Starting {Config.APP_NAME} v{Config.VERSION}")
        await ui.display_system_status("Running test session")
        await ui.display_system_status(f"Using test database: {Config.DATABASE_PATH}")
        await ui.display_system_status(f"Session duration: {Config.SESSION_DURATION_MINUTES} minutes")
        
        # Check if API key is provided
        if not Config.GOOGLE_API_KEY or Config.GOOGLE_API_KEY == "your_actual_google_gemini_api_key_here":
            await ui.display_system_status("ERROR: Please configure your Google Gemini API key in the .env file.")
            await ui.display_system_status("See README.md for setup instructions.")
            return
        
        # Initialize services
        db_service = DatabaseService(Config.DATABASE_PATH)
        rag_service = RAGService(Config.DOMAIN_KNOWLEDGE_PATH, Config.VECTOR_DB_PATH)
        llm_service = LLMService(Config.GOOGLE_API_KEY)
        
        # Clear database if requested
        if clear_database:
            await ui.display_system_status("Clearing test database...")
            if db_service.clear_all_data():
                await ui.display_system_status("Test database cleared successfully.")
            else:
                await ui.display_system_status("Warning: Failed to clear test database.")
        
        # Check if therapy plan exists
        latest_plan = db_service.get_latest_therapy_plan()
        
        if latest_plan is None:
            # First-time run: Intake workflow
            await ui.display_system_status("No existing therapy plan found. Starting intake process...")
            intake_agent = IntakeAgent(llm_service, db_service)
            intake_session = await intake_agent.conduct_intake(ui)
            
            # Assessment phase: Recommend therapy styles and create initial plan
            await ui.display_system_status("Assessing your needs and recommending therapy styles...")
            assessment_agent = AssessmentAgent(llm_service, db_service, rag_service)  # Pass RAG service
            recommendations = await assessment_agent.conduct_assessment(intake_session)
            
            # Let user select therapy style from recommendations
            await ui.display_system_status("Assessing your needs and recommending therapy styles...")
            selected_style = await ui.present_therapy_style_selection(recommendations)
            await ui.display_system_status(f"Selected therapy style: {selected_style}")
            
            # Create initial plan with selected style
            initial_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
            await ui.display_system_status(f"Initial {selected_style.upper()} therapy plan created.")
        else:
            # Load existing plan
            await ui.display_system_status("Existing therapy plan found. Loading...")
            initial_plan = latest_plan
        
        # Initialize agents
        psychoanalyst_agent = PsychoanalystAgent(llm_service, db_service, rag_service)
        reflection_agent = ReflectionAgent(llm_service, db_service, rag_service)
        
        # Conduct session with test duration
        await ui.display_system_status(f"Starting {Config.SESSION_DURATION_MINUTES}-minute therapy session...")
        session_transcript = await psychoanalyst_agent.conduct_session(initial_plan, Config.SESSION_DURATION_MINUTES, ui)
        
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

def main():
    """Main entry point with command line arguments."""
    parser = argparse.ArgumentParser(description='Run a short test session.')
    parser.add_argument('--no-clear', action='store_true', 
                       help='Do not clear the test database before running')
    
    args = parser.parse_args()
    
    # Run the test
    asyncio.run(test_short_session(clear_database=not args.no_clear))

if __name__ == "__main__":
    main()
