"""
Console client for connecting to the backend therapy service.
Trio-based implementation for structured concurrency.
"""

import trio
from trio_websocket import open_websocket_url, ConnectionClosed
import json
import logging
import uuid
from typing import Optional, Dict, Any
import httpx

from .event_sink import ConsoleEventSink, NoOpConsoleEventSink
from .input_providers import (
    HumanInputProvider,
    InputContext,
    InputResult,
    InputProvider,
    infer_prompt_kind,
    simulator_phase_for_action,
)
from .output import ConsoleOutput
from .websocket_protocol import (
    ClientMessageTypes,
    ServerMessageTypes,
)


logger = logging.getLogger(__name__)

ONE_SHOT_WORKFLOW_ACTIONS = {
    "complete_profile",
    "select_therapy_style",
    "start_therapy",
    "retry_plan_update",
}


class WorkflowActionError(RuntimeError):
    """Raised when a workflow action fails and should not be retried silently."""


class ConsoleClient:
    """Console client that connects to backend therapy service via API and WebSocket.

    Uses Trio for structured concurrency and automatic resource cleanup.
    """

    def __init__(
        self,
        backend_url: str,
        websocket_url: str,
        user_id: str | None,
        output: ConsoleOutput,
        websocket_origin: str | None = None,
        input_provider: InputProvider | None = None,
        event_sink: ConsoleEventSink | None = None,
        api_timeout_seconds: float = 60.0,
    ):
        self.backend_url = backend_url.rstrip("/")
        self.websocket_url = websocket_url.rstrip("/")
        self.websocket_origin = (websocket_origin or self.backend_url).rstrip("/")
        self.user_id = user_id
        self.output = output
        self.input_provider = input_provider or HumanInputProvider(output)
        self.event_sink = event_sink or NoOpConsoleEventSink()
        self.api_timeout_seconds = api_timeout_seconds

        # HTTP session for API calls
        self.http_client: Optional[httpx.AsyncClient] = None

        # WebSocket connection
        self.ws = None
        self.connected = False
        self.reconnect_required = False

        # Streaming state
        self.current_message = ""
        self.is_streaming = False

        # Session state
        self.session_ready = trio.Event()
        self.session_started_event = trio.Event()
        self.waiting_for_initial_message = False
        self.waiting_for_response = False
        self.response_complete = trio.Event()
        self.current_session_id: Optional[str] = None
        self.session_end_requested = False
        self.session_ended_event = trio.Event()
        self.pending_recommendations: list[dict[str, Any]] | None = None
        self.latest_workflow_action: dict[str, Any] | None = None
        self._latest_workflow_action_signature: str | None = None
        self._unconsumed_workflow_action_signature: str | None = None
        self._workflow_action_event = trio.Event()
        self._completed_one_shot_workflow_action_keys: set[
            tuple[str, str, str | None]
        ] = set()
        self._current_workflow_action_guard_signature: str | None = None
        self.latest_job_statuses: dict[str, dict[str, Any]] = {}
        self.last_recommendations_signature: str | None = None
        self.last_displayed_wait_signature: str | None = None
        self.registered = False
        self.welcome_shown = False
        self.current_profile: dict[str, Any] | None = None

    def _build_websocket_url(self) -> str:
        """Build the backend WebSocket URL for the current user profile."""
        ws_url = self.websocket_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        if not ws_url.endswith("/ws"):
            ws_url = f"{ws_url}/ws"
        return f"{ws_url}?user_id={self.user_id}"

    def _websocket_headers(self) -> list[tuple[str, str]]:
        """Headers required by backend WebSocket origin validation."""
        return [("Origin", self.websocket_origin)]

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
        await self.event_sink.emit("ws_message", message=message)

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
        elif msg_type == ServerMessageTypes.JOB_STATUS:
            await self._handle_job_status(data)
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
                        await self.event_sink.emit(
                            "assistant_response", text=full_message
                        )

                # If we were waiting for initial message, show welcome UI and signal ready
                if self.waiting_for_initial_message:
                    self.waiting_for_initial_message = False
                    # Show welcome message AFTER therapist greeting completes
                    self._show_welcome_message()
                    self.session_ready.set()

                # Signal response complete for regular messages
                elif self.waiting_for_response:
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
        self.session_started_event.set()
        # Always wait for the initial message before allowing user input.
        self.waiting_for_initial_message = True
        self.welcome_shown = False
        await self.event_sink.emit("session_started", data=data)

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
        await self.event_sink.emit("error", message="WebSocket error", data=data)

    async def _handle_assessment_recommendations(self, data: Dict[str, Any]):
        """Display assessment recommendations without interrupting the chat flow."""
        recommendations = data.get("recommendations") or []
        if not recommendations:
            logger.info("Received assessment_recommendations without payload")
            return
        self.pending_recommendations = recommendations
        signature = json.dumps(recommendations, sort_keys=True, separators=(",", ":"))
        if signature == self.last_recommendations_signature:
            logger.debug("Suppressing duplicate assessment recommendations display")
            return
        self.last_recommendations_signature = signature

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
            "🧭 You'll be prompted to select a therapy style next.",
            flush=True,
        )

    async def _handle_workflow_next_action(self, data: Dict[str, Any]):
        """Store workflow next action updates for display/polling."""
        signature = self._workflow_action_signature(data)
        previous_signature = self._latest_workflow_action_signature
        self.latest_workflow_action = data
        self._latest_workflow_action_signature = signature
        if (
            signature != previous_signature
            or self._unconsumed_workflow_action_signature == signature
        ):
            self._unconsumed_workflow_action_signature = signature
        self._workflow_action_event.set()
        self._workflow_action_event = trio.Event()
        await self.event_sink.emit(
            "workflow_action", action=data, delivery_source="websocket"
        )

    async def _handle_job_status(self, data: Dict[str, Any]):
        """Store backend job progress updates for probes and diagnostics."""
        job_id = data.get("job_id")
        if job_id:
            self.latest_job_statuses[str(job_id)] = data
        await self.event_sink.emit("job_status", status=data, delivery_source="websocket")

    async def _handle_session_ended(self, data: Dict[str, Any]):
        """Handle server-side session end notification."""
        reason = data.get("reason", "Session ended")
        self.output.user_text(
            f"\n👋 {reason}. Exiting console client.", flush=True
        )
        self.session_end_requested = True
        self.session_ended_event.set()
        self.current_session_id = None
        self.session_ready = trio.Event()
        if self.waiting_for_response:
            self.response_complete.set()
            self.waiting_for_response = False
        await self.event_sink.emit("session_ended", data=data)

    async def _api_request(
        self, method: str, endpoint: str, **kwargs
    ) -> Dict[str, Any]:
        """Make an API request to the backend."""
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

        url = f"{self.backend_url}/api{endpoint}"
        response = await self.http_client.request(method, url, **kwargs)
        if response.is_error:
            body = response.text
            raise RuntimeError(
                f"{method} {endpoint} failed with "
                f"{response.status_code}: {body[:500]}"
            )

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
    ) -> bool:
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
                return False
            await self._api_request("POST", "/workflow/complete_profile", json=payload)
            self.output.user_text(
                "✅ Profile saved. Re-checking workflow...", flush=True
            )
            return True
        except Exception as e:
            self.output.error(f"❌ Failed to save profile: {e}")
            return False

    async def _select_therapy_style(self) -> bool:
        """Prompt the user to select a therapy style and submit it."""
        recommendations = self.pending_recommendations
        options: list[dict[str, Any]] = []

        if not recommendations:
            self.output.user_text(
                "⏳ Waiting for assessment recommendations before selecting a therapy style.",
                flush=True,
            )
            await trio.sleep(2)
            return False

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
            return False

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
            await self.event_sink.emit(
                "error", message="Invalid therapy style selection"
            )
            return False

        try:
            if not self.current_session_id:
                self.output.user_text(
                    "⚠️  No active session. Please reconnect.", flush=True
                )
                await self.event_sink.emit(
                    "error",
                    message="No active session during therapy style selection",
                )
                return False
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
            await self.event_sink.emit(
                "therapy_style_selected",
                selected_therapy_style=chosen_style,
                session_id=self.current_session_id,
            )
            self.pending_recommendations = None
            return True
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self.output.error(f"❌ Failed to save therapy style: {message}")
            await self.event_sink.emit(
                "error",
                message="Therapy style selection failed",
                data={"message": message, "session_id": self.current_session_id},
            )
            raise WorkflowActionError("Therapy style selection failed") from exc

    async def _start_therapy(self, ws) -> bool:
        """Offer seamless continuation into the first plan-linked therapy session."""
        choice = await self._get_user_input("Start therapy now? [Y/n]: ", default="y")
        if choice.strip().lower() not in {"", "y", "yes"}:
            await self._request_end_session(
                ws, reason="User finished onboarding without starting therapy"
            )
            return False
        if not self.current_session_id:
            self.output.error("❌ No active intake session. Please reconnect.")
            return False
        self.session_started_event = trio.Event()
        response = await self._api_request(
            "POST",
            "/workflow/start_therapy",
            json={"user_id": self.user_id, "session_id": self.current_session_id},
        )
        session = response.get("session") or {}
        if session.get("session_id"):
            self.current_session_id = session["session_id"]
        with trio.move_on_after(2):
            await self.session_started_event.wait()
        if not self.session_started_event.is_set():
            self.reconnect_required = True
            self.output.system("🔄 Reconnecting to start the therapy session...")
            return False
        self.output.user_text("✅ Starting your therapy session...", flush=True)
        return True

    async def _retry_plan_update(self) -> bool:
        """Offer an explicit retry for a failed post-session reflection."""
        choice = await self._get_user_input("Retry plan update now? [Y/n]: ", default="y")
        if choice.strip().lower() not in {"", "y", "yes"}:
            self.output.user_text("Plan update retry deferred.", flush=True)
            return False
        if not self.current_session_id:
            self.output.error("❌ No therapy session is available to retry.")
            return False
        await self._api_request(
            "POST",
            "/workflow/retry_plan_update",
            json={"user_id": self.user_id, "session_id": self.current_session_id},
        )
        self.output.user_text("⏳ Retrying session reflection...", flush=True)
        return True

    async def _get_user_input(
        self,
        prompt: Optional[str] = None,
        default: Optional[str] = None,
    ) -> str:
        """Get input from the configured input provider."""
        context = InputContext(
            prompt=prompt,
            default=default,
            prompt_kind=infer_prompt_kind(prompt),
            user_id=self.user_id,
            session_id=self.current_session_id,
            workflow_action=self.latest_workflow_action,
            simulator_phase=simulator_phase_for_action(self.latest_workflow_action),
            pending_recommendations=self.pending_recommendations,
            transcript_tail=[],
            turn_index=0,
        )
        await self.event_sink.emit("prompt", context=context)

        provider_result = await self.input_provider.get_input(context)
        if isinstance(provider_result, InputResult):
            user_input = provider_result.text
            input_origin = provider_result.input_origin
            fallback_reason = provider_result.fallback_reason
        else:
            user_input = provider_result
            input_origin = None
            fallback_reason = None

        if not user_input and default is not None:
            self.output.log_input(f"{default} (default)")
            await self.event_sink.emit(
                "user_input",
                text=default,
                source=self.input_provider.__class__.__name__,
                context=context,
                used_default=True,
                input_origin=input_origin,
                fallback_reason=fallback_reason,
            )
            return default
        self.output.log_input(user_input)
        await self.event_sink.emit(
            "user_input",
            text=user_input,
            source=self.input_provider.__class__.__name__,
            context=context,
            input_origin=input_origin,
            fallback_reason=fallback_reason,
        )
        return user_input

    async def _fetch_profiles(self) -> list[dict[str, Any]] | None:
        """Fetch profile summaries for login selection."""
        try:
            response = await self._api_request("GET", "/user/profiles")
        except Exception as exc:
            logger.error("Failed to fetch profiles: %s", exc)
            return None

        profiles = response.get("profiles")
        if isinstance(profiles, list):
            return profiles
        return None

    async def _select_or_create_profile(self) -> bool:
        """Prompt the user to select an existing profile or create a new one."""
        profiles = await self._fetch_profiles()

        if profiles is None:
            self.output.user_text(
                "⚠️  Could not load existing profiles. Creating a new profile.",
                flush=True,
            )
            return await self._create_new_profile()

        if not profiles:
            self.output.user_text(
                "ℹ️  No profiles found. Creating a new profile.",
                flush=True,
            )
            return await self._create_new_profile()

        self.output.user_text("\n👤 Select a profile:", flush=True)
        for idx, profile in enumerate(profiles, start=1):
            name = profile.get("name") or "Unknown"
            status = profile.get("status") or "unknown"
            language = profile.get("primary_language") or "English"
            self.output.user_text(
                f"{idx}. {name} ({status}, {language})", flush=True
            )

        create_option = len(profiles) + 1
        self.output.user_text(
            f"{create_option}. Create new profile", flush=True
        )

        while True:
            selection = await self._get_user_input(
                "Enter the number for your choice: "
            )
            if not selection.isdigit():
                self.output.user_text(
                    "⚠️  Please enter a number from the list.", flush=True
                )
                continue

            choice = int(selection)
            if 1 <= choice <= len(profiles):
                selected_profile = profiles[choice - 1]
                selected_user_id = selected_profile.get("user_id")
                if not selected_user_id:
                    self.output.user_text(
                        "⚠️  Selected profile is missing a user id. Try again.",
                        flush=True,
                    )
                    continue
                success = await self._login_existing_profile(
                    selected_user_id, selected_profile
                )
                if success:
                    name = selected_profile.get("name") or selected_user_id
                    status = selected_profile.get("status") or "unknown"
                    self.output.system(
                        f"✅ Selected profile: {name} ({status})"
                    )
                return success

            if choice == create_option:
                return await self._create_new_profile()

            self.output.user_text(
                "⚠️  Selection out of range. Try again.", flush=True
            )

    async def _login_existing_profile(
        self, user_id: str, profile_summary: dict[str, Any] | None = None
    ) -> bool:
        """Log in an existing user profile before opening a WebSocket."""
        self.user_id = user_id
        payload = {"user_id": user_id}

        try:
            response = await self._api_request(
                "POST",
                "/user/login",
                json=payload,
            )
        except Exception as exc:
            self.output.error(f"❌ Failed to login profile: {exc}")
            return False

        if response.get("error"):
            self.output.error(f"❌ Login failed: {response['error']}")
            return False

        session = response.get("session") or {}
        self.current_session_id = session.get("session_id")
        if not self.current_session_id:
            self.output.error("❌ Login did not return a session id.")
            return False

        self.latest_workflow_action = response.get("workflow_next_action")
        self.registered = True

        await self._load_profile_details(profile_summary)
        await self.event_sink.emit(
            "profile_selected",
            user_id=self.user_id,
            session_id=self.current_session_id,
        )
        self.output.user_text(
            "✅ Logged in. Connecting to WebSocket...", flush=True
        )
        return True

    async def _load_profile_details(
        self, profile_summary: dict[str, Any] | None = None
    ) -> None:
        """Load full profile details for logging and defaults."""
        if not self.user_id or not self.current_session_id:
            return

        try:
            response = await self._api_request(
                "GET",
                "/user/profile",
                params={
                    "user_id": self.user_id,
                    "session_id": self.current_session_id,
                },
            )
            if response.get("error"):
                self.output.user_text(
                    f"⚠️  Could not load profile details: {response['error']}",
                    flush=True,
                )
                self.current_profile = profile_summary
                return
            self.current_profile = response
        except Exception as exc:
            self.output.user_text(
                f"⚠️  Could not load profile details: {exc}", flush=True
            )
            self.current_profile = profile_summary

    async def _create_new_profile(self) -> bool:
        """Create a new user profile before opening a WebSocket."""
        if not self.user_id:
            self.user_id = uuid.uuid4().hex
            logger.info("Generated new user_id: %s", self.user_id)
            self.output.system(f"ℹ️  Generated user_id: {self.user_id}")

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

        payload = {
            "user_id": self.user_id,
            "name": name,
            "primary_language": primary_language,
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
        self.current_profile = response
        await self.event_sink.emit(
            "profile_created",
            user_id=self.user_id,
            session_id=self.current_session_id,
        )
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
        if not self.current_session_id:
            self.output.user_text("⚠️  No active session to end.", flush=True)
            return

        try:
            session_id = self.current_session_id
            response = await self._api_request(
                "POST",
                f"/sessions/{session_id}/end",
                json={
                    "user_id": self.user_id,
                    "session_id": session_id,
                    "reason": reason,
                },
            )
            if not self.session_end_requested:
                await self._handle_session_ended(response)
            logger.debug("Sent end_session request for session %s", self.current_session_id)
        except Exception as e:
            logger.error(f"Error sending end_session: {e}")
            self.output.error(f"❌ Failed to end session: {e}")

    async def _request_end_session(
        self, ws, reason: str | None = None, timeout_seconds: float = 8.0
    ) -> None:
        """Send end_session and wait briefly for server confirmation."""
        self.session_ended_event = trio.Event()
        await self._send_end_session(ws, reason=reason)
        if self.session_end_requested:
            return
        with trio.move_on_after(timeout_seconds) as cancel_scope:
            await self.session_ended_event.wait()
        if cancel_scope.cancelled_caught:
            self.output.user_text(
                "⚠️  Session end was not confirmed by the server in time.",
                flush=True,
            )

    async def _get_user_status(self) -> Dict[str, Any]:
        """Get user status from backend API."""
        try:
            return await self._api_request(
                "GET",
                "/user/status",
                params={"user_id": self.user_id},
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

    def _workflow_action_signature(self, action: dict[str, Any]) -> str:
        """Return a stable action signature for freshness and deduplication."""
        state_signature = action.get("state_signature")
        if state_signature:
            return str(state_signature)
        return json.dumps(action, sort_keys=True, separators=(",", ":"), default=str)

    def _workflow_action_execution_key(
        self, action: dict[str, Any]
    ) -> tuple[str, str, str | None] | None:
        """Return the idempotency key for one-shot workflow actions."""
        required_action = action.get("required_action")
        if required_action not in ONE_SHOT_WORKFLOW_ACTIONS:
            return None
        session_id = action.get("session_id") or self.current_session_id
        return (
            str(required_action),
            self._workflow_action_signature(action),
            str(session_id) if session_id else None,
        )

    def _refresh_workflow_action_execution_guard(
        self, action: dict[str, Any]
    ) -> None:
        """Clear one-shot completions when the workflow instruction advances."""
        signature = self._workflow_action_signature(action)
        if signature == self._current_workflow_action_guard_signature:
            return
        self._completed_one_shot_workflow_action_keys.clear()
        self._current_workflow_action_guard_signature = signature

    async def _skip_completed_one_shot_action(
        self, action: dict[str, Any]
    ) -> bool:
        """Skip duplicate one-shot actions that already completed locally."""
        key = self._workflow_action_execution_key(action)
        if key is None or key not in self._completed_one_shot_workflow_action_keys:
            return False
        await self.event_sink.emit(
            "workflow_action_skipped",
            action=action.get("required_action"),
            session_id=key[2],
            state_signature=key[1],
            reason="duplicate_one_shot_action",
        )
        return True

    def _mark_one_shot_action_completed(self, action: dict[str, Any]) -> None:
        """Remember a successfully completed one-shot workflow action."""
        key = self._workflow_action_execution_key(action)
        if key is not None:
            self._completed_one_shot_workflow_action_keys.add(key)

    async def _next_workflow_action(
        self,
        *,
        prefer_ws_timeout_seconds: float = 0.25,
        allow_cached_websocket: bool = True,
        ignored_websocket_signature: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Prefer a fresh WebSocket workflow action, with HTTP polling fallback."""
        if (
            allow_cached_websocket
            and self.latest_workflow_action
            and self._unconsumed_workflow_action_signature
            == self._latest_workflow_action_signature
            and self._latest_workflow_action_signature != ignored_websocket_signature
        ):
            self._unconsumed_workflow_action_signature = None
            return self.latest_workflow_action, "websocket"

        if prefer_ws_timeout_seconds > 0:
            with trio.move_on_after(prefer_ws_timeout_seconds):
                await self._workflow_action_event.wait()
            if (
                self.latest_workflow_action
                and self._unconsumed_workflow_action_signature
                == self._latest_workflow_action_signature
                and self._latest_workflow_action_signature != ignored_websocket_signature
            ):
                self._unconsumed_workflow_action_signature = None
                return self.latest_workflow_action, "websocket"

        action = await self._get_next_action()
        self.latest_workflow_action = action
        self._latest_workflow_action_signature = self._workflow_action_signature(action)
        self._unconsumed_workflow_action_signature = None
        await self.event_sink.emit(
            "workflow_action",
            action=action,
            delivery_source="http_poll",
        )
        return action, "http_poll"

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

    async def _await_session_ready(self, timeout_seconds: float | None = None) -> bool:
        """Wait for the initial greeting without enabling overlapping chat."""
        if self.session_ready.is_set():
            return True
        if timeout_seconds is None:
            timeout_seconds = 60.0
        with trio.move_on_after(timeout_seconds) as cancel_scope:
            await self.session_ready.wait()
        if cancel_scope.cancelled_caught:
            message = (
                "Initial greeting did not finish in time. "
                "Chat remains disabled to avoid overlapping responses."
            )
            self.output.error(f"❌ {message}")
            await self.event_sink.emit(
                "error",
                message="Initial greeting timeout",
                data={"timeout_seconds": timeout_seconds},
            )
            self.waiting_for_initial_message = False
            if not self.is_streaming:
                self.output.user_text(" " * 30, end="\r", log=False)
            return False
        return True

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
                next_action, _delivery_source = await self._next_workflow_action(
                    prefer_ws_timeout_seconds=0.1,
                )
                required_action = next_action.get("required_action")
                if required_action not in {"start_intake", "continue_therapy"}:
                    # Workflow advanced to a non-chat step (e.g., wait/style selection).
                    return False
                try:
                    pre_input_workflow_signature = (
                        self._latest_workflow_action_signature
                    )
                    user_message = await self._get_user_input()

                    # Slash commands
                    if user_message.startswith("/"):
                        command = user_message.lower().strip()
                        if command in ["/quit", "/end"]:
                            await self._request_end_session(
                                ws, reason="User ended session"
                            )
                            self.output.user_text(
                                "👋 Ending current session...", flush=True
                            )
                            return True
                        elif command == "/exit":
                            await self._request_end_session(
                                ws, reason="User exited console"
                            )
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
                        await self._request_end_session(ws, reason="User ended session")
                        self.output.user_text("👋 Exiting console client.", flush=True)
                        return True

                    latest_action, _delivery_source = await self._next_workflow_action(
                        prefer_ws_timeout_seconds=0.1,
                        ignored_websocket_signature=pre_input_workflow_signature,
                    )
                    latest_required_action = latest_action.get("required_action")
                    if latest_required_action not in {
                        "start_intake",
                        "continue_therapy",
                    }:
                        await self.event_sink.emit(
                            "discarded_input",
                            reason="workflow_advanced_before_send",
                            required_action=latest_required_action,
                        )
                        return False

                    await self._display_message("user", user_message)

                    self.waiting_for_response = True
                    self.response_complete = trio.Event()
                    await self._send_chat_message(ws, user_message)
                    await self.response_complete.wait()

                    if self.session_end_requested:
                        return True
                    if (
                        self.latest_workflow_action
                        and self.latest_workflow_action.get("required_action")
                        not in {"start_intake", "continue_therapy"}
                    ):
                        return False

                except KeyboardInterrupt:
                    await self._request_end_session(ws, reason="User exited console")
                    self.output.user_text("\n👋 Exiting console client.", flush=True)
                    return True
                except Exception as e:
                    logger.error(f"Error in chat loop: {e}")
                    self.output.error(f"❌ Error: {e}")
                    await self.event_sink.emit(
                        "error", message="Chat loop failed", data=repr(e)
                    )
                    raise
        finally:
            self.waiting_for_response = False

    async def _follow_workflow(self, ws):
        """Drive the console experience based on the backend workflow."""
        wait_count = 0
        next_wait_heartbeat_seconds = 60

        while True:
            next_action, delivery_source = await self._next_workflow_action()
            action = next_action.get("required_action")
            prompt = next_action.get("prompt")
            self._refresh_workflow_action_execution_guard(next_action)
            self.output.system(
                f"Workflow action: {action} prompt={prompt!r} source={delivery_source}"
            )

            if action == "error":
                self.output.error(
                    f"❌ Workflow error: {next_action.get('error')}"
                )
                break

            if action == "wait":
                reason = prompt or "Waiting for backend instructions."
                wait_count += 1
                wait_signature = next_action.get("state_signature") or json.dumps(
                    {
                        "workflow_state": next_action.get("workflow_state"),
                        "required_action": action,
                        "prompt": prompt,
                        "session_id": next_action.get("session_id"),
                    },
                    sort_keys=True,
                )
                if wait_signature != self.last_displayed_wait_signature:
                    self.last_displayed_wait_signature = wait_signature
                    wait_count = 1
                    next_wait_heartbeat_seconds = 60
                    self.output.user_text(
                        f"⏳ Backend requested wait: {reason}", flush=True
                    )
                    self.output.user_text(
                        "   Waiting for workflow to advance... (Ctrl+C to exit)",
                        flush=True,
                    )
                elif (wait_count - 1) * 2 >= next_wait_heartbeat_seconds:
                    self.output.user_text(
                        "⏳ Still waiting "
                        f"({next_wait_heartbeat_seconds}s elapsed): {reason}",
                        flush=True,
                    )
                    next_wait_heartbeat_seconds += 60

                if not self.connected:
                    self.output.user_text(
                        "⚠️  Connection lost while waiting. Exiting.", flush=True
                    )
                    break

                await trio.sleep(2)
                continue

            if await self._skip_completed_one_shot_action(next_action):
                await trio.sleep(0.25)
                continue

            if action == "complete_profile":
                if await self._complete_profile(
                    next_action.get("required_fields"),
                    next_action.get("defaults"),
                ):
                    self._mark_one_shot_action_completed(next_action)
                continue

            if action == "select_therapy_style":
                if await self._select_therapy_style():
                    self._mark_one_shot_action_completed(next_action)
                continue

            if action == "start_therapy":
                if await self._start_therapy(ws):
                    self._mark_one_shot_action_completed(next_action)
                else:
                    break
                continue

            if action == "retry_plan_update":
                if await self._retry_plan_update():
                    self._mark_one_shot_action_completed(next_action)
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

                if not await self._await_session_ready():
                    break
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
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.api_timeout_seconds)
        ) as http_client:
            self.http_client = http_client

            if not await self._select_or_create_profile():
                return

            ws_url = self._build_websocket_url()
            while True:
                self.reconnect_required = False
                await self._run_websocket_session(ws_url)
                if not self.reconnect_required:
                    break

    async def _run_websocket_session(self, ws_url: str) -> None:
        """Connect once and follow the workflow until completion or reconnect."""
        logger.info(f"Connecting to WebSocket: {ws_url}")

        try:
            # Include Origin header for CORS validation during WebSocket handshake
            async with open_websocket_url(
                ws_url, extra_headers=self._websocket_headers()
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
