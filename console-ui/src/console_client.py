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
        self.pending_recommendations: list[dict[str, Any]] | None = None
        self.latest_workflow_action: dict[str, Any] | None = None
        self.registered = False

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
        elif msg_type == ServerMessageTypes.WORKFLOW_NEXT_ACTION:
            await self._handle_workflow_next_action(data)
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
        self.session_end_requested = False
        self.session_ready = trio.Event()
        # Always wait for the initial message before allowing user input.
        self.waiting_for_initial_message = True

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
        self.pending_recommendations = recommendations

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
            "To select a style, submit POST /api/workflow/select_therapy_style "
            "with the desired selected_therapy_style value.",
            flush=True,
        )

    async def _handle_workflow_next_action(self, data: Dict[str, Any]):
        """Store workflow next action updates for display/polling."""
        self.latest_workflow_action = data
        required_action = data.get("required_action")
        prompt = data.get("prompt")
        if required_action == "wait":
            print(f"\n⏳ {prompt or 'Waiting for backend workflow...'}", flush=True)

    async def _handle_session_ended(self, data: Dict[str, Any]):
        """Handle server-side session end notification."""
        reason = data.get("reason", "Session ended")
        print(f"\n👋 {reason}. Exiting console client.", flush=True)
        self.session_end_requested = True
        self.current_session_id = None
        self.session_ready = trio.Event()
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

    async def _complete_profile(
        self,
        required_fields: list[str] | None = None,
        defaults: dict[str, Any] | None = None,
    ):
        """Prompt the user for required profile details and submit them via the API."""
        print("\n📝 Profile required to continue.", flush=True)
        required_fields = required_fields or ["name"]
        defaults = defaults or {}

        def build_prompt(field_name: str) -> str:
            label = field_name.replace("_", " ")
            default_value = defaults.get(field_name)
            suffix = f" [{default_value}]" if default_value else ""
            return f"Enter {label}{suffix}: "

        payload: dict[str, Any] = {
            "user_id": self.user_id,
            "session_id": self.current_session_id,
        }

        for field in required_fields:
            response = await self._get_user_input(build_prompt(field))
            value = response or defaults.get(field)
            if field == "name" and not value:
                value = self.user_id
            if value:
                payload[field] = value

        try:
            if not self.current_session_id:
                print("⚠️  No active session. Please reconnect.", flush=True)
                return
            await self._api_request("POST", "/workflow/complete_profile", json=payload)
            print("✅ Profile saved. Re-checking workflow...", flush=True)
        except Exception as e:
            print(f"❌ Failed to save profile: {e}", flush=True)

    async def _select_therapy_style(self):
        """Prompt the user to select a therapy style and submit it."""
        recommendations = self.pending_recommendations
        options: list[dict[str, Any]] = []

        if not recommendations:
            print(
                "⏳ Waiting for assessment recommendations before selecting a therapy style.",
                flush=True,
            )
            await trio.sleep(2)
            return

        for rec in recommendations:
            options.append(
                {
                    "style": rec.get("style_id"),
                    "description": rec.get("explanation"),
                }
            )

        if not options:
            print("⚠️  No therapy styles available yet. Try again later.", flush=True)
            return

        print("\n🧭 Select a therapy style:", flush=True)
        for idx, option in enumerate(options, start=1):
            label = option.get("style") or f"option_{idx}"
            description = option.get("description")
            if description:
                print(f"{idx}. {label} - {description}", flush=True)
            else:
                print(f"{idx}. {label}", flush=True)

        selection = await self._get_user_input("Enter the number or style id: ")
        chosen_style = None
        if selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < len(options):
                chosen_style = options[idx].get("style")
        else:
            chosen_style = selection.strip().lower() if selection else None

        if not chosen_style:
            print("⚠️  Invalid selection. Please try again.", flush=True)
            return

        try:
            if not self.current_session_id:
                print("⚠️  No active session. Please reconnect.", flush=True)
                return
            await self._api_request(
                "POST",
                "/workflow/select_therapy_style",
                json={
                    "user_id": self.user_id,
                    "session_id": self.current_session_id,
                    "selected_therapy_style": chosen_style,
                },
            )
            print("✅ Therapy style saved. Re-checking workflow...", flush=True)
            self.pending_recommendations = None
        except Exception as exc:
            print(f"❌ Failed to save therapy style: {exc}", flush=True)

    async def _get_user_input(self, prompt: Optional[str] = None) -> str:
        """Get input from the user via console (non-blocking)."""
        if prompt:
            print(f"{prompt}")

        # Use trio.to_thread to avoid blocking the event loop
        user_input = await trio.to_thread.run_sync(
            lambda: input("\nYour response: ").strip()
        )
        return user_input

    async def _register_user(self) -> bool:
        """Register or refresh a user profile before opening a WebSocket."""
        if self.registered and self.current_session_id:
            return True

        print("\n📝 Let’s set up your profile before starting.", flush=True)
        name = await self._get_user_input("Enter your name (required): ")
        if not name:
            name = self.user_id
        primary_language = await self._get_user_input(
            "Primary language [English]: "
        )
        if not primary_language:
            primary_language = "English"
        session_mode = await self._get_user_input("Session mode [virtual]: ")
        if not session_mode:
            session_mode = "virtual"

        payload = {
            "user_id": self.user_id,
            "name": name,
            "primary_language": primary_language,
            "session_mode": session_mode,
        }

        try:
            response = await self._api_request(
                "POST",
                "/user/register",
                json=payload,
            )
        except Exception as exc:
            print(f"❌ Failed to register profile: {exc}", flush=True)
            return False

        if response.get("error"):
            print(f"❌ Registration failed: {response['error']}", flush=True)
            return False

        session = response.get("session") or {}
        self.current_session_id = session.get("session_id")
        if not self.current_session_id:
            print("❌ Registration did not return a session id.", flush=True)
            return False
        self.latest_workflow_action = response.get("workflow_next_action")
        self.registered = True
        print("✅ Profile registered. Connecting to WebSocket...", flush=True)
        return True

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
        if not self.current_session_id:
            return {"error": "No active session"}
        try:
            return await self._api_request(
                "GET",
                "/user/status",
                params={
                    "user_id": self.user_id,
                    "session_id": self.current_session_id,
                },
            )
        except Exception as e:
            logger.error(f"Error getting user status: {e}")
            return {"error": str(e)}

    async def _get_next_action(self) -> Dict[str, Any]:
        """Fetch workflow next action from backend."""
        if not self.current_session_id:
            return {"required_action": "error", "error": "No active session"}
        try:
            return await self._api_request(
                "GET",
                "/workflow/next",
                params={
                    "user_id": self.user_id,
                    "session_id": self.current_session_id,
                },
            )
        except Exception as e:
            logger.error(f"Error getting workflow next action: {e}")
            return {"required_action": "error", "error": str(e)}

    async def _get_session_timer(self) -> Dict[str, Any]:
        """Get session timer information from backend API."""
        if not self.current_session_id:
            return {"error": "No active session"}

        try:
            return await self._api_request(
                "GET",
                f"/sessions/{self.current_session_id}/timer",
                params={
                    "user_id": self.user_id,
                    "session_id": self.current_session_id,
                },
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

    async def _ensure_session(self, ws) -> None:
        """Prompt the user to reconnect when no active session is bound."""
        if not self.connected or not ws:
            print("❌ Cannot start session: not connected to server", flush=True)
            return

        print(
            "⚠️  No active session. Please reconnect to start a new session.",
            flush=True,
        )
        self.connected = False

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
        wait_count = 0

        while True:
            next_action = await self._get_next_action()
            action = next_action.get("required_action")

            if action == "error":
                print(f"❌ Workflow error: {next_action.get('error')}", flush=True)
                break

            if action == "wait":
                reason = next_action.get(
                    "prompt", "Waiting for backend instructions."
                )
                wait_count += 1
                if wait_count == 1:
                    print(f"⏳ Backend requested wait: {reason}", flush=True)
                    print(
                        "   Waiting for workflow to advance... (Ctrl+C to exit)",
                        flush=True,
                    )
                elif wait_count % 10 == 0:
                    print(f"⏳ Still waiting: {reason}", flush=True)

                if not self.connected:
                    print("⚠️  Connection lost while waiting. Exiting.", flush=True)
                    break

                await trio.sleep(2)
                continue

            if action == "complete_profile":
                await self._complete_profile(
                    next_action.get("required_fields"),
                    next_action.get("defaults"),
                )
                continue

            if action == "select_therapy_style":
                await self._select_therapy_style()
                continue

            if action in {"start_intake", "continue_therapy"}:
                if not self.current_session_id:
                    await self._ensure_session(ws)
                if not self.connected:
                    print(
                        "⚠️  Connection lost while starting session. Exiting workflow.",
                        flush=True,
                    )
                    break

                await self.session_ready.wait()
                exit_console = await self._chat_loop(ws)

                if exit_console:
                    break

                continue

            print("⚠️  Unexpected workflow response. Exiting.", flush=True)
            break

    async def run(self):
        """Run the console client interface with structured concurrency."""
        # Create HTTP client
        async with httpx.AsyncClient() as http_client:
            self.http_client = http_client

            if not await self._register_user():
                return

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
