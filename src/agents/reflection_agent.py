from datetime import datetime
import uuid
from typing import List, Dict, Any
from services.llm_service import LLMService
from services.db_service import DatabaseService
from services.rag_service import RAGService
from utils.data_models import Session, TherapyPlan
from prompts.reflection_prompts import CREATE_INITIAL_PLAN_PROMPT, UPDATE_PLAN_PROMPT, SESSION_SUMMARY_PROMPT

class ReflectionAgent:
    """Agent responsible for analyzing conversations and creating/refining therapy plans."""
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, rag_service: RAGService):
        """
        Initialize the Reflection Agent.
        
        Args:
            llm_service (LLMService): The LLM service for generating responses.
            db_service (DatabaseService): The database service for storing plans.
            rag_service (RAGService): The RAG service for retrieving domain knowledge.
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_id = "default_user"  # In a real implementation, this would be dynamic
    
    def create_initial_plan(self, intake_session: Session) -> TherapyPlan:
        """
        Create the initial therapy plan based on the intake session.
        
        Args:
            intake_session (Session): The completed intake session.
            
        Returns:
            TherapyPlan: The initial therapy plan.
        """
        print("Reflection Agent: Analyzing intake session and creating initial therapy plan...")
        
        # Get all previous sessions for this user to understand history
        previous_sessions = self.db_service.get_all_sessions_for_user(self.user_id)
        
        # Prepare session transcript for analysis
        session_text = "\n".join([f"{msg.role}: {msg.content}" for msg in intake_session.transcript])
        
        # Get relevant domain knowledge
        relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(session_text, n_results=3)
        
        # Create context for LLM
        context = f"""
        Intake Session Transcript:
        {session_text}
        
        Relevant Psychological Knowledge:
        """
        for i, knowledge in enumerate(relevant_knowledge, 1):
            context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"
        
        # Generate initial therapy plan
        plan_prompt = CREATE_INITIAL_PLAN_PROMPT.format(context=context)
        
        structured_response = self.llm_service.generate_structured_response(
            plan_prompt, 
            '{"focus": "string", "goals": "string", "techniques": "string", "themes": "string"}'
        )
        
        # Create therapy plan object
        plan_id = str(uuid.uuid4())
        plan_details = {
            "focus": "Exploring thoughts and feelings",
            "goals": "Build therapeutic relationship and identify key concerns",
            "techniques": "Active listening, reflection, open-ended questions",
            "themes": "Initial concerns and background"
        }
        
        # Try to parse the LLM response
        if "raw_response" in structured_response:
            try:
                # In a real implementation, you'd parse the JSON properly
                # For now, we'll use the raw response as a string
                raw_response = structured_response["raw_response"]
                # Simple extraction of key information (this would be more sophisticated in practice)
                if "focus" in raw_response.lower():
                    plan_details["focus"] = raw_response.split("focus")[1].split(":")[1].split('"')[1] if '"' in raw_response.split("focus")[1].split(":")[1] else plan_details["focus"]
            except:
                pass
        
        therapy_plan = TherapyPlan(
            plan_id=plan_id,
            user_id=self.user_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details=plan_details,
            version=1
        )
        
        # Save plan to database
        self.db_service.save_therapy_plan(therapy_plan)
        print("Initial therapy plan created and saved.\n")
        
        return therapy_plan
    
    def update_plan(self, session: Session, current_plan: TherapyPlan) -> TherapyPlan:
        """
        Update the therapy plan based on a completed session.
        
        Args:
            session (Session): The completed therapy session.
            current_plan (TherapyPlan): The current therapy plan.
            
        Returns:
            TherapyPlan: The updated therapy plan.
        """
        print("Reflection Agent: Analyzing session and updating therapy plan...")
        
        # Get all sessions for comprehensive analysis
        all_sessions = self.db_service.get_all_sessions_for_user(self.user_id)
        
        # Prepare session transcript for analysis
        session_text = "\n".join([f"{msg.role}: {msg.content}" for msg in session.transcript])
        
        # Prepare all sessions context
        all_sessions_text = ""
        for i, sess in enumerate(all_sessions[-3:], 1):  # Last 3 sessions
            sess_text = "\n".join([f"{msg.role}: {msg.content}" for msg in sess.transcript])
            all_sessions_text += f"\n\nSession {i}:\n{sess_text}"
        
        # Get relevant domain knowledge
        relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(session_text, n_results=2)
        
        # Create context for LLM
        context = f"""
        Current Therapy Plan (Version {current_plan.version}):
        {current_plan.plan_details}
        
        Latest Session Transcript:
        {session_text}
        
        Recent Session History:
        {all_sessions_text}
        
        Relevant Psychological Knowledge:
        """
        for i, knowledge in enumerate(relevant_knowledge, 1):
            context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"
        
        # Generate updated therapy plan
        update_prompt = UPDATE_PLAN_PROMPT.format(context=context)
        
        structured_response = self.llm_service.generate_structured_response(
            update_prompt,
            '{"focus": "string", "goals": "string", "techniques": "string", "themes": "string"}'
        )
        
        # Create updated therapy plan object
        plan_id = str(uuid.uuid4())
        updated_plan_details = current_plan.plan_details.copy()
        
        # Try to update with LLM response
        if "raw_response" in structured_response:
            try:
                # In a real implementation, you'd parse the JSON properly
                raw_response = structured_response["raw_response"]
                updated_plan_details["updated_from_session"] = session.session_id
            except:
                pass
        
        updated_plan = TherapyPlan(
            plan_id=plan_id,
            user_id=self.user_id,
            created_at=current_plan.created_at,
            updated_at=datetime.now(),
            plan_details=updated_plan_details,
            version=current_plan.version + 1
        )
        
        # Save updated plan to database
        self.db_service.save_therapy_plan(updated_plan)
        print(f"Therapy plan updated to version {updated_plan.version} and saved.\n")
        
        return updated_plan
    
    def generate_session_summary(self, session: Session) -> Dict[str, Any]:
        """
        Generate a summary of a session for record-keeping.
        
        Args:
            session (Session): The session to summarize.
            
        Returns:
            Dict[str, Any]: Session summary including key themes and insights.
        """
        session_text = "\n".join([f"{msg.role}: {msg.content}" for msg in session.transcript])
        
        summary_prompt = SESSION_SUMMARY_PROMPT.format(session_text=session_text)
        
        summary = self.llm_service.generate_response(summary_prompt)
        
        return {
            "session_id": session.session_id,
            "summary": summary,
            "timestamp": session.timestamp.isoformat()
        }
