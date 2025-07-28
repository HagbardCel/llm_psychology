from datetime import datetime
import uuid
from typing import List
from services.llm_service import LLMService
from services.db_service import DatabaseService
from utils.data_models import Session, Message, UserProfile
from prompts.intake_prompts import INITIAL_GREETING_PROMPT, CONTINUE_CONVERSATION_PROMPT, CLOSING_PROMPT
from ui.base_ui import BaseUI

class IntakeAgent:
    """Agent responsible for handling the initial user interaction and context retrieval."""
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService):
        """
        Initialize the Intake Agent.
        
        Args:
            llm_service (LLMService): The LLM service for generating responses.
            db_service (DatabaseService): The database service for storing sessions.
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.user_id = "default_user"  # In a real implementation, this would be dynamic
    
    async def _collect_user_profile(self, ui: BaseUI) -> UserProfile:
        """
        Collect user profile information at the beginning of the session.
        
        Args:
            ui (BaseUI): The UI interface to use for interaction.
            
        Returns:
            UserProfile: The collected user profile information.
        """
        await ui.display_system_status("Before we begin, I'd like to get to know you better.")
        await ui.display_system_status("This information will help me provide you with a more personalized experience.\n")
        
        # Collect user information
        name = await ui.get_user_input("What is your name? ")
        name = name.strip()
        if not name:
            name = "Anonymous User"
        
        birthdate_str = await ui.get_user_input("What is your birthdate? (YYYY-MM-DD, optional): ")
        birthdate_str = birthdate_str.strip()
        birthdate = None
        if birthdate_str:
            try:
                birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d")
            except ValueError:
                await ui.display_system_status("Invalid date format. Birthdate will not be recorded.")
        
        profession = await ui.get_user_input("What is your profession? (optional): ")
        profession = profession.strip()
        if not profession:
            profession = None
        
        # Create user profile
        profile = UserProfile(
            user_id=self.user_id,
            name=name,
            birthdate=birthdate,
            profession=profession,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Save to database
        self.db_service.save_user_profile(profile)
        await ui.display_system_status(f"Thank you, {name}. Your information has been recorded.\n")
        
        return profile
    
    async def conduct_intake(self, ui: BaseUI) -> Session:
        """
        Conduct the initial intake conversation with the user.
        
        Args:
            ui (BaseUI): The UI interface to use for interaction.
            
        Returns:
            Session: The completed intake session.
        """
        await ui.display_system_status("Welcome to your virtual psychoanalysis session.")
        await ui.display_system_status("I'm here to help you explore your thoughts and feelings.")
        await ui.display_system_status("Please feel free to share whatever is on your mind.\n")
        
        # Collect user profile information
        user_profile = await self._collect_user_profile(ui)
        
        # Initialize session
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=self.user_id,
            timestamp=datetime.now(),
            transcript=[]
        )
        
        # Initial greeting with personalized touch
        initial_prompt = INITIAL_GREETING_PROMPT.format(user_name=user_profile.name)
        
        initial_response = self.llm_service.generate_response(initial_prompt)
        await ui.display_message("therapist", initial_response)
        
        # Add to transcript
        session.transcript.append(Message(
            role="assistant",
            content=initial_response,
            timestamp=datetime.now()
        ))
        
        # Conversation loop
        while True:
            user_input = await ui.get_user_input()
            
            if user_input.lower() in ['quit', 'exit', 'bye', 'goodbye']:
                break
            
            if user_input:
                # Add user message to transcript
                session.transcript.append(Message(
                    role="user",
                    content=user_input,
                    timestamp=datetime.now()
                ))
                
                # Generate response using context
                context = [{"role": msg.role, "content": msg.content} for msg in session.transcript]
                response = self.llm_service.generate_response(
                    CONTINUE_CONVERSATION_PROMPT,
                    context
                )
                
                await ui.display_message("therapist", response)
                
                # Add assistant response to transcript
                session.transcript.append(Message(
                    role="assistant",
                    content=response,
                    timestamp=datetime.now()
                ))
        
        # End session
        closing_prompt = CLOSING_PROMPT
        
        closing_response = self.llm_service.generate_response(closing_prompt)
        await ui.display_message("therapist", closing_response)
        
        # Add closing to transcript
        session.transcript.append(Message(
            role="assistant",
            content=closing_response,
            timestamp=datetime.now()
        ))
        
        # Save session to database
        self.db_service.save_session(session)
        await ui.display_system_status("Intake session completed and saved.\n")
        
        return session
