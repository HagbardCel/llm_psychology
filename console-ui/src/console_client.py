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
from .output import ConsoleOutput
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

    def __init__(
        self,
        backend_url: str,
        websocket_url: str,
        user_id: str,
        output: ConsoleOutput,
    ):
        self.backend_url = backend_url.rstrip("/")
        self.websocket_url = websocket_url
        self.user_id = user_id
        self.output = output

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
        self.welcome_shown = False

    def _show_welcome_message(self) -> None:
        """Display chat instructions once per session."""
        if self.welcome_shown:
            return
        self.welcome_shown = True
        self.output.user_text(
            "\n💬 You can now chat with your therapist.",
            flush=True,
        )
        self.output.user_text(
            "   Commands: /timer (show time), /quit (finish session), /exit (close console)",
            flush=True,
        )
        self.output.user_text("=" * 60, flush=True)
        self.output.user_text("", log=False)

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
                    self.output.user_text(
                        "\n\033[94mTHERAPIST\033[0m: ",
                        end="",
                        flush=True,
                        log=False,
                    )
                    self.is_streaming = True
                    self.current_message = ""

                # Display chunk in real-time
                self.output.user_text(chunk, end="", flush=True, log=False)
                self.current_message += chunk
            else:
                # Streaming complete
                if self.is_streaming:
                    self.output.user_text("", log=False)  # New line after complete message
                    full_message = self.current_message
                    self.is_streaming = False
                    self.current_message = ""
                    if full_message:
                        self.output.log_chat("therapist", full_message)

                # If we were waiting for initial message, show welcome UI and signal ready
                if self.waiting_for_initial_message:
                    self.waiting_for_initial_message = False
                    # Show welcome message AFTER therapist greeting completes
                    self._show_welcome_message()
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
        self.welcome_shown = False

    async def _handle_connected(self, data: Dict[str, Any]):
        """Handle connection confirmation."""
        user_id = data.get("user_id", "unknown")
        name = data.get("name", user_id)
        status = data.get("status", "unknown")

        self.output.system(f"🔐 Connected as: {name} (user_id: {user_id})")
        if status == "PROFILE_ONLY":
            self.output.system("ℹ️  New user profile created")

    async def _handle_typing_start(self):
        """Handle therapist typing indicator."""
        if (
            not self.is_streaming
            and (self.waiting_for_response or self.waiting_for_initial_message)
        ):
            self.output.user_text("\n💭 Therapist is typing...", end="\r", flush=True)

    async def _handle_typing_stop(self):
        """Handle therapist stopped typing."""
        if not self.is_streaming:
            self.output.user_text(" " * 30, end="\r", log=False)  # Clear typing indicator

    async def _handle_error(self, data: Dict[str, Any]):
        """Handle WebSocket errors."""
        self.output.error(f"\n❌ Error: {data.get('message', data)}")

    async def _handle_assessment_recommendations(self, data: Dict[str, Any]):
        """Display assessment recommendations without interrupting the chat flow."""
        recommendations = data.get("recommendations") or []
        if not recommendations:
            logger.info("Received assessment_recommendations without payload")
            return
        self.pending_recommendations = recommendations

        self.output.user_text("\n" + "=" * 60, flush=True)
        self.output.user_text("🎯 ASSESSMENT RECOMMENDATIONS", flush=True)
        self.output.user_text("=" * 60, flush=True)
        for idx, rec in enumerate(recommendations, start=1):
            style = rec.get("style_id", f"option_{idx}")
            explanation = rec.get("explanation", "No explanation provided.")
            score = rec.get("score")
            if score is not None:
                self.output.user_text(
                    f"{idx}. {style} (score: {score:.2f})", flush=True
                )
            else:
                self.output.user_text(f"{idx}. {style}", flush=True)
            self.output.user_text(f"   {explanation}", flush=True)
            self.output.user_text("---", flush=True)

        self.output.user_text(
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
            self.output.user_text(
                f"\n⏳ {prompt or 'Waiting for backend workflow...'}", flush=True
            )

    async def _handle_session_ended(self, data: Dict[str, Any]):
        """Handle server-side session end notification."""
        reason = data.get("reason", "Session ended")
        self.output.user_text(
            f"\n👋 {reason}. Exiting console client.", flush=True
        )
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
            self.output.user_text(
                f"\033[94m{role_display}\033[0m: {text}", log=False
            )  # Blue
        elif role == "user":
            self.output.user_text(
                f"\033[92m{role_display}\033[0m: {text}", log=False
            )  # Green
        else:
            self.output.user_text(
                f"\033[93m{role_display}\033[0m: {text}", log=False
            )  # Yellow
        self.output.log_chat(role, text)

    async def _complete_profile(
        self,
        required_fields: list[str] | None = None,
        defaults: dict[str, Any] | None = None,
    ):
        """Prompt the user for required profile details and submit them via the API."""
        self.output.user_text("\n📝 Profile required to continue.", flush=True)
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
                self.output.user_text(
                    "⚠️  No active session. Please reconnect.", flush=True
                )
                return
            await self._api_request("POST", "/workflow/complete_profile", json=payload)
            self.output.user_text(
                "✅ Profile saved. Re-checking workflow...", flush=True
            )
        except Exception as e:
            self.output.error(f"❌ Failed to save profile: {e}")

    async def _select_therapy_style(self):
        """Prompt the user to select a therapy style and submit it."""
        recommendations = self.pending_recommendations
        options: list[dict[str, Any]] = []

        if not recommendations:
            self.output.user_text(
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
            self.output.user_text(
                "⚠️  No therapy styles available yet. Try again later.",
                flush=True,
            )
            return

        self.output.user_text("\n🧭 Select a therapy style:", flush=True)
        for idx, option in enumerate(options, start=1):
            label = option.get("style") or f"option_{idx}"
            description = option.get("description")
            if description:
                self.output.user_text(f"{idx}. {label} - {description}", flush=True)
            else:
                self.output.user_text(f"{idx}. {label}", flush=True)

        selection = await self._get_user_input("Enter the number or style id: ")
        chosen_style = None
        if selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < len(options):
                chosen_style = options[idx].get("style")
        else:
            chosen_style = selection.strip().lower() if selection else None

        if not chosen_style:
            self.output.user_text(
                "⚠️  Invalid selection. Please try again.", flush=True
            )
            return

        try:
            if not self.current_session_id:
                self.output.user_text(
                    "⚠️  No active session. Please reconnect.", flush=True
                )
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
            self.output.user_text(
                "✅ Therapy style saved. Re-checking workflow...", flush=True
            )
            self.pending_recommendations = None
        except Exception as exc:
            self.output.error(f"❌ Failed to save therapy style: {exc}")

    async def _get_user_input(
        self,
        prompt: Optional[str] = None,
        default: Optional[str] = None,
    ) -> str:
        """Get input from the user via console (non-blocking)."""
        if prompt:
            self.output.prompt(f"{prompt}")

        # Use trio.to_thread to avoid blocking the event loop
        self.output.prompt("\nYour response: ", end="")
        user_input = await trio.to_thread.run_sync(
            lambda: input().strip()
        )
        if not user_input and default is not None:
            self.output.log_input(f"{default} (default)")
            return default
        self.output.log_input(user_input)
        return user_input

    async def _register_user(self) -> bool:
        """Register or refresh a user profile before opening a WebSocket."""
        if self.registered and self.current_session_id:
            return True

        self.output.user_text(
            "\n📝 Let’s set up your profile before starting.", flush=True
        )
        name = await self._get_user_input("Enter your name (required): ")
        if not name:
            name = self.user_id
        primary_language = await self._get_user_input(
            "Primary language [English]: ",
            default="English",
        )
        session_mode = await self._get_user_input(
            "Session mode [virtual]: ",
            default="virtual",
        )

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
            self.output.error(f"❌ Failed to register profile: {exc}")
            return False

        if response.get("error"):
            self.output.error(f"❌ Registration failed: {response['error']}")
            return False

        session = response.get("session") or {}
        self.current_session_id = session.get("session_id")
        if not self.current_session_id:
            self.output.error("❌ Registration did not return a session id.")
            return False
        self.latest_workflow_action = response.get("workflow_next_action")
        self.registered = True
        self.output.user_text(
            "✅ Profile registered. Connecting to WebSocket...", flush=True
        )
        return True

    async def _send_chat_message(self, ws, message: str):
        """Send a chat message via WebSocket."""
        if not self.connected or not ws:
            self.output.error("❌ Not connected to WebSocket server")
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
            self.output.error(f"❌ Failed to send message: {e}")

    async def _send_end_session(self, ws, reason: str | None = None):
        """Request the backend to end the current session."""
        if not self.connected or not ws:
            self.output.error("❌ Not connected to WebSocket server")
            return

        if not self.current_session_id:
            self.output.user_text("⚠️  No active session to end.", flush=True)
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
            self.output.error(f"❌ Failed to end session: {e}")

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
            self.output.user_text(
                f"\n⚠️  Could not retrieve timer: {timer_data['error']}", flush=True
            )
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
        self.output.user_text("\n" + "=" * 60, flush=True)
        self.output.user_text("⏱️  SESSION TIMER", flush=True)
        self.output.user_text("=" * 60, flush=True)
        self.output.user_text(f"Time elapsed:   {int(elapsed)} minutes", flush=True)
        self.output.user_text(f"Time remaining: {int(remaining)} minutes", flush=True)
        self.output.user_text(f"Total duration: {total} minutes", flush=True)

        if extensions_used > 0:
            self.output.user_text(
                f"Extensions:     {extensions_used}/{max_extensions} used", flush=True
            )
        else:
            self.output.user_text(
                f"Extensions:     {max_extensions} available", flush=True
            )

        if is_time_up:
            self.output.user_text(
                "\n⚠️  Time is up! Session should be ending soon.", flush=True
            )
        elif remaining < 5:
            self.output.user_text("\n⚠️  Less than 5 minutes remaining!", flush=True)
        elif can_extend and remaining < 10:
            self.output.user_text(
                "\nℹ️  Running low on time. You can extend the session.",
                flush=True,
            )

        self.output.user_text("=" * 60, flush=True)
        self.output.user_text("", log=False)

    async def _ensure_session(self, ws) -> None:
        """Prompt the user to reconnect when no active session is bound."""
        if not self.connected or not ws:
            self.output.error("❌ Cannot start session: not connected to server")
            return

        self.output.user_text(
            "⚠️  No active session. Please reconnect to start a new session.",
            flush=True,
        )
        self.connected = False

    async def _await_session_ready(self, timeout_seconds: float = 8.0) -> None:
        """Wait for initial greeting, but fall back to allowing input on timeout."""
        if self.session_ready.is_set():
            return
        with trio.move_on_after(timeout_seconds) as cancel_scope:
            await self.session_ready.wait()
        if cancel_scope.cancelled_caught:
            self.output.system(
                "Initial greeting not received in time; allowing user input."
            )
            self.waiting_for_initial_message = False
            if not self.is_streaming:
                self.output.user_text(" " * 30, end="\r", log=False)
            self._show_welcome_message()
            self.session_ready.set()

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
                            self.output.user_text(
                                "👋 Ending current session...", flush=True
                            )
                            return True
                        elif command == "/exit":
                            await self._send_end_session(ws, reason="User exited console")
                            self.output.user_text(
                                "👋 Exiting console client. Take care.", flush=True
                            )
                            return True
                        elif command == "/timer":
                            await self._display_timer_info()
                            continue
                        else:
                            self.output.user_text(
                                "⚠️  Unknown command. Available: /timer, /quit (finish session), /exit (close console).",
                                flush=True,
                            )
                            continue

                    if not user_message:
                        continue

                    # Legacy exit keywords without slash exit the console completely
                    if user_message.lower() in ["quit", "exit", "bye"]:
                        await self._send_end_session(ws, reason="User ended session")
                        self.output.user_text("👋 Exiting console client.", flush=True)
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
                    self.output.user_text("\n👋 Exiting console client.", flush=True)
                    return True
                except Exception as e:
                    logger.error(f"Error in chat loop: {e}")
                    self.output.error(f"❌ Error: {e}")
        finally:
            self.waiting_for_response = False

    async def _follow_workflow(self, ws):
        """Drive the console experience based on the backend workflow."""
        wait_count = 0

        while True:
            next_action = await self._get_next_action()
            action = next_action.get("required_action")
            prompt = next_action.get("prompt")
            self.output.system(
                f"Workflow action: {action} prompt={prompt!r}"
            )

            if action == "error":
                self.output.error(
                    f"❌ Workflow error: {next_action.get('error')}"
                )
                break

            if action == "wait":
                reason = prompt or "Waiting for backend instructions."
                wait_count += 1
                if wait_count == 1:
                    self.output.user_text(
                        f"⏳ Backend requested wait: {reason}", flush=True
                    )
                    self.output.user_text(
                        "   Waiting for workflow to advance... (Ctrl+C to exit)",
                        flush=True,
                    )
                elif wait_count % 10 == 0:
                    self.output.user_text(
                        f"⏳ Still waiting: {reason}", flush=True
                    )

                if not self.connected:
                    self.output.user_text(
                        "⚠️  Connection lost while waiting. Exiting.", flush=True
                    )
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
                    self.output.user_text(
                        "⚠️  Connection lost while starting session. Exiting workflow.",
                        flush=True,
                    )
                    break

                await self._await_session_ready()
                exit_console = await self._chat_loop(ws)

                if exit_console:
                    break

                continue

            self.output.user_text(
                "⚠️  Unexpected workflow response. Exiting.", flush=True
            )
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
                    self.output.system("✅ Connected to therapy session server")

                    # Use nursery for structured concurrency
                    async with trio.open_nursery() as nursery:
                        # Start WebSocket receiver task
                        nursery.start_soon(self._websocket_receiver, ws)

                        # Give connection a moment to stabilize
                        await trio.sleep(1)

                        if not self.connected:
                            self.output.error(
                                "❌ Failed to establish connection. Exiting."
                            )
                            nursery.cancel_scope.cancel()
                            return

                        # Get user status
                        self.output.system("📊 Checking user status...")
                        status = await self._get_user_status()

                        if "error" in status:
                            self.output.system(
                                f"⚠️  Could not get user status: {status['error']}"
                            )
                            self.output.system("Proceeding with basic session...")
                        else:
                            workflow_state = status.get("workflow_state")
                            if workflow_state:
                                self.output.system(
                                    f"📍 Current workflow state: {workflow_state}"
                                )

                        try:
                            await self._follow_workflow(ws)
                        finally:
                            # Cancel nursery to clean up receiver task
                            nursery.cancel_scope.cancel()

            except ConnectionClosed:
                self.output.error("❌ WebSocket connection closed unexpectedly")
                logger.error("WebSocket connection closed")
            except Exception as e:
                logger.error(f"Failed to connect to WebSocket: {e}")
                self.output.error(f"❌ Failed to connect to WebSocket server: {e}")
