"""Trio-native server composition."""

import gzip
import inspect
import logging
from datetime import datetime

import trio
from hypercorn.config import Config as HypercornConfig
from hypercorn.trio import serve
from quart import Blueprint, jsonify, request
from quart_cors import cors
from quart_trio import QuartTrio

from psychoanalyst_app.api.cache_utils import CACHE_PRESETS, add_cache_headers
from psychoanalyst_app.api.session_routes import create_session_routes
from psychoanalyst_app.api.therapy_routes import create_therapy_routes
from psychoanalyst_app.api.user_routes import create_user_routes
from psychoanalyst_app.api.version_routes import create_version_routes
from psychoanalyst_app.api.workflow_routes import create_workflow_routes
from psychoanalyst_app.api.ws_handler import register_ws_handler
from psychoanalyst_app.config import Settings
from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.models.http import HealthCheckResponseDTO
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

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

        # 1b. Configure CORS for HTTP and WebSocket clients.
        self.app = cors(
            self.app,
            allow_origin=self.container.config.CORS_ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type"],
        )

        # 1c. Configure response compression
        self._setup_compression()

        # 2. Get Trio-compatible services
        self.db_service: TrioDatabaseService = container.get("trio_db_service")

        # 3. Initialize orchestration layer (Phase 3)

        # 4. Setup routes and handlers
        self._setup_http_routes()
        register_ws_handler(self.app, self)

        logger.info("Trio server initialized")

    def _setup_compression(self):
        """Setup gzip compression for HTTP responses."""

        @self.app.after_request
        async def compress_response(response):
            """Compress response if client accepts gzip and response is large enough."""
            # Check if client accepts gzip encoding
            accept_encoding = request.headers.get("Accept-Encoding", "")
            if "gzip" not in accept_encoding.lower():
                return response

            # Skip compression for WebSocket upgrade responses
            if response.status_code == 101:
                return response

            # Get response data
            response_data = response.get_data()
            if inspect.isawaitable(response_data):
                response_data = await response_data

            # Only compress if response is larger than 500 bytes
            if len(response_data) < 500:
                return response

            # Skip if already compressed
            if response.headers.get("Content-Encoding"):
                return response

            # Compress the response
            compressed_data = gzip.compress(response_data, compresslevel=6)

            # Update response
            set_data_result = response.set_data(compressed_data)
            if inspect.isawaitable(set_data_result):
                await set_data_result
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Content-Length"] = str(len(compressed_data))

            # Add Vary header to indicate response varies by encoding
            response.headers["Vary"] = "Accept-Encoding"

            reduction = 100 * (1 - len(compressed_data) / len(response_data))
            logger.debug(
                "Compressed response: %s -> %s bytes (%.1f%% reduction)",
                len(response_data),
                len(compressed_data),
                reduction,
            )

            return response

        logger.info("Response compression configured (gzip, min 500 bytes)")

    def _initialize_orchestration(self, nursery: trio.Nursery):
        """Initialize Trio orchestration components."""
        from psychoanalyst_app.orchestration.trio_agent_orchestrator import (
            TrioAgentOrchestrator,
        )
        from psychoanalyst_app.orchestration.trio_conversation_manager import (
            TrioConversationManager,
        )
        from psychoanalyst_app.orchestration.trio_workflow_engine import (
            TrioWorkflowEngine,
        )
        from psychoanalyst_app.services.session_enrichment import (
            SessionEnrichmentService,
            run_session_enrichment_worker,
        )

        # Get services
        llm_service = self.container.get("llm_service")
        rag_service = self.container.get("rag_service")

        # Create orchestration components, passing the nursery
        self.workflow_engine = TrioWorkflowEngine(self.db_service)
        self.conversation_manager = TrioConversationManager(
            llm_service, rag_service, self.db_service, nursery, self.container.config
        )
        self.orchestrator = TrioAgentOrchestrator(
            self.container, self.workflow_engine, self.conversation_manager, nursery
        )

        # Background Tier 2 enrichment worker (no LLM calls on read paths)
        self.session_enrichment_service = SessionEnrichmentService(
            llm_service=llm_service, db_service=self.db_service
        )
        nursery.start_soon(
            run_session_enrichment_worker,
            self.db_service,
            self.session_enrichment_service,
        )

        logger.info("Orchestration layer initialized with nursery")

    def _setup_http_routes(self):
        """Setup HTTP API routes."""
        health_bp = Blueprint("health", __name__)

        @health_bp.route("/health", methods=["GET"])
        async def health_check():
            return await self._health_check()

        self.app.register_blueprint(create_version_routes(self))
        self.app.register_blueprint(health_bp)
        self.app.register_blueprint(create_user_routes(self))
        self.app.register_blueprint(create_session_routes(self))
        self.app.register_blueprint(create_therapy_routes(self))
        self.app.register_blueprint(create_workflow_routes(self))
        logger.info("HTTP routes configured for Trio server")

    async def _health_check(self):
        """Health check endpoint (used by tests and HTTP route)."""
        db_healthy = await self.db_service.health_check()
        dto = HealthCheckResponseDTO(
            status="healthy" if db_healthy else "unhealthy",
            service="therapy-backend-trio",
            database="healthy" if db_healthy else "unhealthy",
            timestamp=datetime.utcnow(),
        )
        response = jsonify(dto.model_dump(mode="json"))
        return add_cache_headers(response, **CACHE_PRESETS["user_data"])

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

            # Signal that server is ready (orchestration initialized, binding complete).
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
