"""
Console client for connecting to the backend therapy service.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any
import aiohttp
import socketio

from .base_ui import BaseUI


logger = logging.getLogger(__name__)


class ConsoleClient:
    """Console client that connects to backend therapy service via API and WebSocket."""
    
    def __init__(self, backend_url: str, websocket_url: str, user_id: str, auth_token: str):
        self.backend_url = backend_url.rstrip('/')
        self.websocket_url = websocket_url
        self.user_id = user_id
        self.auth_token = auth_token
        
        # HTTP session for API calls
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Socket.IO client for real-time communication
        self.sio = socketio.AsyncClient()
        self.connected = False
        
        # Setup Socket.IO event handlers
        self._setup_socketio_handlers()
    
    def _setup_socketio_handlers(self):
        """Setup Socket.IO event handlers."""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info("Connected to WebSocket server")
            print("✅ Connected to therapy session server")
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            logger.info("Disconnected from WebSocket server")
            print("❌ Disconnected from therapy session server")
        
        @self.sio.event
        async def response(data):
            """Handle responses from the therapy backend."""
            try:
                if data.get('type') == 'chat_response':
                    await self._display_message('therapist', data.get('message', ''))
                elif data.get('type') == 'session_started':
                    print(f"✅ {data.get('message', 'Session started')}")
                elif data.get('error'):
                    print(f"❌ Error: {data['error']}")
            except Exception as e:
                logger.error(f"Error handling WebSocket response: {e}")
        
        @self.sio.event
        async def connected(data):
            """Handle connection confirmation."""
            print(f"🔐 Authenticated as user: {data.get('user_id', 'unknown')}")
        
        @self.sio.event
        async def error(data):
            """Handle WebSocket errors."""
            print(f"❌ WebSocket Error: {data}")
    
    async def _initialize_session(self):
        """Initialize HTTP session and WebSocket connection."""
        # Create HTTP session
        self.session = aiohttp.ClientSession()
        
        # Connect to WebSocket
        try:
            await self.sio.connect(
                self.websocket_url,
                auth={
                    'user_id': self.user_id,
                    'token': self.auth_token
                }
            )
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            print(f"❌ Failed to connect to WebSocket server: {e}")
    
    async def _cleanup_session(self):
        """Cleanup HTTP session and WebSocket connection."""
        if self.sio.connected:
            await self.sio.disconnect()
        
        if self.session:
            await self.session.close()
    
    async def _api_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make an API request to the backend."""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        url = f"{self.backend_url}/api{endpoint}"
        headers = kwargs.get('headers', {})
        headers['Authorization'] = f"Bearer {self.auth_token}"
        kwargs['headers'] = headers
        
        async with self.session.request(method, url, **kwargs) as response:
            if response.content_type == 'application/json':
                return await response.json()
            else:
                text = await response.text()
                return {'text': text, 'status': response.status}
    
    async def _display_message(self, role: str, text: str):
        """Display a message in the console."""
        role_display = role.upper()
        if role == "therapist":
            print(f"\033[94m{role_display}\033[0m: {text}")  # Blue
        elif role == "user":
            print(f"\033[92m{role_display}\033[0m: {text}")  # Green
        else:
            print(f"\033[93m{role_display}\033[0m: {text}")  # Yellow
    
    async def _get_user_input(self, prompt: Optional[str] = None) -> str:
        """Get input from the user via console."""
        if prompt:
            print(f"{prompt}")
        
        user_input = input("\nYour response: ").strip()
        return user_input
    
    async def _send_chat_message(self, message: str):
        """Send a chat message via WebSocket."""
        if not self.connected:
            print("❌ Not connected to WebSocket server")
            return
        
        try:
            await self.sio.emit('message', {
                'type': 'chat_message',
                'data': {'message': message}
            })
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            print(f"❌ Failed to send message: {e}")
    
    async def _get_user_status(self) -> Dict[str, Any]:
        """Get user status from backend API."""
        try:
            return await self._api_request('GET', '/user/status')
        except Exception as e:
            logger.error(f"Error getting user status: {e}")
            return {'error': str(e)}
    
    async def _start_therapy_session(self):
        """Start a therapy session."""
        if not self.connected:
            print("❌ Cannot start session: not connected to server")
            return
        
        print("🎯 Starting therapy session...")
        await self.sio.emit('message', {
            'type': 'session_request',
            'data': {'session_type': 'therapy'}
        })
    
    async def run(self):
        """Run the console client interface."""
        try:
            # Initialize connections
            await self._initialize_session()
            
            # Wait a moment for connection to establish
            await asyncio.sleep(1)
            
            if not self.connected:
                print("❌ Failed to establish connection. Exiting.")
                return
            
            # Get user status
            print("📊 Checking user status...")
            status = await self._get_user_status()
            
            if 'error' in status:
                print(f"⚠️  Could not get user status: {status['error']}")
                print("Proceeding with basic session...")
            
            # Start therapy session
            await self._start_therapy_session()
            
            # Main chat loop
            print("\n💬 You can now chat with your therapist. Type 'quit' or 'exit' to end the session.")
            print("=" * 60)
            
            while True:
                try:
                    # Get user input
                    user_message = await self._get_user_input()
                    
                    # Check for exit commands
                    if user_message.lower() in ['quit', 'exit', 'bye', 'goodbye']:
                        print("👋 Ending therapy session...")
                        break
                    
                    if not user_message:
                        continue
                    
                    # Display user message
                    await self._display_message('user', user_message)
                    
                    # Send message via WebSocket
                    await self._send_chat_message(user_message)
                    
                    # Brief pause for response
                    await asyncio.sleep(0.1)
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.error(f"Error in chat loop: {e}")
                    print(f"❌ Error: {e}")
            
        finally:
            # Cleanup
            await self._cleanup_session()
