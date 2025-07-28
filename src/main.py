#!/usr/bin/env python3
"""
Main entry point for the Virtual LLM-Driven Psychoanalyst App.
"""

import sys
import os
import asyncio

# Add the src directory to the Python path
sys.path.append(os.path.dirname(__file__))

from config import Config
from services.db_service import DatabaseService
from services.rag_service import RAGService
from services.llm_service import LLMService
from agents.intake_agent import IntakeAgent
from agents.reflection_agent import ReflectionAgent
from agents.psychoanalyst_agent import PsychoanalystAgent
from ui.textual_ui import ConsoleUI

async def main():
    """Main application entry point."""
    # Initialize UI
    ui = ConsoleUI()
    
    try:
        # Display startup message
        await ui.display_system_status(f"Starting {Config.APP_NAME} v{Config.VERSION}")
        
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
        
        # Conduct a single session with configurable duration
        session_transcript = await psychoanalyst_agent.conduct_session(initial_plan, Config.SESSION_DURATION_MINUTES, ui)
        
        # Reflection agent updates plan
        reflection_agent.update_plan(session_transcript, initial_plan)
        
        await ui.display_system_status("Thank you for using the Virtual LLM-Driven Psychoanalyst. Goodbye!")
    except Exception as e:
        await ui.display_system_status(f"Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
