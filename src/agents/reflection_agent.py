from datetime import datetime
import uuid
import logging
from typing import List, Dict, Any
from services.llm_service import LLMService
from services.db_service import DatabaseService
from services.rag_service import RAGService
from services.style_service import style_service
from models.data_models import Session, TherapyPlan
from context.user_context import UserContext
from prompts.reflection_prompts import CREATE_INITIAL_PLAN_PROMPT, UPDATE_PLAN_PROMPT, SESSION_SUMMARY_PROMPT
from exceptions import ReflectionError

logger = logging.getLogger(__name__)

class ReflectionAgent:
    """Agent responsible for analyzing conversations and creating/refining therapy plans."""
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, rag_service: RAGService, user_context: UserContext):
        """
        Initialize the Reflection Agent.
        
        Args:
            llm_service (LLMService): The LLM service for generating responses.
            db_service (DatabaseService): The database service for storing plans.
            rag_service (RAGService): The RAG service for retrieving domain knowledge.
            user_context (UserContext): User context for this reflection session.
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
    
    def create_initial_plan(self, intake_session: Session) -> TherapyPlan:
        """
        Create the initial therapy plan based on the intake session.
        
        Args:
            intake_session (Session): The completed intake session.
            
        Returns:
            TherapyPlan: The initial therapy plan.
        """
        logger.info("Reflection Agent: Analyzing intake session and creating initial therapy plan...")
        
        # Get all previous sessions for this user to understand history
        previous_sessions = self.db_service.get_all_sessions_for_user(self.user_context.user_id)
        
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
                import json
                # Extract JSON from the raw response
                raw_response = structured_response["raw_response"].strip()
                
                # Remove any markdown code block markers if present
                if raw_response.startswith("```json"):
                    raw_response = raw_response[7:]  # Remove ```json
                if raw_response.startswith("```"):
                    raw_response = raw_response[3:]  # Remove ```
                if raw_response.endswith("```"):
                    raw_response = raw_response[:-3]  # Remove ```
                
                # Parse the JSON
                parsed_response = json.loads(raw_response)
                
                # Update plan details with parsed response
                if "focus" in parsed_response:
                    plan_details["focus"] = parsed_response["focus"]
                if "goals" in parsed_response:
                    plan_details["goals"] = parsed_response["goals"]
                if "techniques" in parsed_response:
                    plan_details["techniques"] = parsed_response["techniques"]
                if "themes" in parsed_response:
                    plan_details["themes"] = parsed_response["themes"]
            except Exception as e:
                logger.error(f"Error parsing LLM response: {e}", exc_info=True)
                # Fall back to default plan_details
                pass
        
        therapy_plan = TherapyPlan(
            plan_id=plan_id,
            user_id=self.user_context.user_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details=plan_details,
            version=1
        )
        
        # Save plan to database
        self.db_service.save_therapy_plan(therapy_plan)
        logger.info("Initial therapy plan created and saved.")
        
        return therapy_plan
    
    def create_initial_plan_with_style(self, intake_session: Session, selected_style: str) -> TherapyPlan:
        """
        Create the initial therapy plan based on the intake session and selected therapy style.
        
        Args:
            intake_session (Session): The completed intake session.
            selected_style (str): The selected therapy style.
            
        Returns:
            TherapyPlan: The initial therapy plan with selected style.
        """
        logger.info(f"Reflection Agent: Analyzing intake session and creating initial {selected_style.upper()} therapy plan...")
        
        # Get style-specific reflection prompt
        if style_service.get_style_pack(selected_style):
            reflection_prompt = style_service.get_reflection_prompt(selected_style)
            knowledge_source = style_service.get_knowledge_source(selected_style)
        else:
            reflection_prompt = ""
            knowledge_source = None
        
        # Prepare session transcript for analysis
        session_text = "\n".join([f"{msg.role}: {msg.content}" for msg in intake_session.transcript])
        
        # Get relevant domain knowledge filtered by style
        if knowledge_source:
            relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(
                session_text, 
                n_results=3, 
                filter_source=knowledge_source
            )
        else:
            relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(session_text, n_results=3)
        
        # Create context for LLM
        context = f"""
        Intake Session Transcript:
        {session_text}
        
        Relevant Psychological Knowledge:
        """
        for i, knowledge in enumerate(relevant_knowledge, 1):
            context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"
        
        # Use style-specific prompt if available
        if reflection_prompt:
            plan_prompt = f"""
{reflection_prompt}

Context for analysis:
{context}

Please create an initial therapy plan based on this {selected_style.upper()} approach.
"""
        else:
            plan_prompt = CREATE_INITIAL_PLAN_PROMPT.format(context=context)
        
        structured_response = self.llm_service.generate_structured_response(
            plan_prompt, 
            '{"focus": "string", "goals": "string", "techniques": "string", "themes": "string"}'
        )
        
        # Create therapy plan object
        plan_id = str(uuid.uuid4())
        plan_details = {
            "focus": f"Initial {selected_style.upper()} approach",
            "goals": "Build therapeutic relationship and identify key concerns",
            "techniques": f"Approach appropriate for {selected_style.upper()}",
            "themes": "Initial concerns and background"
        }
        
        # Try to parse the LLM response
        if "raw_response" in structured_response:
            try:
                import json
                # Extract JSON from the raw response
                raw_response = structured_response["raw_response"].strip()
                
                # Remove any markdown code block markers if present
                if raw_response.startswith("```json"):
                    raw_response = raw_response[7:]  # Remove ```json
                if raw_response.startswith("```"):
                    raw_response = raw_response[3:]  # Remove ```
                if raw_response.endswith("```"):
                    raw_response = raw_response[:-3]  # Remove ```
                
                # Parse the JSON
                parsed_response = json.loads(raw_response)
                
                # Update plan details with parsed response
                if "focus" in parsed_response:
                    plan_details["focus"] = parsed_response["focus"]
                if "goals" in parsed_response:
                    plan_details["goals"] = parsed_response["goals"]
                if "techniques" in parsed_response:
                    plan_details["techniques"] = parsed_response["techniques"]
                if "themes" in parsed_response:
                    plan_details["themes"] = parsed_response["themes"]
            except Exception as e:
                logger.error(f"Error parsing LLM response: {e}", exc_info=True)
                # Fall back to default plan_details
                pass
        
        therapy_plan = TherapyPlan(
            plan_id=plan_id,
            user_id=self.user_context.user_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details=plan_details,
            version=1,
            selected_therapy_style=selected_style
        )
        
        # Save plan to database
        self.db_service.save_therapy_plan(therapy_plan)
        logger.info(f"Initial {selected_style.upper()} therapy plan created and saved.")
        
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
        logger.info("Reflection Agent: Analyzing session and updating therapy plan...")
        
        # Handle None plan gracefully
        if current_plan is None:
            logger.warning("No current plan provided. Creating default plan.")
            # Create a default plan when no current plan exists
            plan_id = str(uuid.uuid4())
            default_plan_details = {
                "focus": "Initial assessment",
                "goals": "Establish baseline and identify key concerns",
                "techniques": "Assessment and evaluation",
                "themes": "Initial consultation"
            }
            
            default_plan = TherapyPlan(
                plan_id=plan_id,
                user_id=self.user_context.user_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                plan_details=default_plan_details,
                version=1,
                selected_therapy_style="cbt"  # Default style
            )
            
            # Save default plan to database
            self.db_service.save_therapy_plan(default_plan)
            logger.info("Default therapy plan created and saved.")
            return default_plan
        
        # Handle None session gracefully
        if session is None:
            logger.warning("No session provided. Returning current plan unchanged.")
            return current_plan
        
        # Get the selected therapy style from the current plan
        selected_style = current_plan.selected_therapy_style
        if selected_style and style_service.get_style_pack(selected_style):
            reflection_prompt = style_service.get_reflection_prompt(selected_style)
            knowledge_source = style_service.get_knowledge_source(selected_style)
        else:
            reflection_prompt = ""
            knowledge_source = None
        
        # Get all sessions for comprehensive analysis
        all_sessions = self.db_service.get_all_sessions_for_user(self.user_context.user_id)
        
        # Prepare session transcript for analysis
        session_text = "\n".join([f"{msg.role}: {msg.content}" for msg in session.transcript])
        
        # Prepare all sessions context
        all_sessions_text = ""
        for i, sess in enumerate(all_sessions[-3:], 1):  # Last 3 sessions
            sess_text = "\n".join([f"{msg.role}: {msg.content}" for msg in sess.transcript])
            all_sessions_text += f"\n\nSession {i}:\n{sess_text}"
        
        # Get relevant domain knowledge filtered by style
        if knowledge_source:
            relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(
                session_text, 
                n_results=2, 
                filter_source=knowledge_source
            )
        else:
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
        
        # Use style-specific prompt if available
        if reflection_prompt:
            update_prompt = f"""
{reflection_prompt}

Context for analysis:
{context}

Please update the therapy plan based on this {selected_style.upper()} approach.
"""
        else:
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
                import json
                # Extract JSON from the raw response
                raw_response = structured_response["raw_response"].strip()
                
                # Remove any markdown code block markers if present
                if raw_response.startswith("```json"):
                    raw_response = raw_response[7:]  # Remove ```json
                if raw_response.startswith("```"):
                    raw_response = raw_response[3:]  # Remove ```
                if raw_response.endswith("```"):
                    raw_response = raw_response[:-3]  # Remove ```
                
                # Parse the JSON
                parsed_response = json.loads(raw_response)
                
                # Update plan details with parsed response
                if "focus" in parsed_response:
                    updated_plan_details["focus"] = parsed_response["focus"]
                if "goals" in parsed_response:
                    updated_plan_details["goals"] = parsed_response["goals"]
                if "techniques" in parsed_response:
                    updated_plan_details["techniques"] = parsed_response["techniques"]
                if "themes" in parsed_response:
                    updated_plan_details["themes"] = parsed_response["themes"]
                    
                updated_plan_details["updated_from_session"] = session.session_id
            except Exception as e:
                logger.error(f"Error parsing LLM response in update_plan: {e}", exc_info=True)
                # Fall back to default updated_plan_details
                updated_plan_details["updated_from_session"] = session.session_id
                pass
        
        updated_plan = TherapyPlan(
            plan_id=plan_id,
            user_id=self.user_context.user_id,
            created_at=current_plan.created_at,
            updated_at=datetime.now(),
            plan_details=updated_plan_details,
            version=current_plan.version + 1,
            selected_therapy_style=current_plan.selected_therapy_style
        )
        
        # Save updated plan to database
        self.db_service.save_therapy_plan(updated_plan)
        logger.info(f"Therapy plan updated to version {updated_plan.version} and saved.")
        
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
