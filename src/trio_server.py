"""
Trio-native server implementation using Hypercorn, Quart, and trio-websocket.
"""

import gzip
import json
import logging
from datetime import datetime

import trio
from hypercorn.config import Config as HypercornConfig
from hypercorn.trio import serve
from quart import jsonify, request, websocket
from quart_trio import QuartTrio
from quart_cors import cors

from config import Settings, settings
from container.service_container import ServiceContainer
from models.data_models import UserProfile, UserStatus
from services.auth_service import AuthService
from services.trio_db_service import TrioDatabaseService
from api.auth_routes import create_auth_routes
from api.auth_middleware import create_auth_middleware
from api.version_routes import version_bp
from api.cache_utils import add_cache_headers, CACHE_PRESETS

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

        # 1b. Configure CORS for frontend access
        self.app = cors(
            self.app,
            allow_origin=["http://localhost:5173"],  # Frontend dev server
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"]
        )

        # 1c. Configure response compression
        self._setup_compression()

        # 2. Get Trio-compatible services
        self.db_service: TrioDatabaseService = container.get("trio_db_service")

        # 2b. Initialize authentication service
        self.auth_service = AuthService(
            secret_key=settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
            access_token_expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        )

        # 2c. Create auth middleware decorator
        self.require_auth = create_auth_middleware(
            self.auth_service, settings.REQUIRE_AUTHENTICATION
        )

        # 3. Initialize orchestration layer (Phase 3)

        # 4. Setup routes and handlers
        self._setup_http_routes()
        self._setup_websocket_handler()

        logger.info("Trio server initialized")

    def _setup_compression(self):
        """Setup gzip compression for HTTP responses."""
        @self.app.after_request
        async def compress_response(response):
            """Compress response if client accepts gzip and response is large enough."""
            # Check if client accepts gzip encoding
            accept_encoding = request.headers.get('Accept-Encoding', '')
            if 'gzip' not in accept_encoding.lower():
                return response

            # Skip compression for WebSocket upgrade responses
            if response.status_code == 101:
                return response

            # Get response data
            response_data = await response.get_data()

            # Only compress if response is larger than 500 bytes
            if len(response_data) < 500:
                return response

            # Skip if already compressed
            if response.headers.get('Content-Encoding'):
                return response

            # Compress the response
            compressed_data = gzip.compress(response_data, compresslevel=6)

            # Update response
            await response.set_data(compressed_data)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(compressed_data))

            # Add Vary header to indicate response varies by encoding
            response.headers['Vary'] = 'Accept-Encoding'

            logger.debug(
                f"Compressed response: {len(response_data)} -> {len(compressed_data)} bytes "
                f"({100 * (1 - len(compressed_data) / len(response_data)):.1f}% reduction)"
            )

            return response

        logger.info("Response compression configured (gzip, min 500 bytes)")

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
        # Version information (no auth required)
        self.app.register_blueprint(version_bp)

        # Authentication routes (no auth required)
        auth_bp = create_auth_routes(self.db_service, self.auth_service)
        self.app.register_blueprint(auth_bp)

        # Health check (no auth required)
        self.app.route("/health", methods=["GET"])(self._health_check)

        # User management (protected)
        self.app.route("/api/user/status", methods=["GET"])(
            self.require_auth(self._get_user_status)
        )
        self.app.route("/api/user/profile", methods=["POST"])(
            self.require_auth(self._create_user_profile)
        )

        # Session management (protected)
        self.app.route("/api/sessions", methods=["GET"])(
            self.require_auth(self._get_sessions)
        )
        self.app.route("/api/sessions/<session_id>", methods=["GET"])(
            self.require_auth(self._get_session)
        )
        self.app.route("/api/sessions", methods=["POST"])(
            self.require_auth(self._create_session)
        )
        self.app.route("/api/sessions/<session_id>/extend", methods=["POST"])(
            self.require_auth(self._extend_session)
        )

        # Therapy operations (protected)
        self.app.route("/api/therapy/styles", methods=["GET"])(
            self.require_auth(self._get_therapy_styles)
        )
        self.app.route("/api/therapy/plan", methods=["GET"])(
            self.require_auth(self._get_therapy_plan)
        )
        self.app.route("/api/therapy/plan", methods=["POST"])(
            self.require_auth(self._create_therapy_plan)
        )

        # Workflow operations (protected)
        self.app.route("/api/workflow/next-action", methods=["POST"])(
            self.require_auth(self._get_next_action)
        )

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
        response = jsonify(
            {
                "status": "healthy" if db_healthy else "unhealthy",
                "service": "therapy-backend-trio",
                "database": "healthy" if db_healthy else "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        # Cache health check for 10 seconds
        return add_cache_headers(response, **CACHE_PRESETS["user_data"])

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
        try:
            data = await request.get_json()
            user_id = data.get("user_id")
            if not user_id:
                return jsonify({"error": "User ID is required"}), 400

            # Delegate to orchestrator (business logic layer)
            profile = await self.orchestrator.create_user_profile(
                user_id=user_id,
                name=data.get("name"),
                birthdate=data.get("birthdate"),
                profession=data.get("profession"),
            )
            return jsonify(profile.model_dump()), 201

        except ValueError as e:
            # Expected errors (validation, etc.)
            logger.error(f"Validation error creating profile: {e}")
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            # Unexpected errors - log and crash
            logger.error(f"CRITICAL ERROR in _create_user_profile: {e}", exc_info=True)
            raise

    async def _get_sessions(self):
        """Get all sessions for a user."""
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        sessions = await self.db_service.get_user_sessions(user_id)
        return jsonify([s.model_dump() for s in sessions])

    async def _get_session(self, session_id):
        """Get a specific session."""
        session = await self.db_service.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404
        return jsonify(session.model_dump())

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
        """Get available therapy styles with descriptions."""
        try:
            style_service = self.container.get("style_service")
            styles = style_service.get_available_styles()

            # Return structured data with descriptions
            result = []
            for style_id in styles:
                style_pack = style_service.get_style_pack(style_id)
                result.append({
                    "style": style_id,
                    "name": style_id.capitalize(),  # "freud" -> "Freud"
                    "description": (
                        style_pack.description if style_pack
                        else f"{style_id} therapy approach"
                    )
                })

            response = jsonify(result)
            # Cache therapy styles for 1 hour (they rarely change)
            return add_cache_headers(response, **CACHE_PRESETS["static_long"])

        except Exception as e:
            logger.error(f"CRITICAL ERROR in _get_therapy_styles: {e}", exc_info=True)
            raise

    async def _get_therapy_plan(self):
        """Get therapy plan for a user."""
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        # This is a placeholder
        return jsonify({"message": "Therapy plan not implemented", "user_id": user_id})

    async def _create_therapy_plan(self):
        """Create a therapy plan for a user."""
        try:
            data = await request.get_json()
            user_id = data.get("user_id")
            therapy_style = data.get("therapy_style")

            if not user_id or not therapy_style:
                return jsonify({
                    "error": "user_id and therapy_style are required"
                }), 400

            # Delegate to orchestrator (business logic layer)
            plan = await self.orchestrator.create_therapy_plan(
                user_id, therapy_style
            )

            # Frontend expects updated user profile in response
            profile = await self.db_service.get_user_profile(user_id)
            return jsonify(profile.model_dump()), 201

        except ValueError as e:
            # Expected errors (invalid style, user not found, etc.)
            logger.error(f"Validation error creating therapy plan: {e}")
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            # Unexpected errors - log and crash
            logger.error(f"CRITICAL ERROR in _create_therapy_plan: {e}", exc_info=True)
            raise

    async def _get_next_action(self):
        """Determine next action for frontend based on user's workflow state."""
        try:
            from models.api_models import WorkflowNextActionRequest, WorkflowNextActionResponse
            from orchestration.models import WorkflowState

            data = await request.get_json()

            # Validate request
            req = WorkflowNextActionRequest(**data)

            # Get user profile to determine workflow state
            profile = await self.db_service.get_user_profile(req.user_id)
            if not profile:
                return jsonify({
                    "action": "error",
                    "error": f"User not found: {req.user_id}"
                }), 404

            # Determine next action based on workflow state
            workflow_state = WorkflowState(profile.workflow_state)
            response = self._determine_next_action(workflow_state, profile)

            return jsonify(response.model_dump()), 200

        except ValueError as e:
            logger.error(f"Validation error in _get_next_action: {e}")
            return jsonify({
                "action": "error",
                "error": str(e)
            }), 400
        except Exception as e:
            logger.error(f"CRITICAL ERROR in _get_next_action: {e}", exc_info=True)
            raise

    def _determine_next_action(self, workflow_state, profile) -> 'WorkflowNextActionResponse':
        """Map workflow state to frontend action."""
        from models.api_models import WorkflowNextActionResponse, WorkflowDisplayAction
        from orchestration.models import WorkflowState

        # Map workflow states to frontend routes/actions
        state_action_map = {
            WorkflowState.NEW: ("navigate", "/profile", "User needs to create profile"),
            WorkflowState.INTAKE_IN_PROGRESS: ("navigate", "/intake", "User needs to complete intake"),
            WorkflowState.INTAKE_COMPLETE: ("navigate", "/assessment", "User needs assessment"),
            WorkflowState.ASSESSMENT_IN_PROGRESS: ("navigate", "/assessment", "User is completing assessment"),
            WorkflowState.ASSESSMENT_COMPLETE: ("navigate", "/assessment", "User needs to select therapy style"),
            WorkflowState.PLAN_COMPLETE: ("navigate", "/dashboard", "User can start therapy session"),
            WorkflowState.THERAPY_IN_PROGRESS: ("wait", None, "Session in progress"),
            WorkflowState.REFLECTION_IN_PROGRESS: ("wait", None, "Reflection in progress"),
        }

        action_type, route, reason = state_action_map.get(
            workflow_state,
            ("navigate", "/profile", "Unknown state - redirecting to profile")
        )

        if action_type == "navigate":
            return WorkflowNextActionResponse(
                action=action_type,
                route=route,
                reason=reason
            )
        else:  # wait
            return WorkflowNextActionResponse(
                action=action_type,
                reason=reason
            )

    async def run(self, task_status=trio.TASK_STATUS_IGNORED):
        """Run the Trio server using Hypercorn with proper coordination."""
        # Initialize database service first
        await self.db_service.initialize()
        logger.info("Database service initialized")

        config = HypercornConfig()
        config.bind = [f"{self.host}:{self.port}"]

        async with trio.open_nursery() as server_nursery:
            # Initialize orchestration layer BEFORE starting server
            self._initialize_orchestration(server_nursery)
            logger.info("Orchestration layer initialized")

            # Start Hypercorn in background
            server_nursery.start_soon(serve, self.app, config)

            # Wait for Hypercorn to bind to the port
            await trio.sleep(0.2)

            # Signal that server is ready (orchestration initialized, server binding complete)
            task_status.started()

            # Log after signaling ready
            logger.info(f"Trio server ready on http://{self.host}:{self.port}")
            print(f"🚀 Trio server running on http://{self.host}:{self.port}")
            print(f"   - HTTP API: http://{self.host}:{self.port}/health")
            print(f"   - WebSocket: ws://{self.host}:{self.port}/ws")


async def run_trio_server(config: Settings, host: str, port: int):
    """
    Helper function to initialize and run the TrioServer.
    """
    # Initialize service container
    container = ServiceContainer(config)

    # Create and run server
    server = TrioServer(container, host=host, port=port)
    await server.run()
