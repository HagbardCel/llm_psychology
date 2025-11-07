from datetime import datetime
from typing import Dict, Any, Optional
from services.llm_service import LLMService
from services.db_service import DatabaseService
from services.rag_service import RAGService
from services.style_service import style_service
from models.data_models import Session, TherapyPlan, UserProfile
from context.user_context import UserContext
from prompts.psychoanalyst_prompts import INITIAL_SESSION_PROMPT, CONTINUE_SESSION_PROMPT, CLOSING_SESSION_PROMPT
from ui.base_ui import BaseUI
from agents.base_agent import BaseConversationalAgent
from agents.session_manager import ConversationContext

class PsychoanalystAgent(BaseConversationalAgent):
    """Agent responsible for conducting the main conversational sessions based on the therapy plan."""
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, rag_service: RAGService, user_context: UserContext):
        """
        Initialize the Psychoanalyst Agent.
        
        Args:
            llm_service (LLMService): The LLM service for generating responses.
            db_service (DatabaseService): The database service for storing sessions.
            rag_service (RAGService): The RAG service for retrieving domain knowledge.
            user_context (UserContext): User context for this therapy session.
        """
        super().__init__(llm_service, db_service, user_context)
        self.rag_service = rag_service
    
    async def conduct_session(self, therapy_plan: TherapyPlan, session_duration_minutes: int, ui: BaseUI) -> Session:
        """
        Conduct a therapy session based on the provided therapy plan.
        
        This method now uses the base class session management with proper extension handling.
        """
        # Validate that therapy_plan is provided
        if therapy_plan is None:
            from exceptions import PsychoanalystAgentError
            raise PsychoanalystAgentError("Therapy plan is required to conduct a session")
        
        # Delegate to base class with therapy plan as context
        return await super().conduct_session(therapy_plan, session_duration_minutes, ui)
    
    # Abstract method implementations
    
    async def get_initial_prompt(self, therapy_plan: TherapyPlan) -> str:
        """Get the initial prompt for the therapy session."""
        selected_style = therapy_plan.selected_therapy_style
        
        # Get user profile for personalization
        user_profile = self.db_service.get_user_profile(self.user_context.user_id)
        user_name = user_profile.name if user_profile else "Client"
        
        # Get plan context
        plan_context = self._build_plan_context(therapy_plan)
        
        # Use style-specific prompt if available
        if selected_style and style_service.get_style_pack(selected_style):
            therapist_prompt = style_service.get_psychoanalyst_prompt(selected_style)
            return f"""
{therapist_prompt}

Context for this session:
{plan_context}

User's name: {user_name}

Please provide an appropriate initial greeting for the session.
"""
        else:
            return INITIAL_SESSION_PROMPT.format(
                user_name=user_name,
                plan_context=plan_context
            )
    
    async def handle_user_message(self, message: str, conv_context: ConversationContext) -> str:
        """Handle a user message and generate a therapy response."""
        therapy_plan = conv_context.get('therapy_plan')
        selected_style = therapy_plan.selected_therapy_style if therapy_plan else None
        
        # Get relevant RAG knowledge
        recent_context = " ".join([
            msg.content for msg in conv_context.session_context.session.transcript[-3:]
        ])
        
        if selected_style:
            knowledge_source = style_service.get_knowledge_source(selected_style)
            context_knowledge = self.rag_service.retrieve_relevant_knowledge(
                recent_context, n_results=1, filter_source=knowledge_source
            )
        else:
            context_knowledge = self.rag_service.retrieve_relevant_knowledge(recent_context, n_results=1)
        
        # Build response prompt
        plan_context = conv_context.get('plan_context', '')
        context_messages = [
            {"role": msg.role, "content": msg.content} 
            for msg in conv_context.session_context.session.transcript
        ]
        
        if selected_style and style_service.get_style_pack(selected_style):
            therapist_prompt = style_service.get_psychoanalyst_prompt(selected_style)
            response_prompt = f"""
{therapist_prompt}

Context for this session:
{plan_context}

Additional relevant knowledge:
{context_knowledge[0]['content'] if context_knowledge else 'None'}

Please continue the session based on the conversation history and maintain your therapeutic approach.
"""
        else:
            response_prompt = CONTINUE_SESSION_PROMPT.format(
                plan_context=plan_context,
                additional_knowledge=context_knowledge[0]['content'] if context_knowledge else 'None',
                time_prompt=""
            )
        
        return self.llm_service.generate_response(response_prompt, context_messages)
    
    async def get_initial_conversation_context(self, therapy_plan: TherapyPlan) -> Dict[str, Any]:
        """Get initial conversation context data."""
        return {
            'therapy_plan': therapy_plan,
            'plan_context': self._build_plan_context(therapy_plan)
        }
    
    # Hook method overrides
    
    async def pre_conversation_setup(self, session: Session, therapy_plan: TherapyPlan, ui: BaseUI) -> None:
        """Display therapy session setup information."""
        user_profile = self.db_service.get_user_profile(self.user_context.user_id)
        user_name = user_profile.name if user_profile else "Client"
        selected_style = therapy_plan.selected_therapy_style
        
        await ui.display_system_status(f"Starting therapy session for {user_name}...")
        if selected_style:
            await ui.display_system_status(f"Therapy Style: {selected_style.upper()}")
        await ui.display_system_status(f"Session Focus: {therapy_plan.plan_details.get('focus', 'Exploring your thoughts and feelings')}")
        await ui.display_system_status("You can end the session at any time by typing 'quit', 'exit', or 'bye'.")
        await ui.display_system_status("Please share what's on your mind today.\n")
    
    async def get_closing_response(self, conv_context: ConversationContext) -> Optional[str]:
        """Generate a closing response for the therapy session."""
        therapy_plan = conv_context.get('therapy_plan')
        selected_style = therapy_plan.selected_therapy_style if therapy_plan else None
        plan_context = conv_context.get('plan_context', '')
        
        if selected_style and style_service.get_style_pack(selected_style):
            therapist_prompt = style_service.get_psychoanalyst_prompt(selected_style)
            closing_prompt = f"""
{therapist_prompt}

Context for this session:
{plan_context}

Please provide an appropriate closing for the session.
"""
        else:
            closing_prompt = CLOSING_SESSION_PROMPT.format(plan_context=plan_context)
        
        return self.llm_service.generate_response(closing_prompt)
    
    def _get_agent_display_name(self) -> str:
        """Get the display name for the agent in UI."""
        return "therapist"
    
    # Private helper methods
    
    def _build_plan_context(self, therapy_plan: TherapyPlan) -> str:
        """Build the therapy plan context string."""
        selected_style = therapy_plan.selected_therapy_style
        plan_focus = therapy_plan.plan_details.get('focus', '')
        
        # Get relevant knowledge
        if selected_style:
            knowledge_source = style_service.get_knowledge_source(selected_style)
            relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(
                plan_focus, n_results=2, filter_source=knowledge_source
            )
        else:
            relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(plan_focus, n_results=2)
        
        # Build context
        context = f"""
        Therapy Plan (Version {therapy_plan.version}):
        Focus: {therapy_plan.plan_details.get('focus', 'General exploration')}
        Goals: {therapy_plan.plan_details.get('goals', 'Explore thoughts and feelings')}
        Techniques: {therapy_plan.plan_details.get('techniques', 'Active listening and reflection')}
        
        Relevant Psychological Knowledge:
        """
        
        for i, knowledge in enumerate(relevant_knowledge, 1):
            context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"
        
        return context
