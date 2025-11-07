"""Connection manager for WebSocket sessions."""

import logging
from typing import Dict, Optional, Set
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and user sessions."""
    
    def __init__(self):
        self.connections: Dict[str, dict] = {}  # sid -> connection info
        self.user_sessions: Dict[str, str] = {}  # user_id -> sid
        self.active_sessions: Set[str] = set()  # session IDs
        
    async def connect_user(self, sid: str, user_id: str, auth_token: str) -> bool:
        """
        Connect a user with authentication.
        
        Args:
            sid: Socket ID
            user_id: User identifier
            auth_token: Authentication token
            
        Returns:
            bool: True if connection successful
        """
        try:
            # TODO: Implement proper token validation
            # For now, accept any non-empty token
            if not auth_token:
                logger.warning(f"Connection rejected for user {user_id}: No auth token")
                return False
                
            # Store connection info
            self.connections[sid] = {
                "user_id": user_id,
                "auth_token": auth_token,
                "connected_at": datetime.now(),
                "last_activity": datetime.now()
            }
            
            # Update user session mapping
            if user_id in self.user_sessions:
                # User already connected, disconnect old session
                old_sid = self.user_sessions[user_id]
                if old_sid in self.connections:
                    logger.info(f"Disconnecting old session for user {user_id}")
                    del self.connections[old_sid]
                    
            self.user_sessions[user_id] = sid
            self.active_sessions.add(sid)
            
            logger.info(f"User {user_id} connected with session {sid}")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting user {user_id}: {e}")
            return False
    
    async def disconnect_user(self, sid: str) -> Optional[str]:
        """
        Disconnect a user session.
        
        Args:
            sid: Socket ID
            
        Returns:
            Optional[str]: User ID if found
        """
        try:
            if sid not in self.connections:
                return None
                
            connection_info = self.connections[sid]
            user_id = connection_info["user_id"]
            
            # Clean up connection data
            del self.connections[sid]
            if user_id in self.user_sessions and self.user_sessions[user_id] == sid:
                del self.user_sessions[user_id]
            self.active_sessions.discard(sid)
            
            logger.info(f"User {user_id} disconnected from session {sid}")
            return user_id
            
        except Exception as e:
            logger.error(f"Error disconnecting session {sid}: {e}")
            return None
    
    def get_user_id(self, sid: str) -> Optional[str]:
        """Get user ID for a session."""
        connection = self.connections.get(sid)
        return connection["user_id"] if connection else None
    
    def get_user_session(self, user_id: str) -> Optional[str]:
        """Get session ID for a user."""
        return self.user_sessions.get(user_id)
    
    def is_authenticated(self, sid: str) -> bool:
        """Check if session is authenticated."""
        return sid in self.connections
    
    def update_activity(self, sid: str):
        """Update last activity timestamp for a session."""
        if sid in self.connections:
            self.connections[sid]["last_activity"] = datetime.now()
    
    def get_connection_info(self, sid: str) -> Optional[dict]:
        """Get connection information for a session."""
        return self.connections.get(sid)
    
    def get_active_connections_count(self) -> int:
        """Get count of active connections."""
        return len(self.active_sessions)
    
    def get_connected_users(self) -> Set[str]:
        """Get set of connected user IDs."""
        return set(self.user_sessions.keys())
