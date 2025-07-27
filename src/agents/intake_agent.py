from datetime import datetime
import uuid
from typing import List
from services.llm_service import LLMService
from services.db_service import DatabaseService
from utils.data_models import Session, Message

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
    
    def conduct_intake(self) -> Session:
        """
        Conduct the initial intake conversation with the user.
        
        Returns:
            Session: The completed intake session.
        """
        print("Welcome to your virtual psychoanalysis session.")
        print("I'm here to help you explore your thoughts and feelings.")
        print("Please feel free to share whatever is on your mind.\n")
        
        # Initialize session
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=self.user_id,
            timestamp=datetime.now(),
            transcript=[]
        )
        
        # Initial greeting
        initial_prompt = """
        You are a compassionate psychoanalyst. Your task is to conduct an initial intake session 
        with a new client. Start by warmly welcoming them and explaining that this is an initial 
        session to get to know them better. Ask open-ended questions to help them feel comfortable 
        sharing their thoughts and concerns. Focus on creating a safe, non-judgmental space.
        
        Begin the conversation now.
        """
        
        initial_response = self.llm_service.generate_response(initial_prompt)
        print(f"Psychoanalyst: {initial_response}\n")
        
        # Add to transcript
        session.transcript.append(Message(
            role="assistant",
            content=initial_response,
            timestamp=datetime.now()
        ))
        
        # Conversation loop
        while True:
            user_input = input("You: ").strip()
            
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
                    "Continue the conversation naturally. Show empathy and ask follow-up questions as needed.",
                    context
                )
                
                print(f"Psychoanalyst: {response}\n")
                
                # Add assistant response to transcript
                session.transcript.append(Message(
                    role="assistant",
                    content=response,
                    timestamp=datetime.now()
                ))
        
        # End session
        closing_prompt = """
        You are concluding the intake session. Thank the user for sharing and 
        summarize that this was a good starting point. Mention that you'll reflect 
        on this conversation to create a personalized approach for future sessions.
        """
        
        closing_response = self.llm_service.generate_response(closing_prompt)
        print(f"Psychoanalyst: {closing_response}\n")
        
        # Add closing to transcript
        session.transcript.append(Message(
            role="assistant",
            content=closing_response,
            timestamp=datetime.now()
        ))
        
        # Save session to database
        self.db_service.save_session(session)
        print("Intake session completed and saved.\n")
        
        return session
