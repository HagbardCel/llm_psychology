#!/usr/bin/env python3
"""
Main entry point for the Virtual LLM-Driven Psychoanalyst application.
Implements resumable sessions functionality.
"""

import sys
import os
import asyncio

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from config import Config
from services.db_service import DatabaseService, UserStatus
from services.rag_service import RAGService
from services.llm_service import LLMService
from agents.intake_agent import IntakeAgent
from agents.assessment_agent import AssessmentAgent
from agents.reflection_agent import ReflectionAgent
from agents.psychoanalyst_agent import PsychoanalystAgent
from ui.textual_ui import ConsoleUI

async def main():
    """Main application entry point with resumable sessions."""
    print(f"Starting {Config.APP_NAME} v{Config.VERSION}")
    
    # Initialize UI
    ui = ConsoleUI()
    
    try:
        # Display startup message
        await ui.display_system_status(f"Welcome to {Config.APP_NAME} v{Config.VERSION}")
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
        
        # Check user status to determine workflow
        user_status = db_service.get_user_status()
        await ui.display_system_status(f"User status: {user_status}")
        
        therapy_plan = None
        
        if user_status == UserStatus.PLAN_COMPLETE:
            # Resume from existing therapy plan
            await ui.display_system_status("Resuming from existing therapy plan...")
            therapy_plan = db_service.get_latest_therapy_plan()
            
            # Use reflection agent to provide context to psychoanalyst
            reflection_agent = ReflectionAgent(llm_service, db_service, rag_service)
            psychoanalyst_agent = PsychoanalystAgent(llm_service, db_service, rag_service)
            
            # Conduct session with existing plan
            await ui.display_system_status("Starting therapy session with existing plan...")
            session = await psychoanalyst_agent.conduct_session(therapy_plan, Config.SESSION_DURATION_MINUTES, ui)
            
            # Update therapy plan based on session
            updated_plan = reflection_agent.update_plan(session, therapy_plan)
            await ui.display_system_status("Therapy plan updated based on session.")
            
        elif user_status == UserStatus.INTAKE_COMPLETE:
            # Resume from completed intake, need assessment
            await ui.display_system_status("Resuming from completed intake. Starting assessment...")
            
            # Get the latest session (intake session)
            all_sessions = db_service.get_all_sessions_for_user()
            intake_session = all_sessions[-1] if all_sessions else None
            
            if intake_session:
                # Conduct assessment to recommend therapy styles
                assessment_agent = AssessmentAgent(llm_service, db_service, rag_service)
                recommendations = await assessment_agent.conduct_assessment(intake_session)
                
                # Let user select therapy style from recommendations
                await ui.display_system_status("Assessing your needs and recommending therapy styles...")
                selected_style = await ui.present_therapy_style_selection(recommendations)
                await ui.display_system_status(f"Selected therapy style: {selected_style}")
                
                # Create initial plan with selected style
                therapy_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
                await ui.display_system_status(f"Initial {selected_style.upper()} therapy plan created.")
                
                # Now conduct the therapy session
                psychoanalyst_agent = PsychoanalystAgent(llm_service, db_service, rag_service)
                session = await psychoanalyst_agent.conduct_session(therapy_plan, Config.SESSION_DURATION_MINUTES, ui)
                
                # Update therapy plan based on session
                reflection_agent = ReflectionAgent(llm_service, db_service, rag_service)
                updated_plan = reflection_agent.update_plan(session, therapy_plan)
                await ui.display_system_status("Therapy plan updated based on session.")
            else:
                await ui.display_system_status("Error: No intake session found despite status indicating completion.")
                return
                
        elif user_status == UserStatus.PROFILE_ONLY:
            # Resume from profile only, need to complete intake
            await ui.display_system_status("Resuming intake process...")
            
            # Initialize intake agent and conduct intake
            intake_agent = IntakeAgent(llm_service, db_service)
            intake_session = await intake_agent.conduct_intake(ui)
            
            # Continue with assessment and therapy plan creation
            assessment_agent = AssessmentAgent(llm_service, db_service, rag_service)
            recommendations = await assessment_agent.conduct_assessment(intake_session)
            
            # Let user select therapy style from recommendations
            await ui.display_system_status("Assessing your needs and recommending therapy styles...")
            selected_style = await ui.present_therapy_style_selection(recommendations)
            await ui.display_system_status(f"Selected therapy style: {selected_style}")
            
            # Create initial plan with selected style
            therapy_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
            await ui.display_system_status(f"Initial {selected_style.upper()} therapy plan created.")
            
            # Now conduct the therapy session
            psychoanalyst_agent = PsychoanalystAgent(llm_service, db_service, rag_service)
            session = await psychoanalyst_agent.conduct_session(therapy_plan, Config.SESSION_DURATION_MINUTES, ui)
            
            # Update therapy plan based on session
            reflection_agent = ReflectionAgent(llm_service, db_service, rag_service)
            updated_plan = reflection_agent.update_plan(session, therapy_plan)
            await ui.display_system_status("Therapy plan updated based on session.")
            
        else:
            # No data exists, start from beginning
            await ui.display_system_status("Starting new therapy journey...")
            
            # 1. Intake phase
            intake_agent = IntakeAgent(llm_service, db_service)
            intake_session = await intake_agent.conduct_intake(ui)
            
            # 2. Assessment phase: Recommend therapy styles and create initial plan
            await ui.display_system_status("Assessing your needs and recommending therapy styles...")
            assessment_agent = AssessmentAgent(llm_service, db_service, rag_service)
            recommendations = await assessment_agent.conduct_assessment(intake_session)
            
            # Let user select therapy style from recommendations
            await ui.display_system_status("Assessing your needs and recommending therapy styles...")
            selected_style = await ui.present_therapy_style_selection(recommendations)
            await ui.display_system_status(f"Selected therapy style: {selected_style}")
            
            # Create initial plan with selected style
            therapy_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
            await ui.display_system_status(f"Initial {selected_style.upper()} therapy plan created.")
            
            # 3. Conduct first therapy session
            psychoanalyst_agent = PsychoanalystAgent(llm_service, db_service, rag_service)
            session = await psychoanalyst_agent.conduct_session(therapy_plan, Config.SESSION_DURATION_MINUTES, ui)
            
            # 4. Reflection agent updates plan
            reflection_agent = ReflectionAgent(llm_service, db_service, rag_service)
            updated_plan = reflection_agent.update_plan(session, therapy_plan)
            await ui.display_system_status("Therapy plan updated based on session.")
        
        await ui.display_system_status("Session completed successfully!")
        
    except Exception as e:
        await ui.display_system_status(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
