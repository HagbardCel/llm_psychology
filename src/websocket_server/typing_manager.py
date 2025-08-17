"""Typing indicator manager for WebSocket connections."""

import logging
import asyncio
from typing import Dict, Set
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TypingManager:
    """Manages typing indicators for WebSocket connections."""
    
    def __init__(self, timeout_seconds: int = 5):
        self.typing_users: Dict[str, datetime] = {}  # user_id -> last typing time
        self.timeout_seconds = timeout_seconds
        self._cleanup_task = None
        self._running = False
    
    async def start(self):
        """Start the typing manager cleanup task."""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_typing())
        logger.info("Typing manager started")
    
    async def stop(self):
        """Stop the typing manager."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Typing manager stopped")
    
    def start_typing(self, user_id: str) -> bool:
        """
        Mark user as typing.
        
        Args:
            user_id: User identifier
            
        Returns:
            bool: True if this is a new typing session
        """
        was_typing = user_id in self.typing_users
        self.typing_users[user_id] = datetime.now()
        
        if not was_typing:
            logger.debug(f"User {user_id} started typing")
            return True
        
        return False
    
    def stop_typing(self, user_id: str) -> bool:
        """
        Mark user as stopped typing.
        
        Args:
            user_id: User identifier
            
        Returns:
            bool: True if user was typing
        """
        was_typing = user_id in self.typing_users
        if was_typing:
            del self.typing_users[user_id]
            logger.debug(f"User {user_id} stopped typing")
        
        return was_typing
    
    def is_typing(self, user_id: str) -> bool:
        """Check if user is currently typing."""
        if user_id not in self.typing_users:
            return False
        
        # Check if typing session has expired
        last_typing = self.typing_users[user_id]
        if datetime.now() - last_typing > timedelta(seconds=self.timeout_seconds):
            del self.typing_users[user_id]
            return False
        
        return True
    
    def get_typing_users(self) -> Set[str]:
        """Get set of currently typing users."""
        current_time = datetime.now()
        expired_users = []
        
        # Check for expired typing sessions
        for user_id, last_typing in self.typing_users.items():
            if current_time - last_typing > timedelta(seconds=self.timeout_seconds):
                expired_users.append(user_id)
        
        # Remove expired users
        for user_id in expired_users:
            del self.typing_users[user_id]
        
        return set(self.typing_users.keys())
    
    def get_typing_count(self) -> int:
        """Get count of currently typing users."""
        return len(self.get_typing_users())
    
    async def _cleanup_expired_typing(self):
        """Background task to clean up expired typing indicators."""
        while self._running:
            try:
                # Clean up expired typing sessions
                self.get_typing_users()  # This will clean up expired sessions
                
                # Sleep for cleanup interval
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in typing cleanup task: {e}")
                await asyncio.sleep(1)
