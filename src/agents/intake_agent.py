from datetime import datetime, timedelta
import uuid
from typing import List
from services.llm_service import LLMService
from services.db_service import DatabaseService
from models.data_models import Session, Message, UserProfile, Topic
from context.user_context import UserContext
from prompts.intake_prompts import INITIAL_GREETING_PROMPT, CONTINUE_CONVERSATION_PROMPT, CLOSING_PROMPT
from ui.base_ui import BaseUI
from config import Config

class IntakeAgent:
    """Agent responsible for handling the initial user interaction and context retrieval."""
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, user_context: UserContext):
        """
        Initialize the Intake Agent.
        
        Args:
            llm_service (LLMService): The LLM service for generating responses.
            db_service (DatabaseService): The database service for storing sessions.
            user_context (UserContext): User context for this intake session.
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.user_context = user_context
        self.session_duration = Config.SESSION_DURATION_MINUTES
    
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
            user_id=self.user_context.user_id,
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
    
    def _get_pending_topics(self, session: Session) -> List[str]:
        """Get list of pending topics."""
        return [topic.name for topic in session.topics if topic.status == "pending"]
    
    def _get_covered_topics(self, session: Session) -> List[str]:
        """Get list of covered topics."""
        return [topic.name for topic in session.topics if topic.status in ["covered", "partially_covered"]]
    
    def _update_topic_status(self, session: Session, topic_name: str, status: str):
        """Update the status of a topic."""
        for topic in session.topics:
            if topic.name == topic_name:
                topic.status = status
                break
    
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
        
        # Initialize session with topics
        session_id = str(uuid.uuid4())
        topics = [Topic(name=topic_name) for topic_name in Config.INTAKE_TOPICS]
        session = Session(
            session_id=session_id,
            user_id=self.user_context.user_id,
            timestamp=datetime.now(),
            transcript=[],
            topics=topics
        )
        
        # Start session timer
        session_start_time = datetime.now()
        session_end_time = session_start_time + timedelta(minutes=self.session_duration)
        
        # Initial greeting with personalized touch
        initial_prompt = INITIAL_GREETING_PROMPT.format(
            user_name=user_profile.name,
            session_duration=self.session_duration
        )
        
        initial_response = self.llm_service.generate_response(initial_prompt)
        await ui.display_message("therapist", initial_response)
        
        # Add to transcript
        session.transcript.append(Message(
            role="assistant",
            content=initial_response,
            timestamp=datetime.now()
        ))
        
        # Conversation loop with time and topic awareness
        while True:
            # Check remaining time with higher precision
            current_time = datetime.now()
            remaining_time = session_end_time - current_time
            remaining_seconds = max(0, int(remaining_time.total_seconds()))
            
            # Check if session should end
            if remaining_seconds <= 0:
                await ui.display_system_status("Session time has expired. Wrapping up the assessment.")
                break
            
            # Check if all topics are covered
            pending_topics = self._get_pending_topics(session)
            if not pending_topics:
                await ui.display_system_status("All assessment topics have been covered.")
                break
            
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
                
                # Calculate remaining minutes for the prompt
                remaining_minutes = max(0, int(remaining_time.total_seconds() / 60))
                
                # Generate response using context with time and topic awareness
                covered_topics = self._get_covered_topics(session)
                pending_topics = self._get_pending_topics(session)
                
                # Format the continuation prompt with time and topic information
                formatted_prompt = CONTINUE_CONVERSATION_PROMPT.format(
                    remaining_minutes=remaining_minutes,
                    session_duration=self.session_duration,
                    covered_topics=", ".join(covered_topics) if covered_topics else "None",
                    pending_topics=", ".join(pending_topics)
                )
                
                context = [{"role": msg.role, "content": msg.content} for msg in session.transcript]
                response = self.llm_service.generate_response(
                    formatted_prompt,
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
