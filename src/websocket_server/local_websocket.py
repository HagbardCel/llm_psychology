"""Local WebSocket server for real-time communication."""

import logging
import asyncio
from typing import Dict, Any, Optional
import socketio
from aiohttp import web

from .connection_manager import ConnectionManager
from .message_handler import MessageHandler
from .typing_manager import TypingManager

logger = logging.getLogger(__name__)


class LocalWebSocketServer:
    """WebSocket server for real-time therapy session communication."""
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        
        # Initialize components
        self.connection_manager = ConnectionManager()
        self.message_handler = MessageHandler(self.connection_manager)
        self.typing_manager = TypingManager()
        
        # Initialize Socket.IO server
        self.sio = socketio.AsyncServer(
            cors_allowed_origins="*",
            logger=logger,
            engineio_logger=logger
        )
        
        # Create aiohttp app
        self.app = web.Application()
        self.sio.attach(self.app)
        
        # Register event handlers
        self._register_handlers()
        
        self._server = None
        self._runner = None
    
    def _register_handlers(self):
        """Register WebSocket event handlers."""
        
        @self.sio.event
        async def connect(sid, environ, auth):
            """Handle client connection."""
            try:
                # Extract authentication data
                user_id = auth.get("user_id") if auth else None
                auth_token = auth.get("token") if auth else None
                
                if not user_id or not auth_token:
                    logger.warning(f"Connection rejected from {sid}: Missing auth data")
                    return False
                
                # Authenticate user
                success = await self.connection_manager.connect_user(sid, user_id, auth_token)
                if not success:
                    logger.warning(f"Connection rejected for user {user_id}")
                    return False
                
                # Send connection confirmation
                await self.sio.emit("connected", {
                    "status": "connected",
                    "user_id": user_id,
                    "timestamp": asyncio.get_event_loop().time()
                }, room=sid)
                
                logger.info(f"User {user_id} connected successfully")
                return True
                
            except Exception as e:
                logger.error(f"Error during connection: {e}")
                return False
        
        @self.sio.event
        async def disconnect(sid):
            """Handle client disconnection."""
            try:
                user_id = await self.connection_manager.disconnect_user(sid)
                if user_id:
                    # Stop typing if user was typing
                    self.typing_manager.stop_typing(user_id)
                    logger.info(f"User {user_id} disconnected")
                
            except Exception as e:
                logger.error(f"Error during disconnection: {e}")
        
        @self.sio.event
        async def message(sid, data):
            """Handle incoming messages."""
            try:
                if not isinstance(data, dict):
                    await self.sio.emit("error", {"error": "Invalid message format"}, room=sid)
                    return
                
                event_type = data.get("type")
                message_data = data.get("data", {})
                
                if not event_type:
                    await self.sio.emit("error", {"error": "Missing message type"}, room=sid)
                    return
                
                # Handle the message
                response = await self.message_handler.handle_message(sid, event_type, message_data)
                
                if response:
                    await self.sio.emit("response", response, room=sid)
                
            except Exception as e:
                logger.error(f"Error handling message from {sid}: {e}")
                await self.sio.emit("error", {"error": "Message processing failed"}, room=sid)
        
        @self.sio.event
        async def typing_start(sid, data):
            """Handle typing start event."""
            try:
                user_id = self.connection_manager.get_user_id(sid)
                if user_id:
                    is_new = self.typing_manager.start_typing(user_id)
                    if is_new:
                        # In a multi-user scenario, broadcast to other users
                        pass
                
            except Exception as e:
                logger.error(f"Error handling typing start: {e}")
        
        @self.sio.event
        async def typing_stop(sid, data):
            """Handle typing stop event."""
            try:
                user_id = self.connection_manager.get_user_id(sid)
                if user_id:
                    was_typing = self.typing_manager.stop_typing(user_id)
                    if was_typing:
                        # In a multi-user scenario, broadcast to other users
                        pass
                
            except Exception as e:
                logger.error(f"Error handling typing stop: {e}")
        
        @self.sio.event
        async def ping(sid, data):
            """Handle ping for connection testing."""
            await self.sio.emit("pong", {"timestamp": asyncio.get_event_loop().time()}, room=sid)
    
    async def start(self):
        """Start the WebSocket server."""
        try:
            # Start typing manager
            await self.typing_manager.start()
            
            # Create and start aiohttp runner
            self._runner = web.AppRunner(self.app)
            await self._runner.setup()
            
            site = web.TCPSite(self._runner, self.host, self.port)
            await site.start()
            
            logger.info(f"WebSocket server started on {self.host}:{self.port}")
            
        except Exception as e:
            logger.error(f"Failed to start WebSocket server: {e}")
            raise
    
    async def stop(self):
        """Stop the WebSocket server."""
        try:
            # Stop typing manager
            await self.typing_manager.stop()
            
            # Stop aiohttp runner
            if self._runner:
                await self._runner.cleanup()
            
            logger.info("WebSocket server stopped")
            
        except Exception as e:
            logger.error(f"Error stopping WebSocket server: {e}")
    
    async def broadcast_to_user(self, user_id: str, event: str, data: Dict[str, Any]):
        """Broadcast message to a specific user."""
        try:
            sid = self.connection_manager.get_user_session(user_id)
            if sid:
                await self.sio.emit(event, data, room=sid)
            else:
                logger.warning(f"No active session for user {user_id}")
                
        except Exception as e:
            logger.error(f"Error broadcasting to user {user_id}: {e}")
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            "active_connections": self.connection_manager.get_active_connections_count(),
            "connected_users": list(self.connection_manager.get_connected_users()),
            "typing_users": list(self.typing_manager.get_typing_users())
        }


# Standalone server function for testing
async def run_standalone_server(host: str = "localhost", port: int = 8765):
    """Run WebSocket server as standalone application."""
    server = LocalWebSocketServer(host, port)
    
    try:
        await server.start()
        logger.info(f"Standalone WebSocket server running on {host}:{port}")
        
        # Keep server running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await server.stop()


if __name__ == "__main__":
    # Configure logging for standalone mode
    logging.basicConfig(level=logging.INFO)
    
    # Run the server
    asyncio.run(run_standalone_server())
