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
from .websocket_protocol import (
    ClientMessageTypes,
    ServerMessageTypes,
    WS_PROTOCOL_VERSION,
)


logger = logging.getLogger(__name__)


class ConsoleClient:
    """Console client that connects to backend therapy service via API and WebSocket.

    Uses Trio for structured concurrency and automatic resource cleanup.
    """

    def __init__(self, backend_url: str, websocket_url: str, user_id: str):
        self.backend_url = backend_url.rstrip("/")
        self.websocket_url = websocket_url
        self.user_id = user_id

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
        self.current_session_id: Optional[str] = None
        self.session_end_requested = False

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
        msg_type = message.get("type")
        data = message.get("data", {})

        logger.debug(f"Received message type: {msg_type}")

        if msg_type == ServerMessageTypes.CHAT_RESPONSE_CHUNK:
            await self._handle_chat_response_chunk(data)
        elif msg_type == ServerMessageTypes.SESSION_STARTED:
            await self._handle_session_started(data)
        elif msg_type == ServerMessageTypes.CONNECTED:
            await self._handle_connected(data)
        elif msg_type == ServerMessageTypes.TYPING_START:
            await self._handle_typing_start()
        elif msg_type == ServerMessageTypes.TYPING_STOP:
            await self._handle_typing_stop()
        elif msg_type == ServerMessageTypes.ERROR:
            await self._handle_error(data)
        elif msg_type == ServerMessageTypes.ASSESSMENT_RECOMMENDATIONS:
            await self._handle_assessment_recommendations(data)
        elif msg_type == ServerMessageTypes.SESSION_ENDED:
            await self._handle_session_ended(data)
        else:
            logger.warning(f"Unknown message type: {msg_type}")

    async def _handle_chat_response_chunk(self, data: Dict[str, Any]):
        """Handle streaming response chunks from therapist."""
        try:
            chunk = data.get("chunk", "")
            is_complete = data.get("is_complete", False)

            if not is_complete:
                # Accumulate and display chunk
                if not self.is_streaming:
                    # First chunk - start new message
                    print("\n\033[94mTHERAPIST\033[0m: ", end="", flush=True)
                    self.is_streaming = True
                    self.current_message = ""

                # Display chunk in real-time
                print(chunk, end="", flush=True)
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
                    print(
                        "\n💬 You can now chat with your therapist.",
                        flush=True,
                    )
                    print(
                        "   Commands: /timer (show time), /quit (finish session), /exit (close console)",
                        flush=True,
                    )
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
        # Capture session_id for timer requests
        self.current_session_id = data.get("session_id")

        # Check if there's an initial message coming
        has_initial_message = data.get("has_initial_message", False)

        if has_initial_message:
            # Wait for the initial message before allowing user input
            # (Welcome message will be shown AFTER therapist greeting completes)
            self.waiting_for_initial_message = True
        else:
            # No initial message, ready to start immediately
            print(f"\n✅ Your therapy session has begun.", flush=True)
            print(
                "\n💬 You can now chat with your therapist.",
                flush=True,
            )
            print(
                "   Commands: /timer (show time), /quit (finish session), /exit (close console)",
                flush=True,
            )
            print("=" * 60, flush=True)
            print()  # Add blank line for better visibility
            self.session_ready.set()

    async def _handle_connected(self, data: Dict[str, Any]):
        """Handle connection confirmation."""
        user_id = data.get("user_id", "unknown")
        name = data.get("name", user_id)
        status = data.get("status", "unknown")

        print(f"🔐 Connected as: {name} (user_id: {user_id})", flush=True)
        if status == "PROFILE_ONLY":
            print(f"ℹ️  New user profile created", flush=True)

    async def _handle_typing_start(self):
        """Handle therapist typing indicator."""
        if not self.is_streaming:
            print("\n💭 Therapist is typing...", end="\r")

    async def _handle_typing_stop(self):
        """Handle therapist stopped typing."""
        if not self.is_streaming:
            print(" " * 30, end="\r")  # Clear typing indicator

    async def _handle_error(self, data: Dict[str, Any]):
        """Handle WebSocket errors."""
        print(f"\n❌ Error: {data.get('message', data)}")

    async def _handle_assessment_recommendations(self, data: Dict[str, Any]):
        """Display assessment recommendations without interrupting the chat flow."""
        recommendations = data.get("recommendations") or []
        if not recommendations:
            logger.info("Received assessment_recommendations without payload")
            return

        print("\n" + "=" * 60, flush=True)
        print("🎯 ASSESSMENT RECOMMENDATIONS", flush=True)
        print("=" * 60, flush=True)
        for idx, rec in enumerate(recommendations, start=1):
            style = rec.get("style_id", f"option_{idx}")
            explanation = rec.get("explanation", "No explanation provided.")
            score = rec.get("score")
            if score is not None:
                print(f"{idx}. {style} (score: {score:.2f})", flush=True)
            else:
                print(f"{idx}. {style}", flush=True)
            print(f"   {explanation}", flush=True)
            print("---", flush=True)

        print(
            "To select a style, submit POST /api/therapy/plan "
            "with the desired therapy_style value.",
            flush=True,
        )

    async def _handle_session_ended(self, data: Dict[str, Any]):
        """Handle server-side session end notification."""
        reason = data.get("reason", "Session ended")
        print(f"\n👋 {reason}. Exiting console client.", flush=True)
        self.session_end_requested = True
        if self.waiting_for_response:
            self.response_complete.set()
            self.waiting_for_response = False

    async def _api_request(
        self, method: str, endpoint: str, **kwargs
    ) -> Dict[str, Any]:
        """Make an API request to the backend."""
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

        url = f"{self.backend_url}/api{endpoint}"
        response = await self.http_client.request(method, url, **kwargs)

        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        else:
            return {"text": response.text, "status": response.status_code}

    async def _display_message(self, role: str, text: str):
        """Display a message in the console."""
        role_display = role.upper()
        if role == "therapist":
            print(f"\033[94m{role_display}\033[0m: {text}")  # Blue
        elif role == "user":
            print(f"\033[92m{role_display}\033[0m: {text}")  # Green
        else:
            print(f"\033[93m{role_display}\033[0m: {text}")  # Yellow

    @staticmethod
    def _route_to_session_type(route: str) -> str | None:
        """Map workflow routes to session types."""
        route_map = {
            "/intake": "intake",
            "/assessment": "assessment",
            "/session/new": "therapy",
        }
        return route_map.get(route)

    async def _complete_profile(self):
        """Prompt the user for profile details and submit them via the API."""
        print("\n📝 Profile required to continue.", flush=True)
        name = await self._get_user_input("Enter your name: ")
        data_of_birth = await self._get_user_input(
            "Enter your date of birth (YYYY-MM-DD) or press Enter to skip: "
        )
        profession = await self._get_user_input(
            "Enter your profession (optional, press Enter to skip): "
        )

        payload = {
            "user_id": self.user_id,
            "name": name or self.user_id,
            "data_of_birth": data_of_birth or None,
            "profession": profession or None,
        }

        try:
            await self._api_request("POST", "/user/profile", json=payload)
            print("✅ Profile saved. Re-checking workflow...", flush=True)
        except Exception as e:
            print(f"❌ Failed to save profile: {e}", flush=True)

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
                "type": ClientMessageTypes.CHAT_MESSAGE,
                "data": {"message": message},
            }
            await ws.send_message(json.dumps(msg_data))
            logger.debug(f"Sent chat message: {message[:50]}...")
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            print(f"❌ Failed to send message: {e}")

    async def _send_end_session(self, ws, reason: str | None = None):
        """Request the backend to end the current session."""
        if not self.connected or not ws:
            print("❌ Not connected to WebSocket server")
            return

        if not self.current_session_id:
            print("⚠️  No active session to end.", flush=True)
            return

        try:
            payload = {"reason": reason} if reason else {}
            msg_data = {
                "type": ClientMessageTypes.END_SESSION,
                "data": payload,
            }
            await ws.send_message(json.dumps(msg_data))
            logger.debug("Sent end_session request for session %s", self.current_session_id)
        except Exception as e:
            logger.error(f"Error sending end_session: {e}")
            print(f"❌ Failed to end session: {e}")

    async def _get_user_status(self) -> Dict[str, Any]:
        """Get user status from backend API."""
        try:
            return await self._api_request(
                "GET", "/user/status", params={"user_id": self.user_id}
            )
        except Exception as e:
            logger.error(f"Error getting user status: {e}")
            return {"error": str(e)}

    async def _get_next_action(
        self, current_route: str | None = None
    ) -> Dict[str, Any]:
        """Fetch workflow next action from backend."""
        payload: Dict[str, Any] = {"user_id": self.user_id}
        if current_route:
            payload["current_route"] = current_route

        try:
            return await self._api_request(
                "POST", "/workflow/next-action", json=payload
            )
        except Exception as e:
            logger.error(f"Error getting workflow next action: {e}")
            return {"action": "error", "error": str(e)}

    async def _get_session_timer(self) -> Dict[str, Any]:
        """Get session timer information from backend API."""
        if not self.current_session_id:
            return {"error": "No active session"}

        try:
            return await self._api_request(
                "GET", f"/sessions/{self.current_session_id}/timer"
            )
        except Exception as e:
            logger.error(f"Error getting session timer: {e}")
            return {"error": str(e)}

    async def _display_timer_info(self):
        """Fetch and display session timer information."""
        timer_data = await self._get_session_timer()

        if "error" in timer_data:
            print(f"\n⚠️  Could not retrieve timer: {timer_data['error']}", flush=True)
            return

        # Extract timing information
        elapsed = timer_data.get("elapsed_minutes", 0)
        remaining = timer_data.get("remaining_minutes", 0)
        total = timer_data.get("total_duration_minutes", 0)
        extensions_used = timer_data.get("extensions_used", 0)
        max_extensions = timer_data.get("max_extensions", 0)
        can_extend = timer_data.get("can_extend", False)
        is_time_up = timer_data.get("is_time_up", False)

        # Format and display
        print("\n" + "=" * 60, flush=True)
        print("⏱️  SESSION TIMER", flush=True)
        print("=" * 60, flush=True)
        print(f"Time elapsed:   {int(elapsed)} minutes", flush=True)
        print(f"Time remaining: {int(remaining)} minutes", flush=True)
        print(f"Total duration: {total} minutes", flush=True)

        if extensions_used > 0:
            print(
                f"Extensions:     {extensions_used}/{max_extensions} used", flush=True
            )
        else:
            print(f"Extensions:     {max_extensions} available", flush=True)

        if is_time_up:
            print("\n⚠️  Time is up! Session should be ending soon.", flush=True)
        elif remaining < 5:
            print("\n⚠️  Less than 5 minutes remaining!", flush=True)
        elif can_extend and remaining < 10:
            print(
                f"\nℹ️  Running low on time. You can extend the session.",
                flush=True,
            )

        print("=" * 60, flush=True)
        print()

    async def _start_session(self, ws, session_type: str):
        """Start a workflow-driven session."""
        if not self.connected or not ws:
            print("❌ Cannot start session: not connected to server", flush=True)
            return

        session_type = session_type.lower()
        self.session_ready = trio.Event()
        self.waiting_for_initial_message = False
        self.current_session_id = None
        self.is_streaming = False
        self.current_message = ""
        print(f"🎯 Starting {session_type} session...", flush=True)
        msg_data = {
            "type": ClientMessageTypes.SESSION_REQUEST,
            "data": {"session_type": session_type},
        }
        await ws.send_message(json.dumps(msg_data))

    async def _chat_loop(self, ws) -> bool:
        """
        Chat loop for a single session.

        Returns:
            True if the user chose to exit the console entirely, False to continue workflow.
        """
        try:
            while True:
                if self.session_end_requested:
                    return True
                try:
                    user_message = await self._get_user_input()

                    # Slash commands
                    if user_message.startswith("/"):
                        command = user_message.lower().strip()
                        if command in ["/quit", "/end"]:
                            await self._send_end_session(ws, reason="User ended session")
                            print("👋 Ending current session...", flush=True)
                            return True
                        elif command == "/exit":
                            await self._send_end_session(ws, reason="User exited console")
                            print("👋 Exiting console client. Take care.", flush=True)
                            return True
                        elif command == "/timer":
                            await self._display_timer_info()
                            continue
                        else:
                            print(
                                "⚠️  Unknown command. Available: /timer, /quit (finish session), /exit (close console).",
                                flush=True,
                            )
                            continue

                    if not user_message:
                        continue

                    # Legacy exit keywords without slash exit the console completely
                    if user_message.lower() in ["quit", "exit", "bye"]:
                        await self._send_end_session(ws, reason="User ended session")
                        print("👋 Exiting console client.", flush=True)
                        return True

                    await self._display_message("user", user_message)

                    self.waiting_for_response = True
                    self.response_complete = trio.Event()
                    await self._send_chat_message(ws, user_message)

                    await self.response_complete.wait()

                    if self.session_end_requested:
                        return True

                except KeyboardInterrupt:
                    await self._send_end_session(ws, reason="User exited console")
                    print("\n👋 Exiting console client.", flush=True)
                    return True
                except Exception as e:
                    logger.error(f"Error in chat loop: {e}")
                    print(f"❌ Error: {e}")
        finally:
            self.waiting_for_response = False

    async def _follow_workflow(self, ws):
        """Drive the console experience based on the backend workflow."""
        current_route: str | None = None
        wait_count = 0

        while True:
            next_action = await self._get_next_action(current_route)
            action = next_action.get("action")
            route = next_action.get("route")

            if action == "error":
                print(f"❌ Workflow error: {next_action.get('error')}", flush=True)
                break

            if action == "wait":
                reason = next_action.get("reason", "Waiting for backend instructions.")
                wait_count += 1

                session_type = self._route_to_session_type(route) if route else None
                if session_type:
                    logger.info(
                        "Workflow returned wait for %s; starting %s session",
                        route,
                        session_type,
                    )
                    action = "navigate"
                else:
                    if wait_count == 1:
                        print(f"⏳ Backend requested wait: {reason}", flush=True)
                        print(
                            "   Waiting for workflow to advance... (Ctrl+C to exit)",
                            flush=True,
                        )
                        if "reflection" in reason.lower() or "session" in reason.lower():
                            print(
                                "   If this never resolves, try `make clean-testdb` "
                                "or change `USER_ID` to start a fresh user profile.",
                                flush=True,
                            )
                    elif wait_count % 10 == 0:
                        print(f"⏳ Still waiting: {reason}", flush=True)

                    if not self.connected:
                        print("⚠️  Connection lost while waiting. Exiting.", flush=True)
                        break

                    await trio.sleep(2)
                    continue

            if action == "display":
                display = next_action.get("display") or {}
                title = display.get("title") or "Workflow update"
                description = display.get("description")
                print(f"ℹ️  {title}", flush=True)
                if description:
                    print(description, flush=True)
                # Display is informational; keep polling unless connection drops.
                if not self.connected:
                    break
                await trio.sleep(2)
                continue

            if action != "navigate" or not route:
                print("⚠️  Unexpected workflow response. Exiting.", flush=True)
                break

            if route == "/profile":
                await self._complete_profile()
                current_route = route
                continue

            if route == "/dashboard":
                print(
                    "✅ Workflow complete. You can start therapy sessions from the dashboard.",
                    flush=True,
                )
                break

            session_type = self._route_to_session_type(route)
            if not session_type:
                print(f"⚠️  Unsupported workflow route: {route}", flush=True)
                break

            await self._start_session(ws, session_type)
            if not self.connected:
                print("⚠️  Connection lost while starting session. Exiting workflow.", flush=True)
                break

            await self.session_ready.wait()
            exit_console = await self._chat_loop(ws)
            current_route = route

            if exit_console:
                break

    async def run(self):
        """Run the console client interface with structured concurrency."""
        # Create HTTP client
        async with httpx.AsyncClient() as http_client:
            self.http_client = http_client

            # Connect to WebSocket and run with structured concurrency
            ws_url = self.websocket_url.replace("http://", "ws://").replace(
                "https://", "wss://"
            )
            if not ws_url.endswith("/ws"):
                ws_url = f"{ws_url}/ws"

            # Add user_id as query parameter (server only expects user_id, not token)
            ws_url = f"{ws_url}?user_id={self.user_id}"

            # Extract origin for CORS (required for WebSocket handshake)
            origin = self.backend_url  # Use backend_url as origin (e.g., http://api-usertest:8000)

            logger.info(f"Connecting to WebSocket: {ws_url}")

            try:
                # Include Origin header for CORS validation during WebSocket handshake
                async with open_websocket_url(
                    ws_url, extra_headers=[("Origin", origin)]
                ) as ws:
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
                            print(
                                "❌ Failed to establish connection. Exiting.",
                                flush=True,
                            )
                            nursery.cancel_scope.cancel()
                            return

                        # Get user status
                        print("📊 Checking user status...", flush=True)
                        status = await self._get_user_status()

                        if "error" in status:
                            print(
                                f"⚠️  Could not get user status: {status['error']}",
                                flush=True,
                            )
                            print("Proceeding with basic session...", flush=True)
                        else:
                            workflow_state = status.get("workflow_state")
                            if workflow_state:
                                print(
                                    f"📍 Current workflow state: {workflow_state}",
                                    flush=True,
                                )

                        try:
                            await self._follow_workflow(ws)
                        finally:
                            # Cancel nursery to clean up receiver task
                            nursery.cancel_scope.cancel()

            except ConnectionClosed:
                print("❌ WebSocket connection closed unexpectedly", flush=True)
                logger.error("WebSocket connection closed")
            except Exception as e:
                logger.error(f"Failed to connect to WebSocket: {e}")
                print(f"❌ Failed to connect to WebSocket server: {e}", flush=True)
