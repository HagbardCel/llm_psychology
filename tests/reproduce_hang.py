import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import trio

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from orchestration.models import SessionInfo, WorkflowState
from orchestration.trio_agent_orchestrator import TrioAgentOrchestrator
from ui.base_ui import BaseUI


# Mock dependencies
class MockServiceContainer:
    def get(self, name):
        return MagicMock()


class MockWorkflowEngine:
    async def get_user_state(self, user_id):
        return WorkflowState.NEW

    def get_current_agent(self, state):
        return "INTAKE"

    async def transition(self, user_id, state):
        pass


class MockConversationManager:
    def __init__(self):
        self.websockets = {}

    def register_websocket(self, session_id, ws):
        self.websockets[session_id] = ws

    def unregister_websocket(self, session_id):
        if session_id in self.websockets:
            del self.websockets[session_id]

    async def send_typing_indicator(self, session_id, is_typing):
        pass

    async def send_stream_chunk(self, session_id, chunk, is_complete=False):
        ws = self.websockets.get(session_id)
        if ws:
            await ws.send(chunk, is_complete)

    async def add_message(self, session_id, role, content):
        pass


class MockWebSocket:
    def __init__(self):
        self.completion_event = trio.Event()

    async def send(self, chunk, is_complete):
        if is_complete:
            self.completion_event.set()


async def reproduce():
    logging.basicConfig(level=logging.INFO)

    # Setup mocks
    container = MockServiceContainer()
    workflow_engine = MockWorkflowEngine()
    conversation_manager = MockConversationManager()

    async with trio.open_nursery() as nursery:
        orchestrator = TrioAgentOrchestrator(
            container, workflow_engine, conversation_manager, nursery
        )

        # Mock _create_session to return a dummy ID
        orchestrator._create_session = AsyncMock(return_value="session_123")

        # Mock process_message to raise an exception
        async def mock_process_message(*args, **kwargs):
            raise Exception("Simulated Failure in process_message")
            yield "chunk"  # unreachable

        orchestrator.process_message = mock_process_message

        # Mock create_user_profile
        orchestrator.create_user_profile = AsyncMock()

        # Setup UI side
        user_id = "test_user"
        ws = MockWebSocket()
        conversation_manager.register_websocket(user_id, ws)

        print("Starting session...")
        session_info = await orchestrator.start_session(user_id)

        if session_info.has_initial_message:
            print("Waiting for initial message completion...")
            with trio.move_on_after(5) as cancel_scope:
                await ws.completion_event.wait()

            if cancel_scope.cancelled_caught:
                print("TIMEOUT: UI hung waiting for completion event!")
            else:
                print("Success: Completion event received.")
        else:
            print("No initial message scheduled.")


if __name__ == "__main__":
    trio.run(reproduce)
