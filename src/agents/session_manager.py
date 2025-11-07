"""Session management and state handling for conversational agents."""

import time
import logging
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Awaitable
from models.data_models import Session, Message
from ui.base_ui import BaseUI


class SessionState(Enum):
    """Represents the current state of a therapy session."""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    TIME_WARNING = "time_warning"
    TIME_EXPIRED = "time_expired"
    EXTENDING = "extending"
    CLOSING = "closing"
    COMPLETED = "completed"


@dataclass
class SessionContext:
    """Context information for managing a session."""
    session: Session
    state: SessionState
    start_time: float
    end_time: float
    duration_minutes: int
    extensions_granted: int = 0
    max_extensions: int = 2
    extension_duration_minutes: int = 5
    warning_threshold_minutes: int = 10
    
    @property
    def remaining_time_seconds(self) -> float:
        """Get remaining time in seconds."""
        return max(0, self.end_time - time.time())
    
    @property
    def remaining_time_minutes(self) -> int:
        """Get remaining time in minutes."""
        return int(self.remaining_time_seconds / 60)
    
    @property
    def is_time_expired(self) -> bool:
        """Check if session time has expired."""
        return self.remaining_time_seconds <= 0
    
    @property
    def should_show_time_warning(self) -> bool:
        """Check if time warning should be shown."""
        return (self.remaining_time_minutes <= self.warning_threshold_minutes 
                and self.state == SessionState.ACTIVE)
    
    @property
    def can_extend(self) -> bool:
        """Check if session can be extended."""
        return self.extensions_granted < self.max_extensions
    
    def extend_session(self) -> None:
        """Extend the session by the configured duration."""
        if not self.can_extend:
            raise ValueError("Maximum extensions reached")
        
        self.end_time = time.time() + (self.extension_duration_minutes * 60)
        self.extensions_granted += 1
        self.state = SessionState.EXTENDING


@dataclass
class ConversationContext:
    """Context for conversation management and customization."""
    agent_type: str
    session_context: SessionContext
    custom_data: Dict[str, Any]
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get custom data value."""
        return self.custom_data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set custom data value."""
        self.custom_data[key] = value


class TherapySessionManager:
    """Manages session state, time management, and conversation flow."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def create_session_context(self, session: Session, duration_minutes: int, **kwargs) -> SessionContext:
        """Create a new session context with timing information."""
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)
        
        return SessionContext(
            session=session,
            state=SessionState.INITIALIZING,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            max_extensions=kwargs.get('max_extensions', 2),
            extension_duration_minutes=kwargs.get('extension_duration_minutes', 5),
            warning_threshold_minutes=kwargs.get('warning_threshold_minutes', 10)
        )
    
    async def run_conversation_loop(
        self,
        session_context: SessionContext,
        ui: BaseUI,
        message_handler: Callable[[str, ConversationContext], Awaitable[str]],
        response_customizer: Optional[Callable[[str, ConversationContext], Awaitable[str]]] = None
    ) -> SessionContext:
        """Main conversation loop with proper extension handling."""
        
        conv_context = ConversationContext(
            agent_type="agent",  # Will be set by concrete agents
            session_context=session_context,
            custom_data={}
        )
        
        session_context.state = SessionState.ACTIVE
        
        while session_context.state in [SessionState.ACTIVE, SessionState.EXTENDING]:
            # Check time and handle warnings/expiry
            if session_context.is_time_expired and session_context.state in [SessionState.ACTIVE, SessionState.EXTENDING]:
                session_context.state = await self._handle_time_expiry(ui, session_context)
                if session_context.state == SessionState.CLOSING:
                    break
                elif session_context.state == SessionState.EXTENDING:
                    # Continue with the extended time
                    continue
            elif session_context.should_show_time_warning:
                await self._show_time_warning(ui, session_context)
                session_context.state = SessionState.TIME_WARNING
            
            # Get user input
            user_input = await ui.get_user_input()
            
            # Check for quit commands
            if self._is_quit_command(user_input):
                await ui.display_system_status("You've chosen to end the session.")
                session_context.state = SessionState.CLOSING
                break
            
            # Process non-empty input
            if user_input.strip():
                # Add user message to transcript
                session_context.session.transcript.append(Message(
                    role="user",
                    content=user_input,
                    timestamp=datetime.now()
                ))
                
                # Generate response through agent-specific handler
                response = await message_handler(user_input, conv_context)
                
                # Apply response customization if provided
                if response_customizer:
                    response = await response_customizer(response, conv_context)
                
                # Display response
                await ui.display_message("agent", response)
                
                # Add assistant response to transcript
                session_context.session.transcript.append(Message(
                    role="assistant",
                    content=response,
                    timestamp=datetime.now()
                ))
                
                # Reset state to active if we were showing warnings
                if session_context.state == SessionState.TIME_WARNING:
                    session_context.state = SessionState.ACTIVE
        
        session_context.state = SessionState.COMPLETED
        return session_context
    
    async def _handle_time_expiry(self, ui: BaseUI, session_context: SessionContext) -> SessionState:
        """Handle session time expiry with extension logic."""
        await ui.display_system_status("Our session time is now up.")
        
        if not session_context.can_extend:
            await ui.display_system_status("Maximum extensions reached. Session will now close.")
            return SessionState.CLOSING
        
        while True:
            extend_input = await ui.get_user_input("Would you like to continue for another 5 minutes to wrap up? (y/n): ")
            extend_choice = extend_input.strip().lower()
            
            if extend_choice == 'y':
                session_context.extend_session()
                await ui.display_system_status("Okay, let's continue for another 5 minutes.")
                self.logger.info(f"Session extended. Extensions granted: {session_context.extensions_granted}")
                return SessionState.EXTENDING
            elif extend_choice == 'n':
                return SessionState.CLOSING
            else:
                await ui.display_system_status("Invalid input. Please enter 'y' or 'n'.")
    
    async def _show_time_warning(self, ui: BaseUI, session_context: SessionContext) -> None:
        """Show time warning to user."""
        remaining_minutes = session_context.remaining_time_minutes
        await ui.display_system_status(f"Time remaining: {remaining_minutes} minutes.")
    
    def _is_quit_command(self, user_input: str) -> bool:
        """Check if user input is a quit command."""
        quit_commands = ['quit', 'exit', 'bye', 'goodbye']
        return user_input.lower().strip() in quit_commands