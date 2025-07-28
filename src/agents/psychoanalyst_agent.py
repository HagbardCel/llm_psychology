from datetime import datetime
import uuid
from typing import List
from services.llm_service import LLMService
from services.db_service import DatabaseService
from services.rag_service import RAGService
from utils.data_models import Session, Message, TherapyPlan, UserProfile
from prompts.psychoanalyst_prompts import INITIAL_SESSION_PROMPT, CONTINUE_SESSION_PROMPT, CLOSING_SESSION_PROMPT

class PsychoanalystAgent:
    """Agent responsible for conducting the main conversational sessions based on the therapy plan."""
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, rag_service: RAGService):
        """
        Initialize the Psychoanalyst Agent.
        
        Args:
            llm_service (LLMService): The LLM service for generating responses.
            db_service (DatabaseService): The database service for storing sessions.
            rag_service (RAGService): The RAG service for retrieving domain knowledge.
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_id = "default_user"  # In a real implementation, this would be dynamic
    
    def conduct_session(self, therapy_plan: TherapyPlan) -> Session:
        """
        Conduct a therapy session based on the provided therapy plan.
        
        Args:
            therapy_plan (TherapyPlan): The therapy plan to guide the session.
            
        Returns:
            Session: The completed therapy session.
        """
        # Retrieve user profile to get the name
        user_profile = self.db_service.get_user_profile(self.user_id)
        user_name = user_profile.name if user_profile else "Client"
        
        print(f"Starting therapy session for {user_name}...")
        print(f"Session Focus: {therapy_plan.plan_details.get('focus', 'Exploring your thoughts and feelings')}")
        print("Please share what's on your mind today.\n")
        
        # Initialize session
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=self.user_id,
            timestamp=datetime.now(),
            transcript=[]
        )
        
        # Get relevant domain knowledge based on the therapy plan
        plan_focus = therapy_plan.plan_details.get('focus', '')
        relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(plan_focus, n_results=2)
        
        # Create context with therapy plan and domain knowledge
        plan_context = f"""
        Therapy Plan (Version {therapy_plan.version}):
        Focus: {therapy_plan.plan_details.get('focus', 'General exploration')}
        Goals: {therapy_plan.plan_details.get('goals', 'Explore thoughts and feelings')}
        Techniques: {therapy_plan.plan_details.get('techniques', 'Active listening and reflection')}
        
        Relevant Psychological Knowledge:
        """
        
        for i, knowledge in enumerate(relevant_knowledge, 1):
            plan_context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"
        
        # Initial greeting with personalized touch
        initial_prompt = INITIAL_SESSION_PROMPT.format(
            user_name=user_name,
            plan_context=plan_context
        )
        
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
                
                # Get relevant knowledge based on current conversation
                recent_context = " ".join([msg.content for msg in session.transcript[-3:]])  # Last 3 messages
                context_knowledge = self.rag_service.retrieve_relevant_knowledge(recent_context, n_results=1)
                
                # Generate response using context, therapy plan, and domain knowledge
                context_messages = [{"role": msg.role, "content": msg.content} for msg in session.transcript]
                
                response_prompt = CONTINUE_SESSION_PROMPT.format(
                    plan_context=plan_context,
                    additional_knowledge=context_knowledge[0]['content'] if context_knowledge else 'None'
                )
                
                response = self.llm_service.generate_response(response_prompt, context_messages)
                
                print(f"Psychoanalyst: {response}\n")
                
                # Add assistant response to transcript
                session.transcript.append(Message(
                    role="assistant",
                    content=response,
                    timestamp=datetime.now()
                ))
        
        # End session
        closing_prompt = CLOSING_SESSION_PROMPT.format(plan_context=plan_context)
        
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
        print("Therapy session completed and saved.\n")
        
        return session
