#!/usr/bin/env python3
"""
Main entry point for the Virtual LLM-Driven Psychoanalyst application.
Implements resumable sessions functionality.
"""

import sys
import os
import asyncio
import logging

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from config import Config, setup_logging
from services.db_service import UserStatus
from container.service_container import ServiceContainer
from context.user_context import UserContext
from ui.textual_ui import ConsoleUI
from exceptions import (
    ConfigurationError, DatabaseError, AgentError, 
    LLMServiceError, RAGServiceError, PsychoanalystError
)

# Set up logging using centralized configuration
setup_logging()
logger = logging.getLogger(__name__)


async def handle_workflow_error(ui: ConsoleUI, e: Exception, workflow_stage: str) -> None:
    """
    Handle workflow errors with appropriate logging and user feedback.
    
    Args:
        ui: UI instance for displaying messages
        e: Exception that occurred
        workflow_stage: Description of the workflow stage where error occurred
    """
    if isinstance(e, AgentError):
        error_msg = f"Agent error during {workflow_stage}: {e}"
        logger.error(error_msg)
        await ui.display_system_status(error_msg)
        await ui.display_system_status(f"{workflow_stage.title()} could not be completed. Please try again.")
    elif isinstance(e, DatabaseError):
        error_msg = f"Database error during {workflow_stage}: {e}"
        logger.error(error_msg)
        await ui.display_system_status(error_msg)
        await ui.display_system_status("Database operation failed. Please check your data directory.")
    elif isinstance(e, LLMServiceError):
        error_msg = f"LLM service error during {workflow_stage}: {e}"
        logger.error(error_msg)
        await ui.display_system_status(error_msg)
        await ui.display_system_status("AI service unavailable. Please check your API configuration.")
    elif isinstance(e, RAGServiceError):
        error_msg = f"Knowledge retrieval error during {workflow_stage}: {e}"
        logger.error(error_msg)
        await ui.display_system_status(error_msg)
        await ui.display_system_status("Knowledge base access failed. Session may continue with limited context.")
    else:
        error_msg = f"Unexpected error during {workflow_stage}: {e}"
        logger.error(error_msg, exc_info=True)
        await ui.display_system_status(error_msg)
        await ui.display_system_status("An unexpected error occurred. Please try again.")


async def main():
    """Main application entry point with resumable sessions."""
    logger.info(f"Starting {Config.APP_NAME} v{Config.VERSION}")
    
    # Initialize UI
    ui = ConsoleUI()
    
    try:
        # Display startup message
        await ui.display_system_status(f"Welcome to {Config.APP_NAME} v{Config.VERSION}")
        await ui.display_system_status(f"Session duration: {Config.SESSION_DURATION_MINUTES} minutes")
        
        # Initialize service container
        logger.info("Initializing service container...")
        try:
            container = ServiceContainer(Config)
            await ui.display_system_status("Service container initialized successfully")
        except ConfigurationError as e:
            error_msg = f"Configuration error: {e}"
            logger.error(error_msg)
            await ui.display_system_status(error_msg)
            await ui.display_system_status("Please check your .env file configuration.")
            return
        except Exception as e:
            error_msg = f"Failed to initialize services: {e}"
            logger.error(error_msg)
            await ui.display_system_status(error_msg)
            return
        
        # Run database migrations
        try:
            logger.info("Running database migrations...")
            await ui.display_system_status("Checking database migrations...")
            
            migration_service = container.get('migration_service')
            migration_status = migration_service.get_migration_status()
            
            if migration_status['pending_count'] > 0:
                await ui.display_system_status(f"Applying {migration_status['pending_count']} pending migrations...")
                applied_migrations = migration_service.run_migrations()
                await ui.display_system_status(f"Successfully applied {len(applied_migrations)} migrations")
                for migration in applied_migrations:
                    logger.info(f"Applied migration: {migration}")
            else:
                await ui.display_system_status("Database is up to date")
                
        except Exception as e:
            error_msg = f"Migration failed: {e}"
            logger.error(error_msg)
            await ui.display_system_status(error_msg)
            await ui.display_system_status("Application startup aborted due to migration failure")
            return
        
        # Create user context (using default user for now, will be dynamic in multi-user setup)
        user_context = UserContext("default_user")
        logger.info(f"User context created: {user_context}")
        
        # Get database service and check user status
        try:
            db_service = container.get('db_service')
            user_status = db_service.get_user_status()
            logger.info(f"User status: {user_status}")
            await ui.display_system_status(f"User status: {user_status}")
        except DatabaseError as e:
            error_msg = f"Database error while checking user status: {e}"
            logger.error(error_msg)
            await ui.display_system_status(error_msg)
            return
        except Exception as e:
            error_msg = f"Unexpected error accessing database: {e}"
            logger.error(error_msg)
            await ui.display_system_status(error_msg)
            return
        
        therapy_plan = None
        
        if user_status == UserStatus.PLAN_COMPLETE:
            # Resume from existing therapy plan
            try:
                await ui.display_system_status("Resuming from existing therapy plan...")
                therapy_plan = db_service.get_latest_therapy_plan()
                
                if therapy_plan is None:
                    error_msg = "Error: No therapy plan found despite status indicating plan completion."
                    logger.error(error_msg)
                    await ui.display_system_status(error_msg)
                    return
                
                # Create agents using service container
                reflection_agent = container.create_reflection_agent(user_context)
                psychoanalyst_agent = container.create_psychoanalyst_agent(user_context)
                
                # Conduct session with existing plan
                await ui.display_system_status("Starting therapy session with existing plan...")
                session = await psychoanalyst_agent.conduct_session(therapy_plan, Config.SESSION_DURATION_MINUTES, ui)
                
                # Update therapy plan based on session
                updated_plan = reflection_agent.update_plan(session, therapy_plan)
                await ui.display_system_status("Therapy plan updated based on session.")
                
            except Exception as e:
                await handle_workflow_error(ui, e, "therapy session")
                return
            
        elif user_status == UserStatus.INTAKE_COMPLETE:
            # Resume from completed intake, need assessment
            try:
                await ui.display_system_status("Resuming from completed intake. Starting assessment...")
                
                # Get the latest session (intake session)
                all_sessions = db_service.get_all_sessions_for_user()
                intake_session = all_sessions[-1] if all_sessions else None
                
                if intake_session:
                    # Create agents using service container
                    assessment_agent = container.create_assessment_agent(user_context)
                    reflection_agent = container.create_reflection_agent(user_context)
                    recommendations = await assessment_agent.conduct_assessment(intake_session)
                    
                    # Let user select therapy style from recommendations
                    await ui.display_system_status("Assessing your needs and recommending therapy styles...")
                    selected_style = await ui.present_therapy_style_selection(recommendations)
                    await ui.display_system_status(f"Selected therapy style: {selected_style}")
                    
                    # Create initial plan with selected style
                    therapy_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
                    await ui.display_system_status(f"Initial {selected_style.upper()} therapy plan created.")
                    
                    # Now conduct the therapy session
                    psychoanalyst_agent = container.create_psychoanalyst_agent(user_context)
                    session = await psychoanalyst_agent.conduct_session(therapy_plan, Config.SESSION_DURATION_MINUTES, ui)
                    
                    # Update therapy plan based on session (reuse existing reflection_agent)
                    updated_plan = reflection_agent.update_plan(session, therapy_plan)
                    await ui.display_system_status("Therapy plan updated based on session.")
                else:
                    await ui.display_system_status("Error: No intake session found despite status indicating completion.")
                    return
                    
            except Exception as e:
                await handle_workflow_error(ui, e, "assessment and therapy session")
                return
                
        elif user_status == UserStatus.PROFILE_ONLY:
            # Resume from profile only, need to complete intake
            try:
                await ui.display_system_status("Resuming intake process...")
                
                # Create intake agent using service container
                intake_agent = container.create_intake_agent(user_context)
                intake_session = await intake_agent.conduct_intake(ui)
                
                # Create agents using service container
                assessment_agent = container.create_assessment_agent(user_context)
                reflection_agent = container.create_reflection_agent(user_context)
                recommendations = await assessment_agent.conduct_assessment(intake_session)
                
                # Let user select therapy style from recommendations
                await ui.display_system_status("Assessing your needs and recommending therapy styles...")
                selected_style = await ui.present_therapy_style_selection(recommendations)
                await ui.display_system_status(f"Selected therapy style: {selected_style}")
                
                # Create initial plan with selected style
                therapy_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
                await ui.display_system_status(f"Initial {selected_style.upper()} therapy plan created.")
                
                # Now conduct the therapy session
                psychoanalyst_agent = container.create_psychoanalyst_agent(user_context)
                session = await psychoanalyst_agent.conduct_session(therapy_plan, Config.SESSION_DURATION_MINUTES, ui)
                
                # Update therapy plan based on session (reuse existing reflection_agent)
                updated_plan = reflection_agent.update_plan(session, therapy_plan)
                await ui.display_system_status("Therapy plan updated based on session.")
                
            except Exception as e:
                await handle_workflow_error(ui, e, "intake, assessment and therapy session")
                return
            
        else:
            # No data exists, start from beginning
            try:
                await ui.display_system_status("Starting new therapy journey...")
                
                # 1. Intake phase
                intake_agent = container.create_intake_agent(user_context)
                intake_session = await intake_agent.conduct_intake(ui)
                
                # 2. Assessment phase: Recommend therapy styles and create initial plan
                await ui.display_system_status("Assessing your needs and recommending therapy styles...")
                
                # Create agents using service container
                assessment_agent = container.create_assessment_agent(user_context)
                reflection_agent = container.create_reflection_agent(user_context)
                recommendations = await assessment_agent.conduct_assessment(intake_session)
                
                # Let user select therapy style from recommendations
                await ui.display_system_status("Assessing your needs and recommending therapy styles...")
                selected_style = await ui.present_therapy_style_selection(recommendations)
                await ui.display_system_status(f"Selected therapy style: {selected_style}")
                
                # Create initial plan with selected style
                therapy_plan = assessment_agent.create_initial_plan_with_style(intake_session, selected_style)
                await ui.display_system_status(f"Initial {selected_style.upper()} therapy plan created.")
                
                # 3. Conduct first therapy session
                psychoanalyst_agent = container.create_psychoanalyst_agent(user_context)
                session = await psychoanalyst_agent.conduct_session(therapy_plan, Config.SESSION_DURATION_MINUTES, ui)
                
                # 4. Update plan with existing reflection agent
                updated_plan = reflection_agent.update_plan(session, therapy_plan)
                await ui.display_system_status("Therapy plan updated based on session.")
                
            except Exception as e:
                await handle_workflow_error(ui, e, "complete therapy journey")
                return
        
        await ui.display_system_status("Session completed successfully!")
        
    except ConfigurationError as e:
        await ui.display_system_status(f"Configuration error: {str(e)}")
        logger.error(f"Configuration error: {e}", exc_info=True)
    except Exception as e:
        await ui.display_system_status(f"Unexpected error: {str(e)}")
        logger.error(f"Unexpected error: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup service container if it was created
        try:
            if 'container' in locals():
                container.shutdown()
                logger.info("Service container shutdown complete")
        except Exception as e:
            logger.error(f"Error during container shutdown: {e}")

if __name__ == "__main__":
    asyncio.run(main())
