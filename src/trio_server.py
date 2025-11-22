"""
Trio-native server implementation using Hypercorn, Quart, and trio-websocket.
This server will replace the asyncio-based UnifiedServer.
"""

import json
import logging
from datetime import datetime

import trio
from hypercorn.config import Config as HypercornConfig
from hypercorn.trio import serve
from quart import jsonify, request, websocket
from quart_trio import QuartTrio

from config import Settings
from container.service_container import ServiceContainer
from models.data_models import UserProfile, UserStatus
from services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioServer:
    """
    Trio-native server providing both HTTP API and WebSocket services.
    """

    def __init__(
        self, container: ServiceContainer, host: str = "0.0.0.0", port: int = 8000
    ):
        self.container = container
        self.host = host
        self.port = port

        # 1. Initialize QuartTrio app
        self.app = QuartTrio(__name__)

        # 2. Get Trio-compatible services
        self.db_service: TrioDatabaseService = container.get("trio_db_service")

        # 3. Initialize orchestration layer (Phase 3)

        # 4. Setup routes and handlers
        self._setup_http_routes()
        self._setup_websocket_handler()

        logger.info("Trio server initialized")

    def _initialize_orchestration(self, nursery: trio.Nursery):
        """Initialize Trio orchestration components."""
        from orchestration.trio_agent_orchestrator import TrioAgentOrchestrator
        from orchestration.trio_conversation_manager import TrioConversationManager
        from orchestration.trio_workflow_engine import TrioWorkflowEngine

        # Get services
        llm_service = self.container.get("llm_service")
        rag_service = self.container.get("rag_service")

        # Create orchestration components, passing the nursery
        self.workflow_engine = TrioWorkflowEngine(self.db_service)
        self.conversation_manager = TrioConversationManager(
            llm_service, rag_service, self.db_service, nursery
        )
        self.orchestrator = TrioAgentOrchestrator(
            self.container, self.workflow_engine, self.conversation_manager, nursery
        )

        logger.info("Orchestration layer initialized with nursery")

    def _setup_http_routes(self):
        """Setup HTTP API routes."""
        # Health check
        self.app.route("/health", methods=["GET"])(self._health_check)

        # User management
        self.app.route("/api/user/status", methods=["GET"])(self._get_user_status)
        self.app.route("/api/user/profile", methods=["POST"])(self._create_user_profile)

        # Session management
        self.app.route("/api/sessions", methods=["GET"])(self._get_sessions)
        self.app.route("/api/sessions/<session_id>", methods=["GET"])(self._get_session)
        self.app.route("/api/sessions", methods=["POST"])(self._create_session)
        self.app.route("/api/sessions/<session_id>/extend", methods=["POST"])(
            self._extend_session
        )

        # Therapy operations
        self.app.route("/api/therapy/styles", methods=["GET"])(self._get_therapy_styles)
        self.app.route("/api/therapy/plan", methods=["GET"])(self._get_therapy_plan)
        self.app.route("/api/therapy/plan", methods=["POST"])(self._create_therapy_plan)

        logger.info("HTTP routes configured for Trio server")

    def _setup_websocket_handler(self):
        """Setup the main WebSocket handler with structured concurrency."""

        @self.app.websocket("/ws")
        async def ws_endpoint():
            """
            WebSocket endpoint using Trio structured concurrency.
            Expects user_id as a query parameter: /ws?user_id=<user_id>
            """
            session_id = None

            # Extract user_id from query parameters
            user_id = websocket.args.get("user_id")

            if not user_id:
                await websocket.close(1002, "user_id query parameter is required")
                logger.warning(
                    "WebSocket connection rejected: missing user_id query parameter"
                )
                return

            logger.info(f"WebSocket connection request for user: {user_id}")

            # Validate user exists, create if needed
            user_profile = await self.db_service.get_user_profile(user_id)
            if not user_profile:
                # Auto-create basic profile for new users
                user_profile = UserProfile(
                    user_id=user_id,
                    name=user_id,  # Use user_id as default name
                    status=UserStatus.PROFILE_ONLY,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                await self.db_service.save_user_profile(user_profile)
                logger.info(f"Auto-created profile for new user: {user_id}")

            # Send connection confirmation with user info
            await websocket.send(
                json.dumps(
                    {
                        "type": "connected",
                        "data": {
                            "user_id": user_id,
                            "name": user_profile.name,
                            "status": user_profile.status.value,
                        },
                    }
                )
            )

            logger.info(f"WebSocket connection established for user: {user_id}")

            try:
                while True:
                    raw_message = await websocket.receive()
                    message = json.loads(raw_message)
                    msg_type = message.get("type")

                    if msg_type == "session_request":
                        # Clean up previous session if exists
                        if session_id:
                            self.conversation_manager.unregister_websocket(session_id)
                            logger.info(f"Switching session from {session_id}")

                        # Start session and get session info
                        session_info = await self.orchestrator.start_session(user_id)
                        session_id = session_info.session_id

                        # Register websocket for this session
                        self.conversation_manager.register_websocket(
                            session_id, websocket._get_current_object()
                        )

                        # Send session started confirmation
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "session_started",
                                    "data": session_info.to_dict(),
                                }
                            )
                        )

                    elif msg_type == "chat_message":
                        if not session_id:
                            await websocket.close(
                                1002, "First message must be session_request"
                            )
                            return

                        await self._handle_chat_message_ws(
                            raw_message, session_id, user_id
                        )

                    else:
                        # Ignore unknown message types or handle as needed
                        pass

            except Exception as e:
                logger.error(
                    f"WebSocket error for session {session_id}: {e}", exc_info=True
                )
            finally:
                if session_id:
                    self.conversation_manager.unregister_websocket(session_id)
                logger.info(f"WebSocket connection closed for session {session_id}")

        logger.info("WebSocket handler configured for Trio server")

    async def _handle_chat_message_ws(
        self, raw_message: str, session_id: str, user_id: str
    ):
        """Handles incoming chat messages for an established session."""
        try:
            message = json.loads(raw_message)
            if message.get("type") != "chat_message":
                # Ignore other message types in this simplified handler
                return

            message_content = message.get("data", {}).get("message", "").strip()
            if not message_content:
                return

            # Stream response chunks from orchestrator
            async for chunk in self.orchestrator.process_message(
                user_id, message_content, session_id
            ):
                await websocket.send(
                    json.dumps(
                        {
                            "type": "chat_response_chunk",
                            "data": {"chunk": chunk, "is_complete": False},
                        }
                    )
                )

            # Send completion message
            await websocket.send(
                json.dumps(
                    {
                        "type": "chat_response_chunk",
                        "data": {"chunk": "", "is_complete": True},
                    }
                )
            )

        except json.JSONDecodeError:
            logger.warning(f"Received invalid JSON in session {session_id}")
        except Exception as e:
            logger.error(
                f"Error handling chat message in session {session_id}: {e}",
                exc_info=True,
            )

    async def _health_check(self):
        """Health check endpoint."""
        db_healthy = await self.db_service.health_check()
        return jsonify(
            {
                "status": "healthy" if db_healthy else "unhealthy",
                "service": "therapy-backend-trio",
                "database": "healthy" if db_healthy else "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    async def _get_user_status(self):
        """Get user workflow state."""
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        state = await self.orchestrator.get_user_state(user_id)
        return jsonify(
            {
                "user_id": user_id,
                "workflow_state": state.value,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    async def _create_user_profile(self):
        """Create a new user profile."""
        data = await request.get_json()
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400

        profile = await self.orchestrator.create_user_profile(
            user_id=user_id,
            name=data.get("name"),
            birthdate=data.get("birthdate"),
            profession=data.get("profession"),
        )
        return jsonify(profile.to_dict()), 201

    async def _get_sessions(self):
        """Get all sessions for a user."""
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        sessions = await self.db_service.get_user_sessions(user_id)
        return jsonify([s.to_dict() for s in sessions])

    async def _get_session(self, session_id):
        """Get a specific session."""
        session = await self.db_service.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404
        return jsonify(session.to_dict())

    async def _create_session(self):
        """Create a new session."""
        data = await request.get_json()
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400

        user_profile = await self.db_service.get_user_profile(user_id)
        if not user_profile:
            return jsonify({"error": "User profile not found"}), 404

        session_info = await self.orchestrator.start_session(user_id)
        return (
            jsonify(
                {
                    "session_id": session_info.session_id,
                    "user_id": user_id,
                    "type": "therapy",
                    "status": "created",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ),
            201,
        )

    async def _extend_session(self, session_id):
        """Extend a session."""
        # This is a placeholder
        return jsonify({"message": "Session extended", "session_id": session_id})

    async def _get_therapy_styles(self):
        """Get available therapy styles."""
        # This is a placeholder
        return jsonify(["CBT", "Psychoanalytic", "Humanistic"])

    async def _get_therapy_plan(self):
        """Get therapy plan for a user."""
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        # This is a placeholder
        return jsonify({"message": "Therapy plan not implemented", "user_id": user_id})

    async def _create_therapy_plan(self):
        """Create a therapy plan for a user."""
        # This is a placeholder
        return jsonify({"message": "Therapy plan creation not implemented"}), 201

    async def run(self, task_status=trio.TASK_STATUS_IGNORED):
        """Run the Trio server using Hypercorn."""
        # Initialize database service first
        await self.db_service.initialize()
        logger.info("Database service initialized")

        config = HypercornConfig()
        config.bind = [f"{self.host}:{self.port}"]
        logger.info(f"Starting Trio server on {self.host}:{self.port}")
        print(f"🚀 Trio server running on http://{self.host}:{self.port}")
        print(f"   - HTTP API: http://{self.host}:{self.port}/health")
        print(f"   - WebSocket: ws://{self.host}:{self.port}/ws")

        async with trio.open_nursery() as nursery:
            # Pass the nursery to the orchestration layer
            self._initialize_orchestration(nursery)

            # Signal that the server is starting
            task_status.started()

            await serve(self.app, config)


async def run_trio_server(config: Settings, host: str, port: int):
    """
    Helper function to initialize and run the TrioServer.
    """
    # Initialize service container
    container = ServiceContainer(config)

    # Create and run server
    server = TrioServer(container, host=host, port=port)
    await server.run()
