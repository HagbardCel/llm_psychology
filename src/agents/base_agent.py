"""Base class for conversational agents with shared session management."""

import uuid
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional
from services.llm_service import LLMService
from services.db_service import DatabaseService
from context.user_context import UserContext
from models.data_models import Session, Message
from ui.base_ui import BaseUI
from agents.session_manager import (
    TherapySessionManager, SessionContext, ConversationContext, SessionState
)


class BaseConversationalAgent(ABC):
    """
    Base class providing common session management for all conversational agents.
    
    This class implements the Template Method pattern, providing a shared session
    lifecycle while allowing agents to customize specific behaviors through
    abstract and hook methods.
    """
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, user_context: UserContext):
        """
        Initialize the base conversational agent.
        
        Args:
            llm_service: The LLM service for generating responses
            db_service: The database service for storing sessions
            user_context: User context for this session
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.user_context = user_context
        self.session_manager = TherapySessionManager()
        self.logger = logging.getLogger(__name__)
    
    async def conduct_session(self, context: Any, duration_minutes: int, ui: BaseUI) -> Session:
        """
        Main session orchestrator - shared across all agents.
        
        This template method defines the common session flow while allowing
        customization through abstract and hook methods.
        
        Args:
            context: Agent-specific context (e.g., TherapyPlan, assessment data)
            duration_minutes: Duration of the session in minutes
            ui: The UI interface to use for interaction
            
        Returns:
            Session: The completed session
        """
        # Initialize session
        session = self._initialize_session()
        session_context = self.session_manager.create_session_context(
            session, duration_minutes, **self._get_session_config()
        )
        
        # Pre-conversation setup
        await self.pre_conversation_setup(session, context, ui)
        
        # Display initial greeting
        initial_prompt = await self.get_initial_prompt(context)
        initial_response = self.llm_service.generate_response(initial_prompt)
        await ui.display_message(self._get_agent_display_name(), initial_response)
        
        # Add initial greeting to transcript
        session.transcript.append(Message(
            role="assistant",
            content=initial_response,
            timestamp=datetime.now()
        ))
        
        # Update conversation context with agent-specific data
        conv_context = ConversationContext(
            agent_type=self._get_agent_type(),
            session_context=session_context,
            custom_data=await self.get_initial_conversation_context(context)
        )
        
        # Run main conversation loop
        session_context = await self.session_manager.run_conversation_loop(
            session_context=session_context,
            ui=ui,
            message_handler=self._create_message_handler(conv_context),
            response_customizer=self._create_response_customizer(conv_context)
        )
        
        # Generate closing response if session completed naturally
        if session_context.state == SessionState.COMPLETED:
            closing_response = await self.get_closing_response(conv_context)
            if closing_response:
                await ui.display_message(self._get_agent_display_name(), closing_response)
                session.transcript.append(Message(
                    role="assistant",
                    content=closing_response,
                    timestamp=datetime.now()
                ))
        
        # Post-conversation cleanup
        await self.post_conversation_cleanup(session, context, ui)
        
        # Save session
        self.db_service.save_session(session)
        await ui.display_system_status("Session completed and saved.")
        
        return session
    
    # Abstract Methods - Must be implemented by concrete agents
    
    @abstractmethod
    async def get_initial_prompt(self, context: Any) -> str:
        """Get the initial prompt for the session."""
        pass
    
    @abstractmethod
    async def handle_user_message(self, message: str, conv_context: ConversationContext) -> str:
        """Handle a user message and generate a response."""
        pass
    
    @abstractmethod
    async def get_initial_conversation_context(self, context: Any) -> Dict[str, Any]:
        """Get initial conversation context data."""
        pass
    
    # Hook Methods - Optional customization points
    
    async def pre_conversation_setup(self, session: Session, context: Any, ui: BaseUI) -> None:
        """Optional pre-conversation setup."""
        pass
    
    async def post_conversation_cleanup(self, session: Session, context: Any, ui: BaseUI) -> None:
        """Optional post-conversation cleanup."""
        pass
    
    async def customize_response(self, response: str, conv_context: ConversationContext) -> str:
        """Optional response post-processing."""
        return response
    
    async def should_extend_session(self, conv_context: ConversationContext) -> bool:
        """Optional custom extension logic."""
        return True  # Default: allow extensions
    
    async def get_closing_response(self, conv_context: ConversationContext) -> Optional[str]:
        """Optional closing response generation."""
        return None
    
    def _get_session_config(self) -> Dict[str, Any]:
        """Get session configuration parameters."""
        return {
            'max_extensions': 2,
            'extension_duration_minutes': 5,
            'warning_threshold_minutes': 10
        }
    
    def _get_agent_type(self) -> str:
        """Get the agent type identifier."""
        return self.__class__.__name__.lower().replace('agent', '')
    
    def _get_agent_display_name(self) -> str:
        """Get the display name for the agent in UI."""
        return "agent"
    
    def _initialize_session(self) -> Session:
        """Initialize a new session."""
        return Session(
            session_id=str(uuid.uuid4()),
            user_id=self.user_context.user_id,
            timestamp=datetime.now(),
            transcript=[]
        )
    
    def _create_message_handler(self, conv_context: ConversationContext):
        """Create a message handler for the session manager."""
        async def handler(message: str, context: ConversationContext) -> str:
            return await self.handle_user_message(message, context)
        return handler
    
    def _create_response_customizer(self, conv_context: ConversationContext):
        """Create a response customizer for the session manager."""
        async def customizer(response: str, context: ConversationContext) -> str:
            return await self.customize_response(response, context)
        return customizer