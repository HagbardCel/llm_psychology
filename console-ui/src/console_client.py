"""
Console client for connecting to the backend therapy service.
Trio-based implementation for structured concurrency.
"""

import trio
from trio_websocket import open_websocket_url, ConnectionClosed
import json
import logging
from typing import Optional, Dict, Any
import httpx

from .base_ui import BaseUI


logger = logging.getLogger(__name__)


class ConsoleClient:
    """Console client that connects to backend therapy service via API and WebSocket.

    Uses Trio for structured concurrency and automatic resource cleanup.
    """

    def __init__(self, backend_url: str, websocket_url: str, user_id: str, auth_token: str):
        self.backend_url = backend_url.rstrip('/')
        self.websocket_url = websocket_url
        self.user_id = user_id
        self.auth_token = auth_token

        # HTTP session for API calls
        self.http_client: Optional[httpx.AsyncClient] = None

        # WebSocket connection
        self.ws = None
        self.connected = False

        # Streaming state
        self.current_message = ""
        self.is_streaming = False

        # Session state
        self.session_ready = trio.Event()
        self.waiting_for_initial_message = False
        self.waiting_for_response = False
        self.response_complete = trio.Event()

    async def _websocket_receiver(self, ws):
        """Background task to receive and handle WebSocket messages."""
        try:
            while True:
                try:
                    message = await ws.get_message()
                    data = json.loads(message)
                    await self._handle_websocket_message(data)
                except ConnectionClosed:
                    logger.info("WebSocket connection closed")
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse WebSocket message: {e}")
        except Exception as e:
            logger.error(f"Error in WebSocket receiver: {e}")
        finally:
            self.connected = False
            logger.info("WebSocket receiver task ended")

    async def _handle_websocket_message(self, message: Dict[str, Any]):
        """Handle incoming WebSocket message."""
        msg_type = message.get('type')
        data = message.get('data', {})

        logger.debug(f"Received message type: {msg_type}")

        if msg_type == 'chat_response_chunk':
            await self._handle_chat_response_chunk(data)
        elif msg_type == 'session_started':
            await self._handle_session_started(data)
        elif msg_type == 'connected':
            await self._handle_connected(data)
        elif msg_type == 'typing_start':
            await self._handle_typing_start()
        elif msg_type == 'typing_stop':
            await self._handle_typing_stop()
        elif msg_type == 'error':
            await self._handle_error(data)
        else:
            logger.warning(f"Unknown message type: {msg_type}")

    async def _handle_chat_response_chunk(self, data: Dict[str, Any]):
        """Handle streaming response chunks from therapist."""
        try:
            chunk = data.get('chunk', '')
            is_complete = data.get('is_complete', False)

            if not is_complete:
                # Accumulate and display chunk
                if not self.is_streaming:
                    # First chunk - start new message
                    print("\n\033[94mTHERAPIST\033[0m: ", end='', flush=True)
                    self.is_streaming = True
                    self.current_message = ""

                # Display chunk in real-time
                print(chunk, end='', flush=True)
                self.current_message += chunk
            else:
                # Streaming complete
                if self.is_streaming:
                    print()  # New line after complete message
                    self.is_streaming = False
                    self.current_message = ""

                # If we were waiting for initial message, show welcome UI and signal ready
                if self.waiting_for_initial_message:
                    self.waiting_for_initial_message = False
                    # Show welcome message AFTER therapist greeting completes
                    print("\n💬 You can now chat with your therapist. Type '/quit' to end the session.", flush=True)
                    print("=" * 60, flush=True)
                    print()  # Add blank line for better visibility
                    self.session_ready.set()

                # Signal response complete for regular messages
                if self.waiting_for_response:
                    self.response_complete.set()
                    self.waiting_for_response = False

        except Exception as e:
            logger.error(f"Error handling streaming chunk: {e}")

    async def _handle_session_started(self, data: Dict[str, Any]):
        """Handle session started confirmation."""
        # Check if there's an initial message coming
        has_initial_message = data.get('has_initial_message', False)

        if has_initial_message:
            # Wait for the initial message before allowing user input
            # (Welcome message will be shown AFTER therapist greeting completes)
            self.waiting_for_initial_message = True
        else:
            # No initial message, ready to start immediately
            print(f"\n✅ Your therapy session has begun.", flush=True)
            print("\n💬 You can now chat with your therapist. Type '/quit' to end the session.", flush=True)
            print("=" * 60, flush=True)
            print()  # Add blank line for better visibility
            self.session_ready.set()

    async def _handle_connected(self, data: Dict[str, Any]):
        """Handle connection confirmation."""
        user_id = data.get('user_id', 'unknown')
        name = data.get('name', user_id)
        status = data.get('status', 'unknown')
        
        print(f"🔐 Connected as: {name} (user_id: {user_id})", flush=True)
        if status == 'PROFILE_ONLY':
            print(f"ℹ️  New user profile created", flush=True)

    async def _handle_typing_start(self):
        """Handle therapist typing indicator."""
        if not self.is_streaming:
            print("\n💭 Therapist is typing...", end='\r')

    async def _handle_typing_stop(self):
        """Handle therapist stopped typing."""
        if not self.is_streaming:
            print(" " * 30, end='\r')  # Clear typing indicator

    async def _handle_error(self, data: Dict[str, Any]):
        """Handle WebSocket errors."""
        print(f"\n❌ Error: {data.get('message', data)}")

    async def _api_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make an API request to the backend."""
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

        url = f"{self.backend_url}/api{endpoint}"
        headers = kwargs.get('headers', {})
        headers['Authorization'] = f"Bearer {self.auth_token}"
        kwargs['headers'] = headers

        response = await self.http_client.request(method, url, **kwargs)

        if response.headers.get('content-type', '').startswith('application/json'):
            return response.json()
        else:
            return {'text': response.text, 'status': response.status_code}

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
        """Get input from the user via console (non-blocking)."""
        if prompt:
            print(f"{prompt}")

        # Use trio.to_thread to avoid blocking the event loop
        user_input = await trio.to_thread.run_sync(
            lambda: input("\nYour response: ").strip()
        )
        return user_input

    async def _send_chat_message(self, ws, message: str):
        """Send a chat message via WebSocket."""
        if not self.connected or not ws:
            print("❌ Not connected to WebSocket server")
            return

        try:
            msg_data = {
                'type': 'chat_message',
                'data': {'message': message}
            }
            await ws.send_message(json.dumps(msg_data))
            logger.debug(f"Sent chat message: {message[:50]}...")
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            print(f"❌ Failed to send message: {e}")

    async def _get_user_status(self) -> Dict[str, Any]:
        """Get user status from backend API."""
        try:
            return await self._api_request('GET', '/user/status', params={'user_id': self.user_id})
        except Exception as e:
            logger.error(f"Error getting user status: {e}")
            return {'error': str(e)}

    async def _start_therapy_session(self, ws):
        """Start a therapy session."""
        if not self.connected or not ws:
            print("❌ Cannot start session: not connected to server", flush=True)
            return

        print("🎯 Starting therapy session...", flush=True)
        msg_data = {
            'type': 'session_request',
            'data': {'session_type': 'therapy'}
        }
        await ws.send_message(json.dumps(msg_data))

    async def run(self):
        """Run the console client interface with structured concurrency."""
        # Create HTTP client
        async with httpx.AsyncClient() as http_client:
            self.http_client = http_client

            # Connect to WebSocket and run with structured concurrency
            ws_url = self.websocket_url.replace('http://', 'ws://').replace('https://', 'wss://')
            if not ws_url.endswith('/ws'):
                ws_url = f"{ws_url}/ws"
            
            # Add user_id as query parameter
            ws_url = f"{ws_url}?user_id={self.user_id}"

            logger.info(f"Connecting to WebSocket: {ws_url}")

            try:
                async with open_websocket_url(ws_url) as ws:
                    self.ws = ws
                    self.connected = True
                    logger.info("Connected to WebSocket server")
                    print("✅ Connected to therapy session server", flush=True)

                    # Use nursery for structured concurrency
                    async with trio.open_nursery() as nursery:
                        # Start WebSocket receiver task
                        nursery.start_soon(self._websocket_receiver, ws)

                        # Give connection a moment to stabilize
                        await trio.sleep(1)

                        if not self.connected:
                            print("❌ Failed to establish connection. Exiting.", flush=True)
                            nursery.cancel_scope.cancel()
                            return

                        # Get user status
                        print("📊 Checking user status...", flush=True)
                        status = await self._get_user_status()

                        if 'error' in status:
                            print(f"⚠️  Could not get user status: {status['error']}", flush=True)
                            print("Proceeding with basic session...", flush=True)

                        # Start therapy session
                        await self._start_therapy_session(ws)

                        # Wait for session to be fully ready (including any initial message)
                        await self.session_ready.wait()

                        # Main chat loop (welcome message already shown in session_started handler)
                        try:
                            while True:
                                try:
                                    # Get user input
                                    user_message = await self._get_user_input()

                                    # Check for system commands (starting with /)
                                    if user_message.startswith('/'):
                                        command = user_message.lower().strip()
                                        if command in ['/quit', '/exit']:
                                            print("👋 Ending therapy session...")
                                            break
                                        else:
                                            print(f"⚠️  Unknown command: {command}. Type '/quit' to exit.", flush=True)
                                            continue

                                    if not user_message:
                                        continue

                                    # Display user message
                                    await self._display_message('user', user_message)

                                    # Send message via WebSocket and wait for response
                                    self.waiting_for_response = True
                                    self.response_complete = trio.Event()
                                    await self._send_chat_message(ws, user_message)

                                    # Wait for response to complete before prompting for next input
                                    await self.response_complete.wait()

                                except KeyboardInterrupt:
                                    break
                                except Exception as e:
                                    logger.error(f"Error in chat loop: {e}")
                                    print(f"❌ Error: {e}")
                        finally:
                            # Cancel nursery to clean up receiver task
                            nursery.cancel_scope.cancel()

            except ConnectionClosed:
                print("❌ WebSocket connection closed unexpectedly", flush=True)
                logger.error("WebSocket connection closed")
            except Exception as e:
                logger.error(f"Failed to connect to WebSocket: {e}")
                print(f"❌ Failed to connect to WebSocket server: {e}", flush=True)
