#!/usr/bin/env python3
"""
Standalone Terminal UI for the Virtual LLM-Driven Psychoanalyst.
This is the main entry point for running the application locally without Docker.
"""

import json
import logging
import uuid

import trio

from psychoanalyst_app.config import Settings, setup_logging
from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.orchestration.trio_agent_orchestrator import TrioAgentOrchestrator
from psychoanalyst_app.orchestration.trio_conversation_manager import TrioConversationManager
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine
from psychoanalyst_app.services.session_enrichment import (
    SessionEnrichmentService,
    run_session_enrichment_worker,
)
from psychoanalyst_app.ui.base_ui import BaseUI
from psychoanalyst_app.utils.ws_protocol import ServerMessageTypes

logger = logging.getLogger(__name__)


class TerminalWebSocket:
    """Mock WebSocket for handling async messages in terminal."""

    def __init__(self):
        self.completion_event = trio.Event()

    async def send(self, message: str):
        """Handle incoming message from conversation manager."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == ServerMessageTypes.TYPING_START:
                print("\n🤖 Analyst: ", end="", flush=True)

            elif msg_type == ServerMessageTypes.CHAT_RESPONSE_CHUNK:
                chunk_data = data.get("data", {})
                chunk = chunk_data.get("chunk", "")
                is_complete = chunk_data.get("is_complete", False)

                print(chunk, end="", flush=True)

                if is_complete:
                    print()  # Newline at end
                    self.completion_event.set()

        except Exception as e:
            print(f"\n❌ Error in TerminalWebSocket: {e}")


class TerminalUI(BaseUI):
    """Simple terminal UI for interacting with the agent."""

    def __init__(self, orchestrator: TrioAgentOrchestrator, settings: Settings):
        self.orchestrator = orchestrator
        self.user_id = str(uuid.uuid4())
        print(f"🧠 {settings.APP_NAME} v{settings.VERSION}")
        print("=" * 60)
        print(f"User ID: {self.user_id}")
        print("Type 'quit', 'exit', or 'bye' to end the session.")
        print("=" * 60)
        print()

    async def display_message(self, role: str, text: str) -> None:
        """Display a message in the UI."""
        if role == "user":
            print(f"\n👤 You: {text}")
        else:
            print(f"\n🤖 {role.capitalize()}: {text}")

    async def get_user_input(self, prompt: str | None = None) -> str:
        """Get input from user in a non-blocking way."""
        p = prompt if prompt else "\n👤 You: "
        return await trio.to_thread.run_sync(input, p)

    async def display_system_status(self, status: str) -> None:
        """Log a technical system status message."""
        logger.info(status)

    async def display_user_message(self, message: str) -> None:
        """Display a user-facing message in console."""
        print(f"\n{message}")

    async def present_therapy_style_selection(self, recommendations: list[dict]) -> str:
        """Present therapy style recommendations and get user selection."""
        print("\nRecommended Therapy Styles:")
        for i, style in enumerate(recommendations, 1):
            print(f"{i}. {style['name']}: {style['description']}")

        while True:
            choice = await self.get_user_input("Select a style (number): ")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(recommendations):
                    return recommendations[idx]["id"]
            except ValueError:
                pass
            print("Invalid selection. Please try again.")

    async def display_stream(self, stream_iterator):
        """Display streaming response."""
        print("\n🤖 Analyst: ", end="", flush=True)
        async for chunk in stream_iterator:
            print(chunk, end="", flush=True)
        print()  # Newline at end

    async def run(self) -> None:
        """Run the UI event loop."""
        try:
            # Register mock websocket for async messages (like initial greeting)
            ws = TerminalWebSocket()
            # Register with user_id initially (though orchestrator uses session_id for greeting)
            self.orchestrator.conversation_manager.register_websocket(self.user_id, ws)

            session_info = await self.orchestrator.start_session(
                self.user_id, send_initial_message=True
            )

            # CRITICAL FIX: Register websocket with session_id so initial greeting (sent to session_id)
            # can be received. The orchestrator sends to session_id, not user_id.
            self.orchestrator.conversation_manager.register_websocket(
                session_info.session_id, ws
            )

            # Wait for the initial greeting to complete before accepting input.
            await ws.completion_event.wait()

            # Main interaction loop
            while True:
                try:
                    user_input = await self.get_user_input()

                    # Check for slash commands
                    if user_input.startswith("/"):
                        command = user_input.lower().strip()
                        if command in ["/quit", "/exit", "/bye"]:
                            print("\n👋 Session ended. Take care.")
                            break
                        else:
                            print(
                                f"⚠️  Unknown command: {command}. Type '/quit' to exit."
                            )
                            continue

                    # Legacy exit commands (optional, keeping for convenience)
                    if user_input.lower() in ["quit", "exit", "bye"]:
                        print("\n👋 Session ended. Take care.")
                        break

                    if not user_input.strip():
                        continue

                    # Process message and stream response
                    await self.display_stream(
                        self.orchestrator.process_message(
                            self.user_id, user_input, session_info.session_id
                        )
                    )

                except EOFError:
                    break
                except KeyboardInterrupt:
                    print("\n\n👋 Session interrupted.")
                    break

            # Cleanup
            self.orchestrator.conversation_manager.unregister_websocket(self.user_id)

        except trio.Cancelled:
            logger.info("UI loop cancelled")
            print("\n🛑 Session cancelled.")
        except Exception as e:
            logger.critical(f"Fatal error in UI loop: {e}", exc_info=True)
            print(f"\n❌ Fatal error: {e}")
            print("Please check the logs for more details.")


async def main():
    """
    Main entry point for the application.

    Initializes the service container, database, and orchestration layer,
    then starts the terminal UI.
    """
    settings = Settings()
    setup_logging(settings)
    logger.info("Starting Standalone Terminal UI")

    # Initialize container
    container = ServiceContainer(settings)

    # Get services
    llm_service = container.get("llm_service")
    rag_service = container.get("rag_service")
    db_service = container.get("trio_db_service")

    # Initialize DB
    await db_service.initialize()

    async with trio.open_nursery() as nursery:
        # Initialize Orchestration Layer
        workflow_engine = TrioWorkflowEngine(db_service)
        conversation_manager = TrioConversationManager(
            llm_service, rag_service, db_service, nursery, container.config
        )
        orchestrator = TrioAgentOrchestrator(
            container, workflow_engine, conversation_manager, nursery
        )

        # Background Tier 2 enrichment worker (for async job queue)
        enrichment_service = SessionEnrichmentService(
            llm_service=llm_service, db_service=db_service
        )
        nursery.start_soon(run_session_enrichment_worker, db_service, enrichment_service)

        ui = TerminalUI(orchestrator, settings)
        await ui.run()

    return 0


if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        pass
