from typing import List, Dict
from services.llm_service import LLMService
from services.db_service import DatabaseService
from services.rag_service import RAGService
from services.style_service import style_service
from models.data_models import Session, TherapyPlan
from context.user_context import UserContext
from datetime import datetime
import uuid

class AssessmentAgent:
    """Agent responsible for assessing user needs and recommending therapy styles."""
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, rag_service: RAGService, user_context: UserContext, reflection_agent=None):
        """
        Initialize the Assessment Agent.
        
        Args:
            llm_service (LLMService): The LLM service for generating responses.
            db_service (DatabaseService): The database service for storing therapy plans.
            rag_service (RAGService): The RAG service for retrieving domain knowledge.
            user_context (UserContext): User context for this assessment session.
            reflection_agent: Optional ReflectionAgent for dependency injection.
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.reflection_agent = reflection_agent
    
    def _generate_recommendations(self, intake_session: Session) -> List[Dict[str, str]]:
        """
        Generate therapy style recommendations based on the intake session.
        
        Args:
            intake_session (Session): The completed intake session.
            
        Returns:
            List[Dict[str, str]]: List of recommended therapy styles with descriptions.
        """
        # Get all available therapy styles
        available_styles = style_service.get_available_styles()
        
        # Create a comprehensive session summary for assessment
        session_context = []
        for msg in intake_session.transcript:
            session_context.append(f"{msg.role}: {msg.content}")
        
        session_summary = "\n".join(session_context)
        
        # For each style, use the assessment prompt to evaluate suitability
        style_assessments = {}
        
        for style_id in available_styles:
            assessment_prompt = style_service.get_assessment_prompt(style_id)
            
            # Create a prompt to evaluate the session against this style's criteria
            evaluation_prompt = f"""
{assessment_prompt}

Based on the following intake session transcript, assess whether this patient would be a good candidate for {style_id.upper()} therapy:

Session Transcript:
{session_summary}

Please provide a brief assessment of why this patient might or might not be suitable for {style_id.upper()} therapy, focusing on the key indicators you see in the transcript.
"""
            
            # Generate assessment
            assessment = self.llm_service.generate_response(evaluation_prompt)
            style_assessments[style_id] = assessment
        
        # Create recommendations with descriptions
        recommendations = []
        for style_id in available_styles:
            recommendations.append({
                "style_id": style_id,
                "name": style_id.upper(),
                "description": style_service.get_style_description(style_id),
                "assessment": style_assessments[style_id]
            })
        
        # Sort recommendations by relevance (for now, we'll keep all but limit to 3 in the UI)
        return recommendations
    
    async def conduct_assessment(self, intake_session: Session) -> List[Dict[str, str]]:
        """
        Conduct the assessment process and generate therapy style recommendations.
        
        Args:
            intake_session (Session): The completed intake session.
            
        Returns:
            List[Dict[str, str]]: List of recommended therapy styles with descriptions.
        """
        # Generate therapy style recommendations
        recommendations = self._generate_recommendations(intake_session)
        
        return recommendations
    
    def create_initial_plan_with_style(self, intake_session: Session, selected_style: str) -> TherapyPlan:
        """
        Create an initial therapy plan with the selected therapy style.
        
        Args:
            intake_session (Session): The completed intake session.
            selected_style (str): The user-selected therapy style.
            
        Returns:
            TherapyPlan: The initial therapy plan with selected style.
        """
        # Use the injected ReflectionAgent dependency
        if self.reflection_agent is None:
            # Fallback: create temporary instance if not injected
            from agents.reflection_agent import ReflectionAgent
            reflection_agent = ReflectionAgent(self.llm_service, self.db_service, self.rag_service)
        else:
            reflection_agent = self.reflection_agent
        
        return reflection_agent.create_initial_plan_with_style(intake_session, selected_style)
